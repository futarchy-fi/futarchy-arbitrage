# PNK Price Calculation Methodology

## Overview

The PNK price calculation uses a multi-hop approach through WETH as an intermediary to determine accurate USD and sDAI prices.

## Price Calculation Flow

```
PNK → WETH → WXDAI (USD) → sDAI
```

### Step 1: WETH/USD Price Discovery

From the WETH/WXDAI pool (`0x1865d5445010e0baf8be2eb410d3eae4a68683c2`):

```python
# Get reserves from WETH/WXDAI pool
r0, r1 = await self._get_reserves(weth_wxdai_pool)

# Determine token0 position
t0_weth = await self._get_token0(weth_wxdai_pool)

# Calculate WETH price in USD (WXDAI = 1 USD)
if t0_weth == weth_address:
    weth_usd = (r1/1e18)/(r0/1e18)  # WXDAI per WETH
else:
    weth_usd = (r0/1e18)/(r1/1e18)  # WXDAI per WETH
```

### Step 2: sDAI Rate Calculation

Get the current sDAI conversion rate:

```python
sdai_rate = await self._get_sdai_rate()
# This returns how much DAI 1 sDAI is worth
```

### Step 3: PNK/WETH Price

From the PNK/WETH pool (`0x2613Cb099C12CECb1bd290Fd0eF6833949374165`):

```python
# Get reserves from PNK/WETH pool
p0, p1 = await self._get_reserves(self.pool_id)

# Determine token0 position
t0_pool = await self._get_token0(self.pool_id)

# Calculate PNK price in WETH
if t0_pool == weth_address:
    price_weth = (p0/1e18)/(p1/1e18)  # WETH per PNK
else:
    price_weth = (p1/1e18)/(p0/1e18)  # WETH per PNK
```

### Step 4: Final Price Calculations

```python
# PNK price in USD
price_usd = price_weth * weth_usd

# PNK price in sDAI
price_sdai = price_usd / sdai_rate
```

## Return Format

The method returns a dictionary with three price formats:

```python
{
    "sdai": price_sdai,   # PNK price in sDAI
    "usd": price_usd,     # PNK price in USD
    "weth": price_weth    # PNK price in WETH
}
```

## Key Assumptions

1. **WXDAI = 1 USD**: The WXDAI stablecoin is assumed to maintain 1:1 peg with USD
2. **18 Decimal Precision**: All tokens (PNK, WETH, WXDAI) use 18 decimal places
3. **Uniswap V2 Pool Structure**: Both pools follow standard constant product AMM formula
4. **sDAI Rate Accuracy**: The sDAI contract provides accurate DAI conversion rates

## Error Handling Considerations

- Check for zero reserves (empty pools)
- Validate token0 addresses match expected tokens
- Handle potential RPC call failures
- Implement slippage tolerance for actual trades based on these prices