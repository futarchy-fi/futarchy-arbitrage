# 04 – Fund ERC20 (sDAI) ◐

Implements ERC20 (sDAI) funding with decimals handling, preflight checks, EIP‑1559/legacy gas, dry‑run planning, and JSON logging. Parity with `fund-xdai` including `--only-path`, `--ensure-path`, and `--always`.

## Module

- `src/setup/fund_erc20.py`
  - Minimal ERC20 ABI: `decimals`, `balanceOf`, `transfer`.
  - Reads recipients from `index.json` or scans `--out` for `0x*.json`.
  - Computes amounts in token base units using on-chain `decimals` (fallback 18).
  - Preflight: funder token balance, native balance for gas, RPC connectivity, chainId, gas sanity.
  - Dry‑run emits a plan JSON; execution writes final results with receipts.

## CLI

- `python -m src.setup.cli fund-sdai --amount 5.0 [--token $SDAI_ADDR] --from-env FUNDER_PRIVATE_KEY [--rpc-url ...] [--chain-id 100] [--only <csv|glob>] [--only-path <glob>] [--ensure-path <csv>] [--mnemonic|--mnemonic-env] [--keystore-pass|--keystore-pass-env] [--always] [--dry-run] [--confirm] [--max-fee-gwei 2 --priority-fee-gwei 1 | --legacy --gas-price-gwei 1] [--gas-limit 90000] [--timeout 120] [--log <path>]`

Behavior:
- `--only` filters by address; `--only-path` filters by HD path (exact or glob).
- `--ensure-path` ensures specified HD paths exist (creates keystore + index if missing); without `--only*`, defaults to funding just those ensured paths.
- `--always` sends exactly `--amount` to each selected address (does not top-up).

Log output:
- Default: `build/wallets/funding_<timestamp>.json` with summary (token, decimals, target units, gas budget, sufficiency flags) and per‑recipient results (before/after in base units, delta, tx hash, status).

## Verification

1) Prepare wallets and a funder key in `.env`:
- `python -m src.setup.cli generate --mode random --count 2 --out build/wallets`
- `printf "FUNDER_PRIVATE_KEY=0x...\nSDAI_TOKEN_ADDRESS=0x...\nRPC_URL=https://rpc.gnosischain.com\n" > .env.sdai`

2) Dry‑run plan (no txs):
- `python -m src.setup.cli fund-sdai --amount 5 --env-file .env.sdai --from-env FUNDER_PRIVATE_KEY --out build/wallets --dry-run`

3) Execute with confirmation:
- `python -m src.setup.cli fund-sdai --amount 5 --env-file .env.sdai --from-env FUNDER_PRIVATE_KEY --out build/wallets --confirm`

4) Ensure and fund specific HD paths (exact send each time):
- `python -m src.setup.cli fund-sdai --amount 5 --env-file .env.seed --ensure-path "m/44'/60'/0'/0/5,m/44'/60'/0'/0/7" --always --confirm`

Notes:
- Defaults to EIP‑1559 on Gnosis; use `--legacy` if your provider requires `gasPrice`.
- Safety: Aborts if funder token or native balance is insufficient for total + gas.
- Fast‑fail checks: RPC connectivity, chainId mismatch, EIP‑1559 support (unless `--legacy`), and ERC20 transfer gas limit sanity.

## Unified CLI (bonus)

Use `fund-all` to ensure paths (optional) and fund both xDAI and sDAI in one command:

- `python -m src.setup.cli fund-all --env-file .env.seed --ensure-path "m/44'/60'/0'/0/5,m/44'/60'/0'/0/7" --xdai 0.01 --sdai 5 --confirm`

