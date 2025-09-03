# Wallet Setup and Funding Modules

## Goal

- Create modules under `src/setup` to generate wallets, securely store their private keys, and fund them with specified amounts of native xDAI and ERC20 sDAI.

## Scope

- Wallet generation (N new or from provided keys).
- Secure storage (encrypted keystores; optional env emission with explicit opt-in).
- Funding flows: native xDAI and ERC20 sDAI, with idempotent top-up behavior.
- CLI entrypoints for generation and funding operations.
- Pre-flight validation, balance checks, logging, and dry-run support.

## Deliverables

- `src/setup/wallet_manager.py` – wallet create/import, load/save, list.
- `src/setup/keystore.py` – keystore encrypt/decrypt helpers and I/O.
- `src/setup/fund_xdai.py` – native token funding logic with nonce/gas handling.
- `src/setup/fund_erc20.py` – ERC20 funding logic (sDAI) with decimals handling.
- `src/setup/cli.py` – unified CLI: generate, fund-xdai, fund-sdai, fund-all, list.
- Task logs: `build/wallets/funding_<timestamp>.json`.
- Documentation updates in this task file and brief usage notes in README if needed.

## Architecture

- Config sources: JSON config and/or .env (aligned with repo), with CLI overrides.
- Web3 connection via existing `config.network.DEFAULT_RPC_URLS` fallback; default chainId=100.
- Minimal ERC20 ABI (`balanceOf`, `transfer`, `decimals`).
- Storage layout:
  - Encrypted keystores: `build/wallets/<address>.json`.
  - Index: `build/wallets/index.json` (addresses, metadata; no secrets).
  - Optional per-wallet env files only with `--emit-env`.

## CLI Design

- `python -m src.setup.cli generate --count 10 [--prefix teamA] [--keystore-pass <pass>|--keystore-pass-env WALLET_KEYSTORE_PASSWORD] [--emit-env] [--force]`
- `python -m src.setup.cli list [--keystore-dir build/wallets]`
- `python -m src.setup.cli fund-xdai --amount 0.01 --from-env FUNDER_PRIVATE_KEY [--rpc-url ...] [--max-fee-gwei 2] [--dry-run] [--only <csv|glob>] [--only-path <glob>] [--ensure-path <csv>] [--mnemonic|--mnemonic-env] [--keystore-pass|--keystore-pass-env] [--always]`
- `python -m src.setup.cli fund-sdai --amount 5.0 [--token $SDAI_ADDR] --from-env FUNDER_PRIVATE_KEY [--rpc-url ...] [--dry-run] [--only <csv|glob>] [--only-path <glob>] [--ensure-path <csv>] [--mnemonic|--mnemonic-env] [--keystore-pass|--keystore-pass-env] [--always]`
- `python -m src.setup.cli fund-all --xdai 0.01 --sdai 5.0 [--token $SDAI_ADDR] --from-env FUNDER_PRIVATE_KEY [--rpc-url ...] [--dry-run] [--only <csv|glob>] [--only-path <glob>] [--ensure-path <csv>] [--mnemonic|--mnemonic-env] [--keystore-pass|--keystore-pass-env] [--always]`

Common flags: `--rpc-url`, `--chain-id`, `--keystore-dir`, `--index`, `--batch-size`, `--timeout`, `--confirm`.

## Funding Workflow

1. Read recipients from keystore index (or explicit list via `--only`).
2. Pre-flight checks:
   - RPC connectivity and expected `chainId`.
   - Funder’s xDAI and sDAI balances sufficient for requested totals + gas.
3. For each recipient:
   - Query current balances.
   - Compute transfer amount: top-up to target (default) or send exact `--amount` with `--always`.
   - Build and send transactions with sequential nonce management per funder.
   - Await receipts with timeout and basic retry/backoff.
4. Emit per-recipient results (before → after, deltas, tx hashes) and aggregate summary.

## Safety & Security

