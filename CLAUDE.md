# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a futarchy arbitrage bot for Gnosis Chain that monitors price discrepancies between Balancer pools and Swapr pools to execute profitable trades. The bot trades conditional Company tokens (YES/NO tokens) against sDAI when prices diverge from the synthetic "ideal" price.

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
source futarchy_env/bin/activate && source .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF && python -m src.arbitrage_commands.complex_bot \
    --amount 0.1 \
    --interval 120 \
    --tolerance 0.04
```

### Installing Dependencies
```bash
pip install -r requirements.txt
```

### Running Tests
```bash
python -m pytest tests/
```

### Market Data Fetcher

The `fetch_market_data.py` script in `src/setup/` connects to Supabase to fetch market event data and automatically update environment files with correct pool and token addresses.

#### Common Usage
```bash
# Update environment file with addresses from market event metadata
source futarchy_env/bin/activate && source .env.0x<PROPOSAL_ADDRESS> && python -m src.setup.fetch_market_data --proposal --update-env .env.0x<PROPOSAL_ADDRESS>

# View market event metadata without updating
source futarchy_env/bin/activate && source .env.0x<PROPOSAL_ADDRESS> && python -m src.setup.fetch_market_data --proposal
```

#### Address Mapping
The script extracts addresses from Supabase market event metadata and maps them to environment variables:

| Environment Variable | Metadata Path |
|---------------------|---------------|
| `SWAPR_POOL_YES_ADDRESS` | `metadata.conditional_pools.yes.address` |
| `SWAPR_POOL_NO_ADDRESS` | `metadata.conditional_pools.no.address` |
| `SWAPR_POOL_PRED_YES_ADDRESS` | `metadata.prediction_pools.yes.address` |
| `SWAPR_POOL_PRED_NO_ADDRESS` | `metadata.prediction_pools.no.address` |
| `SWAPR_SDAI_YES_ADDRESS` | `metadata.currencyTokens.yes.wrappedCollateralTokenAddress` |
| `SWAPR_SDAI_NO_ADDRESS` | `metadata.currencyTokens.no.wrappedCollateralTokenAddress` |
| `SWAPR_GNO_YES_ADDRESS` | `metadata.companyTokens.yes.wrappedCollateralTokenAddress` |
| `SWAPR_GNO_NO_ADDRESS` | `metadata.companyTokens.no.wrappedCollateralTokenAddress` |

#### Required Environment Variables
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_ANON_KEY`/`SUPABASE_EDGE_TOKEN`) - Supabase API key
- `FUTARCHY_PROPOSAL_ADDRESS` - Proposal address to use as market event ID

## Code Architecture

### Core Structure
- `src/arbitrage_commands/` - Main trading strategies and bot logic
  - `simple_bot.py` - Main arbitrage bot that monitors prices and executes trades
  - `complex_bot.py` - Price discovery and side determination
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
- If both YES and NO prices on Swapr < Balancer price → Buy conditional Company tokens
- If both YES and NO prices on Swapr > Balancer price → Sell conditional Company tokens

**Buy Conditional Company Token Process** (`buy_cond.py`):
1. **Split sDAI** into YES and NO conditional sDAI tokens using FutarchyRouter
2. **Swap conditional sDAI to conditional Company tokens** on Swapr pools (both YES and NO)
3. **Merge conditional Company tokens** back into regular Company token using FutarchyRouter
4. **Handle imbalances**: If YES/NO amounts differ, liquidate excess conditional sDAI
5. **Sell Company token for sDAI** on Balancer to complete the arbitrage loop

**Conditional sDAI Liquidation** (`conditional_sdai_liquidation.py`):
- Handles imbalances when YES and NO token amounts don't match
- For excess YES tokens: Direct swap YES→sDAI on Swapr
- For excess NO tokens: Buy YES tokens with sDAI, then merge back to sDAI
- Uses 1% slippage tolerance for liquidation swaps

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
- `FUTARCHY_ROUTER_ADDRESS` - FutarchyRouter contract for splitting/merging tokens
- `FUTARCHY_PROPOSAL_ADDRESS` - Futarchy proposal contract address
- `SDAI_TOKEN_ADDRESS` - sDAI token contract
- `COMPANY_TOKEN_ADDRESS` - Company token contract (previously GNO)
- `SWAPR_SDAI_YES_ADDRESS` - Conditional sDAI YES token
- `SWAPR_SDAI_NO_ADDRESS` - Conditional sDAI NO token
- `SWAPR_GNO_YES_ADDRESS` - Conditional Company YES token
- `SWAPR_GNO_NO_ADDRESS` - Conditional Company NO token

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

### Code Style Guidelines
- **Logging**: Use `print()` statements for arbitrage commands, `logging` module for helpers
- **Comments**: Use section headers with dashes for major sections
- **Handler Functions**: Transaction simulation handlers should be prefixed with `handle_`
- **Debug Output**: Keep debug prints minimal; consolidate into single-line summaries
- **Error Handling**: Add descriptive error messages with context

### Transaction Flow
The bot uses a simulation-first approach:
1. Build transaction bundles as Tenderly-compatible dictionaries
2. Simulate transactions to calculate optimal parameters
3. Execute on-chain only after successful simulation
4. Each transaction has an associated handler function for state tracking