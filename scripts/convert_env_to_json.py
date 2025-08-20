#!/usr/bin/env python3
"""
Convert .env.0x* files to JSON configuration format.

Usage:
    python scripts/convert_env_to_json.py
    python scripts/convert_env_to_json.py --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF
"""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
try:
    from dotenv import dotenv_values  # type: ignore
except Exception:
    # Fallback lightweight parser when python-dotenv is unavailable
    def dotenv_values(path):  # type: ignore
        values = {}
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.lower().startswith("export "):
                        line = line[7:].lstrip()
                    if "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    # Strip surrounding quotes
                    if (val.startswith("\"") and val.endswith("\"")) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    values[key] = val
        except FileNotFoundError:
            return {}
        return values


def find_env_files() -> List[Path]:
    """Find all .env.0x* files in the project root."""
    root = Path(".")
    pattern = r"\.env\.0x[a-fA-F0-9]+"
    env_files = []
    
    for file in root.glob(".env.0x*"):
        if re.match(r".*\.env\.0x[a-fA-F0-9]+$", str(file)):
            env_files.append(file)
    
    return sorted(env_files)


def load_env_file(env_path: Path) -> Dict[str, str]:
    """Load environment variables from file."""
    # Load base .env if exists
    base_env = Path(".env")
    env_vars = {}
    
    if base_env.exists():
        env_vars.update(dotenv_values(base_env))
    
    # Load specific env file
    env_vars.update(dotenv_values(env_path))
    
    return env_vars


def extract_proposal_address(env_path: Path) -> Optional[str]:
    """Extract proposal address from filename or env vars."""
    # Try to extract from filename
    filename = env_path.name
    match = re.search(r"0x[a-fA-F0-9]{40}", filename)
    if match:
        return match.group(0)
    
    # Fall back to env var
    env_vars = load_env_file(env_path)
    return env_vars.get("FUTARCHY_PROPOSAL_ADDRESS")


