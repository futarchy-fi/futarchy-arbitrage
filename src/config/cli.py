"""CLI commands for managing bot configurations in Supabase.

This module provides command-line tools for registering, configuring,
and managing arbitrage bots using the Supabase configuration system.
"""

import argparse
import glob
import json
import os
import sys
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv

try:
    from tabulate import tabulate
except ModuleNotFoundError:  # pragma: no cover - fallback when optional dep missing
    def tabulate(rows, headers, tablefmt=None):
        # Minimal fallback that renders a plain aligned table when python-tabulate
        # is not installed. Keeps interface-compatible behaviour for our usage.
        columns = len(headers)
        widths = [len(h) for h in headers]
        for row in rows:
            for idx in range(columns):
                cell = str(row[idx]) if idx < len(row) else ""
                widths[idx] = max(widths[idx], len(cell))

        def fmt_row(row_values):
            padded = []
            for idx in range(columns):
                cell = str(row_values[idx]) if idx < len(row_values) else ""
                padded.append(cell.ljust(widths[idx]))
            return " | ".join(padded)

        lines = [fmt_row(headers)]
        lines.append("-+-".join("-" * w for w in widths))
        for row in rows:
            lines.append(fmt_row(row))
        return "\n".join(lines)

from web3 import Web3

try:
    from web3.middleware import geth_poa_middleware
except ImportError:  # pragma: no cover - optional dependency
    geth_poa_middleware = None

sys.path.insert(0, '/home/ubuntu/futarchy-arbitrage')

from src.config.config_manager import ConfigManager
from src.config.key_manager import create_deterministic_address

try:
    from src.setup.deployment_links import scan_deploy_logs, latest_links_by_path
except ImportError:  # pragma: no cover - optional helper
    scan_deploy_logs = None
    latest_links_by_path = None

# Load environment variables from .env if present so commands work out of the box.
load_dotenv()


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


ERC20_MIN_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Potential token sources to probe (searched in order).
TOKEN_SOURCES: Dict[str, List[Tuple[str, ...]]] = {
    "sDAI": [
        ("config", "parameters", "sdai_token_address"),
        ("config", "proposal", "tokens", "currency", "address"),
    ],
    "GNO": [
        ("config", "parameters", "company_token_address"),
        ("config", "proposal", "tokens", "company", "address"),
    ],
    "YES_sDAI": [
        ("config", "parameters", "swapr_sdai_yes_address"),
        ("config", "proposal", "tokens", "yes_currency", "address"),
    ],
    "NO_sDAI": [
        ("config", "parameters", "swapr_sdai_no_address"),
        ("config", "proposal", "tokens", "no_currency", "address"),
    ],
    "YES_GNO": [
        ("config", "parameters", "swapr_gno_yes_address"),
        ("config", "proposal", "tokens", "yes_company", "address"),
    ],
    "NO_GNO": [
        ("config", "parameters", "swapr_gno_no_address"),
        ("config", "proposal", "tokens", "no_company", "address"),
    ],
}

ENV_TOKEN_FALLBACKS: Dict[str, Tuple[str, ...]] = {
    "sDAI": ("SDAI_TOKEN_ADDRESS",),
    "GNO": ("COMPANY_TOKEN_ADDRESS",),
    "YES_sDAI": ("SWAPR_SDAI_YES_ADDRESS",),
    "NO_sDAI": ("SWAPR_SDAI_NO_ADDRESS",),
    "YES_GNO": ("SWAPR_GNO_YES_ADDRESS",),
    "NO_GNO": ("SWAPR_GNO_NO_ADDRESS",),
}

EXECUTOR_ENV_KEYS: Tuple[str, ...] = (
    "FUTARCHY_ARB_EXECUTOR_V5",
    "EXECUTOR_V5_ADDRESS",
    "ARBITRAGE_EXECUTOR_ADDRESS",
    "PREDICTION_ARB_EXECUTOR_V1",
)

EXECUTOR_DEPLOYMENT_GLOBS: Tuple[str, ...] = (
    "deployments/deployment_executor_v5_*.json",
    "deployments/deployment_prediction_arb_v1_*.json",
)

EXECUTOR_KEYWORDS: Tuple[str, ...] = ("executor", "arb_executor")


def _inject_poa_if_needed(w3: Web3) -> None:
    """Inject POA middleware when available to support Gnosis-style chains."""
    if geth_poa_middleware is None:
        return
    try:
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except ValueError:
        # Middleware already present
        pass


def _build_web3(rpc_url: str) -> Web3:
    """Instantiate Web3 for the supplied RPC endpoint."""
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    _inject_poa_if_needed(w3)
    if not w3.is_connected():
        raise RuntimeError(f"Failed to connect to RPC {rpc_url}")
    return w3


def _resolve_path(obj: Dict, path: Tuple[str, ...]) -> Optional[str]:
    """Traverse nested dictionaries using a tuple path."""
    current = obj
    for segment in path:
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current if isinstance(current, str) else None


