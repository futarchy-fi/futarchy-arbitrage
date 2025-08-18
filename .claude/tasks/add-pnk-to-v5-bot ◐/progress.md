# PNK Integration into FutarchyArbExecutorV5 — Progress

Summary
- Goal: add isolated PNK buy/sell flows (sDAI↔WETH↔PNK) and integrate them into a new, complete arbitrage flow without altering existing behavior.

Status Snapshot
- Subtask 1 (constants & route): ✅ Completed
- Subtask 2 (buy sDAI→WETH→PNK): ✅ Completed — `buyPnkWithSdai` implemented; integrated into SELL flow (Step 2). BUY path now sells PNK back to sDAI in the same tx when `comp==PNK` (inline call to `sellPnkForSdai` inside `buy_conditional_arbitrage_balancer`).
- Subtask 3 (sell PNK→WETH→sDAI): ✅ Completed — helper implemented and validated; wired into both SELL and BUY (when comp==PNK) paths.
- Subtask 4 (ABI & usage shape): ✅ Completed — added `buy_conditional_arbitrage_pnk` (short signature); Python executor updated to use it (no Balancer fallback) and bot v2 supports `BOT_TYPE` (balancer|pnk|kleros).

Evidence
- BUY tx with merged PNK not sold: 0x88567e6ab9ec4ebefffd1483de3cee2d0cc7b9f8fb570ec9b02c1cb2e3240e90

Next Focus
- Monitor PNK route stability; pools/indices are hard-coded. Consider making poolIds configurable.
- Add dry-run quoting and slippage guards if needed.

Notes
- BUY helper now uses a single-branch Vault route (sDAI→ASSET_4→GNO→WETH) to avoid BAL#304 observed with dual-branch split.
- Bot v2: `BOT_TYPE=pnk|kleros` uses PNK price model; `kleros` comparator imported from light_bot.
- New CLI tools: `fund_executor` (send sDAI to V5) and `pull_sdai` (owner sweep). Strict env (no fallbacks) where requested.
