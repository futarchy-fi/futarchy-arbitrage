"""CLI commands for managing bot configurations in Supabase.

This module provides command-line tools for registering, configuring,
and managing arbitrage bots using the Supabase configuration system.
"""

import argparse
import json
import sys
from typing import Optional
from tabulate import tabulate

sys.path.insert(0, '/home/ubuntu/futarchy-arbitrage')

from src.config.config_manager import ConfigManager
from src.config.key_manager import create_deterministic_address


def register_bot(args):
    """Register a new bot in the system."""
    config_manager = ConfigManager()
    
    # Parse config JSON if provided
    config = None
    if args.config:
        try:
            config = json.loads(args.config)
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON in config: {args.config}")
            sys.exit(1)
    
    # Register the bot
    try:
        bot = config_manager.register_bot(
            bot_name=args.name,
            bot_type=args.type,
            config=config,
            derivation_path=args.derivation_path
        )
        
        print(f"Successfully registered bot '{args.name}'")
        print(f"Wallet address: {bot['wallet_address']}")
        print(f"Derivation path: {bot['key_derivation_path']}")
        print(f"Status: {bot['status']} (use 'activate' command to enable)")
        
    except Exception as e:
        print(f"Error registering bot: {e}")
        sys.exit(1)


def list_bots(args):
    """List all bots or active bots."""
    config_manager = ConfigManager()
    
    if args.all:
        bots = config_manager.list_all_bots()
        title = "All Bots"
    else:
        bots = config_manager.list_active_bots()
        title = "Active Bots"
    
    if not bots:
        print(f"No {title.lower()} found")
        return
    
    # Prepare table data
    headers = ["Name", "Type", "Status", "Wallet Address", "Created"]
    rows = []
    
    for bot in bots:
        rows.append([
            bot['bot_name'],
            bot['bot_type'],
            bot['status'],
            bot['wallet_address'][:10] + "...",
            bot['created_at'][:10]
        ])
    
    print(f"\n{title}:")
    print(tabulate(rows, headers=headers, tablefmt="grid"))


def show_bot(args):
    """Show detailed information about a specific bot."""
    config_manager = ConfigManager()
    
    try:
        bot = config_manager.get_bot_config(args.name)
        
        print(f"\nBot: {bot['bot_name']}")
        print(f"Type: {bot['bot_type']}")
        print(f"Status: {bot['status']}")
        print(f"Wallet: {bot['wallet_address']}")
        print(f"Derivation Path: {bot['key_derivation_path']}")
        print(f"Created: {bot['created_at']}")
        print(f"Updated: {bot['updated_at']}")
        
        print("\nConfiguration:")
        print(json.dumps(bot['config'], indent=2))
        
        # Show market assignments
        assignments = bot.get('bot_market_assignments', [])
        if assignments:
            print(f"\nMarket Assignments ({len(assignments)}):")
            for i, assignment in enumerate(assignments):
                print(f"  {i+1}. Market: {assignment['market_event_id']}, "
                      f"Pool: {assignment['pool_id']}, "
                      f"Active: {assignment['is_active']}")
        else:
            print("\nNo market assignments")
            
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def activate_bot(args):
    """Activate a bot."""
    config_manager = ConfigManager()
    
    try:
        bot = config_manager.activate_bot(args.name)
        print(f"Bot '{args.name}' activated successfully")
    except Exception as e:
        print(f"Error activating bot: {e}")
        sys.exit(1)


def deactivate_bot(args):
    """Deactivate a bot."""
    config_manager = ConfigManager()
    
    try:
        bot = config_manager.deactivate_bot(args.name)
        print(f"Bot '{args.name}' deactivated successfully")
    except Exception as e:
        print(f"Error deactivating bot: {e}")
        sys.exit(1)


def update_config(args):
    """Update bot configuration."""
    config_manager = ConfigManager()
    
    # Parse the value
    try:
        # Try to parse as JSON first
        value = json.loads(args.value)
    except json.JSONDecodeError:
        # If not JSON, use as string
        value = args.value
    
    # Build config update dictionary
    config_update = {}
    keys = args.key.split('.')
    current = config_update
    
    for key in keys[:-1]:
        current[key] = {}
        current = current[key]
    
    current[keys[-1]] = value
    
    try:
        bot = config_manager.update_config(args.name, config_update)
        print(f"Updated configuration for bot '{args.name}'")
        print(f"Key: {args.key}")
        print(f"New value: {value}")
    except Exception as e:
        print(f"Error updating configuration: {e}")
        sys.exit(1)


