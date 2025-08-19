Title: ABI shape and usage constraints for new PNK functions

Status
- ✅ Completed: signatures finalized and integrated with Python executor and bot v2.

Objective
- Define minimal, executor-friendly function signatures that match the script semantics and integrate with existing off-chain executor behavior without extra wiring.

Function signatures (no events)
- `function buyPnkWithSdai(uint256 amountSdaiIn, uint256 minWethOut, uint256 minPnkOut) external`
- `function sellPnkForSdai(uint256 amountPnkIn, uint256 minWethOut, uint256 minSdaiOut) external`

Rules
- Use internal constants for all addresses, poolIds, assets order, deadlines; recipient is `address(this)`.
- Approvals are handled internally via the existing max-approve helper; no Permit2 needed for these hops.
- No gas, slippage, or profit semantics added here (handled off-chain by current executor/CLI via mins).
- All amounts are in wei (uint256); zeros for min-out disable that guard.
- Reverts on standard failures (insufficient output, batchSwap/Swapr revert).
