# arcron-vesting

Scheduled TestNet release of a locked ALGO balance to a beneficiary — pull-not-push, driven by Arcron keeper 769891898.

## Pull-not-push: accrue() is accounting only

The hook cannot push ALGO. Arcron `execute` inner-calls `accrue()` with the method selector only: no payment, no inner transaction, no extra accounts from the keeper. `accrue` only writes `credited` from the linear vest. The beneficiary pulls with `claim()` in their own transaction.


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

## LocalNet recreate (not TestNet)

Create, `set_keeper(Application(...))`, and a mock-keeper inner-call of `accrue()` were proven on AlgoKit LocalNet (`dockernet-v1`). That is **not** TestNet. Do **not** copy any LocalNet app id into `docs/deploy.json` or Pages. `appId` stays 0 until a real TestNet create.

LocalNet ids are ephemeral (DevMode / reset). They are not a product and they are not for GitHub Pages.
LocalNet proof for Pages lives in `docs/localnet.json` (CRT shows it when present). `docs/deploy.json` stays honest TestNet `appId: 0`.

```bash
# Docker daemon required
algokit localnet start
# wait until localhost:4001 /v2/status answers

pip install puyapy py-algorand-sdk
python scripts/localnet_recreate.py
# writes docs/localnet.json with network:"localnet" and the new appId
```

The script talks only to `localhost:4001` / `4002`, signs with the LocalNet KMD
`unencrypted-default-wallet` (never prints a mnemonic), refuses TestNet/MainNet
genesis ids, and never modifies `docs/deploy.json`.

DevMode holds last-round at 0 until the first tx. A successful create is a confirmed
`application-index` on genesis id `dockernet-v1`, not a TestNet explorer link.


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
- CI is compile + static hook tests, not a LocalNet execute.
- No TestNet create, no upkeep, no execute, no claim. Dispenser captcha/401. appId stays 0.
- Pages board stays NOT DEPLOYED until `docs/deploy.json` `appId` is flipped after a real create.
- If `accrue` never runs, claimable stays 0 even after the vest clock. This demo is hook-credits-only: a missed hook means the beneficiary waits. `claim` does not recompute the vest.
- TestNet keeper 769891898 may be late. Interval 30 is the demo floor so ordinary lateness is not treated as a signal. Arcron min is 10.
- No MainNet. Scripts refuse a MainNet algod URL.

## Honesty block

Unaudited. TestNet only. First-party demo, not a product. No MainNet path; scripts refuse a MainNet algod URL. Do not send mainnet funds. Keeper 769891898. Throwaway dispenser. Apache-2.0. Pull pattern: the schedule accounts; the beneficiary pulls; the hook cannot push. Hook is `accrue()`, zero args. Auth is `Application(keeper).address`, never `itob`. Upgradeable keeper is a rug vector: the creator can `set_keeper` again and retarget (including stalling credit so the beneficiary never becomes claimable).
