#!/usr/bin/env python3
"""
setup_bot.py
============
Generate a .env file for a new bot configuration from a JSON proposal file.

Usage:
    python -m src.setup.setup_bot <json_file_path> [--template <template_env_file>]
    
Example:
    python -m src.setup.setup_bot src/config/proposals/0xec50a351C0A4A122DC614058C0481Bb9487Abdaa.json
    python -m src.setup.setup_bot proposal.json --template .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF
"""

import json
import os
import sys
import argparse
from pathlib import Path
from typing import Dict, Any


def load_json_config(json_path: str) -> Dict[str, Any]:
    """Load and parse the JSON configuration file."""
    with open(json_path, 'r') as f:
        return json.load(f)


def load_template_env(template_path: str) -> Dict[str, str]:
    """Load a template .env file and parse it into a dictionary."""
    env_vars = {}
    
    with open(template_path, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            # Parse export statements
            if line.startswith('export '):
                line = line[7:]  # Remove 'export '
            # Split on first = only
            if '=' in line:
                key, value = line.split('=', 1)
                env_vars[key] = value
    
    return env_vars


def extract_values_from_json(config: Dict[str, Any]) -> Dict[str, str]:
    """Extract the required environment variable values from JSON config."""
    values = {}
    
    # Extract pool addresses
    values['SWAPR_POOL_YES_ADDRESS'] = config['pools']['yesPool']['address']
    values['SWAPR_POOL_NO_ADDRESS'] = config['pools']['noPool']['address']
    values['SWAPR_POOL_PRED_YES_ADDRESS'] = config['pools']['predictionPools']['yes']
    values['SWAPR_POOL_PRED_NO_ADDRESS'] = config['pools']['predictionPools']['no']
    
    # Extract token addresses
    values['SWAPR_SDAI_YES_ADDRESS'] = config['tokens']['conditionalTokens']['YES_sDAI']
    values['SWAPR_SDAI_NO_ADDRESS'] = config['tokens']['conditionalTokens']['NO_sDAI']
    values['SWAPR_GNO_YES_ADDRESS'] = config['tokens']['conditionalTokens']['YES_GNO']
    values['SWAPR_GNO_NO_ADDRESS'] = config['tokens']['conditionalTokens']['NO_GNO']
    
    # Extract proposal address
    values['FUTARCHY_PROPOSAL_ADDRESS'] = config['proposalId']
    
    # Extract company token address (PNK in this case)
    values['COMPANY_TOKEN_ADDRESS'] = config['tokens']['baseTokens']['company']['address']
    
    # Extract sDAI token address
    values['SDAI_TOKEN_ADDRESS'] = config['tokens']['baseTokens']['currency']['address']
    
    # Extract router address
    values['FUTARCHY_ROUTER_ADDRESS'] = config['contracts']['futarchyRouter']
    
    return values


def generate_env_file(template_vars: Dict[str, str], json_values: Dict[str, str], output_path: str):
    """Generate a new .env file by updating template with JSON values."""
    # Update template with new values
    updated_vars = template_vars.copy()
    updated_vars.update(json_values)
    
    # Write to output file
    with open(output_path, 'w') as f:
        # Group related variables
        f.write("# Bot-specific configuration\n")
        f.write("## Wallet\n")
        for key in ['PRIVATE_KEY', 'BOT_ADDRESS', 'USER_ADDRESS']:
            if key in updated_vars:
                f.write(f"export {key}={updated_vars[key]}\n")
        
        f.write("\n## Proposal-specific\n")
        pool_keys = [
            'SWAPR_POOL_YES_ADDRESS',
            'SWAPR_POOL_NO_ADDRESS', 
            'SWAPR_POOL_PRED_YES_ADDRESS',
            'SWAPR_POOL_PRED_NO_ADDRESS'
        ]
        for key in pool_keys:
            if key in updated_vars:
                f.write(f"export {key}={updated_vars[key]}\n")
        
        f.write("\n")
        token_keys = [
            'SWAPR_SDAI_YES_ADDRESS',
            'SWAPR_SDAI_NO_ADDRESS',
            'SWAPR_GNO_YES_ADDRESS',
            'SWAPR_GNO_NO_ADDRESS'
        ]
        for key in token_keys:
            if key in updated_vars:
                f.write(f"export {key}={updated_vars[key]}\n")
        
        f.write("\n")
        f.write(f"export FUTARCHY_PROPOSAL_ADDRESS={updated_vars['FUTARCHY_PROPOSAL_ADDRESS']}\n")
        
        f.write("\n# Base Configuration\n")
        base_keys = [
            'SWAPR_ROUTER_ADDRESS',
            'BALANCER_ROUTER_ADDRESS',
            'BALANCER_PERMIT_2_ADDRESS',
            'COMPANY_TOKEN_ADDRESS',
            'SDAI_TOKEN_ADDRESS',
            'BALANCER_POOL_ADDRESS'
        ]
        for key in base_keys:
            if key in updated_vars:
                f.write(f"export {key}={updated_vars[key]}\n")
        
        # Add remaining configuration
        f.write("\n\n")
        remaining_keys = [
            'TENDERLY_ACCESS_KEY',
            'TENDERLY_ACCOUNT_SLUG', 
            'TENDERLY_PROJECT_SLUG',
            'FUTARCHY_ROUTER_ADDRESS',
            'WALLET_ADDRESS',
            'RPC_URL',
            'CHAIN_ID',
            'AMOUNT',
            'EXPIRATION',
            'SIG_DEADLINE',
            'BALANCER_VAULT_ADDRESS',
            'BALANCER_VAULT_V3_ADDRESS',
            'NONCE',
            'PROJECT_ID',
            'SUPABASE_EDGE_TOKEN',
            'PYTHONPATH'
        ]
        
        # Add Tenderly config with comments
        tenderly_commented = [
            ('TENDERLY_ACCESS_KEY', 'bIP3wG67wXNFfxCWyzVYXkNUFakYYYvs'),
            ('TENDERLY_ACCOUNT_SLUG', 'nicscl2'),
            ('TENDERLY_PROJECT_SLUG', 'project'),
            ('TENDERLY_ACCESS_KEY', 'HORgT3-2V3iP238-jNNMr8OafNWzXwoi'),
            ('TENDERLY_ACCOUNT_SLUG', 'NicholasSCL'),
            ('TENDERLY_PROJECT_SLUG', 'project')
        ]
        
        for key, value in tenderly_commented:
            f.write(f"# export {key}={value}\n")
        
        # Active Tenderly config
        for key in ['TENDERLY_ACCESS_KEY', 'TENDERLY_ACCOUNT_SLUG', 'TENDERLY_PROJECT_SLUG']:
            if key in updated_vars:
                f.write(f"export {key}={updated_vars[key]}\n")
        
        f.write("\n")
        
        # Router addresses with comment
        f.write("# export FUTARCHY_ROUTER_ADDRESS=0xe2996f6bc88ba0f2ad3a6e2a71ac55884ec9f74e\n")
        if 'FUTARCHY_ROUTER_ADDRESS' in updated_vars:
            f.write(f"export FUTARCHY_ROUTER_ADDRESS={updated_vars['FUTARCHY_ROUTER_ADDRESS']}\n")
        
        f.write("\n\n")
        
        # Remaining vars
        for key in ['WALLET_ADDRESS', 'RPC_URL', 'CHAIN_ID', 'AMOUNT', 'EXPIRATION', 'SIG_DEADLINE']:
            if key in updated_vars:
                f.write(f"export {key}={updated_vars[key]}\n")
        
        # Balancer configuration section
        f.write("\n## Balancer Configuration\n")
        balancer_inline_keys = [
            ('TOKEN_IN_ADDRESS', '0xaf204776c7245bF4147c2612BF6e5972Ee483701', 'sDAI (BASE_CURRENCY_ADDRESS)'),
            ('TOKEN_IN_NAME', 'sDAI', None),
            ('TOKEN_OUT_ADDRESS', '0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644', 'waGNO (Default from example)'),
            ('TOKEN_OUT_NAME', 'waGNO', None),
            ('POOL_ADDRESS', '0xd1d7fa8871d84d0e77020fc28b7cd5718c446522', 'Balancer sDAI/waGNO Pool (Default from example)')
        ]
        
        for key, default_val, comment in balancer_inline_keys:
            value = updated_vars.get(key, default_val)
            if comment:
                f.write(f"{key}={value} # {comment}\n")
            else:
                f.write(f"{key}={value}\n")
        
        for key in ['BALANCER_VAULT_ADDRESS', 'BALANCER_VAULT_V3_ADDRESS', 'NONCE']:
            if key in updated_vars:
                f.write(f"export {key}={updated_vars[key]}\n")
        
        spender_inline_keys = [
            ('SPENDER_ADDRESS', '0xe2fa4e1d17725e72dcdAfe943Ecf45dF4B9E285b', 'BatchRouter (Default from example)'),
            ('SPENDER_NAME', 'BatchRouter', None),
            ('PERMIT_AMOUNT', '1000000000000000000', '1 token with 18 decimals (Example default uses 0.001)')
        ]
        
        for key, default_val, comment in spender_inline_keys:
            value = updated_vars.get(key, default_val)
            if comment:
                f.write(f"{key}={value} # {comment}\n")
            else:
                f.write(f"{key}={value}\n")
        
        f.write("\n")
        
        # Final vars
        for key in ['PROJECT_ID', 'SUPABASE_EDGE_TOKEN', 'PYTHONPATH']:
            if key in updated_vars:
                f.write(f"{key}={updated_vars[key]}\n")
                if key != 'PYTHONPATH':
                    f.write("\n")
                    
        # Ensure PYTHONPATH is exported
        f.write("export PYTHONPATH=src\n")


def main():
    parser = argparse.ArgumentParser(description="Generate a .env file for a bot from JSON configuration")
    parser.add_argument("json_file", help="Path to the JSON configuration file")
    parser.add_argument("--template", default=".env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF",
                        help="Template .env file to use as base (default: .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF)")
    parser.add_argument("--force", "-f", action="store_true", 
                        help="Force overwrite existing .env file without prompting")
    
    args = parser.parse_args()
    
    # Load JSON config
    try:
        config = load_json_config(args.json_file)
        proposal_id = config['proposalId']
    except Exception as e:
        print(f"Error loading JSON file: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Load template env
    try:
        template_vars = load_template_env(args.template)
    except Exception as e:
        print(f"Error loading template file: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Extract values from JSON
    try:
        json_values = extract_values_from_json(config)
    except KeyError as e:
        print(f"Error: Missing required field in JSON: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Generate output filename
    output_path = f".env.{proposal_id}"
    
    # Check if file already exists
    if os.path.exists(output_path) and not args.force:
        response = input(f"File {output_path} already exists. Overwrite? (y/N): ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)
    
    # Generate the env file
    try:
        generate_env_file(template_vars, json_values, output_path)
        print(f"Successfully created {output_path}")
        print(f"\nTo use this configuration:")
        print(f"  source {output_path}")
        print(f"  python -m src.arbitrage_commands.simple_bot --amount 0.01 --interval 120 --tolerance 0.2")
    except Exception as e:
        print(f"Error generating env file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()