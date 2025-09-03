[# 05 – Deploy FutarchyArbExecutorV5 ◐]

## Goal

Deploy the FutarchyArbExecutorV5 contract with the owner set to a specific HD path EOA, wired into the setup CLI. Provide dry‑run planning, preflight checks, optional auto‑funding of the deployer, and clear logs/artifacts.

## Context

- Contract: `contracts/FutarchyArbExecutorV5.sol`
  - Constructor sets `owner = msg.sender` (no constructor args). The deploy transaction must be signed by the intended owner EOA.
  - Ownership can be transferred post‑deploy, but primary flow is “deploy from owner”.
- We already support ensuring HD paths and funding xDAI; we will reuse these patterns to derive/create the deployer account and ensure it has gas.

## Deliverables

- `src/setup/deploy_v5.py`:
  - Compile V5 with `solcx` (>= 0.8.24), return ABI/bytecode.
  - Derive deployer `LocalAccount` from mnemonic + `--path` (or decrypt from keystore if provided).
  - Preflight checks: RPC connectivity, chainId, EIP‑1559 (or `--legacy`), gas estimate with buffer, deployer xDAI balance sufficiency.
  - Optional: auto‑fund deployer with `--fund-xdai <amount>` using existing funding flow.
  - Deploy (or dry‑run), await receipt, write artifacts and JSON log.
  - Save ABI to `src/config/abis/FutarchyArbExecutorV5.json`; optionally update an env file with the address.
- `src/setup/cli.py`:
  - New subcommand `deploy-v5` with flags below.

## CLI

- `python -m src.setup.cli deploy-v5 --path "m/44'/60'/0'/0/5" [--ensure-path] [--mnemonic|--mnemonic-env] [--keystore-pass|--keystore-pass-env] [--fund-xdai 0.02 --funder-env FUNDER_PRIVATE_KEY] [--rpc-url ...] [--chain-id 100] [--dry-run] [--confirm] [--legacy|--max-fee-gwei 2 --priority-fee-gwei 1] [--timeout 300] [--log <path>]`

Flags:
- `--path`: Required HD path for the deployer EOA (owner = msg.sender).
- `--ensure-path`: Create keystore/index for `--path` if missing (no secrets in index).
- `--mnemonic|--mnemonic-env`: Source for HD derivation when ensuring/deriving.
- `--keystore-pass|--keystore-pass-env`: Password resolution when writing keystore (reuse existing resolver; mnemonic derivation doesn’t require it).
- `--fund-xdai <eth>`: If deployer xDAI is insufficient, top up from `--funder-env` before deployment.
- Network/gas: `--env-file`, `--rpc-url`, `--chain-id`, `--legacy|--max-fee-gwei/--priority-fee-gwei`, `--timeout`.
- Safety: `--dry-run` writes a plan; `--confirm` required to broadcast.

## Workflow

1) Load env (`--env-file`), resolve RPC/chain.
2) Ensure/derive the deployer account for `--path` (mnemonic required if not present).
3) Preflight:
   - RPC connectivity and expected `chainId`.
   - EIP‑1559 support (unless `--legacy`).
   - Compile V5, estimate gas with buffer; compute max fees and total cost.
   - Check deployer xDAI balance; optionally auto‑fund if `--fund-xdai` is provided.
4) Dry‑run: emit a deployment plan JSON (owner addr/path, gas settings, cost estimate).
5) Deploy (with `--confirm`): sign constructor tx from deployer; send; wait for receipt.
6) Artifacts/logs: write ABI JSON, deployment log `build/wallets/deploy_v5_<timestamp>.json`, and optionally update an env file with the deployed address.

## Validation

- Strict early failures: missing mnemonic when ensuring path; chainId mismatch; RPC not reachable; insufficient xDAI without `--fund-xdai`; EIP‑1559 unsupported unless `--legacy`.
- Gas guardrails: require sane gas limit and clear cost estimates before sending.
- Deterministic: if re‑run with `--dry-run` only, no network state changes.

## Risks & Mitigations

- Wrong owner: Always display `owner=<address>` derived from `--path` before sending; require `--confirm`.
- Insufficient gas: auto‑fund path or abort early with a precise message.
- Compiler/tooling drift: pin `solc` (>= 0.8.24) and display version in logs.

## Acceptance Criteria

- Can deploy FutarchyArbExecutorV5 on Gnosis with owner as the HD path EOA.
- Dry‑run shows owner/path, gas/cost estimates, and plan log.
- Optional auto‑funding successfully tops up the deployer and proceeds.
- ABI saved, JSON log written, and (optional) env updated with the address.

## Examples

- Dry‑run (plan only):
  - `python -m src.setup.cli deploy-v5 --path "m/44'/60'/0'/0/5" --env-file .env.seed --dry-run`
- Deploy (confirm, EIP‑1559 gas):
  - `python -m src.setup.cli deploy-v5 --path "m/44'/60'/0'/0/5" --env-file .env.seed --max-fee-gwei 2 --priority-fee-gwei 1 --confirm`
- Ensure path and auto‑fund deployer if needed:
  - `python -m src.setup.cli deploy-v5 --path "m/44'/60'/0'/0/7" --ensure-path --mnemonic-env MNEMONIC --env-file .env.seed --fund-xdai 0.02 --funder-env FUNDER_PRIVATE_KEY --confirm`

