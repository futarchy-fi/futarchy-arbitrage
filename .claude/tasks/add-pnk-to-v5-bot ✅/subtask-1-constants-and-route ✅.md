Title: Add PNK trading constants and Balancer route (Gnosis)

Status
- Completed: constants, poolIds, assets order, deadlines, and helpers are implemented in FutarchyArbExecutorV5.sol and deployed.

Objective
- Centralize constants used by the new PNK buy/sell flows. Keep them isolated and easy to swap if pools change.

What to add
- Addresses (checksummed):
  - `SDAI = 0xaf204776c7245bF4147c2612BF6e5972Ee483701`
  - `WETH = 0x6A023CCd1ff6F2045C3309768eAd9E68F978f6e1`
  - `PNK  = 0x37b60f4E9A31A64cCc0024dce7D0fD07eAA0F7B3`
  - `BALANCER_VAULT = 0xBA12222222228d8Ba445958a75a0704d566BF2C8`
  - `SWAPR_V2_ROUTER = 0xE43e60736b1cb4a75ad25240E2f9a62Bff65c0C0` (allow env override at runtime if desired)

- Balancer batchSwap route (sDAI → WETH), copied exactly from the working script:
  - poolIds (bytes32):
    - `0xa91c413d8516164868f6cca19573fe38f88f5982000200000000000000000157`
    - `0x7e5870ac540adfd01a213c829f2231c309623eb10002000000000000000000e9`
    - `0x40d2cbc586dd8df50001cdba3f65cd4bbc32d596000200000000000000000154`
    - `0x480d4f66cc41a1b6784a53a10890e5ece31d75c000020000000000000000014e`
    - `0xa99fd9950b5d5dceeaf4939e221dca8ca9b938ab000100000000000000000025`
  - assets order (indices):
    - `[SDAI, 0xC0d871bD13eBdf5c4ff059D8243Fb38210608bD6, WETH, 0xE0eD85F76D9C552478929fab44693E03F0899F23, 0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb]`
  - swap steps (GIVEN_IN), with `amount` split 50/50: (0→1, 1→2) and (0→3, 3→4, 4→2)
  - limits: `+SDAI in`, `-minWETH out`, others 0
  - deadline: `9007199254740991`

- Deadlines
  - Balancer batchSwap: `9007199254740991`
  - Swapr v2 swap: `3510754692` (far future)

Minimal interfaces (for implementation)
- IVault.batchSwap (SwapKind.GIVEN_IN, BatchSwapStep[], address[] assets, FundManagement, int256[] limits, uint256 deadline) → int256[] assetDeltas
- IERC20 minimal (balanceOf, approve)
- IAlgebra/Swapr exactInputSingle as already present in V5

Acceptance
- Constants grouped under a PNK-specific section or library in V5 and used only by the new PNK functions.
