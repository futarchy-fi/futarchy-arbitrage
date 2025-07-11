# Scalable Configuration System Proposal

## Overview

Replace the current `.env` file-based configuration with a scalable system that:
- Uses a single master private key in `.env`
- Derives bot-specific keys using HD wallet key derivation
- Stores configuration in Supabase
- Supports multiple bots and markets dynamically

## Current Problems

1. **Multiple .env files**: `.env.0x9590dAF4...`, `.env.0x1234...` for each market
2. **Key management**: Each bot needs its own private key stored in plaintext
3. **Configuration sprawl**: Contract addresses, pool addresses mixed with secrets
4. **No centralized management**: Hard to manage multiple bots across markets
5. **Security risks**: Multiple private keys in multiple files

## Proposed Architecture

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
│         Supabase Database               │
│   • Bot Configurations                  │
│   • Market Configurations               │
│   • Pool Addresses                      │
│   • Key Derivation Paths               │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│      Runtime Configuration              │
│   • Derived Private Keys                │
│   • Merged Configuration                │
│   • Cached Data                         │
└─────────────────────────────────────────┘
```

### 2. Database Schema (Supabase)

#### Markets Table
```sql
CREATE TABLE markets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    chain_id INTEGER NOT NULL,
    futarchy_proposal_address TEXT NOT NULL,
    futarchy_router_address TEXT NOT NULL,
    company_token_address TEXT NOT NULL,
    sdai_token_address TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### Pools Table
```sql
CREATE TABLE pools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id UUID REFERENCES markets(id),
    pool_type TEXT NOT NULL, -- 'balancer', 'swapr'
    pool_name TEXT NOT NULL, -- 'yes', 'no', 'pred_yes', 'main'
    pool_address TEXT NOT NULL,
    token_addresses JSONB NOT NULL, -- Array of token addresses
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### Bot Configurations Table
```sql
CREATE TABLE bot_configurations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bot_name TEXT NOT NULL UNIQUE,
    market_id UUID REFERENCES markets(id),
    key_derivation_path TEXT NOT NULL, -- e.g., "m/44'/60'/0'/0/1"
    bot_type TEXT NOT NULL, -- 'simple', 'complex', 'light', 'unified'
    config JSONB NOT NULL, -- Bot-specific configuration
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### Trading Parameters Table
```sql
CREATE TABLE trading_parameters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bot_config_id UUID REFERENCES bot_configurations(id),
    parameter_name TEXT NOT NULL,
    parameter_value JSONB NOT NULL,
    valid_from TIMESTAMP DEFAULT NOW(),
    valid_to TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 3. Key Derivation System

```python
# src/config/key_manager.py
from eth_account import Account
from eth_keys import keys
from mnemonic import Mnemonic
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
        # Implementation using BIP32/BIP44 HD wallet derivation
        # This is a simplified example - use proper HD wallet library
        seed = hashlib.sha256(
            f"{self.master_key}{derivation_path}".encode()
        ).digest()
        
        derived_account = Account.from_key(seed)
        return derived_account.key.hex()
    
    def get_account(self, bot_name: str, config: BotConfig) -> Account:
        """Get derived account for a specific bot"""
        derived_key = self.derive_key(config.key_derivation_path)
        return Account.from_key(derived_key)
```

### 4. Configuration Manager

```python
# src/config/config_manager.py
from supabase import create_client, Client
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class MarketConfig:
    id: str
    name: str
    chain_id: int
    futarchy_proposal_address: str
    futarchy_router_address: str
    company_token_address: str
    sdai_token_address: str
    pools: Dict[str, PoolConfig]

@dataclass
class BotConfig:
    id: str
    bot_name: str
    market_id: str
    key_derivation_path: str
    bot_type: str
    parameters: Dict[str, Any]
    market: Optional[MarketConfig] = None

class ConfigManager:
    def __init__(self):
        # Only these come from .env
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_ANON_KEY")
        self.master_key = os.getenv("MASTER_PRIVATE_KEY")
        
        # Initialize connections
        self.supabase = create_client(self.supabase_url, self.supabase_key)
        self.key_manager = KeyManager(self.master_key)
        
        # Cache for performance
        self._config_cache: Dict[str, BotConfig] = {}
        self._market_cache: Dict[str, MarketConfig] = {}
    
    def get_bot_config(self, bot_name: str) -> BotConfig:
        """Get complete configuration for a bot"""
        if bot_name in self._config_cache:
            return self._config_cache[bot_name]
        
        # Fetch from Supabase
        response = self.supabase.table('bot_configurations').select(
            "*, markets(*, pools(*))"
        ).eq('bot_name', bot_name).single().execute()
        
        config = self._parse_bot_config(response.data)
        self._config_cache[bot_name] = config
        return config
    
    def get_bot_account(self, bot_name: str) -> Account:
        """Get derived account for bot"""
        config = self.get_bot_config(bot_name)
        return self.key_manager.get_account(bot_name, config)
    
    def update_trading_parameter(
        self, 
        bot_name: str, 
        param_name: str, 
        param_value: Any
    ):
        """Update a trading parameter in Supabase"""
        bot_config = self.get_bot_config(bot_name)
        
        self.supabase.table('trading_parameters').insert({
            'bot_config_id': bot_config.id,
            'parameter_name': param_name,
            'parameter_value': param_value
        }).execute()
        
        # Invalidate cache
        if bot_name in self._config_cache:
            del self._config_cache[bot_name]