def assign_market(args):
    """Assign a bot to a market."""
    config_manager = ConfigManager()
    
    try:
        assignment = config_manager.assign_bot_to_market(
            bot_name=args.bot_name,
            market_event_id=args.market_event_id,
            pool_id=args.pool_id,
            is_active=not args.inactive
        )
        
        status = "active" if not args.inactive else "inactive"
        print(f"Assigned bot '{args.bot_name}' to market {args.market_event_id} "
              f"and pool {args.pool_id} ({status})")
              
    except Exception as e:
        print(f"Error assigning market: {e}")
        sys.exit(1)


def export_config(args):
    """Export bot configuration to file."""
    config_manager = ConfigManager()
    
    try:
        config_manager.export_bot_config(args.name, args.file)
        print(f"Exported configuration for bot '{args.name}' to {args.file}")
    except Exception as e:
        print(f"Error exporting configuration: {e}")
        sys.exit(1)


def import_config(args):
    """Import bot configuration from file."""
    config_manager = ConfigManager()
    
    try:
        bot = config_manager.import_bot_config(args.file, args.new_name)
        bot_name = args.new_name or bot['bot_name']
        print(f"Imported configuration for bot '{bot_name}' from {args.file}")
    except Exception as e:
        print(f"Error importing configuration: {e}")
        sys.exit(1)


def generate_address(args):
    """Generate a deterministic address for a bot name."""
    # This requires master key from environment
    import os
    master_key = os.getenv("MASTER_PRIVATE_KEY")
    
    if not master_key:
        print("Error: MASTER_PRIVATE_KEY not set in environment")
        sys.exit(1)
    
    address, derivation_path = create_deterministic_address(args.name, master_key)
    
    print(f"Bot name: {args.name}")
    print(f"Address: {address}")
    print(f"Derivation path: {derivation_path}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Manage arbitrage bot configurations'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Register bot command
    register_parser = subparsers.add_parser('register', help='Register a new bot')
    register_parser.add_argument('--name', required=True, help='Bot name')
    register_parser.add_argument('--type', required=True, 
                               choices=['market_maker', 'arbitrage'],
                               help='Bot type')
    register_parser.add_argument('--config', help='JSON configuration (optional)')
    register_parser.add_argument('--derivation-path', help='HD wallet derivation path (auto-generated if not provided)')
    register_parser.set_defaults(func=register_bot)
    
    # List bots command
    list_parser = subparsers.add_parser('list', help='List bots')
    list_parser.add_argument('--all', action='store_true', 
                           help='Show all bots (default: active only)')
    list_parser.set_defaults(func=list_bots)
    
    # Show bot command
    show_parser = subparsers.add_parser('show', help='Show bot details')
    show_parser.add_argument('name', help='Bot name')
    show_parser.set_defaults(func=show_bot)
    
    # Activate bot command
    activate_parser = subparsers.add_parser('activate', help='Activate a bot')
    activate_parser.add_argument('name', help='Bot name')
    activate_parser.set_defaults(func=activate_bot)
    
    # Deactivate bot command
    deactivate_parser = subparsers.add_parser('deactivate', help='Deactivate a bot')
    deactivate_parser.add_argument('name', help='Bot name')
    deactivate_parser.set_defaults(func=deactivate_bot)
    
    # Update config command
    update_parser = subparsers.add_parser('update', help='Update bot configuration')
    update_parser.add_argument('name', help='Bot name')
    update_parser.add_argument('--key', required=True, 
                             help='Configuration key (e.g., strategy.spread_percentage)')
    update_parser.add_argument('--value', required=True, 
                             help='New value (JSON or string)')
    update_parser.set_defaults(func=update_config)
    
    # Assign market command
    assign_parser = subparsers.add_parser('assign', help='Assign bot to market')
    assign_parser.add_argument('--bot-name', required=True, help='Bot name')
    assign_parser.add_argument('--market-event-id', required=True, 
                             help='Market event ID')
    assign_parser.add_argument('--pool-id', required=True, help='Pool ID')
    assign_parser.add_argument('--inactive', action='store_true',
                             help='Create inactive assignment')
    assign_parser.set_defaults(func=assign_market)
    
    # Export config command
    export_parser = subparsers.add_parser('export', help='Export bot configuration')
    export_parser.add_argument('name', help='Bot name')
    export_parser.add_argument('--file', required=True, help='Output file path')
    export_parser.set_defaults(func=export_config)
    
    # Import config command
    import_parser = subparsers.add_parser('import', help='Import bot configuration')
    import_parser.add_argument('file', help='Input file path')
    import_parser.add_argument('--new-name', help='New bot name (optional)')
    import_parser.set_defaults(func=import_config)
    
    # Generate address command
    address_parser = subparsers.add_parser('address', 
                                         help='Generate address for bot name')
    address_parser.add_argument('name', help='Bot name')
    address_parser.set_defaults(func=generate_address)
    
    # Parse arguments
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(0)
    
    # Execute command
    args.func(args)


if __name__ == '__main__':
    main()