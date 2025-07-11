# Scalable Configuration System - IMPLEMENTED

## Overview

Replace the current `.env` file-based configuration with a scalable system that:
- Uses a single master private key in `.env`
- Derives bot-specific keys using HD wallet key derivation
- Stores configuration in Supabase
- Supports multiple bots and markets dynamically
- **SIMPLIFIED: Just 2 tables for minimal complexity**

## Current Problems

1. **Multiple .env files**: `.env.0x9590dAF4...`, `.env.0x1234...` for each market
2. **Key management**: Each bot needs its own private key stored in plaintext
3. **Configuration sprawl**: Contract addresses, pool addresses mixed with secrets
4. **No centralized management**: Hard to manage multiple bots across markets
5. **Security risks**: Multiple private keys in multiple files

## Implemented Architecture (Simplified)

### 1. Configuration Layers

```
┌─────────────────────────────────────────┐
│          .env (Local Only)              │
│   • MASTER_PRIVATE_KEY                  │
│   • SUPABASE_URL                        │
│   • SUPABASE_ANON_KEY                   │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│      Supabase Database (2 Tables)       │
│   • bot_configurations                  │
│   • bot_market_assignments              │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│      Runtime Configuration              │
│   • Derived Private Keys                │
│   • Merged Configuration                │
└─────────────────────────────────────────┘
```

### 2. Database Schema (As Implemented)

#### Bot Configurations Table
```sql
CREATE TABLE bot_configurations (
    id SERIAL PRIMARY KEY,
    bot_name VARCHAR(255) NOT NULL UNIQUE,
    wallet_address VARCHAR(255) NOT NULL UNIQUE,
    key_derivation_path VARCHAR(255) NOT NULL, -- e.g., "m/44'/60'/0'/0/1"
    bot_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'inactive' CHECK (status IN ('active', 'inactive')),
    config JSONB NOT NULL DEFAULT '{}', -- All bot-specific config goes here
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

#### Bot Market Assignments Table
```sql
CREATE TABLE bot_market_assignments (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER REFERENCES bot_configurations(id) ON DELETE CASCADE,
    market_event_id VARCHAR(255) REFERENCES market_event(id),
    pool_id VARCHAR(255) REFERENCES pools(id),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bot_id, market_event_id, pool_id)
);
```

### 3. JSONB Config Structure

The `config` field in `bot_configurations` stores all bot-specific configuration:

```json
{
  "strategy": {
    "type": "market_maker",
    "spread_percentage": 0.005,
    "rebalance_threshold": 0.02,
    "max_position_size": "1000.0",
    "min_trade_size": "10.0"
  },
  "risk": {
    "max_daily_trades": 100,
    "risk_limit": "5000.0",
    "stop_loss_percentage": 0.05
  },
  "contracts": {
    "futarchy_proposal_address": "0x...",
    "futarchy_router_address": "0x...",
    "custom_addresses": {}
  },
  "parameters": {
    "trading_amount": "0.1",
    "gas_price_gwei": "5",
    "slippage_tolerance": 0.01
  }
}
```

### 4. Key Derivation System

```python
# src/config/key_manager.py
from eth_account import Account
import hashlib

class KeyManager:
    def __init__(self, master_private_key: str):
        """Initialize with master private key from .env"""
        self.master_key = master_private_key
        
    def derive_key(self, derivation_path: str) -> str:
        """
        Derive a child private key from master using path
        Path format: "m/purpose'/coin_type'/account'/change/index"
        Example: "m/44'/60'/0'/0/1" for first Ethereum account
        """
        # Simplified example - use proper HD wallet library in production
        seed = hashlib.sha256(
            f"{self.master_key}{derivation_path}".encode()
        ).digest()
        
        derived_account = Account.from_key(seed)
        return derived_account.key.hex()
    
    def get_account(self, bot_config: dict) -> Account:
        """Get derived account for a specific bot"""
        derived_key = self.derive_key(bot_config['key_derivation_path'])
        return Account.from_key(derived_key)
```

### 5. Configuration Manager (Simplified)

```python
# src/config/config_manager.py
from supabase import create_client
import os
from typing import Dict, Any, Optional

