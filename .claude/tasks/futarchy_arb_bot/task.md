# Futarchy Arbitrage Bot Task

## Objective
Create an automated arbitrage bot that monitors price discrepancies between Balancer and Swapr pools for futarchy markets and executes profitable trades using the FutarchyArbExecutorV5 contract.

## Requirements

### Core Functionality
- Monitor prices from Swapr YES/NO pools and Balancer pool at configurable intervals
- Calculate ideal price based on prediction market probabilities
- Determine arbitrage opportunities when price deviations exceed tolerance
- Execute trades via the `arbitrage_executor` module

### Price Discovery Logic
1. Fetch spot prices from:
   - Swapr YES pool (conditional YES token)
   - Swapr NO pool (conditional NO token)
   - Swapr prediction YES pool (for probability calculation)
   - Balancer pool (composite token)

2. Calculate ideal Balancer price:
   ```
   ideal_price = pred_yes_price * yes_price + (1 - pred_yes_price) * no_price
   ```

3. Determine trade direction:
   - If Balancer price > ideal price → BUY flow (buy conditionals, merge, sell composite)
   - If Balancer price < ideal price → SELL flow (buy composite, split, sell conditionals)

4. Identify cheaper conditional token:
   - Compare YES and NO prices to determine which is cheaper
   - Pass this to executor as the `--cheaper` parameter

### CLI Configuration
```bash
python -m src.arbitrage_bot \
  --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF \
  --amount 0.01 \
  --interval 120 \
  --tolerance 0.04 \
  --min-profit -0.01 \
  --dry-run  # Optional: simulate without executing
```

### Integration Points
- Use `src.executor.arbitrage_executor` for trade execution
- Reuse price fetching logic from `src.helpers.swapr_price` and `src.helpers.balancer_price`
- Support both dry-run (simulation) and live execution modes

## Implementation Plan

1. **Price Monitoring Module**
   - Fetch prices from all required pools
   - Calculate ideal price and price deviations
   - Log price information for debugging

2. **Decision Engine**
   - Determine if arbitrage opportunity exists (price deviation > tolerance)
   - Choose appropriate flow (buy/sell) based on price comparison
   - Identify cheaper conditional token

3. **Execution Module**
   - Call `arbitrage_executor` with correct parameters
   - Handle prefunding if needed
   - Log transaction results

4. **Main Loop**
   - Run continuously with configurable interval
   - Handle errors gracefully without stopping
   - Support clean shutdown on interrupt

## Success Criteria
- Bot correctly identifies arbitrage opportunities
- Executes trades using the simplified `arbitrage_executor` interface
- Respects tolerance and min-profit thresholds
- Runs continuously without memory leaks or crashes
- Provides clear logging of decisions and actions