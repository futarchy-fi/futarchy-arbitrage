# Add PNK Buy/Sell Flows to futarchyArbExecutorV5

Goal: add new, isolated functions that clone the existing “Balancer complete” buy/sell flows but substitute the trading legs with the PNK path we verified on-chain:

- Buy: sDAI → WETH via Balancer Vault batchSwap (GIVEN_IN), then WETH → PNK via Swapr v2 Router.
- Sell: PNK → WETH via Swapr v2 Router, then WETH → sDAI via Balancer Vault batchSwap (GIVEN_IN, mirrored route).

These should be new functions (no behavior changes to existing flows) and respect v5 gas/min‑profit semantics.

---

## Interfaces, Addresses, Constants (Gnosis)

- `BalancerVault`: `0xBA12222222228d8Ba445958a75a0704d566BF2C8`
- `SwaprV2Router` (default): `0xE43e60736b1cb4a75ad25240E2f9a62Bff65c0C0` (env override allowed)
- `SDAI`: `0xaf204776c7245bf4147c2612bf6e5972ee483701`
- `WETH`: `0x6A023CCd1ff6F2045C3309768eAd9E68F978f6e1`
- `PNK` : `0x37b60f4E9A31A64cCc0024dce7D0fD07eAA0F7B3`

Balancer poolIds and assets ordering (for the sDAI→WETH step), copied exactly from the working script and docs:

- poolIds (bytes32):
  - `0xa91c413d8516164868f6cca19573fe38f88f5982000200000000000000000157`
  - `0x7e5870ac540adfd01a213c829f2231c309623eb10002000000000000000000e9`
  - `0x40d2cbc586dd8df50001cdba3f65cd4bbc32d596000200000000000000000154`
  - `0x480d4f66cc41a1b6784a53a10890e5ece31d75c000020000000000000000014e`
  - `0xa99fd9950b5d5dceeaf4939e221dca8ca9b938ab000100000000000000000025`

- assets order (indices for batchSwap):
  - `[SDAI, 0xC0d871bD13eBdf5c4ff059D8243Fb38210608bD6, WETH, 0xE0eD85F76D9C552478929fab44693E03F0899F23, 0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb]`

Deadlines and gas presets (to avoid estimator reverts):

- `Vault.batchSwap` deadline: `9007199254740991`
- `Swapr v2` deadline: `3510754692` (far-future)
- Pre-set `gas` when building: `Vault ~1_000_000`, `Swapr ~800_000` (still apply EIP‑1559 fields)

---

## High-Level Changes

1) Add config/consts
- Add addresses and poolIds to a v5 config module or executor-level constants; allow router override via env/config.
- Keep these behind a feature flag or clearly namespaced constants (PNK-specific).

2) New executor functions (do not modify existing)
- `def exec_buy_pnk_with_sdai_v5(...):`
  - Inputs (aligned with v5 CLI patterns): `amount_sdai`, `min_weth` (optional), `min_pnk` (optional), `force_send` (gas pre-set toggle), `slippage_bps` (optional), and contextual args already present in v5 executor (signer, w3, chainId).
  - Behavior: build and send (a) sDAI→WETH batchSwap then (b) WETH→PNK swap, exactly as in the working script.
  - Always send to sender; no external recipient arg.

- `def exec_sell_pnk_for_sdai_v5(...):`
  - Inputs: `amount_pnk`, `min_weth` (optional), `min_sdai` (optional), `force_send`, and contextual args.
  - Behavior: (a) PNK→WETH via Swapr v2, then (b) WETH→sDAI via Balancer Vault batchSwap, mirroring the route indices but reversing direction and amounts as needed.

3) CLI wiring (non-invasive)
- Add new subcommands/flags for PNK buy/sell in the v5 CLI module(s) without altering existing ones.
- Use clear names: `arbv5:buy-pnk` and `arbv5:sell-pnk` (or similar) under the futarchy executor commands.

4) Gas semantics (align with v1/v5 policy)
- Default: do not pre-populate gas; estimate post-build with +20% buffer.
- If estimation fails (BAL#507/STF) or `--force-send` is set, set explicit `gas` to the presets above.
- Apply EIP‑1559 fields (`maxFeePerGas`, `maxPriorityFeePerGas`) using the existing helper.

5) Min-profit and slippage semantics
- Reuse v5 signed min-profit machinery where applicable (accept negative values).
- For these PNK flows specifically, expose `--min-weth` (for the Balancer leg limits) and `--min-pnk`/`--min-sdai` for the final leg.
- If `slippage_bps` provided, compute implied min-out via on-chain quotes (`queryBatchSwap` for Balancer, `getAmountsOut` for v2) in dry-run step; otherwise trust user-provided mins.

