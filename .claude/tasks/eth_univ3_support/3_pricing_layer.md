# 3. Pricing Layer Overhaul

## 3.1 Conditional Pricing
- Implement `src/helpers/uniswap_v3_price.py` to read `slot0` from each conditional pool and convert `sqrtPriceX96` into human prices using token decimals.
- Replace `helpers/swapr_price.get_pool_price` with a backend-agnostic dispatcher that selects Uniswap logic when `BOT_TYPE=uniswapv3`.

## 3.2 Spot Pricing
- Create a compositor that multiplies TSLAON→USDC and USDC→USDS Uniswap V3 prices for buy flows, and performs the inverse for sells.
- Cache hop fee tiers and pool addresses from config; expose adjustable slippage cushions fed by config/env.

## 3.3 Prediction Price Integration
- Treat prediction YES/NO pools as Uniswap V3 sources, reusing the same helper path used for conditional pools to simplify maintenance.