- Default encrypted keystores; require password via CLI flag or env; never log private keys.
- Plaintext `.env.<address>` only with `--emit-env` and explicit warning.
- `--dry-run` for previewing actions and totals.
- Per-tx gas cap and total outflow confirmation (`--confirm`) for large batches.
- Option to migrate plaintext env keys to encrypted keystores (`--encrypt-existing`).

## Validation & Reporting

- Early fast‑fail: RPC connectivity, expected `chainId`, EIP‑1559 support (unless legacy), gas limit sanity (>=21000).
- Validate ERC20 decimals (fallback 18 if call fails); amount normalization.
- Pre/post balance checks for recipients; skip idempotently when funded (unless `--always`).
- Write JSON log to `build/wallets/funding_<timestamp>.json` with inputs, outcomes, failures (includes `always` flag).

## Implementation Plan

- [x] 01 Keystore: helpers + progressive CLI (see subtask-1-keystore ✅.md).
- [x] 02 Wallet Manager: gen/import/index + CLI (see subtask-2-wallet-manager ✅.md).
- [x] 03 Fund xDAI: native token funding + CLI (see subtask-3-fund-xdai ✅.md).
- [x] 04 Fund ERC20: sDAI funding + CLI (see subtask-4-fund-erc20.md).
- [x] Integrations: validations, summaries, JSON logging; unified `fund-all` CLI.
- [ ] 05 Deploy V5: owner=HD path + CLI (see subtask-5-deploy-v5 ◐.md).
- [ ] Docs: usage examples, cautions, and config notes.

## Current Status (Subtask 1)

- HD keystore support implemented: derive from mnemonic + path, create encrypted keystores.
- .env integration: `--env-file` supported for resolving `MNEMONIC`, `WALLET_KEYSTORE_PASSWORD`, and `PRIVATE_KEY`.
- New one-shot command: `hd-new` generates an in-memory mnemonic and temporary password, derives N accounts, and writes keystores.
- See subtask-1-keystore ✅.md for verification commands and examples.

### Current CLI (keystore phase)

- `keystore-create`: from `--private-key`, `--private-key-env` (default `PRIVATE_KEY`), or `--random`; supports `--env-file`.
- `keystore-decrypt`: decrypt keystore; supports `--env-file` for password.
- `hd-derive`: derive from `--mnemonic` or `--mnemonic-env`; supports `--env-file` for mnemonic/password.
- `hd-new`: generate mnemonic+password in memory; derive `--count` at `--path-base`.

## Subtasks

1) Keystore – `.claude/tasks/wallet-setup-and-funding ◐/subtask-1-keystore ✅.md`
2) Wallet Manager – `.claude/tasks/wallet-setup-and-funding ◐/subtask-2-wallet-manager ✅.md`
3) Fund xDAI – `.claude/tasks/wallet-setup-and-funding ◐/subtask-3-fund-xdai.md`
4) Fund ERC20 – `.claude/tasks/wallet-setup-and-funding ◐/subtask-4-fund-erc20.md`

## Open Questions

- Prefer keystore-only by default, or mirror existing `.env.<address>` pattern by default?
- Support CSV address lists and per-address overrides for amounts?
- Any limits on batch size or rate (RPC/provider constraints)?

## Dependencies

- `web3`, `eth_account`, existing repo’s network config and sDAI address.
- Funder account with sufficient xDAI and sDAI balances.

## Risks & Mitigations

- Nonce conflicts in parallel sends → single-process sequential nonce; optional `--batch-size` throttling.
- Gas price spikes → `--max-fee-gwei` and retry with backoff.
- Token with non-18 decimals → dynamic decimals fetch with fallback.

## Acceptance Criteria

- Can generate N new wallets with encrypted keystores and index.
- Can fund selected wallets to target xDAI and sDAI balances with clear logs.
- Dry-run mode displays intended actions without sending transactions.
- No plaintext private keys produced unless explicitly requested.
