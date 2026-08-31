#!/usr/bin/env python3
"""LocalNet listen: set_keeper + mock inner-call accrue on the recreate app.

Talks only to localhost:4001 (algod) and localhost:4002 (KMD).
Never prints a mnemonic or private key. Never writes docs/deploy.json.
TestNet deploy.json stays appId 0 until a real TestNet create.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from algosdk.abi import Method
from algosdk.atomic_transaction_composer import (
    AccountTransactionSigner,
    AtomicTransactionComposer,
    TransactionWithSigner,
)
from algosdk.kmd import KMDClient
from algosdk.logic import get_application_address
from algosdk.transaction import (
    ApplicationCreateTxn,
    OnComplete,
    PaymentTxn,
    StateSchema,
    wait_for_confirmation,
)
from algosdk.v2client.algod import AlgodClient

ROOT = Path(__file__).resolve().parents[1]
LOCALNET_JSON = ROOT / "docs" / "localnet.json"
LISTEN_JSON = ROOT / "docs" / "listen.json"
DEPLOY_JSON = ROOT / "docs" / "deploy.json"
MOCK_SRC = ROOT / "smart_contracts" / "mock_keeper" / "contract.py"
MOCK_ARTIFACT_DIR = ROOT / "smart_contracts" / "artifacts" / "mock_keeper"

ALGOD_URL = "http://localhost:4001"
KMD_URL = "http://localhost:4002"
TOKEN = "a" * 64
BANK = "IFZZOTEBLLAV7DA4WP7IPZWZW67KXB5ZNYLZAWJ2S6M3KKNAX55BRXVK2Y"

SET_KEEPER = Method.from_signature("set_keeper(uint64)void")
CONFIGURE = Method.from_signature("configure(address,uint64,uint64)void")
FUND = Method.from_signature("fund(pay)uint64")
CLAIM = Method.from_signature("claim()uint64")
MK_ACCRUE = Method.from_signature("accrue(uint64)void")


def refuse_wrong_network(genesis_id: str | None) -> None:
    g = (genesis_id or "").lower()
    if "testnet" in g:
        sys.exit("refusing: algod looks like TestNet (use LocalNet only)")
    if "mainnet" in g:
        sys.exit("refusing: algod looks like MainNet")


def assert_deploy_json_honest() -> None:
    if not DEPLOY_JSON.is_file():
        return
    cfg = json.loads(DEPLOY_JSON.read_text())
    if int(cfg.get("appId") or 0) != 0:
        print(
            f"warning: docs/deploy.json appId={cfg.get('appId')} "
            "(this script does not modify it)",
            file=sys.stderr,
        )


def wait_confirmed(client: AlgodClient, txid: str) -> dict:
    last_err = None
    for _ in range(16):
        try:
            return wait_for_confirmation(client, txid, 8)
        except Exception as e:
            last_err = e
            time.sleep(0.4)
            pending = client.pending_transaction_info(txid)
            if pending.get("confirmed-round", 0):
                return pending
    raise SystemExit(f"tx not confirmed: {txid} err={last_err}")


def params(algod: AlgodClient, fee: int = 2000):
    sp = algod.suggested_params()
    sp.flat_fee = True
    sp.fee = fee
    last = int(algod.status().get("last-round") or 0)
    sp.first = last
    sp.last = last + 1_000
    return sp


def funded_account(algod: AlgodClient, kmd: KMDClient) -> tuple[str, bytes]:
    wallets = kmd.list_wallets()
    wallet = next(w for w in wallets if w.get("name") == "unencrypted-default-wallet")
    handle = kmd.init_wallet_handle(wallet["id"], "")
    try:
        keys = kmd.list_keys(handle)
        best = None
        best_amt = -1
        for addr in keys:
            if addr == BANK:
                continue
            amt = int(algod.account_info(addr).get("amount") or 0)
            if amt > best_amt:
                best = addr
                best_amt = amt
        if not best or best_amt < 1_000_000:
            raise SystemExit(f"no funded LocalNet account (best_amt={best_amt})")
        pk = kmd.export_key(handle, "", best)
        return best, pk
    finally:
        kmd.release_wallet_handle(handle)


def compile_teal(client: AlgodClient, path: Path) -> bytes:
    result = client.compile(path.read_text())
    return base64.b64decode(result["result"])


def ensure_mock_artifacts() -> tuple[Path, Path]:
    MOCK_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    approval = MOCK_ARTIFACT_DIR / "MockKeeper.approval.teal"
    clear = MOCK_ARTIFACT_DIR / "MockKeeper.clear.teal"
    if approval.is_file() and clear.is_file():
        return approval, clear
    if not MOCK_SRC.is_file():
        sys.exit(f"missing mock keeper source: {MOCK_SRC}")
    cmd = [
        sys.executable,
        "-m",
        "puyapy",
        str(MOCK_SRC),
        "--out-dir",
        str(MOCK_ARTIFACT_DIR),
        "--resource-encoding",
        "value",
    ]
    print("compile:", " ".join(cmd), file=sys.stderr)
    subprocess.check_call(cmd, cwd=ROOT)
    if not (approval.is_file() and clear.is_file()):
        sys.exit(f"puyapy did not produce mock keeper artifacts under {MOCK_ARTIFACT_DIR}")
    return approval, clear


def decode_global(app: dict) -> dict[str, int | str]:
    out: dict[str, int | str] = {}
    params_ = app.get("params") or {}
    for kv in params_.get("global-state") or []:
        key = base64.b64decode(kv.get("key") or "").decode("utf-8", errors="replace")
        val = kv.get("value") or {}
        if int(val.get("type") or 0) == 2:
            out[key] = int(val.get("uint") or 0)
        else:
            out[key] = str(val.get("bytes") or "")
    return out


def execute_atc(algod: AlgodClient, atc: AtomicTransactionComposer, method: str) -> dict:
    try:
        result = atc.execute(algod, 8)
    except Exception as e:
        raise SystemExit(f"{method} failed: {e}") from e
    txid = result.tx_ids[-1] if result.tx_ids else ""
    info = algod.pending_transaction_info(txid) if txid else {}
    inners = info.get("inner-txns") or info.get("inner-transactions") or []
    return {
        "method": method,
        "txid": txid,
        "round": int(info.get("confirmed-round") or 0),
        "success": True,
        "innerCount": len(inners),
    }


def call_abi(
    algod: AlgodClient,
    addr: str,
    signer: AccountTransactionSigner,
    app_id: int,
    method: Method,
    method_args: list | None = None,
    foreign_apps: list[int] | None = None,
    extra_payment: PaymentTxn | None = None,
    fee: int = 2000,
) -> dict:
    atc = AtomicTransactionComposer()
    args = list(method_args or [])
    if extra_payment is not None:
        args.append(TransactionWithSigner(extra_payment, signer))
    atc.add_method_call(
        app_id=app_id,
        method=method,
        sender=addr,
        sp=params(algod, fee=fee),
        signer=signer,
        method_args=args,
        foreign_apps=foreign_apps or [],
    )
    return execute_atc(algod, atc, method.name)


def main() -> None:
    assert_deploy_json_honest()
    if not LOCALNET_JSON.is_file():
        sys.exit("missing docs/localnet.json — run scripts/localnet_recreate.py first")
    proof = json.loads(LOCALNET_JSON.read_text())
    if proof.get("network") != "localnet":
        sys.exit(f"refusing: docs/localnet.json network={proof.get('network')!r}")
    app_id = int(proof.get("appId") or 0)
    if app_id <= 0:
        sys.exit("docs/localnet.json has no LocalNet appId")

    algod = AlgodClient(TOKEN, ALGOD_URL)
    kmd = KMDClient(TOKEN, KMD_URL)
    status = algod.status()
    versions = algod.versions()
    last_round = int(status.get("last-round") or 0)
    genesis_id = versions.get("genesis_id") or status.get("genesis-id")
    print(f"algod ok genesis_id={genesis_id} last-round={last_round}", file=sys.stderr)
    refuse_wrong_network(str(genesis_id) if genesis_id else None)

    live = algod.application_info(app_id)
    creator = (live.get("params") or {}).get("creator")
    print(f"target Vesting appId={app_id} creator={creator}", file=sys.stderr)

    addr, pk = funded_account(algod, kmd)
    if addr == BANK:
        sys.exit("refusing to sign as TestNet bank")
    signer = AccountTransactionSigner(pk)
    print(f"deployer {addr} localnet_micro={algod.account_info(addr).get('amount')}", file=sys.stderr)

    approval_path, clear_path = ensure_mock_artifacts()
    approval = compile_teal(algod, approval_path)
    clear = compile_teal(algod, clear_path)
    extra = max(0, (len(approval) - 1) // 2048)
    sp = params(algod, fee=2_000 + 1_000 * extra)
    txn = ApplicationCreateTxn(
        sender=addr,
        sp=sp,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=StateSchema(0, 0),
        local_schema=StateSchema(0, 0),
        extra_pages=extra,
    )
    mock_txid = algod.send_transaction(txn.sign(pk))
    mock_conf = wait_confirmed(algod, mock_txid)
    mock_id = int(mock_conf.get("application-index") or 0)
    if mock_id <= 0:
        raise SystemExit(f"mock keeper create returned app id {mock_id} txid={mock_txid}")
    mock_addr = get_application_address(mock_id)
    print(f"created MockKeeper appId={mock_id} round={mock_conf.get('confirmed-round')}", file=sys.stderr)

    fund_mock = PaymentTxn(
        sender=addr, sp=params(algod, fee=1000), receiver=mock_addr, amt=100_000
    )
    fund_mock_txid = algod.send_transaction(fund_mock.sign(pk))
    fund_mock_conf = wait_confirmed(algod, fund_mock_txid)

    vest_addr = get_application_address(app_id)
    calls: list[dict] = []

    rec = call_abi(
        algod, addr, signer, app_id, SET_KEEPER, method_args=[mock_id], foreign_apps=[mock_id]
    )
    rec["keeperAppId"] = mock_id
    calls.append(rec)
    print(f"set_keeper txid={rec['txid']} round={rec['round']}", file=sys.stderr)

    start_round = 0
    duration_rounds = 1
    rec = call_abi(
        algod,
        addr,
        signer,
        app_id,
        CONFIGURE,
        method_args=[addr, start_round, duration_rounds],
    )
    rec["beneficiary"] = addr
    rec["startRound"] = start_round
    rec["durationRounds"] = duration_rounds
    calls.append(rec)
    print(f"configure txid={rec['txid']} round={rec['round']}", file=sys.stderr)

    principal = 1_000_000
    pay = PaymentTxn(
        sender=addr, sp=params(algod, fee=1000), receiver=vest_addr, amt=100_000 + principal
    )
    rec = call_abi(
        algod,
        addr,
        signer,
        app_id,
        FUND,
        extra_payment=pay,
        fee=2000,
    )
    rec["paymentMicroAlgos"] = 100_000 + principal
    rec["principalMicroAlgos"] = principal
    calls.append(rec)
    print(f"fund txid={rec['txid']} round={rec['round']}", file=sys.stderr)

    rec = call_abi(
        algod,
        addr,
        signer,
        mock_id,
        MK_ACCRUE,
        method_args=[app_id],
        foreign_apps=[app_id],
        fee=3000,
    )
    rec["targetAppId"] = app_id
    rec["hook"] = "accrue"
    rec["via"] = "mock_keeper.accrue"
    calls.append(rec)
    print(
        f"accrue via mock txid={rec['txid']} round={rec['round']} inners={rec['innerCount']}",
        file=sys.stderr,
    )

    rec = call_abi(algod, addr, signer, app_id, CLAIM, fee=3000)
    rec["hook"] = "claim"
    rec["via"] = "beneficiary_pull"
    calls.append(rec)
    print(f"claim txid={rec['txid']} round={rec['round']}", file=sys.stderr)

    after = decode_global(algod.application_info(app_id))
    listened_at = datetime.now(timezone.utc).isoformat()
    last_after = int(algod.status().get("last-round") or 0)

    payload = {
        "network": "localnet",
        "genesisId": genesis_id,
        "algod": ALGOD_URL,
        "appId": app_id,
        "appAddress": vest_addr,
        "mockKeeperAppId": mock_id,
        "mockKeeperCreateTxid": mock_txid,
        "mockKeeperConfirmedRound": int(mock_conf.get("confirmed-round") or 0),
        "mockKeeperFundTxid": fund_mock_txid,
        "mockKeeperFundRound": int(fund_mock_conf.get("confirmed-round") or 0),
        "creator": addr,
        "lastRound": last_after,
        "listened_at": listened_at,
        "calls": calls,
        "global": {
            "keeper_app": after.get("keeper_app", 0),
            "locked": after.get("locked", 0),
            "credited": after.get("credited", 0),
            "claimed": after.get("claimed", 0),
            "last_accrue_round": after.get("last_accrue_round", 0),
            "duration_rounds": after.get("duration_rounds", 0),
            "start_round": after.get("start_round", 0),
        },
        "notes": (
            "LocalNet-only listen proof. Do NOT copy this appId into "
            "docs/deploy.json or treat it as TestNet. TestNet stays appId 0 "
            "until a real TestNet create. Did not spend TestNet bank. "
            "Did not poke upkeep 81 or 87."
        ),
    }
    LISTEN_JSON.parent.mkdir(parents=True, exist_ok=True)
    LISTEN_JSON.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {LISTEN_JSON}", file=sys.stderr)
    print(
        json.dumps(
            {
                "network": "localnet",
                "appId": app_id,
                "mockKeeperAppId": mock_id,
                "credited": payload["global"]["credited"],
                "claimed": payload["global"]["claimed"],
                "path": str(LISTEN_JSON),
            }
        )
    )
    del pk


if __name__ == "__main__":
    main()
