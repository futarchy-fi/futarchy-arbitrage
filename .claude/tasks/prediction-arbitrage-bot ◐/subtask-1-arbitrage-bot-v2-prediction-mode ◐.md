# Subtask 1 — BOT_TYPE=prediction in arbitrage_bot_v2

Status: ◐ In Progress

## Objective
Add a new bot mode to `src/arbitrage_commands/arbitrage_bot_v2.py` that sets `BOT_TYPE=prediction` and delegates on-chain execution to `src.executor.prediction_arb_executor` (PredictionArbExecutorV1). In this mode, the bot does not fetch or compare prices; the executor performs the buy/sell/no-op decision and enforces profit guard on-chain.

## Scope
- Only modify `arbitrage_bot_v2` and its config plumbing.
- Do not change `prediction_arb_executor` logic (the bot will just call it).
- Preserve current behavior for other modes (`balancer`, `kleros`/`pnk`).

## Steps
1) Config support
- Accept `bot.type = "prediction"` (from JSON or env `BOT_TYPE`).
- Add optional `contracts.executor_prediction_v1` (env: `PREDICTION_ARB_EXECUTOR_V1` / `PREDICTION_EXECUTOR_V1_ADDRESS`).
- Ensure `to_env_dict()` exports all env vars that `prediction_arb_executor` needs (currency + YES/NO currency tokens, prediction pools, routers, proposal, and executor address if provided).

2) Executor address resolution
- In `get_executor_address()`, branch by `bot.type`:
  - For `prediction`: use `contracts.executor_prediction_v1` if set; else fallback to latest `deployments/deployment_prediction_arb_v1_*.json`.
  - For others: keep V5 discovery as-is.
- Use this address for pre/post sDAI balance snapshots.

3) Validation rules
- If `bot.type=prediction`, require minimal inputs:
  - `wallet.private_key`, `network.rpc_url`, `proposal.address`
  - Tokens: `proposal.tokens.currency.address`, `proposal.tokens.yes_currency.address`, `proposal.tokens.no_currency.address`
  - Pools: `proposal.pools.swapr_yes_currency_currency.address`, `proposal.pools.swapr_no_currency_currency.address`
  - Routers: `contracts.routers.swapr`, `contracts.routers.futarchy`
- Do not require Balancer pool or company token pools in prediction mode.

4) Run loop branching
- If `bot.type=prediction`:
  - Skip `fetch_prices()` and `determine_opportunity()`.
  - Optionally still print pre/post balances and compute net sDAI delta.
  - Invoke `prediction_arb_executor` via subprocess every iteration with `--amount`, `--min-profit`, `--prefund`, and `--env` if available.
  - Optionally pass `--force-flow {buy|sell}` when `bot.run_options.force_flow` is set (for manual forcing).
- Otherwise, keep current flow intact.

5) Execution path wiring
- In `execute_arbitrage()`, branch module selection by `bot.type`:
  - `prediction` → `module = "src.executor.prediction_arb_executor"` and build args: `--amount`, `--min-profit`, `--prefund`, `--env`, `[--force-flow ...]`.
  - Non-prediction → current modules remain.
- Reuse existing env merging and `parse_tx_hash()` to surface tx hash links.

6) Logging & UX
- On startup in prediction mode, print: "Prediction mode: delegating to prediction_arb_executor (no price checks in bot)."
- If executor returns 0 without a tx hash, print: "No-op executed by executor (sum ~= 1)."
- Keep pre/post executor sDAI balance reporting and summary (profit vs `min_profit`).

7) CLI (optional)
- Add `--bot-type` to override config/env with `prediction`.
- Add `--force-flow {buy|sell}` to populate `bot.run_options.force_flow` (prediction mode only).

## Edge Cases
- Missing executor address: actionable error → "Set PREDICTION_ARB_EXECUTOR_V1 or deploy and keep a deployments file".
- Prefunding: leave to `prediction_arb_executor` (`--prefund` flag forwarded).
- Amount semantics: SELL splits `amount` base; BUY performs exact-out `amount` per leg—document in README.
- Timeout/errors: treat like existing executors (summarize stderr on unexpected failures).

## Acceptance Criteria
- `BOT_TYPE=prediction` loop runs without calling price fetchers.
- Subprocess calls `src.executor.prediction_arb_executor` with correct args and env; supports `--prefund` and `--force-flow` passthrough.
- Pre/post sDAI balances are reported against `PredictionArbExecutorV1` address.
- No-op iterations (sum == 1) do not error and continue cleanly.
- Works with both JSON and `.env` configurations.

## Out of Scope
- Changing prediction executor logic or on-chain contract.
- Adding new slippage/tolerance logic (executor already guards via on-chain profit check).

## Done When
- Code merged with unit/integration smoke test (manual) using a small `--amount` and `--min-profit <= 0` on a live or forked RPC, demonstrating at least one tx and one no-op iteration.
