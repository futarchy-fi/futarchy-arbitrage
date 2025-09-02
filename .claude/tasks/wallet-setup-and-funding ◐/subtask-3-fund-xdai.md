# 03 – Fund xDAI ✅

Implements native xDAI top-ups with sequential nonce management, gas controls (EIP‑1559 or legacy), dry‑run planning, and JSON logging.

## Module

- `src/setup/fund_xdai.py`
  - `fund_xdai(...)` entrypoint used by CLI.
  - Web3 setup from `--rpc-url` or `RPC_URL|GNOSIS_RPC_URL` with POA middleware.
  - Reads recipients from `index.json` or scans `--out` for `0x*.json`.
  - Idempotent top‑up to reach `--amount` per wallet (skip if already ≥ target).
  - Preflight balance check for funder: value + worst‑case gas.
  - Dry‑run emits a plan JSON; execution writes final results with receipts.

## CLI

- `python -m src.setup.cli fund-xdai --amount 0.01 --from-env FUNDER_PRIVATE_KEY [--env-file .env] [--rpc-url ...] [--chain-id 100] [--only <csv|glob>] [--dry-run] [--confirm] [--max-fee-gwei 2 --priority-fee-gwei 1 | --legacy --gas-price-gwei 1] [--gas-limit 21000] [--timeout 120] [--log <path>]`

Behavior:
- Without `--confirm`, the command writes a plan JSON and exits (no txs).
- With `--confirm`, it sends transfers sequentially, waiting for receipts.
- `--only` accepts CSV of addresses or glob pattern on checksum addresses (e.g., `0xAbc*`).

Log output:
- Default: `build/wallets/funding_<timestamp>.json` with summary and per‑recipient results (before/after, delta, tx hash, status).

## Verification

1) Prepare wallets and a funder key in `.env`:
- `python -m src.setup.cli generate --mode random --count 2 --out build/wallets`
- `printf "FUNDER_PRIVATE_KEY=0x...\nRPC_URL=https://rpc.gnosischain.com\n" > .env.fx`

2) Dry‑run plan (no txs):
- `python -m src.setup.cli fund-xdai --amount 0.01 --env-file .env.fx --from-env FUNDER_PRIVATE_KEY --out build/wallets --dry-run`

3) Execute with confirmation:
- `python -m src.setup.cli fund-xdai --amount 0.01 --env-file .env.fx --from-env FUNDER_PRIVATE_KEY --out build/wallets --confirm`

Notes:
- Defaults to EIP‑1559 on Gnosis; use `--legacy` if your provider requires `gasPrice`.
- Safety: Will abort if funder balance is insufficient for value + max gas.