```

### 5. Integration with Unified Bot

```python
# src/arbitrage_commands/unified_bot.py
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bot-name', required=True, help='Bot name in Supabase')
    parser.add_argument('--dry-run', action='store_true', help='Run without executing trades')
    args = parser.parse_args()
    
    # Load configuration from Supabase
    config_manager = ConfigManager()
    bot_config = config_manager.get_bot_config(args.bot_name)
    account = config_manager.get_bot_account(args.bot_name)
    
    # Initialize Web3 with derived account
    w3 = Web3(Web3.HTTPProvider(bot_config.market.rpc_url))
    w3.eth.default_account = account.address
    
    # Create bot with configuration
    bot = UnifiedBot(
        config=bot_config,
        account=account,
        w3=w3,
        dry_run=args.dry_run
    )
    
    bot.run()
```

### 6. Migration Strategy

#### Phase 1: Setup Infrastructure
1. Create Supabase project and tables
2. Implement KeyManager and ConfigManager
3. Add support to existing bots to use ConfigManager optionally

#### Phase 2: Data Migration
```python
# migration/migrate_env_to_supabase.py
def migrate_env_file(env_file_path: str, market_name: str):
    """Migrate a .env.0xADDRESS file to Supabase"""
    # Load .env file
    config = dotenv_values(env_file_path)
    
    # Create market entry
    market = {
        'name': market_name,
        'chain_id': 100,  # Gnosis Chain
        'futarchy_proposal_address': config['FUTARCHY_PROPOSAL_ADDRESS'],
        'futarchy_router_address': config['FUTARCHY_ROUTER_ADDRESS'],
        # ... other fields
    }
    
    # Create pool entries
    pools = [
        {
            'pool_type': 'swapr',
            'pool_name': 'yes',
            'pool_address': config['SWAPR_POOL_YES_ADDRESS'],
            # ...
        },
        # ... other pools
    ]
    
    # Insert into Supabase
    # ...
```

#### Phase 3: Transition
1. Run both systems in parallel for testing
2. Gradually migrate bots to use Supabase
3. Deprecate .env files (except master)
4. Remove old configuration code

### 7. Security Considerations

1. **Master Key Protection**:
   - Never store in Supabase
   - Use hardware security module (HSM) in production
   - Rotate periodically

2. **Access Control**:
   - Use Supabase Row Level Security (RLS)
   - Separate read/write permissions
   - API key rotation

3. **Key Derivation**:
   - Use proper BIP32/BIP44 implementation
   - Never expose derivation paths publicly
   - Each bot gets unique derived key

4. **Audit Trail**:
   - Log all configuration changes
   - Track parameter history
   - Monitor unauthorized access

### 8. Benefits

1. **Scalability**: Add new bots/markets without new .env files
2. **Security**: Single master key, derived keys never stored
3. **Management**: Central configuration via Supabase dashboard
4. **Flexibility**: Update parameters without redeploying
5. **Monitoring**: Track all bots from single interface
6. **Version Control**: Configuration history in database

### 9. Example Usage

```bash
# Old way (multiple .env files)
source .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF
python -m src.arbitrage_commands.simple_bot --amount 0.1

# New way (bot name only)
python -m src.arbitrage_commands.unified_bot --bot-name "gnosis-futarchy-bot-1"

# Update configuration via CLI
python -m src.config.cli update-param \
    --bot-name "gnosis-futarchy-bot-1" \
    --param "trading_amount" \
    --value "0.5"

# Create new bot
python -m src.config.cli create-bot \
    --name "gnosis-futarchy-bot-2" \
    --market "gnosis-futarchy-main" \
    --type "complex" \
    --derivation-path "m/44'/60'/0'/0/2"
```

### 10. Future Enhancements

1. **Multi-signature**: Require multiple keys for large trades
2. **Remote Execution**: Bots pull configuration and execute remotely
3. **Performance Metrics**: Store trading results in Supabase
4. **Alerts**: Configure alerts for specific conditions
5. **A/B Testing**: Run multiple strategies on same market
6. **Auto-scaling**: Spawn new bot instances based on load