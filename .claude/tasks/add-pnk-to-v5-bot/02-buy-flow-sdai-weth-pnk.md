Title: Implement buy flow (sDAI → WETH → PNK) in V5

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
  - Call `_swaprExactIn(SWAPR_V2_ROUTER, WETH, PNK, wethBal, minPnkOut)` (helper exists in V5).
  - Optionally sanity-check returned amountOut ≥ `minPnkOut` if helper returns zero on revert this is redundant, so skip extra logic.

Notes
- No new events or profit checks; keep behavior minimal.
- Gas/deadline semantics are internal to protocol calls; off-chain gas estimation policy remains in the Python executor.
- All tokens assumed 18 decimals (true for sDAI/WETH/PNK on Gnosis).

Acceptance
- Compiles and executes end-to-end on-chain with small `amountSdaiIn`.
- Leaves existing functions unmodified; uses only new constants and helpers already in V5.