def _resolve_token_addresses(bot: Dict) -> Dict[str, str]:
    """Derive token label -> address map from a bot configuration."""
    config_blob = bot.get("config", {}) or {}
    addresses: Dict[str, str] = {}
    for label, paths in TOKEN_SOURCES.items():
        for path in paths:
            addr = _resolve_path({"config": config_blob}, path)
            if addr:
                addresses[label] = addr
                break
        if label not in addresses:
            for env_var in ENV_TOKEN_FALLBACKS.get(label, ()):
                env_value = os.getenv(env_var)
                if env_value:
                    addresses[label] = env_value
                    break
    return addresses


def _shorten_address(addr: str) -> str:
    """Shorten an address for table rendering."""
    if not isinstance(addr, str):
        return "-"
    addr = addr.strip()
    if len(addr) <= 12:
        return addr
    return f"{addr[:6]}...{addr[-4:]}"


def _dedupe_preserve(addresses: Iterable[str]) -> List[str]:
    """Deduplicate addresses while preserving order."""
    seen = set()
    deduped: List[str] = []
    for addr in addresses:
        if not isinstance(addr, str):
            continue
        try:
            checksum = Web3.to_checksum_address(addr)
        except ValueError:
            continue
        lowered = checksum.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(checksum)
    return deduped


def _harvest_executor_addresses(obj: object) -> List[str]:
    """Recursively gather executor/deployment contract addresses from config blobs."""
    results: List[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = str(key).lower()
            if isinstance(value, str):
                candidate = value.strip()
                if any(keyword in key_lower for keyword in EXECUTOR_KEYWORDS) and Web3.is_address(candidate):
                    results.append(Web3.to_checksum_address(candidate))
            elif isinstance(value, dict):
                # If the parent key hints at executor, pull address fields inside.
                if any(keyword in key_lower for keyword in EXECUTOR_KEYWORDS):
                    inner = value.get("address")
                    if isinstance(inner, str) and Web3.is_address(inner):
                        results.append(Web3.to_checksum_address(inner))
                results.extend(_harvest_executor_addresses(value))
            elif isinstance(value, list):
                results.extend(_harvest_executor_addresses(value))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_harvest_executor_addresses(item))
    return results


def _latest_deployment_address(pattern: str) -> Optional[str]:
    """Grab the latest deployment address from local deployment artifacts."""
    files = sorted(glob.glob(pattern))
    for path in reversed(files):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        addr = data.get("address")
        if isinstance(addr, str) and Web3.is_address(addr):
            try:
                return Web3.to_checksum_address(addr)
            except ValueError:
                continue
    return None