6) Approvals and balances
- Buy: approve `sDAI → Vault` for `amount_sdai`; then approve `WETH → Swapr` for the received WETH.
- Sell: approve `PNK → Swapr` for `amount_pnk`; then approve `WETH → Vault` for the WETH received from Swapr.
- Optional: use exact-amount approvals to limit risk; or unlimited per config flag.

7) Robustness, logging, errors
- Abort if intermediate WETH amount is zero (both directions).
- Propagate revert reasons; log tx hashes for each step; print final receipt status and gas used.
- Include dry-run mode that only performs on-chain quotes and prints predicted amounts/mins.

---

## Exact Call Shapes (mirror the working script)

Buy (sDAI → WETH → PNK):

1) `IERC20(SDAI).approve(Vault, amount_sdai)`
2) `IVault.batchSwap(SwapKind.GIVEN_IN, swaps, assets, funds, limits, deadline)`
   - swaps (split amount 50/50):
     - `(POOL_1, 0, 1, half, "0x")`
     - `(POOL_2, 1, 2, 0,   "0x")`
     - `(POOL_3, 0, 3, other, "0x")`
     - `(POOL_4, 3, 4, 0,   "0x")`
     - `(POOL_5, 4, 2, 0,   "0x")`
   - assets: `[SDAI, 0xC0d8..., WETH, 0xE0eD..., GNO]`
   - funds: `(sender, false, sender, false)`
   - limits: `[+amount_sdai, 0, -min_weth, 0, 0]`
   - deadline: `9007199254740991`
   - gas: pre-set to `~1_000_000` if needed

3) `IERC20(WETH).approve(SwaprRouter, weth_received)`
4) `IUniswapV2Router02.swapExactTokensForTokens(weth_in, min_pnk, [WETH, PNK], sender, 3510754692)`
   - gas: pre-set to `~800_000` if needed

Sell (PNK → WETH → sDAI):

1) `IERC20(PNK).approve(SwaprRouter, amount_pnk)`
2) `IUniswapV2Router02.swapExactTokensForTokens(amount_pnk, min_weth, [PNK, WETH], sender, 3510754692)`
   - gas: pre-set to `~800_000` if needed

3) `IERC20(WETH).approve(Vault, weth_received)`
4) `IVault.batchSwap(SwapKind.GIVEN_IN, swaps_rev, assets, funds, limits_rev, deadline)`
   - swaps_rev mirrors the BUY structure but with `amount` on the first WETH‑originating step and zeros thereafter; indices stay the same since assets order is identical.
   - Enforce `-min_sdai` in limits on the `SDAI` index; `WETH` is the positive in.
   - deadline: `9007199254740991`; gas per above.

Note: For SELL via Balancer, we can either:
- Use the reverse of the same poolIds (if pools support WETH→SDAI along the same indices), or
- Provide a second, empirically verified poolId set for WETH→SDAI. Start with mirrored route; add a config switch to override if needed.

---

## Integration Steps (Engineering Plan)

1) Add PNK constants and pool route to a v5 config module (or executor-level constants).
   - Status: Completed (implemented in FutarchyArbExecutorV5.sol with helpers)
2) Implement `exec_buy_pnk_with_sdai_v5` using the exact script logic and call shapes above.
   - Status: Partial — on-chain buy helper (`buyPnkWithSdai`) implemented and verified; BUY arbitrage entrypoint for PNK (`buy_conditional_arbitrage_pnk`) implemented but pending deployment to complete Step 6 (PNK→sDAI sell) on the BUY path.
3) Implement `exec_sell_pnk_for_sdai_v5` with mirrored logic; verify indices/limits for WETH→sDAI.
   - Status: Completed — minimal sell helper implemented and validated; separate complete sell entrypoint added.
4) Wire new CLI subcommands and flags (amount/mins/force-send/slippage-bps).
5) Add dry-run quoting that computes mins if `slippage_bps` is provided.
6) Reuse v5 gas helpers and signed min-profit conversion; keep recipient fixed to sender.
7) Manual on-chain test with small `--amount 0.01` sDAI buy; then small PNK sell.
8) Update task docs and usage examples; keep the feature off by default if desired.

---

## Acceptance Criteria

- New functions exist and compile without changing or breaking existing v5 flows.
- On-chain tests succeed for both BUY and SELL using small sizes; tx hashes logged.
- Pre-set gas and far-future deadlines applied only when estimation fails or `--force-send` is set.
- Signed min-profit and slippage bounds respected.
- Script-equivalent behavior: same poolIds/assets order; same deadline and gas handling; always send to sender.

---

## Optional Enhancements (Post-MVP)

- Configurable poolIds/assets via JSON or env to adapt to Balancer pool changes without code edits.
- Automatic pool discovery/quoting via `queryBatchSwap` and choosing the best route at runtime.
- Exact-allowance revocation/cleanup for approvals.
- Telemetry for success/failure rates and gas usage.
