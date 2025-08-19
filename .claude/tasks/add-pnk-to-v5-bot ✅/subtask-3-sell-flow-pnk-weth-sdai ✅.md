Title: Implement sell flow (PNK → WETH → sDAI) in V5

Status
- ✅ Completed — `sellPnkForSdai` implemented and validated on-chain with small-size sells; a separate full PNK sell entrypoint is available for the complete arbitrage path.

Objective
- Add a minimal V5 function that sells PNK back to sDAI by first swapping PNK→WETH on Swapr v2 (exact-in), then swapping WETH→sDAI on Balancer (Vault batchSwap GIVEN_IN) using the mirrored route. Keep logic self-contained.

Proposed function (ABI shape)
- `function sellPnkForSdai(uint256 amountPnkIn, uint256 minWethOut, uint256 minSdaiOut) external`
  - Uses internal constants for addresses, poolIds, assets order, and deadlines.
  - Recipient is `address(this)`; no new events.

Notes
- If reversing the exact steps is invalid for a given pool graph, substitute a known-good WETH→sDAI poolId sequence.
- Keep this function minimal; no profit checks or custom events.
