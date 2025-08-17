Title: ABI shape and usage constraints for new PNK functions

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

Integration notes
- Off-chain caller (current arbitrage executor) only needs to set `amountSdaiIn` or `amountPnkIn` and any desired mins.
- No CLI changes required; can be called via a simple ABI-based transaction builder or added to existing module with minimal glue.
- If we later want flexible routes, we can add overloads that accept poolIds/assets arrays; keep current ones stable as “fixed route” entry points.

Acceptance
- Compiles; abi exported includes both functions; no regressions to existing V5 entry points.
