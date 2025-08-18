Title: Implement buy flow (sDAI → WETH → PNK) in V5

Status
- Partial: buyPnkWithSdai is implemented, verified on-chain (sDAI→WETH via Balancer Vault, WETH→PNK via Swapr v2). Remaining work: integrate this buy op into a new, complete arbitrage flow function as described in the task (separate from existing logic), and expose it via the executor/bot if desired.

Objective
- Add a minimal V5 function that buys PNK using sDAI by first swapping sDAI→WETH on Balancer (Vault batchSwap GIVEN_IN) using the fixed multi-pool route, then swapping WETH→PNK on Swapr v2 (exact-in). Keep logic self-contained and independent of existing flows.

Proposed function (ABI shape)
- `function buyPnkWithSdai(uint256 amountSdaiIn, uint256 minWethOut, uint256 minPnkOut) external`
  - Uses internal constants for addresses, poolIds, assets order, and deadlines.
  - Recipient is `address(this)` for both hops; no custom events; no external recipient.

Steps
- Pre-swap checks: `require(amountSdaiIn > 0)`.
- Approvals: max-approve `SDAI` to `BALANCER_VAULT` (idempotent approve helper).
- Build Balancer batchSwap (GIVEN_IN):
  - Assets array and 5 BatchSwapStep entries as in constants.
  - Split `amountSdaiIn` into `half` and `other = amountSdaiIn - half` for the two branches.
  - Limits: `limits[SDAI_INDEX] = +amountSdaiIn`, `limits[WETH_INDEX] = -minWethOut`, others 0.
  - Funds: `(sender=address(this), fromInternal=false, recipient=address(this), toInternal=false)`.
  - Deadline: `9007199254740991`.
  - Execute `vault.batchSwap` and ignore return deltas (we rely on ERC20 balance checks below).
- Post-Balancer check: read `wethBal = IERC20(WETH).balanceOf(address(this))`; require `wethBal > 0` and `wethBal >= minWethOut` if `minWethOut > 0`.
- Approve and perform Swapr exact-in:
  - Max-approve `WETH` to `SWAPR_V2_ROUTER`.
  - Call Uniswap v2 router `swapExactTokensForTokens(wethBal, minPnkOut, [WETH, PNK], address(this), deadline)`.

Notes
- No new events or profit checks; keep behavior minimal.
- Gas/deadline semantics are internal to protocol calls; off-chain gas estimation policy remains in the Python executor.
- All tokens assumed 18 decimals (true for sDAI/WETH/PNK on Gnosis).

Remaining work to complete this subtask
- Add a new V5 "complete arbitrage" function that composes this buy operation into the end-to-end futarchy flow (in a separate function to avoid touching existing paths).
- Optionally add a thin executor path/CLI entry to trigger the new complete flow.
