# Implementation Plan: PNK Price Support for Light Bot

## Overview

This document outlines the implementation plan for adding PNK price support to the light bot arbitrage system.

## Phase 1: Configuration Setup

### 1.1 Create PNK Configuration Module
Create `src/config/pnk_config.py`:
- Define PNK token address
- Define pool addresses (PNK/WETH, WETH/WXDAI)
- Define sDAI contract address
- Configure decimal precision settings

### 1.2 Update Environment Variables
Add to `.env` files:
```
# PNK Configuration
PNK_TOKEN_ADDRESS=
WETH_ADDRESS=
WETH_WXDAI_POOL=0x1865d5445010e0baf8be2eb410d3eae4a68683c2
PNK_WETH_POOL=0x2613Cb099C12CECb1bd290Fd0eF6833949374165
SDAI_CONTRACT=0x89C80A4540A00b5270347E02e2E144c71da2EceD
```

## Phase 2: Core Implementation

### 2.1 Create PNK Price Monitor
Implement `src/arbitrage_commands/pnk_light_bot.py`:
- Inherit from existing light bot base class
- Override `_current_price` method with PNK-specific logic
- Implement helper methods:
  - `_get_weth_usd_price()`
  - `_get_pnk_weth_price()`
  - `_calculate_pnk_prices()`

### 2.2 Add Pool Interface Methods
- `_get_reserves(pool_address)` - Get pool reserves
- `_get_token0(pool_address)` - Get token0 address
- `_get_sdai_rate()` - Get current sDAI conversion rate

### 2.3 Price Calculation Implementation
```python
class PNKLightBot(LightBotBase):
    async def _current_price(self) -> Dict[str, float]:
        # Implementation following the documented methodology
        weth_usd = await self._get_weth_usd_price()
        sdai_rate = await self._get_sdai_rate()
        pnk_weth = await self._get_pnk_weth_price()
        
        price_usd = pnk_weth * weth_usd
        price_sdai = price_usd / sdai_rate
        
        return {
            "sdai": price_sdai,
            "usd": price_usd,
            "weth": pnk_weth
        }
```

## Phase 3: Integration

### 3.1 Update CLI Interface
Modify `src/cli/cli.py`:
- Add PNK light bot command
- Configure argument parsing for PNK-specific parameters

### 3.2 Create Launch Script
Create `scripts/run_pnk_light_bot.sh`:
```bash
#!/bin/bash
source futarchy_env/bin/activate
source .env.pnk
python -m src.arbitrage_commands.pnk_light_bot \
    --interval 60 \
    --min-profit 0.01
```

## Phase 4: Testing

### 4.1 Unit Tests
Create `tests/test_pnk_price_calculation.py`:
- Test WETH/USD price calculation
- Test PNK/WETH price calculation
- Test sDAI rate integration
- Test edge cases (zero reserves, token order)

### 4.2 Integration Tests
- Test live price fetching from actual pools
- Validate price accuracy against external sources
- Test error handling for RPC failures

### 4.3 Performance Tests
- Measure latency of price calculations
- Test concurrent price updates
- Validate memory usage patterns

## Phase 5: Monitoring and Alerts

### 5.1 Add Logging
- Log price calculations with timestamps
- Track price deviations
- Monitor pool reserve changes

### 5.2 Price Validation
- Compare against external price feeds
- Alert on significant deviations
- Track historical price data

## Timeline

- **Week 1**: Configuration and core implementation
- **Week 2**: Integration and testing
- **Week 3**: Monitoring setup and production deployment

## Success Criteria

1. Accurate PNK price calculation within 0.1% of market price
2. Sub-second price update latency
3. 99.9% uptime for price monitoring
4. Comprehensive test coverage (>90%)
5. Production-ready error handling and logging