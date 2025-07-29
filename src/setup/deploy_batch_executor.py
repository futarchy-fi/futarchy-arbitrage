"""
Deploy FutarchyBatchExecutor Contract
====================================

This script deploys the FutarchyBatchExecutor implementation contract for EIP-7702
bundled transactions on Gnosis Chain.

Usage:
    python -m src.setup.deploy_batch_executor [--verify] [--dry-run]

Environment Variables Required:
    - RPC_URL: Gnosis Chain RPC endpoint
    - PRIVATE_KEY: Deployer private key
    - GNOSISSCAN_API_KEY: (Optional) For contract verification
"""

import os
import sys
import json
import argparse
from typing import Dict, Any, Optional
from pathlib import Path
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from solcx import compile_source, install_solc


# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

# Solidity version to avoid 0xEF opcodes
SOLIDITY_VERSION = "0.8.17"

# Contract source path
# Using Minimal version to avoid 0xEF opcodes
CONTRACT_PATH = Path("contracts/FutarchyBatchExecutorMinimal.sol")

# Deployment gas settings
DEPLOYMENT_GAS_LIMIT = 3_000_000
PRIORITY_FEE_GWEI = 2


# --------------------------------------------------------------------------- #
# Contract Compilation                                                        #
# --------------------------------------------------------------------------- #

def compile_contract() -> Dict[str, Any]:
    """Compile the FutarchyBatchExecutor contract."""
    print("📦 Compiling FutarchyBatchExecutor contract...")
    
    # Install Solidity compiler if needed
    try:
        install_solc(SOLIDITY_VERSION)
    except Exception as e:
        print(f"⚠️  Solidity {SOLIDITY_VERSION} already installed or error: {e}")
    
    # Read contract source
    if not CONTRACT_PATH.exists():
        print(f"❌ Contract file not found: {CONTRACT_PATH}")
        sys.exit(1)
    
    with open(CONTRACT_PATH, 'r') as f:
        contract_source = f.read()
    
    # Compile contract with optimizer settings to avoid 0xEF
    compiled = compile_source(
        contract_source,
        output_values=['abi', 'bin', 'bin-runtime'],
        solc_version=SOLIDITY_VERSION,
        optimize=True,
        optimize_runs=200
    )
    
    # Extract contract data
    contract_id = '<stdin>:FutarchyBatchExecutorMinimal'
    contract_data = compiled[contract_id]
    
    print("✅ Contract compiled successfully")
    return {
        'abi': contract_data['abi'],
        'bytecode': contract_data['bin'],
        'runtime_bytecode': contract_data['bin-runtime']
    }


# --------------------------------------------------------------------------- #
# Bytecode Verification                                                       #
# --------------------------------------------------------------------------- #

