Title: Implement buy flow (sDAI → WETH → PNK) in V5

Status
- ✅ Completed — `buyPnkWithSdai` implemented; integrated into SELL flow (Step 2). BUY arbitrage now liquidates PNK back to sDAI within the same transaction when `comp==PNK` by invoking `sellPnkForSdai` inside `buy_conditional_arbitrage_balancer`. A short-signature PNK entrypoint `buy_conditional_arbitrage_pnk` is also available and supported by the Python executor.

Evidence
- Example BUY tx (merged PNK not sold): 0x88567e6ab9ec4ebefffd1483de3cee2d0cc7b9f8fb570ec9b02c1cb2e3240e90
  - sDAI sent: ~0.01
  - PNK received post-merge: 0.460308479174175043
  - No subsequent PNK→sDAI sell occurred (current deployed entrypoint omits Step 6).

Objective
- Add a minimal V5 function that buys PNK using sDAI by first swapping sDAI→WETH on Balancer (Vault batchSwap GIVEN_IN) using the fixed multi-pool route, then swapping WETH→PNK on Swapr v2 (exact-in). Keep logic self-contained and independent of existing flows.

Implemented
- `function buyPnkWithSdai(uint256 amountSdaiIn, uint256 minWethOut, uint256 minPnkOut) external`
  - Internal constants for addresses, poolIds, assets order, and deadlines.
  - Recipient is `address(this)` for both hops.
  - Updated to a single-branch Vault route (sDAI→ASSET_4→GNO→WETH) to prevent BAL#304 reverts seen with dual-branch split.
- BUY PNK liquidation
  - Inline in `buy_conditional_arbitrage_balancer` when `comp==PNK` (calls `sellPnkForSdai`).
  - Separate entrypoint: `buy_conditional_arbitrage_pnk(...)` (short signature) supported by Python executor.

Next steps to complete
- Monitor route correctness and consider making poolIds configurable via env.
- Add optional slippage controls from quotes.

Notes
- Signed min-profit is supported end-to-end; negative values accepted.
- Python: PNK executor no longer falls back to Balancer; requires the PNK entrypoint.