def env_to_json_config(env_vars: Dict[str, str], 
                       proposal_address: Optional[str] = None,
                       bot_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Convert environment variables to JSON configuration structure."""
    
    # Default bot parameters if not provided
    if bot_params is None:
        bot_params = {
            "amount": 0.01,
            "interval_seconds": 120,
            "tolerance": 0.04,
            "min_profit": 0.0
        }
    
    config = {
        "bot": {
            "type": env_vars.get("BOT_TYPE", "gnosis"),
            "run_options": bot_params
        },
        "network": {
            "rpc_url": env_vars.get("RPC_URL", ""),
            "chain_id": int(env_vars.get("CHAIN_ID", "100"))
        },
        # Intentionally exclude PRIVATE_KEY from migration for safety
        "wallet": {},
        "contracts": {
            "executor_v5": env_vars.get("FUTARCHY_ARB_EXECUTOR_V5") or 
                          env_vars.get("EXECUTOR_V5_ADDRESS") or 
                          env_vars.get("ARBITRAGE_EXECUTOR_V5_ADDRESS", ""),
            "routers": {
                "balancer": env_vars.get("BALANCER_ROUTER_ADDRESS", ""),
                "balancer_vault": env_vars.get("BALANCER_VAULT_ADDRESS") or 
                                 env_vars.get("BALANCER_VAULT_V3_ADDRESS", ""),
                "swapr": env_vars.get("SWAPR_ROUTER_ADDRESS", ""),
                "futarchy": env_vars.get("FUTARCHY_ROUTER_ADDRESS", "")
            }
        },
        "proposal": {
            "address": proposal_address or env_vars.get("FUTARCHY_PROPOSAL_ADDRESS", ""),
            "tokens": {
                "currency": {
                    "address": env_vars.get("SDAI_TOKEN_ADDRESS", ""),
                    "symbol": "sDAI"
                },
                "company": {
                    "address": env_vars.get("COMPANY_TOKEN_ADDRESS") or 
                              env_vars.get("GNO_TOKEN_ADDRESS", ""),
                    "symbol": env_vars.get("COMPANY_SYMBOL", "GNO")
                },
                "yes_currency": {
                    "address": env_vars.get("SWAPR_SDAI_YES_ADDRESS") or
                              env_vars.get("YES_SDAI_ADDRESS", ""),
                    "symbol": "YES-sDAI"
                },
                "no_currency": {
                    "address": env_vars.get("SWAPR_SDAI_NO_ADDRESS") or
                              env_vars.get("NO_SDAI_ADDRESS", ""),
                    "symbol": "NO-sDAI"
                },
                "yes_company": {
                    "address": env_vars.get("SWAPR_GNO_YES_ADDRESS") or
                              env_vars.get("YES_GNO_ADDRESS") or
                              env_vars.get("YES_COMP_ADDRESS", ""),
                    "symbol": "YES-GNO"
                },
                "no_company": {
                    "address": env_vars.get("SWAPR_GNO_NO_ADDRESS") or
                              env_vars.get("NO_GNO_ADDRESS") or
                              env_vars.get("NO_COMP_ADDRESS", ""),
                    "symbol": "NO-GNO"
                }
            },
            "pools": {
                "balancer_company_currency": {
                    "address": env_vars.get("BALANCER_POOL_ADDRESS", ""),
                    "description": "Balancer pool for company/currency pair"
                },
                "swapr_yes_company_yes_currency": {
                    "address": env_vars.get("SWAPR_POOL_YES_ADDRESS") or
                              env_vars.get("YES_POOL_ADDRESS") or
                              env_vars.get("SWAPR_GNO_YES_POOL", ""),
                    "description": "Swapr pool for YES conditional tokens"
                },
                "swapr_no_company_no_currency": {
                    "address": env_vars.get("SWAPR_POOL_NO_ADDRESS") or
                              env_vars.get("NO_POOL_ADDRESS") or
                              env_vars.get("SWAPR_GNO_NO_POOL", ""),
                    "description": "Swapr pool for NO conditional tokens"
                },
                "swapr_yes_currency_currency": {
                    "address": env_vars.get("SWAPR_POOL_PRED_YES_ADDRESS") or
                              env_vars.get("PRED_YES_POOL_ADDRESS") or
                              env_vars.get("SWAPR_SDAI_YES_POOL", ""),
                    "description": "Swapr prediction market pool for YES vs base currency"
                },
                "swapr_no_currency_currency": {
                    "address": env_vars.get("SWAPR_POOL_PRED_NO_ADDRESS") or
                              env_vars.get("PRED_NO_POOL_ADDRESS") or
                              env_vars.get("SWAPR_SDAI_NO_POOL", ""),
                    "description": "Swapr prediction market pool for NO vs base currency"
                }
            }
        }
    }
    
    # Clean up empty strings
    return clean_empty_values(config)


def clean_empty_values(d: Dict[str, Any]) -> Dict[str, Any]:
    """Remove empty strings from nested dictionary."""
    if not isinstance(d, dict):
        return d
    
    cleaned = {}
    for k, v in d.items():
        if isinstance(v, dict):
            nested = clean_empty_values(v)
            if nested:  # Only include if not empty
                cleaned[k] = nested
        elif v != "" and v is not None:  # Keep non-empty values
            cleaned[k] = v
    
    return cleaned


def save_json_config(config: Dict[str, Any], output_path: Path) -> None:
    """Save configuration to JSON file."""
    # Create config directory if it doesn't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"✅ Saved configuration to {output_path}")


def get_bot_params_from_user() -> Dict[str, Any]:
    """Interactively get bot parameters from user."""
    print("\nDefault bot parameters (press Enter to use defaults):")
    
    amount = input("  Amount [0.01]: ").strip()
    interval = input("  Interval (seconds) [120]: ").strip()
    tolerance = input("  Tolerance [0.04]: ").strip()
    min_profit = input("  Min profit [0.0]: ").strip()
    
    params = {
        "amount": float(amount) if amount else 0.01,
        "interval_seconds": int(interval) if interval else 120,
        "tolerance": float(tolerance) if tolerance else 0.04,
        "min_profit": float(min_profit) if min_profit else 0.0
    }
    
    return params


def validate_config(config: Dict[str, Any]) -> List[str]:
    """Validate configuration and return list of warnings."""
    warnings = []
    
    # Check critical fields
    if not config.get("network", {}).get("rpc_url"):
        warnings.append("⚠️  Missing RPC_URL")
    
    if not config.get("proposal", {}).get("address"):
        warnings.append("⚠️  Missing FUTARCHY_PROPOSAL_ADDRESS")
    
    # Check pools
    pools = config.get("proposal", {}).get("pools", {})
    if not pools.get("balancer_company_currency", {}).get("address"):
        warnings.append("⚠️  Missing BALANCER_POOL_ADDRESS")
    
    if not pools.get("swapr_yes_company_yes_currency", {}).get("address"):
        warnings.append("⚠️  Missing SWAPR_POOL_YES_ADDRESS")
    
    if not pools.get("swapr_no_company_no_currency", {}).get("address"):
        warnings.append("⚠️  Missing SWAPR_POOL_NO_ADDRESS")
    
    if not pools.get("swapr_yes_currency_currency", {}).get("address"):
        warnings.append("⚠️  Missing SWAPR_POOL_PRED_YES_ADDRESS")
    
    return warnings


def main():
    """Main conversion process."""
    parser = argparse.ArgumentParser(
        description="Convert .env files to JSON configuration format"
    )
    parser.add_argument(
        "--env",
        help="Specific .env file to convert"
    )
    parser.add_argument(
        "--output-dir",
        default="config",
        help="Output directory for JSON files (default: config)"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactively set bot parameters"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Convert all .env.0x* files found"
    )
    
    args = parser.parse_args()
    
    # Determine which files to convert
    if args.env:
        env_files = [Path(args.env)]
    elif args.all:
        env_files = find_env_files()
        if not env_files:
            print("No .env.0x* files found")
            return
    else:
        env_files = find_env_files()
        if not env_files:
            print("No .env.0x* files found")
            return
        
        print("Found the following .env files:")
        for i, f in enumerate(env_files, 1):
            print(f"  {i}. {f}")
        
        choice = input("\nEnter number to convert (or 'all' for all files): ").strip()
        
        if choice.lower() == 'all':
            pass  # Use all files
        else:
            try:
                idx = int(choice) - 1
                env_files = [env_files[idx]]
            except (ValueError, IndexError):
                print("Invalid choice")
                return
    
    # Get bot parameters
    if args.interactive:
        bot_params = get_bot_params_from_user()
    else:
        bot_params = None
    
    # Convert each file
    output_dir = Path(args.output_dir)
    
    for env_file in env_files:
        print(f"\n{'='*60}")
        print(f"Converting {env_file}")
        print('='*60)
        
        # Load environment variables
        env_vars = load_env_file(env_file)
        
        # Extract proposal address
        proposal_address = extract_proposal_address(env_file)
        
        # Convert to JSON
        config = env_to_json_config(env_vars, proposal_address, bot_params)
        
        # Validate
        warnings = validate_config(config)
        if warnings:
            print("\nValidation warnings:")
            for warning in warnings:
                print(f"  {warning}")
        
        # Determine output filename
        if proposal_address:
            output_name = f"proposal_{proposal_address}.json"
        else:
            # Use env filename as base
            base_name = env_file.stem.replace('.env.', '')
            output_name = f"proposal_{base_name}.json"
        
        output_path = output_dir / output_name
        
        # Save JSON
        save_json_config(config, output_path)
        
        # Show summary
        print(f"\nConfiguration summary:")
        print(f"  Network: {config.get('network', {}).get('chain_id', 'Unknown')}")
        print(f"  Proposal: {config.get('proposal', {}).get('address', 'Unknown')}")
        print(f"  Bot amount: {config.get('bot', {}).get('run_options', {}).get('amount', 'N/A')}")
        print(f"  Bot interval: {config.get('bot', {}).get('run_options', {}).get('interval_seconds', 'N/A')}s")
    
    print(f"\n✨ Conversion complete! JSON configs saved to {output_dir}/")
    print("\nTo use the new JSON configuration:")
    print(f"  python -m src.arbitrage_commands.arbitrage_bot_v2 --config {output_dir}/proposal_*.json")


if __name__ == "__main__":
    main()
