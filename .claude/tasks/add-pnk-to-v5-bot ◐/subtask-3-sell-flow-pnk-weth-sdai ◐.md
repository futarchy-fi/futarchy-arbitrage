Title: Implement sell flow (PNK → WETH → sDAI) in V5

Status
- Partial: base function implemented and validated on-chain with a small-size sell. Remaining: integrate into a new complete arbitrage flow and minimal executor/bot wiring if needed (kept separate from existing paths).

Objective
- Add a minimal V5 function that sells PNK back to sDAI by first swapping PNK→WETH on Swapr v2 (exact-in), then swapping WETH→sDAI on Balancer (Vault batchSwap GIVEN_IN) using the mirrored route. Keep logic self-contained.

Proposed function (ABI shape)
- `function sellPnkForSdai(uint256 amountPnkIn, uint256 minWethOut, uint256 minSdaiOut) external`
  - Uses internal constants for addresses, poolIds, assets order, and deadlines.
  - Recipient is `address(this)`; no new events.

Steps
- Pre-swap checks: `require(amountPnkIn > 0)`.
- Approve and swap PNK→WETH via Swapr exact-in:
  - Max-approve `PNK` to `SWAPR_V2_ROUTER`.
  - Call Uniswap v2 router `swapExactTokensForTokens(amountPnkIn, minWethOut, [PNK, WETH], address(this), deadline)`.
- Balancer batchSwap (GIVEN_IN) WETH→sDAI (mirrored):
  - Approve `WETH` to `BALANCER_VAULT` (max-approve).
  - Use the same assets order. Input index is WETH; output index is sDAI.
  - Reverse steps mirroring the buy path: first step has `amount>0`, subsequent steps `0`.
  - Limits: `limits[WETH_INDEX] = +wethOut`, `limits[SDAI_INDEX] = -minSdaiOut`.
  - Funds: `(sender=address(this), false, recipient=address(this), false)`. Deadline `9007199254740991`.
- Post-Balancer check: verify sDAI balance increased and meets `minSdaiOut` if set.

Notes
- If reversing the exact steps is invalid for a given pool graph, substitute a known-good WETH→sDAI poolId sequence.
- Keep this function minimal; no profit checks or custom events.
