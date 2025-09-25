# 4. Execution Path Changes

## 4.1 Uniswap V3 Swap Helpers
- Build `src/helpers/uniswap_v3_swap.py` utilities for encoding:
  - `exactInputSingle` calls targeting conditional pools.
  - `exactInput` multi-hop calldata for TSLAON ↔ USDC ↔ USDS spot trades.
- Support configurable `sqrtPriceLimitX96` guards and dynamic min-out/min-in thresholds.

## 4.2 Multicall Builder Upgrade
- Extend `MulticallV2Builder` or introduce `MulticallV3Builder` to add helper methods:
  - `add_univ3_exact_input_single`
  - `add_univ3_exact_input_path`
- Inject approvals for TSLAON, YES/NO legs, USDC, and USDS against `SwapRouter02` when building calls.

## 4.3 Flow Script Updates
- Update `buy_cond_eip7702.py`, `sell_cond_eip7702.py`, and sequential scripts to:
  - Consume new Uniswap pricing helpers.
  - Query `QuoterV2` for min-out estimates and apply configured slippage.
  - Reference mainnet token addresses during Futarchy split/merge steps.

## 4.4 Executor Contract Extension
- Add standalone Uniswap entrypoint functions to `FutarchyArbExecutorV5` and redeploy:
  - Mirror existing buy/sell handlers while encoding Uniswap V3 `exactInput`/`exactOutput` paths for both conditional and spot trades.
  - Manage approvals for TSLAON, USDC, USDS, and conditional tokens against `SwapRouter02` alongside legacy router allowances.
  - Preserve Balancer/Swapr flows for Gnosis; gate new functions by config.

## 4.5 Allowance & Prefunding
- Update prefunding routines (`src/executor/arbitrage_executor.py`) to handle USDS/TSLAON balances and ensure Uniswap router allowances are provisioned before execution.
