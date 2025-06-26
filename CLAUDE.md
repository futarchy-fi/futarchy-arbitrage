# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a futarchy arbitrage bot for Gnosis Chain that monitors price discrepancies between Balancer pools and Swapr pools to execute profitable trades. The bot trades conditional GNO tokens (YES/NO tokens) against sDAI when prices diverge from the synthetic "ideal" price.

## Environment Setup

The project uses Python virtual environments. Two common environments are used:
- `futarchy_env/` - Main virtual environment
- `venv/` - Alternative virtual environment

Environment files follow the pattern `.env.0x<address>` where the address corresponds to different futarchy market addresses.

## Common Commands

### Virtual Environment Activation
```bash
source futarchy_env/bin/activate
# or
source venv/bin/activate
```

### Running the Arbitrage Bot
```bash
# Basic bot with environment variables
source futarchy_env/bin/activate && source .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF && python -m src.arbitrage_commands.simple_bot \
    --amount 0.01 \
    --interval 120 \
    --tolerance 0.2

# Side discovery
source futarchy_env/bin/activate && source .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF && python -m src.arbitrage_commands.discover_side 0.1 120
```

### Installing Dependencies
```bash
pip install -r requirements.txt
```

### Running Tests
```bash
python -m pytest tests/
```

## Code Architecture

### Core Structure
- `src/arbitrage_commands/` - Main trading strategies and bot logic
  - `simple_bot.py` - Main arbitrage bot that monitors prices and executes trades
  - `discover_side.py` - Price discovery and side determination
  - `buy_cond.py`, `sell_cond.py` - Conditional token trading logic
  - `*_onchain.py` - On-chain execution variants
- `src/helpers/` - Utility functions for price fetching, swapping, and blockchain interaction
- `src/config/` - Configuration management including ABIs, contracts, tokens, and network settings
- `src/cli/` - Command-line interface dispatcher
- `src/setup/` - Initial setup utilities for allowances and verification

### Key Components

**Price Monitoring**: The bot calculates a synthetic "ideal" price from Swapr pools:
```
ideal_price = pred_price * yes_price + (1 - pred_price) * no_price
```

**Trading Logic**: 
- If both YES and NO prices on Swapr < Balancer price → Buy conditional GNO
- If both YES and NO prices on Swapr > Balancer price → Sell conditional GNO

**Configuration System**: Uses a modular config system in `src/config/` with:
- Network settings (`network.py`)
- Contract addresses and ABIs (`contracts.py`, `abis/`)
- Token configurations (`tokens.py`)
- Pool configurations (`pools.py`)

### Environment Variables Required
- `RPC_URL` - Gnosis Chain RPC endpoint
- `PRIVATE_KEY` - Trading account private key
- `SWAPR_POOL_YES_ADDRESS` - Swapr YES token pool
- `SWAPR_POOL_PRED_YES_ADDRESS` - Swapr prediction YES pool
- `SWAPR_POOL_NO_ADDRESS` - Swapr NO token pool
- `BALANCER_POOL_ADDRESS` - Balancer pool address

## Protocol Integration

The bot integrates with:
- **Balancer V2** - For conditional token trading
- **Swapr** - For price discovery (Algebra/Uniswap V3 compatible)
- **Gnosis Chain** - Network for all operations
- **sDAI** - Primary trading token (Savings DAI)
- **Futarchy Markets** - Conditional token systems

## Development Notes

- The `constants.py` module is deprecated; use the new config modules instead
- Use the CLI dispatcher in `src/cli/cli.py` for running individual modules
- All price calculations use `Decimal` for precision
- Trading amounts are specified in sDAI
- The bot includes comprehensive logging and error handling