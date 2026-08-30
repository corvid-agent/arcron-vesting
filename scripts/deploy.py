#!/usr/bin/env python3
"""Create, configure, fund, and claim the vesting app. TestNet only.

Refuses to run unless ALGOD_SERVER is a TestNet endpoint. Never prints or
writes a mnemonic. If DEPLOYER_MNEMONIC is unset, an ephemeral account is
kept in memory and its *address* is printed for a dispenser.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from algosdk import account, mnemonic, transaction
from algosdk.atomic_transaction_composer import (
    AccountTransactionSigner,
    AtomicTransactionComposer,
    TransactionWithSigner,
)
from algosdk.abi import Method
from algosdk.logic import get_application_address
from algosdk.v2client import algod as algod_mod

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "smart_contracts" / "artifacts" / "vesting"
CONTRACT = ROOT / "smart_contracts" / "vesting" / "contract.py"
KEEPER_APP_ID = 769891898
APP_BASE_MBR = 100_000
CREATE = Method.from_signature("create()void")
SET_KEEPER = Method.from_signature("set_keeper(uint64)void")
CONFIGURE = Method.from_signature("configure(address,uint64,uint64)void")
FUND = Method.from_signature("fund(pay)uint64")
CLAIM = Method.from_signature("claim()uint64")


def _load_dotenv() -> None:
    for name in (".env.example", ".env"):
        path = ROOT / name
        if name != ".env.example" and path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def require_testnet(algod_server: str) -> None:
    s = algod_server.lower()
    if "mainnet" in s:
        sys.exit("refusing to run: ALGOD_SERVER looks like MainNet")
    if "testnet" not in s:
        sys.exit(
            "refusing to run: ALGOD_SERVER must be a TestNet endpoint "
            f"(got {algod_server!r})"
        )


def algod_client() -> tuple[algod_mod.AlgodClient, str]:
    server = os.environ.get("ALGOD_SERVER", "https://testnet-api.algonode.cloud")
    token = os.environ.get("ALGOD_TOKEN", "")
    require_testnet(server)
    return algod_mod.AlgodClient(token, server), server


def load_account() -> tuple[str, str]:
    """Return (address, private_key). Mnemonic stays in env / memory."""
    m = os.environ.get("DEPLOYER_MNEMONIC", "").strip()
    if m:
        pk = mnemonic.to_private_key(m)
        return account.address_from_private_key(pk), pk
    pk = account.generate_account()[0]
    addr = account.address_from_private_key(pk)
    print(f"ephemeral TestNet account (mnemonic not written): {addr}", file=sys.stderr)
    return addr, pk


def compile_contract(client: algod_mod.AlgodClient) -> tuple[bytes, bytes, dict]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
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

    approval_teal = next(ARTIFACT_DIR.glob("*approval.teal"))
    clear_teal = next(ARTIFACT_DIR.glob("*clear.teal"))
    spec_path = next(
        p
        for p in (
            *ARTIFACT_DIR.glob("*.arc32.json"),
            *ARTIFACT_DIR.glob("*.arc56.json"),
        )
    )
    spec = json.loads(spec_path.read_text())
    approval = client.compile(approval_teal.read_text())["result"]
    clear = client.compile(clear_teal.read_text())["result"]
    import base64

    return base64.b64decode(approval), base64.b64decode(clear), spec


def schema_from_spec(spec: dict) -> tuple[transaction.StateSchema, transaction.StateSchema]:
    # arc56: spec["state"]["schema"]["global"]["ints"/"bytes"]
    # arc32: spec["state"]["global"]["num_uints"]
    state = spec.get("state") or {}
    schema = state.get("schema") or spec.get("schema") or {}
    g = schema.get("global") or state.get("global") or {}
    loc = schema.get("local") or state.get("local") or {}
    g_uints = int(g.get("num_uints", g.get("ints", 7)))
    g_bytes = int(g.get("num_byte_slices", g.get("bytes", 1)))
    l_uints = int(loc.get("num_uints", loc.get("ints", 0)))
    l_bytes = int(loc.get("num_byte_slices", loc.get("bytes", 0)))
    return (
        transaction.StateSchema(g_uints, g_bytes),
        transaction.StateSchema(l_uints, l_bytes),
    )


def sp_window(client: algod_mod.AlgodClient, fee: int = 2_000) -> transaction.SuggestedParams:
    sp = client.suggested_params()
    sp.flat_fee = True
    sp.fee = fee
    last = client.status()["last-round"]
    sp.first = last
    sp.last = last + 1_000
    return sp


def wait_for(client: algod_mod.AlgodClient, txid: str) -> dict:
    return transaction.wait_for_confirmation(client, txid, 8)


def create_app(
    client: algod_mod.AlgodClient, addr: str, pk: str, approval: bytes, clear: bytes, spec: dict
) -> int:
    gschema, lschema = schema_from_spec(spec)
    extra = max(0, (len(approval) - 1) // 2048)
    sp = sp_window(client, fee=2_000 + 1_000 * extra)
    txn = transaction.ApplicationCreateTxn(
        sender=addr,
        sp=sp,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=gschema,
        local_schema=lschema,
        app_args=[CREATE.get_selector()],
        extra_pages=extra,
    )
    stx = txn.sign(pk)
    txid = client.send_transaction(stx)
    info = wait_for(client, txid)
    app_id = info["application-index"]
    print(f"created app {app_id} txid={txid}")
    return int(app_id)


def method_call(
    client: algod_mod.AlgodClient,
    addr: str,
    pk: str,
    app_id: int,
    method: Method,
    args: list,
    *,
    foreign_apps: list[int] | None = None,
    foreign_accounts: list[str] | None = None,
    extra_fee: int = 0,
) -> dict:
    signer = AccountTransactionSigner(pk)
    sp = sp_window(client, fee=2_000 + extra_fee)
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id=app_id,
        method=method,
        sender=addr,
        sp=sp,
        signer=signer,
        method_args=args,
        foreign_apps=foreign_apps or [],
        accounts=foreign_accounts or [],
    )
    result = atc.execute(client, 8)
    txid = result.tx_ids[-1]
    print(f"{method.name} txid={txid} return={result.abi_results[-1].return_value!r}")
    return {"txid": txid, "return": result.abi_results[-1].return_value}


def fund_app(
    client: algod_mod.AlgodClient, addr: str, pk: str, app_id: int, amount: int
) -> dict:
    signer = AccountTransactionSigner(pk)
    app_addr = get_application_address(app_id)
    sp = sp_window(client, fee=2_000)
    pay = transaction.PaymentTxn(sender=addr, sp=sp, receiver=app_addr, amt=amount)
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id=app_id,
        method=FUND,
        sender=addr,
        sp=sp_window(client, fee=2_000),
        signer=signer,
        method_args=[TransactionWithSigner(pay, signer)],
    )
    result = atc.execute(client, 8)
    txid = result.tx_ids[-1]
    print(f"fund txid={txid} locked={result.abi_results[-1].return_value!r}")
    return {"txid": txid, "return": result.abi_results[-1].return_value}


def try_dispenser(addr: str) -> bool:
    """Best-effort unattended TestNet faucets. Returns True if balance likely moved."""
    import urllib.error
    import urllib.request

    attempts: list[tuple[str, object]] = []

    def post_json(url: str, payload: dict, headers: dict | None = None) -> tuple[int, str]:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read().decode()[:500]
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:500] if e.fp else ""
            return e.code, body
        except Exception as e:  # noqa: BLE001
            return 0, str(e)

    # Legacy AWS dispenser (often closed / captcha).
    attempts.append(
        (
            "aws",
            post_json(
                "https://dispenser.testnet.aws.algodev.network/dispense",
                {"address": addr},
            ),
        )
    )
    # bank.testnet redirects to Lora (captcha); still try a POST.
    attempts.append(
        (
            "bank",
            post_json("https://bank.testnet.algorand.network", {"address": addr}),
        )
    )
    token = os.environ.get("ALGOKIT_DISPENSER_ACCESS_TOKEN", "").strip()
    if token:
        attempts.append(
            (
                "algokit",
                post_json(
                    "https://api.dispenser.algorandfoundation.tools/fund/0",
                    {"receiver": addr, "amount": 5_000_000},
                    {"Authorization": f"Bearer {token}"},
                ),
            )
        )
    for name, result in attempts:
        print(f"dispenser {name}: {result}", file=sys.stderr)
        status, _body = result
        if status == 200:
            return True
    return False


def wait_funded(client: algod_mod.AlgodClient, addr: str, min_micro: int, timeout_s: int = 90) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        info = client.account_info(addr)
        if int(info.get("amount", 0)) >= min_micro:
            return True
        time.sleep(3)
    return int(client.account_info(addr).get("amount", 0)) >= min_micro


def cmd_create(args: argparse.Namespace) -> int:
    _load_dotenv()
    client, server = algod_client()
    print(f"algod {server}", file=sys.stderr)
    addr, pk = load_account()
    info = client.account_info(addr)
    bal = int(info.get("amount", 0))
    print(f"balance {bal} µALGO", file=sys.stderr)
    need = 3_000_000
    if bal < need:
        print("trying unattended dispensers…", file=sys.stderr)
        try_dispenser(addr)
        if not wait_funded(client, addr, need, timeout_s=60):
            print(
                "not done: account unfunded. Fund this TestNet address from a "
                f"public dispenser, then re-run: {addr}",
                file=sys.stderr,
            )
            return 2
    approval, clear, spec = compile_contract(client)
    app_id = create_app(client, addr, pk, approval, clear, spec)
    method_call(
        client, addr, pk, app_id, SET_KEEPER, [KEEPER_APP_ID], foreign_apps=[KEEPER_APP_ID]
    )
    last = client.status()["last-round"]
    duration = int(args.duration)
    method_call(
        client,
        addr,
        pk,
        app_id,
        CONFIGURE,
        [addr, last, duration],
        foreign_accounts=[addr],
    )
    lock = int(args.lock_micro)
    fund_app(client, addr, pk, app_id, APP_BASE_MBR + lock)
    print(f"APP_ID={app_id}")
    print(f"APP_ADDRESS={get_application_address(app_id)}")
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    _load_dotenv()
    client, _ = algod_client()
    addr, pk = load_account()
    app_id = int(args.app_id)
    result = method_call(client, addr, pk, app_id, CLAIM, [], extra_fee=1_000)
    print(f"CLAIM_TXID={result['txid']}")
    print(f"CLAIM_AMOUNT={result['return']}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="TestNet-only vesting deploy / claim")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="compile, create (zero args), set_keeper, configure, fund")
    c.add_argument("--duration", type=int, default=90, help="vest duration in rounds")
    c.add_argument("--lock-micro", type=int, default=1_000_000, help="principal µALGO (excludes MBR)")
    c.set_defaults(func=cmd_create)
    k = sub.add_parser("claim", help="beneficiary pull; covers inner fee")
    k.add_argument("--app-id", required=True, type=int)
    k.set_defaults(func=cmd_claim)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
