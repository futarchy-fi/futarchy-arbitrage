# 2. Config & Environment Restructure

## 2.1 Schema Extensions
- Enhance `ConfigManager` (`src/arbitrage_commands/arbitrage_bot_v2.ConfigManager`) with a `network` block:
  - `chain_id`, `rpc_url`, `settlement_currency`, `spot_route` (array of `{token_in, token_out, fee}` hops).
  - `conditional_pools` for YES/NO legs and `spot_pools` for multi-hop metadata.
- Enforce validation when `chain_id == 1` to ensure TSLAON, USDS, conditional pools, and Uniswap hop definitions exist.

## 2.2 Environment Templates
- Generate `.env.mainnet.<proposal>` templates including:
  - Uniswap router/quoter addresses and hop fee metadata.
  - Generic `POOL_*` keys replacing legacy `SWAPR_*` entries.
  - Settlements fields for USDS plus compatibility shims for legacy env consumers (e.g., `SDAI_TOKEN_ADDRESS`).
- Extend setup scripts to produce these templates from Supabase metadata, translating existing `SWAPR_*` keys during migration.

## 2.3 CLI Enhancements
- Add `--network mainnet` (or auto-detect) flag to `arbitrage_bot_v2` for loading mainnet defaults and enforcing validations.
- Introduce `BOT_TYPE=uniswapv3` runtime mode to switch pricing/execution helpers from Swapr/Balancer to Uniswap V3.
