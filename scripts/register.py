#!/usr/bin/env python3
"""Register accrue()uint64 on live TestNet keeper 769891898. TestNet only.

Reconstructs the register group from CorvidLabs/arcron examples/register_upkeep.py
and docs/arcron.md public API — does not import KeeperClient (that would need a
clone). Group is [mbr_payment, funding_payment, register ABI call] with box
ref b"u"+itob(next_upkeep_id). Policy is SKIP_AHEAD (1). Never pass CATCH_UP=0
by accident.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from algosdk import account, mnemonic, transaction
from algosdk.abi import ABIType, Method
from algosdk.atomic_transaction_composer import (
    AccountTransactionSigner,
    AtomicTransactionComposer,
    TransactionWithSigner,
)
from algosdk.logic import get_application_address
from algosdk.v2client import algod as algod_mod
from algosdk.v2client import indexer as indexer_mod

ROOT = Path(__file__).resolve().parents[1]
KEEPER_APP_ID = 769891898
SKIP_AHEAD = 1
MIN_UPKEEP_FEE = 4_000
BOX_MBR_FIXED = 2_500 + 400 * 139
MAX_CALL_ARGS = 3
REGISTER = Method.from_signature(
    "register(pay,pay,uint64,byte[][],uint64,uint64,uint64,uint64,uint64,uint64)uint64"
)
HOOK = "accrue()uint64"


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def require_testnet(url: str) -> None:
    s = url.lower()
    if "mainnet" in s:
        sys.exit("refusing to run: endpoint looks like MainNet")
    if "testnet" not in s:
        sys.exit(f"refusing to run: endpoint must be TestNet (got {url!r})")


def algod_client() -> algod_mod.AlgodClient:
    server = os.environ.get("ALGOD_SERVER", "https://testnet-api.algonode.cloud")
    token = os.environ.get("ALGOD_TOKEN", "")
    require_testnet(server)
    return algod_mod.AlgodClient(token, server)


def indexer_client() -> indexer_mod.IndexerClient:
    server = os.environ.get("INDEXER_SERVER", "https://testnet-idx.algonode.cloud")
    token = os.environ.get("INDEXER_TOKEN", "")
    require_testnet(server)
    return indexer_mod.IndexerClient(token, server)


def load_account() -> tuple[str, str]:
    m = os.environ.get("DEPLOYER_MNEMONIC", "").strip()
    if m:
        pk = mnemonic.to_private_key(m)
        return account.address_from_private_key(pk), pk
    pk = account.generate_account()[0]
    addr = account.address_from_private_key(pk)
    print(f"ephemeral TestNet account (mnemonic not written): {addr}", file=sys.stderr)
    return addr, pk


def hook_selector() -> bytes:
    return hashlib.new("sha512_256", HOOK.encode()).digest()[:4]


def read_next_upkeep_id(client: algod_mod.AlgodClient) -> int:
    import base64

    info = client.application_info(KEEPER_APP_ID)
    for kv in info["params"].get("global-state", []):
        key = base64.b64decode(kv["key"]).decode("utf-8", "replace")
        if key == "next_upkeep_id":
            return int(kv["value"].get("uint", 0))
    sys.exit("could not read keeper global next_upkeep_id")


def sp_window(client: algod_mod.AlgodClient, fee: int = 3_000) -> transaction.SuggestedParams:
    sp = client.suggested_params()
    sp.flat_fee = True
    sp.fee = fee
    last = client.status()["last-round"]
    sp.first = last
    sp.last = last + 1_000
    return sp


def cmd_register(args: argparse.Namespace) -> int:
    _load_dotenv()
    client = algod_client()
    addr, pk = load_account()
    target = int(args.app_id)
    selector = hook_selector()
    call_args = [selector]
    if len(call_args) > MAX_CALL_ARGS:
        sys.exit("call_args exceeds MAX_CALL_ARGS")
    encoded = ABIType.from_string("byte[][]").encode([list(a) for a in call_args])
    mbr = BOX_MBR_FIXED + 400 * len(encoded)
    funding = int(args.funding)
    fee = MIN_UPKEEP_FEE
    if funding < fee:
        sys.exit("funding must cover at least one execution")
    next_id = read_next_upkeep_id(client)
    box_name = b"u" + next_id.to_bytes(8, "big")
    keeper_addr = get_application_address(KEEPER_APP_ID)
    print(
        f"registering {HOOK} on keeper {KEEPER_APP_ID} target={target} "
        f"predicted upkeep id={next_id} mbr={mbr} funding={funding} "
        f"policy=SKIP_AHEAD interval={args.interval}",
        file=sys.stderr,
    )
    signer = AccountTransactionSigner(pk)
    pay_sp = sp_window(client, fee=1_000)
    mbr_pay = transaction.PaymentTxn(sender=addr, sp=pay_sp, receiver=keeper_addr, amt=mbr)
    fund_pay = transaction.PaymentTxn(
        sender=addr, sp=pay_sp, receiver=keeper_addr, amt=funding
    )
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id=KEEPER_APP_ID,
        method=REGISTER,
        sender=addr,
        sp=sp_window(client, fee=3_000),
        signer=signer,
        method_args=[
            TransactionWithSigner(mbr_pay, signer),
            TransactionWithSigner(fund_pay, signer),
            target,
            call_args,
            int(args.interval),
            fee,
            SKIP_AHEAD,
            0,  # fee_cap
            0,  # fee_asset
            0,  # asset_fee
        ],
        boxes=[(KEEPER_APP_ID, box_name)],
        foreign_apps=[target],
    )
    result = atc.execute(client, 8)
    upkeep_id = result.abi_results[-1].return_value
    txid = result.tx_ids[-1]
    print(f"UPKEEP_ID={upkeep_id}")
    print(f"REGISTER_TXID={txid}")
    if int(upkeep_id) != next_id:
        print(
            f"warning: returned id {upkeep_id} != predicted {next_id}",
            file=sys.stderr,
        )
    return 0


def find_execute_txid(idx: indexer_mod.IndexerClient, app_id: int) -> str | None:
    """Find an inner app call to our app originating from the keeper app account."""
    keeper_addr = get_application_address(KEEPER_APP_ID)
    selector = hook_selector()
    # Search application txns involving our app, then look for inner calls.
    try:
        resp = idx.search_transactions(
            application_id=app_id,
            tx_type="appl",
            limit=50,
        )
    except Exception as e:  # noqa: BLE001
        print(f"indexer search failed: {e}", file=sys.stderr)
        return None
    for txn in resp.get("transactions", []):
        inners = txn.get("inner-txns") or txn.get("innerTxns") or []
        # Outer may be execute() on the keeper; walk inner tree.
        stack = list(inners)
        while stack:
            inner = stack.pop()
            stack.extend(inner.get("inner-txns") or inner.get("innerTxns") or [])
            if inner.get("tx-type") != "appl" and inner.get("txn", {}).get("type") != "appl":
                # indexer flattened vs nested
                pass
            appl = inner.get("application-transaction") or {}
            inner_app = appl.get("application-id")
            sender = inner.get("sender")
            args = appl.get("application-args") or []
            import base64

            arg0 = b""
            if args:
                try:
                    arg0 = base64.b64decode(args[0])
                except Exception:  # noqa: BLE001
                    arg0 = b""
            if inner_app == app_id and sender == keeper_addr and (
                not arg0 or arg0 == selector
            ):
                return txn.get("id") or ""
        # Some indexers hoist the inner as its own row with inner-id.
        sender = txn.get("sender")
        appl = txn.get("application-transaction") or {}
        if (
            sender == keeper_addr
            and appl.get("application-id") == app_id
        ):
            return txn.get("id") or txn.get("inner-tx-id") or ""
    return None


def cmd_wait(args: argparse.Namespace) -> int:
    _load_dotenv()
    idx = indexer_client()
    app_id = int(args.app_id)
    timeout = int(args.timeout)
    deadline = time.time() + timeout
    print(
        f"waiting up to {timeout}s for keeper execute of app {app_id}…",
        file=sys.stderr,
    )
    while time.time() < deadline:
        txid = find_execute_txid(idx, app_id)
        if txid:
            print(f"EXECUTE_TXID={txid}")
            return 0
        time.sleep(8)
    print("not done: no execute txid found in the wait window", file=sys.stderr)
    return 2


def main() -> int:
    p = argparse.ArgumentParser(description="TestNet-only Arcron register / wait")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register", help="register accrue()uint64 with SKIP_AHEAD")
    r.add_argument("--app-id", required=True, type=int)
    r.add_argument("--interval", type=int, default=30)
    r.add_argument("--funding", type=int, default=40_000)
    r.set_defaults(func=cmd_register)
    w = sub.add_parser("wait", help="poll indexer for keeper execute txid")
    w.add_argument("--app-id", required=True, type=int)
    w.add_argument("--timeout", type=int, default=900, help="seconds")
    w.set_defaults(func=cmd_wait)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
