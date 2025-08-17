Title: Implement sell flow (PNK → WETH → sDAI) in V5

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
  - Call `_swaprExactIn(SWAPR_V2_ROUTER, PNK, WETH, amountPnkIn, minWethOut)` to obtain `wethOut`.
  - Ensure `wethOut > 0` and `wethOut >= minWethOut` if `minWethOut > 0`.
- Balancer batchSwap (GIVEN_IN) WETH→sDAI (mirrored):
  - Approve `WETH` to `BALANCER_VAULT` (max-approve).
  - Use the same assets order. Input index is WETH; output index is sDAI.
  - Steps mirror the buy path topologically in reverse: feed WETH at index 2, traverse pools backwards to index 0 (sDAI). If a strict reverse route is not valid in practice, configure an explicit WETH→sDAI path (same assets array OK) with `amount = wethOut` on the first step and zeros after.
  - Limits: `limits[WETH_INDEX] = +wethOut`, `limits[SDAI_INDEX] = -minSdaiOut`.
  - Funds: `(sender=address(this), false, recipient=address(this), false)`. Deadline `9007199254740991`.
  - Execute `vault.batchSwap`.
- Post-Balancer check: verify sDAI balance increased and meets `minSdaiOut` if set.

Notes
- If reversing the exact steps is invalid for a given pool graph, substitute a known-good WETH→sDAI poolId sequence (document alongside constants). Keep the same assets ordering to simplify indices.
- Keep this function minimal; no profit checks or custom events.

Acceptance
- Compiles and executes end-to-end on-chain with a small `amountPnkIn`.
- Uses only the new constants and existing V5 helpers for approvals and swap.
