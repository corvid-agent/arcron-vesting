# arcron-vesting

Scheduled TestNet release of a locked ALGO balance to a beneficiary — pull-not-push, driven by Arcron keeper 769891898.

## Live proof

**not done** — this commit ships the compiling contract, CI, Pages stub, and scripts. Live TestNet create / register / execute / claim were not confirmed, so ids are zeros. Never invent txids.

| item | value |
|------|-------|
| app id | **not done** |
| upkeep id on 769891898 | **not done** |
| execute txid (keeper called `accrue`) | **not done** |
| claim txid (beneficiary pulled) | **not done** |
| Pera TestNet explorer | **not done** |
| Pages | https://corvid-agent.github.io/arcron-vesting/ (publishes `docs/` from `main` after merge) |

See `docs/deploy.json`.

## How to run

TestNet only. Use a throwaway account and a public TestNet dispenser. Do not put a mnemonic in this sketch or in git.

1. `pip install puyapy py-algorand-sdk`
2. Compile: `puyapy smart_contracts/vesting/contract.py --out-dir smart_contracts/artifacts/vesting`
3. Create with **ZERO** args (`create()void`). Do not pass a uint64. Mapping every uint64 onto 769891898 would freeze a cadence at ~68 years.
4. `set_keeper(Application(769891898))` — pass the application, store `.id`. Auth on the hook is `Application(keeper_app).address`, never `itob(keeper_id)`.
5. `configure(beneficiary, start_round, duration_rounds)` — creator, once. `duration_rounds > 0`. Window is in rounds, not wall-clock.
6. `fund(payment)` — payment to the app, no rekey/close. First 100_000 µALGO is app MBR and is **not** locked. Remainder is principal.
7. Register on keeper 769891898 with **SKIP_AHEAD** (1). Do **not** pass `CATCH_UP=0`. `interval_rounds=30`, `fee_per_execution=4000`, `call_args=[sha512_256(b"accrue()uint64")[:4]]`, `fee_cap=0`, `fee_asset=0`. Fund enough for several executions (e.g. 40_000) plus box MBR (`2500 + 400*139` plus 400 × encoded `byte[][]`).
8. Wait for a keeper to `execute`. Then `claim()` as the beneficiary. Cover the inner payment with `extra_fee` on the outer call (`itxn.Payment(..., fee=0)`).

Scripts (refuse unless `ALGOD_SERVER` is TestNet):

```
python scripts/deploy.py create --duration 90 --lock-micro 1000000
python scripts/register.py register --app-id <id> --interval 30 --funding 40000
python scripts/register.py wait --app-id <id>
python scripts/deploy.py claim --app-id <id>
```

If `DEPLOYER_MNEMONIC` is unset the scripts keep an ephemeral key in memory and print the address to fund from a dispenser.

## Measured cost

| item | µALGO |
|------|-------|
| box MBR (4-byte selector) | `BOX_MBR_FIXED + 400 * len(encoded call_args)` ≈ 62,100 (`2,500 + 400×139` plus the `byte[][]` tail) |
| per execution | 4,000 (`MIN_UPKEEP_FEE`) |
| demo escrow | 40,000 → 10 executions |
| app MBR held back from `locked` | 100,000 |
| live spend | **not done** (no confirmed TestNet deploy in this commit) |

## What does not work

- The hook **cannot push ALGO**. Arcron's inner call only reaches resources the keeper named; the hook moves nothing, calls nothing, and names no extra accounts. The beneficiary is not an available resource. That is why crediting is accounting and `claim()` is a pull.
- If `accrue` never runs, claimable stays 0 even after the vest clock. This demo is hook-credits-only: a missed hook means the beneficiary waits. `claim` does not recompute the vest.
- TestNet keeper 769891898 may be late. Interval 30 is the demo floor so ordinary lateness is not treated as a signal. Arcron min is 10.
- No MainNet. Scripts refuse a MainNet algod URL.

## Honesty block

Unaudited. TestNet only. Upgradeable keeper is a rug vector: the creator can `set_keeper` again and retarget (including stalling credit so the beneficiary never becomes claimable). Throwaway dispenser. Not a product. Do not send real funds.
