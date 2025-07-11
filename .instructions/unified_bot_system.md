# Unified Bot System - Implementation Status

## Overview
The unified bot system replaces individual `.env` files with a centralized Supabase configuration system, enabling scalable multi-bot management with secure key derivation.

## Architecture Components

### 1. Database Schema (Deployed)
```sql
-- bot_configurations: Core bot registry
- id, bot_name, wallet_address, key_derivation_path
- bot_type, status, config (JSONB), timestamps

-- bot_market_assignments: Bot-to-market mappings  
- bot_id, market_event_id, pool_id, is_active
```

### 2. Key Management (`src/config/key_manager.py`)
- HD wallet derivation from single master key
- Deterministic address generation per bot
- BIP44-style paths: `m/44'/60'/0'/0/{index}`
- No private keys stored in database

### 3. Configuration Manager (`src/config/config_manager.py`)
- Supabase integration for bot configs
- Bot lifecycle: register → configure → assign → activate
- JSONB config structure:
  ```json
  {
    "strategy": { "type", "thresholds", "limits" },
    "risk": { "max_daily_trades", "risk_limit" },
    "contracts": { "addresses" },
    "parameters": { "trading_amount", "intervals" }
  }
  ```

### 4. Unified Bot (`src/arbitrage_commands/unified_bot.py`)
- Loads config from Supabase at runtime
- Derives private key from master + path
- Integrates existing arbitrage logic
- Risk management: daily limits, balance checks
- Supports dry-run mode

### 5. CLI Tool (`src/config/cli.py`)
```bash
# Bot management commands
register    # Create new bot
list        # Show bots (--all for inactive)
show        # Bot details + config
activate    # Enable bot
deactivate  # Disable bot
update      # Modify config (dot notation)
assign      # Link to market/pool
export      # Save config to JSON
import      # Load config from JSON
address     # Generate deterministic address
```

## Migration Path

### Environment Setup
```bash
# Old: Multiple .env files
.env.0x9590dAF4...  # Market 1 config + keys
.env.0x1234abcd...  # Market 2 config + keys

# New: Single .env
MASTER_PRIVATE_KEY=0x...
SUPABASE_URL=https://...
SUPABASE_ANON_KEY=eyJ...
```

### Bot Registration Flow
```bash
# 1. Install dependencies
pip install supabase tabulate

# 2. Register bot
python -m src.config.cli register \
  --name "gnosis-futarchy-1" \
  --type arbitrage

# 3. Configure contracts (from old .env values)
python -m src.config.cli update gnosis-futarchy-1 \
  --key "contracts.futarchy_router_address" \
  --value "0x8A9276cD13E36E0DB3bDE82489E87DCE27E0E348"

# 4. Set parameters
python -m src.config.cli update gnosis-futarchy-1 \
  --key "parameters.trading_amount" \
  --value "0.1"

# 5. Assign to market
python -m src.config.cli assign \
  --bot-name "gnosis-futarchy-1" \
  --market-event-id "0x9590dAF4..." \
  --pool-id "0xabc123..."

# 6. Activate and run
python -m src.config.cli activate gnosis-futarchy-1
python -m src.arbitrage_commands.unified_bot \
  --bot-name "gnosis-futarchy-1"
```

## Security Model
- **Master key**: Only in local .env, never in Supabase
- **Derived keys**: Generated at runtime, never stored
- **Access control**: Supabase RLS policies (to be configured)
- **Wallet isolation**: Each bot has unique deterministic address

## Benefits
1. **Scalability**: Unlimited bots from single master key
2. **Flexibility**: JSONB allows schema-free config evolution  
3. **Auditability**: All config changes tracked in database
4. **Simplicity**: 2 tables vs complex normalized schema
5. **Security**: Reduced key exposure, centralized management

## Current Status
✅ Database tables deployed
✅ KeyManager implemented  
✅ ConfigManager implemented
✅ UnifiedBot implemented
✅ CLI tool implemented
✅ Dependencies updated

## Next Steps
1. Configure Supabase RLS policies
2. Migrate existing bot configs
3. Set up monitoring/alerts
4. Add performance tracking
5. Implement strategy templates

## Usage Example
```bash
# List active bots
python -m src.config.cli list

# Check bot details
python -m src.config.cli show gnosis-futarchy-1

# Update tolerance
python -m src.config.cli update gnosis-futarchy-1 \
  --key "strategy.price_tolerance" --value "0.03"

# Run with dry-run
python -m src.arbitrage_commands.unified_bot \
  --bot-name "gnosis-futarchy-1" --dry-run --once
```