class ConfigManager:
    def __init__(self):
        # Only these come from .env
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_ANON_KEY")
        self.master_key = os.getenv("MASTER_PRIVATE_KEY")
        
        self.supabase = create_client(self.supabase_url, self.supabase_key)
        self.key_manager = KeyManager(self.master_key)
        
    def get_bot_config(self, bot_name: str) -> Dict[str, Any]:
        """Get complete configuration for a bot"""
        # Fetch bot configuration
        bot = self.supabase.table('bot_configurations').select(
            "*, bot_market_assignments(*)"
        ).eq('bot_name', bot_name).eq('status', 'active').single().execute()
        
        return bot.data
    
    def get_bot_account(self, bot_name: str) -> Account:
        """Get derived account for bot"""
        config = self.get_bot_config(bot_name)
        return self.key_manager.get_account(config)
    
    def update_config(self, bot_name: str, config_updates: Dict[str, Any]):
        """Update bot configuration"""
        bot = self.get_bot_config(bot_name)
        
        # Merge updates into existing config
        new_config = {**bot['config'], **config_updates}
        
        self.supabase.table('bot_configurations').update({
            'config': new_config,
            'updated_at': 'NOW()'
        }).eq('bot_name', bot_name).execute()
```

### 6. Integration with Existing Bots

```python
# src/arbitrage_commands/unified_bot.py
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bot-name', required=True, help='Bot name in Supabase')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    
    # Load configuration from Supabase
    config_manager = ConfigManager()
    bot_config = config_manager.get_bot_config(args.bot_name)
    account = config_manager.get_bot_account(args.bot_name)
    
    # Extract settings from JSONB config
    strategy_config = bot_config['config']['strategy']
    contract_config = bot_config['config']['contracts']
    
    # Initialize Web3 with derived account
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    w3.eth.default_account = account.address
    
    # Create bot with configuration
    bot = UnifiedBot(
        account=account,
        w3=w3,
        trading_amount=strategy_config.get('trading_amount', '0.1'),
        router_address=contract_config['futarchy_router_address'],
        dry_run=args.dry_run
    )
    
    bot.run()
```

### 7. CLI Commands

```bash
# Register a new bot
python -m src.config.cli register-bot \
    --name "gnosis-futarchy-bot-1" \
    --type "market_maker" \
    --derivation-path "m/44'/60'/0'/0/1"

# Assign bot to market/pool
python -m src.config.cli assign-bot \
    --bot-name "gnosis-futarchy-bot-1" \
    --market-event-id 123 \
    --pool-id "0xabc123..."

# Update bot configuration
python -m src.config.cli update-config \
    --bot-name "gnosis-futarchy-bot-1" \
    --key "strategy.spread_percentage" \
    --value "0.01"

# Run bot (replaces old .env approach)
python -m src.arbitrage_commands.unified_bot --bot-name "gnosis-futarchy-bot-1"
```

### 8. Migration Strategy

#### Phase 1: Infrastructure Setup ✅
- [x] Create Supabase tables (DONE - 2 tables only)
- [ ] Implement KeyManager class
- [ ] Implement ConfigManager class

#### Phase 2: Migration Script
```python
# migration/migrate_env_to_supabase.py
def migrate_env_file(env_file_path: str, bot_name: str):
    """Migrate a .env.0xADDRESS file to new bot configuration"""
    config = dotenv_values(env_file_path)
    
    # Register bot
    bot_data = {
        'bot_name': bot_name,
        'bot_type': 'market_maker',
        'wallet_address': derive_wallet_address(bot_name),
        'key_derivation_path': f"m/44'/60'/0'/0/{hash(bot_name) % 1000}",
        'config': {
            'contracts': {
                'futarchy_proposal_address': config['FUTARCHY_PROPOSAL_ADDRESS'],
                'futarchy_router_address': config['FUTARCHY_ROUTER_ADDRESS'],
            },
            'strategy': {
                'type': 'market_maker',
                'trading_amount': config.get('TRADING_AMOUNT', '0.1')
            }
        }
    }
    
    # Insert into Supabase
    supabase.table('bot_configurations').insert(bot_data).execute()
```

### 9. Benefits of Simplified Design

1. **Minimal Complexity**: Just 2 tables instead of 5
2. **Flexible Configuration**: All config in JSONB - no schema changes needed
3. **Easy Migration**: Simple structure makes migration straightforward
4. **Future-Proof**: Can add features without schema changes
5. **Single Source of Truth**: All bot config in one place
6. **Security**: Only master key in .env, derived keys never stored

### 10. Security Considerations

1. **Master Key Protection**:
   - Never store in Supabase
   - Use environment variables only
   - Consider hardware security module (HSM) in production

2. **Access Control**:
   - Use Supabase Row Level Security (RLS)
   - Separate read/write permissions
   - API key rotation

3. **Key Derivation**:
   - Use proper BIP32/BIP44 implementation
   - Never expose derivation paths publicly
   - Each bot gets unique derived key

### 11. Future Enhancements (Optional)

If needed later, can add:
- Performance tracking table
- Operation logging table
- Strategy templates
- Multi-signature support
- Remote configuration updates

But for now, **keep it simple** with just 2 tables and flexible JSONB configuration.