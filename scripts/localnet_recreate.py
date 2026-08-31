#!/usr/bin/env python3
"""Recreate Vesting on AlgoKit LocalNet and write docs/localnet.json.

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
from algosdk.kmd import KMDClient
from algosdk.logic import get_application_address
from algosdk.transaction import (
    ApplicationCreateTxn,
    OnComplete,
    StateSchema,
    wait_for_confirmation,
)
from algosdk.v2client.algod import AlgodClient

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "smart_contracts" / "vesting" / "contract.py"
ARTIFACT_DIR = ROOT / "smart_contracts" / "artifacts" / "vesting"
OUT = ROOT / "docs" / "localnet.json"
DEPLOY_JSON = ROOT / "docs" / "deploy.json"

ALGOD_URL = "http://localhost:4001"
KMD_URL = "http://localhost:4002"
TOKEN = "a" * 64
CREATE = Method.from_signature("create()void")
CONTRACT_NAME = "Vesting"
SOURCE = "smart_contracts/vesting/contract.py"


def refuse_wrong_network(genesis_id: str | None) -> None:
    g = (genesis_id or "").lower()
    if "testnet" in g:
        sys.exit("refusing: algod looks like TestNet (use LocalNet only)")
    if "mainnet" in g:
        sys.exit("refusing: algod looks like MainNet")


def ensure_artifacts() -> tuple[Path, Path, Path]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    approval = ARTIFACT_DIR / f"{CONTRACT_NAME}.approval.teal"
    clear = ARTIFACT_DIR / f"{CONTRACT_NAME}.clear.teal"
    spec = ARTIFACT_DIR / f"{CONTRACT_NAME}.arc56.json"
    if approval.is_file() and clear.is_file() and spec.is_file():
        return approval, clear, spec
    if not CONTRACT.is_file():
        sys.exit(f"missing contract source: {CONTRACT}")
    cmd = [
        sys.executable,
        "-m",
        "puyapy",
        str(CONTRACT),
        "--out-dir",
        str(ARTIFACT_DIR),
        "--resource-encoding",
        "value",
    ]
    print("compile:", " ".join(cmd), file=sys.stderr)
    subprocess.check_call(cmd, cwd=ROOT)
    if not (approval.is_file() and clear.is_file() and spec.is_file()):
        sys.exit(f"puyapy did not produce expected artifacts under {ARTIFACT_DIR}")
    return approval, clear, spec


def schema_from_spec(spec: dict) -> tuple[StateSchema, StateSchema]:
    state = spec.get("state") or {}
    schema = state.get("schema") or {}
    g = schema.get("global") or {}
    loc = schema.get("local") or {}
    return (
        StateSchema(int(g.get("ints", 0)), int(g.get("bytes", 0))),
        StateSchema(int(loc.get("ints", 0)), int(loc.get("bytes", 0))),
    )


def compile_teal(client: AlgodClient, path: Path) -> bytes:
    result = client.compile(path.read_text())
    return base64.b64decode(result["result"])


def funded_account(algod: AlgodClient, kmd: KMDClient) -> tuple[str, bytes]:
    wallets = kmd.list_wallets()
    wallet = next(w for w in wallets if w.get("name") == "unencrypted-default-wallet")
    handle = kmd.init_wallet_handle(wallet["id"], "")
    try:
        keys = kmd.list_keys(handle)
        best = None
        best_amt = -1
        for addr in keys:
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
    raise SystemExit(f"create not confirmed: {txid} err={last_err}")


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
    if str(cfg.get("network") or "").lower() not in ("testnet", ""):
        print(
            f"warning: docs/deploy.json network={cfg.get('network')!r}",
            file=sys.stderr,
        )


def main() -> None:
    assert_deploy_json_honest()
    approval_path, clear_path, spec_path = ensure_artifacts()

    algod = AlgodClient(TOKEN, ALGOD_URL)
    kmd = KMDClient(TOKEN, KMD_URL)
    status = algod.status()
    versions = algod.versions()
    last_round = int(status.get("last-round") or 0)
    genesis_id = versions.get("genesis_id") or status.get("genesis-id")
    print(f"algod ok genesis_id={genesis_id} last-round={last_round}", file=sys.stderr)
    refuse_wrong_network(str(genesis_id) if genesis_id else None)

    addr, pk = funded_account(algod, kmd)
    info = algod.account_info(addr)
    print(f"deployer {addr} localnet_micro={info.get('amount')}", file=sys.stderr)

    approval = compile_teal(algod, approval_path)
    clear = compile_teal(algod, clear_path)
    arc = json.loads(spec_path.read_text())
    gschema, lschema = schema_from_spec(arc)
    extra = max(0, (len(approval) - 1) // 2048)
    sp = algod.suggested_params()
    sp.flat_fee = True
    sp.fee = 2_000 + 1_000 * extra
    last = int(algod.status().get("last-round") or 0)
    sp.first = last
    sp.last = last + 1_000

    txn = ApplicationCreateTxn(
        sender=addr,
        sp=sp,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=gschema,
        local_schema=lschema,
        app_args=[CREATE.get_selector()],
        extra_pages=extra,
    )
    txid = algod.send_transaction(txn.sign(pk))
    conf = wait_confirmed(algod, txid)
    app_id = int(conf.get("application-index") or 0)
    if app_id <= 0:
        raise SystemExit(f"create returned app id {app_id} txid={txid}")
    # Prove the app exists on this LocalNet algod.
    algod.application_info(app_id)
    app_addr = get_application_address(app_id)
    created_at = datetime.now(timezone.utc).isoformat()

    payload = {
        "network": "localnet",
        "genesisId": genesis_id,
        "algod": ALGOD_URL,
        "appId": app_id,
        "appAddress": app_addr,
        "createTxid": txid,
        "confirmedRound": int(conf.get("confirmed-round") or 0),
        "creator": addr,
        "contract": CONTRACT_NAME,
        "source": SOURCE,
        "extraPages": extra,
        "approvalBytes": len(approval),
        "created_at": created_at,
        "notes": (
            "LocalNet-only recreate proof. Do NOT copy this appId into "
            "docs/deploy.json or treat it as TestNet. TestNet stays appId 0 "
            "until a real TestNet create. Did not spend TestNet bank. "
            "Did not poke upkeep 81 or 87."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"created {CONTRACT_NAME} appId={app_id} round={payload['confirmedRound']}", file=sys.stderr)
    print(f"wrote {OUT}", file=sys.stderr)
    # Machine-readable one-liner for CI / callers (no secrets).
    print(json.dumps({"network": "localnet", "appId": app_id, "path": str(OUT)}))


if __name__ == "__main__":
    main()