def verify_bytecode(bytecode: str) -> bool:
    """
    Check if bytecode contains 0xEF opcodes.
    
    Args:
        bytecode: Hex string of contract bytecode
    
    Returns:
        True if bytecode is clean, False if it contains 0xEF
    """
    # Remove 0x prefix if present
    bytecode = bytecode.replace('0x', '')
    
    # Check for 0xEF at even positions (opcode positions)
    ef_positions = []
    for i in range(0, len(bytecode), 2):
        if bytecode[i:i+2].lower() == 'ef':
            ef_positions.append(i // 2)
    
    if ef_positions:
        print(f"❌ Found 0xEF opcodes at byte positions: {ef_positions}")
        print(f"   Total: {len(ef_positions)} occurrences")
        return False
    
    print("✅ Bytecode verification passed - no 0xEF opcodes found")
    return True


# --------------------------------------------------------------------------- #
# Deployment Functions                                                        #
# --------------------------------------------------------------------------- #

def estimate_deployment_cost(w3: Web3, bytecode: str, account_address: str) -> Dict[str, Any]:
    """Estimate gas costs for deployment."""
    # Get current gas prices
    latest_block = w3.eth.get_block('latest')
    base_fee = latest_block.get('baseFeePerGas', w3.eth.gas_price)
    max_priority_fee = w3.to_wei(PRIORITY_FEE_GWEI, 'gwei')
    max_fee = base_fee + (max_priority_fee * 2)
    
    # Estimate gas - use a conservative estimate for deployment
    # Since we can't estimate without ABI, use a conservative value
    gas_estimate = 1_500_000  # Conservative estimate for contract deployment
    
    # Add 20% buffer
    gas_limit = int(gas_estimate * 1.2)
    
    # Calculate costs
    estimated_cost_wei = gas_limit * max_fee
    estimated_cost_eth = w3.from_wei(estimated_cost_wei, 'ether')
    
    return {
        'gas_estimate': gas_estimate,
        'gas_limit': gas_limit,
        'base_fee_gwei': w3.from_wei(base_fee, 'gwei'),
        'priority_fee_gwei': w3.from_wei(max_priority_fee, 'gwei'),
        'max_fee_gwei': w3.from_wei(max_fee, 'gwei'),
        'estimated_cost_wei': estimated_cost_wei,
        'estimated_cost_eth': estimated_cost_eth
    }


def deploy_contract(w3: Web3, account: Account, contract_data: Dict[str, Any], dry_run: bool = False) -> Optional[str]:
    """Deploy the FutarchyBatchExecutor contract."""
    print("\n🚀 Deploying FutarchyBatchExecutorMinimal...")
    
    # Verify bytecode before deployment
    print("\n🔍 Verifying bytecode...")
    if not verify_bytecode(contract_data['bytecode']):
        print("❌ Deployment aborted: bytecode contains 0xEF opcodes")
        print("   Please check compiler settings and rebuild")
        return None
    
    # Also verify runtime bytecode
    if not verify_bytecode(contract_data['runtime_bytecode']):
        print("❌ Deployment aborted: runtime bytecode contains 0xEF opcodes")
        return None
    
    # Ensure bytecode has 0x prefix
    bytecode = contract_data['bytecode']
    if not bytecode.startswith('0x'):
        bytecode = '0x' + bytecode
    
    # Create contract instance
    contract = w3.eth.contract(
        abi=contract_data['abi'],
        bytecode=bytecode
    )
    
    # Estimate deployment costs
    costs = estimate_deployment_cost(w3, bytecode, account.address)
    
    print(f"\n💰 Deployment Cost Estimates:")
    print(f"   Gas Estimate: {costs['gas_estimate']:,}")
    print(f"   Gas Limit: {costs['gas_limit']:,}")
    print(f"   Base Fee: {costs['base_fee_gwei']:.2f} gwei")
    print(f"   Priority Fee: {costs['priority_fee_gwei']:.2f} gwei")
    print(f"   Max Fee: {costs['max_fee_gwei']:.2f} gwei")
    print(f"   Estimated Cost: {costs['estimated_cost_eth']:.6f} ETH")
    
    # Check balance
    balance = w3.eth.get_balance(account.address)
    balance_eth = w3.from_wei(balance, 'ether')
    print(f"\n💵 Deployer Balance: {balance_eth:.6f} ETH")
    
    if balance < costs['estimated_cost_wei']:
        print("❌ Insufficient balance for deployment!")
        return None
    
    if dry_run:
        print("\n🏃 Dry run mode - skipping actual deployment")
        # Calculate deterministic address (simplified)
        print(f"📍 Contract will be deployed from: {account.address}")
        contract_address = "0x" + "0" * 40  # Placeholder for dry run
        return contract_address
    
    # Build transaction
    nonce = w3.eth.get_transaction_count(account.address)
    
    tx = contract.constructor().build_transaction({
        'from': account.address,
        'nonce': nonce,
        'gas': costs['gas_limit'],
        'maxFeePerGas': int(Decimal(str(costs['base_fee_gwei'])) * Decimal('1e9') + Decimal(str(costs['priority_fee_gwei'])) * Decimal('1e9') * 2),
        'maxPriorityFeePerGas': int(Decimal(str(costs['priority_fee_gwei'])) * Decimal('1e9')),
        'chainId': w3.eth.chain_id
    })
    
    # Sign and send transaction
    print("\n📝 Signing transaction...")
    signed_tx = account.sign_transaction(tx)
    
    print("📡 Broadcasting transaction...")
    # Handle both old and new eth-account versions
    if hasattr(signed_tx, 'rawTransaction'):
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    elif hasattr(signed_tx, 'raw_transaction'):
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    else:
        tx_hash = w3.eth.send_raw_transaction(signed_tx)
    print(f"📋 Transaction Hash: {tx_hash.hex()}")
    
    # Wait for confirmation
    print("⏳ Waiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    
    if receipt['status'] == 1:
        contract_address = receipt['contractAddress']
        print(f"✅ Contract deployed successfully!")
        print(f"📍 Contract Address: {contract_address}")
        print(f"⛽ Gas Used: {receipt['gasUsed']:,}")
        return contract_address
    else:
        print("❌ Deployment failed!")
        return None


# --------------------------------------------------------------------------- #
# Contract Verification                                                       #
# --------------------------------------------------------------------------- #

def verify_contract(contract_address: str, contract_data: Dict[str, Any]) -> bool:
    """Verify contract on Gnosisscan."""
    api_key = os.getenv("GNOSISSCAN_API_KEY")
    if not api_key:
        print("⚠️  GNOSISSCAN_API_KEY not set - skipping verification")
        return False
    
    print(f"\n🔍 Verifying contract on Gnosisscan...")
    # TODO: Implement Gnosisscan verification API call
    print("⚠️  Verification not implemented yet - please verify manually")
    print(f"   Visit: https://gnosisscan.io/address/{contract_address}#code")
    
    return True


# --------------------------------------------------------------------------- #
# Environment Update                                                          #
# --------------------------------------------------------------------------- #

def update_environment_file(contract_address: str) -> None:
    """Update .env.pectra file with the deployment address."""
    env_file = Path(".env.pectra")
    
    # Read existing content if file exists
    existing_content = ""
    if env_file.exists():
        with open(env_file, 'r') as f:
            existing_content = f.read()
    
    # Update or add IMPLEMENTATION_ADDRESS
    lines = existing_content.strip().split('\n') if existing_content else []
    updated = False
    
    for i, line in enumerate(lines):
        if line.startswith('IMPLEMENTATION_ADDRESS='):
            lines[i] = f'IMPLEMENTATION_ADDRESS={contract_address}'
            updated = True
            break
    
    if not updated:
        lines.append(f'IMPLEMENTATION_ADDRESS={contract_address}')
    
    # Add other Pectra-specific settings if not present
    pectra_settings = {
        'PECTRA_ENABLED': 'true',
        'EIP7702_GAS_BUFFER': '20000',
        'BUNDLE_SIMULATION_ENDPOINT': 'http://localhost:8545'  # Default to local fork
    }
    
    for key, value in pectra_settings.items():
        if not any(line.startswith(f'{key}=') for line in lines):
            lines.append(f'{key}={value}')
    
    # Write updated content
    with open(env_file, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    
    print(f"\n✅ Updated {env_file} with deployment address")


# --------------------------------------------------------------------------- #
# Main Deployment Flow                                                        #
# --------------------------------------------------------------------------- #

def main():
    """Main deployment function."""
    parser = argparse.ArgumentParser(description='Deploy FutarchyBatchExecutor contract')
    parser.add_argument('--verify', action='store_true', help='Verify contract on Gnosisscan')
    parser.add_argument('--dry-run', action='store_true', help='Perform dry run without actual deployment')
    args = parser.parse_args()
    
    print("🏗️  FutarchyBatchExecutor Deployment Script")
    print("=" * 50)
    
    # Check environment variables
    rpc_url = os.getenv("RPC_URL")
    private_key = os.getenv("PRIVATE_KEY")
    
    if not rpc_url:
        print("❌ RPC_URL environment variable not set")
        sys.exit(1)
    
    if not private_key and not args.dry_run:
        print("❌ PRIVATE_KEY environment variable not set")
        sys.exit(1)
    
    # Connect to network
    print(f"\n🌐 Connecting to RPC: {rpc_url}")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    
    if not w3.is_connected():
        print("❌ Failed to connect to network")
        sys.exit(1)
    
    chain_id = w3.eth.chain_id
    print(f"✅ Connected to chain ID: {chain_id}")
    
    if chain_id != 100:
        print("⚠️  Warning: Not on Gnosis Chain (expected chain ID: 100)")
    
    # Setup account
    account = None
    if private_key:
        account = Account.from_key(private_key)
        print(f"👤 Deployer Address: {account.address}")
    elif args.dry_run:
        # Use dummy account for dry run
        account = Account.create()
        print(f"👤 Dry Run Address: {account.address}")
    
    # Compile contract
    contract_data = compile_contract()
    
    # Save ABI for reference
    abi_path = Path("src/config/abis/FutarchyBatchExecutorMinimal.json")
    abi_path.parent.mkdir(parents=True, exist_ok=True)
    with open(abi_path, 'w') as f:
        json.dump(contract_data['abi'], f, indent=2)
    print(f"💾 Saved ABI to {abi_path}")
    
    # Also save as the main executor ABI for compatibility
    compat_path = Path("src/config/abis/FutarchyBatchExecutor.json")
    with open(compat_path, 'w') as f:
        json.dump(contract_data['abi'], f, indent=2)
    print(f"💾 Saved compatibility ABI to {compat_path}")
    
    # Deploy contract
    contract_address = deploy_contract(w3, account, contract_data, args.dry_run)
    
    if contract_address and not args.dry_run:
        # Update environment file
        update_environment_file(contract_address)
        
        # Verify if requested
        if args.verify:
            verify_contract(contract_address, contract_data)
        
        # Print summary
        print("\n" + "=" * 50)
        print("🎉 Deployment Summary")
        print(f"   Contract: FutarchyBatchExecutorMinimal")
        print(f"   Address: {contract_address}")
        print(f"   Network: Chain ID {chain_id}")
        print("\n📝 Next Steps:")
        print("   1. Fund the implementation contract if needed")
        print("   2. Test basic functionality with test transactions")
        print("   3. Update pectra_bot.py to use EIP-7702 transactions")
        print("   4. Run infrastructure verification script")


if __name__ == "__main__":
    main()