"""Configuration Manager for bot configuration via Supabase.

This module provides centralized configuration management using Supabase
as the backend store. It handles bot configurations, market assignments,
and integrates with the KeyManager for secure key derivation.
"""

from supabase import create_client, Client
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
import json
import logging
from eth_account import Account

from .key_manager import KeyManager

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages bot configurations stored in Supabase."""
    
    def __init__(self):
        """Initialize ConfigManager with environment variables."""
        # Only these come from .env
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_ANON_KEY")
        self.master_key = os.getenv("MASTER_PRIVATE_KEY")
        
        if not all([self.supabase_url, self.supabase_key, self.master_key]):
            raise ValueError(
                "Missing required environment variables: "
                "SUPABASE_URL, SUPABASE_ANON_KEY, MASTER_PRIVATE_KEY"
            )
        
        self.supabase: Client = create_client(self.supabase_url, self.supabase_key)
        self.key_manager = KeyManager(self.master_key)
        
    def get_bot_config(self, bot_name: str) -> Dict[str, Any]:
        """Get complete configuration for a bot.
        
        Args:
            bot_name: Name of the bot to fetch configuration for
            
        Returns:
            Complete bot configuration including market assignments
            
        Raises:
            ValueError: If bot not found or inactive
        """
        try:
            # Fetch bot configuration with market assignments
            response = self.supabase.table('bot_configurations').select(
                "*, bot_market_assignments(*)"
            ).eq('bot_name', bot_name).eq('status', 'active').single().execute()
            
            if not response.data:
                raise ValueError(f"Bot '{bot_name}' not found or inactive")
                
            return response.data
            
        except Exception as e:
            logger.error(f"Error fetching bot config for {bot_name}: {e}")
            raise
    
    def get_bot_account(self, bot_name: str) -> Account:
        """Get derived account for bot.
        
        Args:
            bot_name: Name of the bot
            
        Returns:
            Derived eth_account.Account instance
        """
        config = self.get_bot_config(bot_name)
        return self.key_manager.get_account(config)
    
    def list_active_bots(self) -> List[Dict[str, Any]]:
        """List all active bots.
        
        Returns:
            List of active bot configurations
        """
        response = self.supabase.table('bot_configurations').select(
            "*"
        ).eq('status', 'active').execute()
        
        return response.data
    
    def register_bot(self, bot_name: str, bot_type: str, 
                    config: Optional[Dict[str, Any]] = None,
                    derivation_path: Optional[str] = None) -> Dict[str, Any]:
        """Register a new bot in the system.
        
        Args:
            bot_name: Unique name for the bot
            bot_type: Type of bot (e.g., 'market_maker', 'arbitrage')
            config: Initial configuration (optional)
            derivation_path: HD wallet derivation path (optional, auto-generated if not provided)
            
        Returns:
            Created bot configuration
        """
        # Generate derivation path if not provided
        if not derivation_path:
            # Get current bot count to generate unique index
            bot_count = len(self.list_all_bots())
            derivation_path = f"m/44'/60'/0'/0/{bot_count + 1}"
        
        # Get wallet address from derivation path
        wallet_address = self.key_manager.get_address(derivation_path)
        
        # Default configuration if not provided
        if config is None:
            config = self._get_default_config(bot_type)
        
        bot_data = {
            'bot_name': bot_name,
            'wallet_address': wallet_address,
            'key_derivation_path': derivation_path,
            'bot_type': bot_type,
            'status': 'inactive',  # Start as inactive
            'config': config
        }
        
        response = self.supabase.table('bot_configurations').insert(
            bot_data
        ).execute()
        
        logger.info(f"Registered bot '{bot_name}' with address {wallet_address}")
        return response.data[0]
    
    def update_config(self, bot_name: str, config_updates: Dict[str, Any],
                     merge: bool = True):
        """Update bot configuration.
        
        Args:
            bot_name: Name of the bot to update
            config_updates: Configuration updates to apply
            merge: If True, merge with existing config. If False, replace entirely.
        """
        if merge:
            # Get current config
            bot = self.get_bot_config(bot_name)
            # Deep merge updates into existing config
            new_config = self._deep_merge(bot['config'], config_updates)
        else:
            new_config = config_updates
        
        response = self.supabase.table('bot_configurations').update({
            'config': new_config,
            'updated_at': datetime.utcnow().isoformat()
        }).eq('bot_name', bot_name).execute()
        
        logger.info(f"Updated configuration for bot '{bot_name}'")
        return response.data[0]
    
    def activate_bot(self, bot_name: str):
        """Activate a bot."""
        response = self.supabase.table('bot_configurations').update({
            'status': 'active',
            'updated_at': datetime.utcnow().isoformat()
        }).eq('bot_name', bot_name).execute()
        
        logger.info(f"Activated bot '{bot_name}'")
        return response.data[0]
    
    def deactivate_bot(self, bot_name: str):
        """Deactivate a bot."""
        response = self.supabase.table('bot_configurations').update({
            'status': 'inactive',
            'updated_at': datetime.utcnow().isoformat()
        }).eq('bot_name', bot_name).execute()
        
        logger.info(f"Deactivated bot '{bot_name}'")
        return response.data[0]
    
    def assign_bot_to_market(self, bot_name: str, market_event_id: str, 
                           pool_id: str, is_active: bool = True):
        """Assign a bot to a market/pool combination.
        
        Args:
            bot_name: Name of the bot
            market_event_id: Market event ID from market_event table
            pool_id: Pool ID from pools table
            is_active: Whether the assignment is active
        """
        # Get bot ID
        bot = self.get_bot_config(bot_name)
        
        assignment_data = {
            'bot_id': bot['id'],
            'market_event_id': market_event_id,
            'pool_id': pool_id,
            'is_active': is_active
        }
        
        response = self.supabase.table('bot_market_assignments').insert(
            assignment_data
        ).execute()
        
        logger.info(
            f"Assigned bot '{bot_name}' to market {market_event_id} "
            f"and pool {pool_id}"
        )
        return response.data[0]
    
    def get_bot_assignments(self, bot_name: str) -> List[Dict[str, Any]]:
        """Get all market assignments for a bot.
        
        Args:
            bot_name: Name of the bot
            
        Returns:
            List of market assignments
        """
        bot = self.get_bot_config(bot_name)
        
        response = self.supabase.table('bot_market_assignments').select(
            "*, market_event(*), pools(*)"
        ).eq('bot_id', bot['id']).eq('is_active', True).execute()
        
        return response.data
    
    def list_all_bots(self) -> List[Dict[str, Any]]:
        """List all bots (active and inactive).
        
        Returns:
            List of all bot configurations
        """
        response = self.supabase.table('bot_configurations').select("*").execute()
        return response.data
    
    def _get_default_config(self, bot_type: str) -> Dict[str, Any]:
        """Get default configuration for a bot type.
        
        Args:
            bot_type: Type of bot
            
        Returns:
            Default configuration dictionary
        """
        defaults = {
            'market_maker': {
                'strategy': {
                    'type': 'market_maker',
                    'spread_percentage': 0.005,
                    'rebalance_threshold': 0.02,
                    'max_position_size': '1000.0',
                    'min_trade_size': '10.0'
                },
                'risk': {
                    'max_daily_trades': 100,
                    'risk_limit': '5000.0',
                    'stop_loss_percentage': 0.05
                },
                'parameters': {
                    'trading_amount': '0.1',
                    'gas_price_gwei': '5',
                    'slippage_tolerance': 0.01
                }
            },
            'arbitrage': {
                'strategy': {
                    'type': 'arbitrage',
                    'min_profit_threshold': 0.001,
                    'max_trade_size': '1000.0',
                    'price_tolerance': 0.02
                },
                'risk': {
                    'max_daily_trades': 200,
                    'risk_limit': '10000.0'
                },
                'parameters': {
                    'trading_amount': '0.1',
                    'gas_price_gwei': '5',
                    'slippage_tolerance': 0.01,
                    'check_interval': 120
                }
            }
        }
        
        base_config = defaults.get(bot_type, defaults['arbitrage'])
        
        # Add empty contracts section (to be filled during assignment)
        base_config['contracts'] = {
            'futarchy_proposal_address': '',
            'futarchy_router_address': '',
            'custom_addresses': {}
        }
        
        return base_config
    
    def _deep_merge(self, base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries.
        
        Args:
            base: Base dictionary
            updates: Updates to merge in
            
        Returns:
            Merged dictionary
        """
        result = base.copy()
        
        for key, value in updates.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
                
        return result
    
    def export_bot_config(self, bot_name: str, filepath: str):
        """Export bot configuration to a JSON file.
        
        Args:
            bot_name: Name of the bot
            filepath: Path to save the configuration
        """
        config = self.get_bot_config(bot_name)
        
        # Remove sensitive information
        export_config = {
            'bot_name': config['bot_name'],
            'bot_type': config['bot_type'],
            'wallet_address': config['wallet_address'],
            'config': config['config'],
            'market_assignments': config.get('bot_market_assignments', [])
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_config, f, indent=2)
            
        logger.info(f"Exported configuration for bot '{bot_name}' to {filepath}")
    
    def import_bot_config(self, filepath: str, new_bot_name: Optional[str] = None):
        """Import bot configuration from a JSON file.
        
        Args:
            filepath: Path to the configuration file
            new_bot_name: Optional new name for the bot (uses name from file if not provided)
        """
        with open(filepath, 'r') as f:
            import_config = json.load(f)
        
        bot_name = new_bot_name or import_config['bot_name']
        
        # Register the bot
        bot = self.register_bot(
            bot_name=bot_name,
            bot_type=import_config['bot_type'],
            config=import_config['config']
        )
        
        logger.info(f"Imported configuration for bot '{bot_name}' from {filepath}")
        return bot