def _resolve_deployment_addresses(
    bot: Dict,
    links_by_path: Optional[Dict[str, List[str]]] = None,
    links_by_wallet: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """Resolve deployment contract addresses associated with a bot."""
    config_blob = bot.get("config", {}) or {}
    harvested: List[str] = []

    path = bot.get("key_derivation_path") or config_blob.get("key_derivation_path")
    if links_by_path and path:
        harvested.extend(links_by_path.get(path, []))

    wallet = bot.get("wallet_address")
    if links_by_wallet and wallet:
        harvested.extend(links_by_wallet.get(wallet.lower(), []))

    harvested.extend(_harvest_executor_addresses(config_blob))

    if not harvested:
        for env_key in EXECUTOR_ENV_KEYS:
            env_val = os.getenv(env_key)
            if env_val and Web3.is_address(env_val):
                try:
                    harvested.append(Web3.to_checksum_address(env_val))
                except ValueError:
                    continue

    if not harvested:
        for pattern in EXECUTOR_DEPLOYMENT_GLOBS:
            addr = _latest_deployment_address(pattern)
            if addr:
                harvested.append(addr)
                break

    return _dedupe_preserve(harvested)


def _format_balance(balance_wei: int, decimals: int = 18) -> str:
    """Convert integer balance to human string with 6 decimals."""
    if balance_wei == 0:
        return "0"
    scaled = Decimal(balance_wei) / (Decimal(10) ** decimals)
    return f"{scaled:.6f}"


def _erc20_balance(w3: Web3, token: str, holder: str) -> int:
    """Fetch ERC20 balance for holder."""
    contract = w3.eth.contract(address=w3.to_checksum_address(token), abi=ERC20_MIN_ABI)
    return int(contract.functions.balanceOf(w3.to_checksum_address(holder)).call())


def report_bots(args):
    """Generate a balances report for bots."""
    config_manager = ConfigManager()
    try:
        base_list = config_manager.list_all_bots() if args.all else config_manager.list_active_bots()
    except Exception as exc:
        print(f"Error fetching bot list: {exc}")
        return
    if not base_list:
        scope = "all bots" if args.all else "active bots"
        print(f"No {scope} found")
        return

    deployment_logs: List = []
    links_by_path: Dict[str, List[str]] = {}
    links_by_wallet: Dict[str, List[str]] = {}
    if scan_deploy_logs is not None and latest_links_by_path is not None:
        try:
            deployment_logs = scan_deploy_logs()
        except Exception as exc:
            print(f"Warning: failed to scan deployment logs: {exc}")
        else:
            latest_map = latest_links_by_path(deployment_logs)
            for link in latest_map.values():
                try:
                    addr = Web3.to_checksum_address(link.address)
                except Exception:
                    continue
                path = getattr(link, "path", None)
                if isinstance(path, str):
                    links_by_path[path] = [addr]
                deployer = getattr(link, "deployer", None)
                if isinstance(deployer, str):
                    links_by_wallet.setdefault(deployer.lower(), []).append(addr)
    if links_by_path:
        links_by_path = {k: _dedupe_preserve(v) for k, v in links_by_path.items()}
    if links_by_wallet:
        links_by_wallet = {k: _dedupe_preserve(v) for k, v in links_by_wallet.items()}

    detailed: List[Dict] = []
    for item in base_list:
        name = item.get("bot_name")
        try:
            detailed.append(config_manager.get_bot_config(name))
        except Exception as exc:
            print(f"Warning: unable to fetch config for '{name}': {exc}")

    if not detailed:
        print("No bot configurations available for reporting")
        return

    rpc_cache: Dict[str, Web3] = {}
    rows: List[Dict[str, str]] = []
    dynamic_labels: List[str] = []

    for bot in detailed:
        name = bot.get("bot_name", "unknown")
        status = bot.get("status", "unknown")
        wallet = bot.get("wallet_address")
        config_blob = bot.get("config", {}) or {}

        if not wallet:
            print(f"Warning: bot '{name}' missing wallet address; skipping")
            continue

        env_rpc = os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL")
        rpc_url = args.rpc or _resolve_path({"config": config_blob}, ("config", "network", "rpc_url")) or env_rpc
        if not rpc_url:
            rpc_url = config_blob.get("network", {}).get("rpc_url")
        if not rpc_url:
            print(f"Warning: bot '{name}' missing RPC URL; skipping")
            continue

        if rpc_url not in rpc_cache:
            try:
                rpc_cache[rpc_url] = _build_web3(rpc_url)
            except Exception as exc:
                print(f"Warning: failed to connect to RPC for '{name}': {exc}")
                continue
        w3 = rpc_cache[rpc_url]

        deployment_addresses = _resolve_deployment_addresses(
            bot,
            links_by_path=links_by_path,
            links_by_wallet=links_by_wallet,
        )
        try:
            native_balance = int(w3.eth.get_balance(w3.to_checksum_address(wallet)))
        except Exception as exc:
            print(f"Warning: failed to fetch native balance for '{name}': {exc}")
            native_balance = 0

        token_addresses = _resolve_token_addresses(bot)
        token_balances: Dict[str, str] = {}
        holders_for_tokens: List[str] = deployment_addresses or [wallet]
        if not deployment_addresses and token_addresses:
            print(f"Warning: no deployment contracts found for '{name}'; using wallet balances for tokens")

        for label, token_addr in token_addresses.items():
            total_balance = 0
            had_success = False
            for holder in holders_for_tokens:
                try:
                    total_balance += _erc20_balance(w3, token_addr, holder)
                    had_success = True
                except Exception as exc:
                    print(f"Warning: token balance lookup failed for '{name}' ({label}) holder {holder}: {exc}")
            token_balances[label] = _format_balance(total_balance) if had_success else "0"

        if "sDAI" not in token_balances and args.sdai:
            total_balance = 0
            had_success = False
            for holder in holders_for_tokens:
                try:
                    total_balance += _erc20_balance(w3, args.sdai, holder)
                    had_success = True
                except Exception as exc:
                    print(f"Warning: fallback sDAI lookup failed for '{name}' holder {holder}: {exc}")
            if had_success:
                token_balances["sDAI"] = _format_balance(total_balance)

        for label in token_balances:
            if label not in dynamic_labels:
                dynamic_labels.append(label)

        rows.append({
            "bot": name,
            "status": status,
            "wallet": wallet,
            "deployment_contracts": deployment_addresses,
            "rpc": rpc_url,
            "native": _format_balance(native_balance),
            **token_balances,
        })

    if not rows:
        print("No balances collected")
        return

    if args.format == "json":
        print(json.dumps({"bots": rows}, indent=2))
        return

    headers = ["Bot", "Status", "Wallet", "Deployment", "Native(xDAI)"] + dynamic_labels
    table_rows = []
    for row in rows:
        deployment_display = ", ".join(_shorten_address(addr) for addr in row.get("deployment_contracts", []))
        if not deployment_display:
            deployment_display = "-"
        table_rows.append(
            [
                row["bot"],
                row.get("status", "-"),
                row.get("wallet", "-"),
                deployment_display,
                row.get("native", "0"),
                *[row.get(label, "0") for label in dynamic_labels],
            ]
        )

    print(tabulate(table_rows, headers=headers, tablefmt="grid"))


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
    report_parser = subparsers.add_parser('report', help='Show balances for bots')
    report_parser.add_argument('--all', action='store_true', help='Include inactive bots')
    report_parser.add_argument('--rpc', help='Override RPC URL for all bots')
    report_parser.add_argument('--sdai', help='Fallback sDAI token address if not present in config')
    report_parser.add_argument('--format', choices=['table', 'json'], default='table')
    report_parser.set_defaults(func=report_bots)

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
