# Futarchy Arbitrage Bot

An automated bot that monitors and executes arbitrage opportunities between Balancer and Swapr pools in futarchy markets.

## Features

- **Continuous Monitoring**: Checks prices at configurable intervals
- **Smart Decision Engine**: Calculates ideal prices and identifies profitable opportunities
- **Automated Execution**: Executes trades via the FutarchyArbExecutorV5 contract
- **Risk Management**: Respects tolerance and minimum profit thresholds
- **Dry Run Mode**: Test strategies without executing real trades

## Installation

The bot is already integrated into the main project. No additional installation needed.

## Usage

### Basic Command

```bash
python -m src.arbitrage_bot \
  --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF \
  --amount 0.01 \
  --interval 120 \
  --tolerance 0.04 \
  --min-profit 0.001
```

### With Virtual Environment

```bash
source futarchy_env/bin/activate
source .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF
python -m src.arbitrage_bot \
  --amount 0.01 \
  --interval 120 \
  --tolerance 0.04 \
  --min-profit 0.001 \
  --prefund
```

### Dry Run Mode (Testing)

```bash
python -m src.arbitrage_bot \
  --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF \
  --amount 0.01 \
  --interval 60 \
  --tolerance 0.02 \
  --min-profit -0.01 \
  --dry-run
```

## Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `--env` | Path to environment file with pool addresses | `.env.0x959...` |
| `--amount` | Amount of sDAI to trade | `0.01` |
| `--interval` | Seconds between price checks | `120` |
| `--tolerance` | Minimum price deviation to trigger trade | `0.04` |
| `--min-profit` | Minimum profit required (can be negative) | `0.001` |
| `--dry-run` | Simulate trades without executing | Flag |
| `--prefund` | Transfer sDAI to executor if needed | Flag |

## How It Works

1. **Price Monitoring**
   - Fetches prices from Swapr YES, NO, and prediction pools
   - Fetches composite token price from Balancer pool

2. **Opportunity Detection**
   - Calculates ideal price: `pred_yes * yes_price + (1 - pred_yes) * no_price`
   - Compares actual Balancer price with ideal price
   - Triggers when deviation exceeds tolerance

3. **Trade Execution**
   - **SELL Flow**: When Balancer is underpriced
     - Buy composite on Balancer
     - Split into conditional tokens
     - Sell conditionals on Swapr
   
   - **BUY Flow**: When Balancer is overpriced
     - Buy cheap conditionals on Swapr
     - Merge into composite token
     - Sell composite on Balancer

4. **Risk Management**
   - Only executes if expected profit > min_profit
   - Handles errors gracefully without stopping
   - Logs all decisions and results

## Required Environment Variables

```bash
# Pool addresses
SWAPR_POOL_YES_ADDRESS=0x...
SWAPR_POOL_NO_ADDRESS=0x...
SWAPR_POOL_PRED_YES_ADDRESS=0x...
BALANCER_POOL_ADDRESS=0x...

# Token addresses
SWAPR_GNO_YES_ADDRESS=0x...
SWAPR_GNO_NO_ADDRESS=0x...
SWAPR_SDAI_YES_ADDRESS=0x...
SWAPR_SDAI_NO_ADDRESS=0x...

# Router addresses
BALANCER_ROUTER_ADDRESS=0x...
SWAPR_ROUTER_ADDRESS=0x...
FUTARCHY_ROUTER_ADDRESS=0x...

# Executor contract
FUTARCHY_ARB_EXECUTOR_V5=0x...

# Connection
RPC_URL=https://...
PRIVATE_KEY=0x...
```

## Monitoring Output

The bot provides detailed logging:

```
🤖 Starting Futarchy Arbitrage Bot
   Amount:      0.01 sDAI
   Interval:    120 seconds
   Tolerance:   0.04
   Min Profit:  0.001 sDAI
   Mode:        LIVE

============================================================
Iteration #1 - 2024-01-14 15:30:00
============================================================

Price Analysis:
  YES price:       0.850000
  NO price:        0.150000
  Prediction YES:  0.600000
  Balancer price:  0.580000
  Ideal price:     0.570000
  Deviation:       0.010000 (1.75%)
  → BUY opportunity: Balancer overpriced by 0.010000
  → NO is cheaper (0.150000 < 0.850000)

Executing arbitrage: BUY flow, NO cheaper
...
✓ Trade executed successfully

💤 Sleeping for 120 seconds...
```

## Safety Features

- **Graceful Shutdown**: Ctrl+C stops the bot cleanly
- **Error Recovery**: Continues operation after non-fatal errors
- **Transaction Timeout**: 2-minute timeout for stuck transactions
- **Prefund Check**: Ensures executor has sufficient balance

## Tips

1. Start with dry-run mode to understand the bot's behavior
2. Use negative min-profit for testing (e.g., `-0.01`)
3. Set reasonable intervals to avoid excessive RPC calls
4. Monitor logs to understand market dynamics
5. Adjust tolerance based on gas costs and expected profits