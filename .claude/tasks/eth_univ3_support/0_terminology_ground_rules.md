# 0. Terminology & Ground Rules

## Token Naming
- **Company (COMP)** → TSLAON (`0xf6b1117ec07684D3958caD8BEb1b302bfD21103f`, 18 decimals). Use `COMPANY_TOKEN_ADDRESS` for config/env bridging.
- **Currency (CUR)** → USDS (18 decimals; address supplied at proposal bootstrap). Maintain backwards compatibility where code expects `SDAI_TOKEN_ADDRESS`.

## Decimal Handling
- Only USDC maintains 6 decimals on mainnet. All other tracked assets (TSLAON, USDS, conditional YES/NO tokens) are 18 decimals.
- Extend math utilities to respect per-token decimals in price conversion, profit checks, and reporting.

## Conditional Pools
- Replace legacy `SWAPR_*` env keys with generic pool identifiers:
  - `POOL_COMPANY_YES_ADDRESS`
  - `POOL_COMPANY_NO_ADDRESS`
  - `POOL_CURRENCY_YES_ADDRESS`
  - `POOL_CURRENCY_NO_ADDRESS`
- Each entry resolves to a Uniswap V3 pool address on mainnet.

## Execution Semantics
- Preserve the existing single-transaction executor flow: split/merge via FutarchyRouter, trade conditionals directly, and route spot legs through Uniswap V3 multi-hop (TSLAON ↔ USDC ↔ USDS).
- No sequential bots or EIP-7702 dependency for mainnet; reuse the executor contract with added Uniswap entrypoints.
