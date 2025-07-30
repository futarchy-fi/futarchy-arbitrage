# PNK Price Support for Light Bot

## Overview

This task adds PNK (Kleros) token price support to the light bot implementation using a multi-hop price calculation methodology.

## Price Calculation Method

The light bot calculates PNK price through the following steps:

1. **Get WETH/USD Price**: From WETH/WXDAI pool to establish USD baseline
2. **Get sDAI Rate**: Current conversion rate from sDAI contract
3. **Get PNK/WETH Price**: From the PNK/WETH pool
4. **Calculate Final Prices**:
   - PNK in USD = PNK/WETH * WETH/USD
   - PNK in sDAI = PNK in USD / sDAI rate

## Key Components

### Pool Addresses
- **PNK/WETH Pool**: `0x2613Cb099C12CECb1bd290Fd0eF6833949374165`
- **WETH/WXDAI Pool**: `0x1865d5445010e0baf8be2eb410d3eae4a68683c2`
- **sDAI Contract**: `0x89C80A4540A00b5270347E02e2E144c71da2EceD`

### Implementation Details

The `_current_price` method (lines 83-98) performs the calculation:

```python
async def _current_price(self) -> Dict[str, float]:
    # Get WETH price in USD from WETH/WXDAI pool
    weth_address = self.cfg.get("WETH_ADDRESS")
    weth_wxdai_pool = self.cfg.get("WETH_WXDAI_POOL")
    r0, r1 = await self._get_reserves(weth_wxdai_pool)
    t0_weth = await self._get_token0(weth_wxdai_pool)
    weth_usd = (r1/1e18)/(r0/1e18) if t0_weth == weth_address else (r0/1e18)/(r1/1e18)

    # Get sDAI rate (how much DAI 1 sDAI is worth)
    sdai_rate = await self._get_sdai_rate()

    # Get PNK/WETH pool reserves and calculate PNK price
    p0, p1 = await self._get_reserves(self.pool_id)
    t0_pool = await self._get_token0(self.pool_id)
    price_weth = (p0/1e18)/(p1/1e18) if t0_pool == weth_address else (p1/1e18)/(p0/1e18)
    price_usd = price_weth * weth_usd
    price_sdai = price_usd / sdai_rate

    return {"sdai": price_sdai, "usd": price_usd, "weth": price_weth}
```

## Task Breakdown

1. **Create PNK price configuration module**
2. **Implement price calculation logic**
3. **Add configuration for PNK-specific pools**
4. **Test price calculation accuracy**
5. **Integrate with existing light bot framework**

## Expected Outcome

The light bot will be able to:
- Monitor PNK price in real-time
- Calculate PNK price in sDAI and USD
- Use accurate multi-hop pricing through WETH as intermediary
- Handle price feeds for PNK-based futarchy markets