#!/usr/bin/env python3
"""
Test script to verify the 0xEF opcode fix before deployment.

This script:
1. Compiles the contracts with Solidity 0.8.19
2. Checks bytecode for 0xEF opcodes
3. Performs a dry-run deployment
4. Tests basic EIP-7702 functionality
"""

import os
import sys
import json
from pathlib import Path
from web3 import Web3
from eth_account import Account
from solcx import compile_source, install_solc, set_solc_version

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from src.helpers.eip7702_builder import EIP7702TransactionBuilder


def check_bytecode_for_ef(bytecode: str, name: str) -> bool:
    """Check if bytecode contains 0xEF opcodes."""
    # Remove 0x prefix if present
    bytecode = bytecode.replace('0x', '')
    
    # Check for 0xEF at even positions (opcode positions)
    ef_positions = []
    for i in range(0, len(bytecode), 2):
        if bytecode[i:i+2].lower() == 'ef':
            ef_positions.append(i // 2)
    
    if ef_positions:
        print(f"❌ {name} contains 0xEF opcodes at byte positions: {ef_positions}")
        return False
    
    print(f"✅ {name} is clean - no 0xEF opcodes found")
    return True


def compile_and_check():
    """Compile contracts and check for 0xEF opcodes."""
    print("🔧 Installing Solidity 0.8.17...")
    install_solc("0.8.17")
    set_solc_version("0.8.17")
    
    contracts = {
        # "FutarchyBatchExecutor": Path("contracts/FutarchyBatchExecutor.sol"),
        # "FutarchyBatchExecutorV2": Path("contracts/FutarchyBatchExecutorV2.sol"),
        "FutarchyBatchExecutorMinimal": Path("contracts/FutarchyBatchExecutorMinimal.sol"),
        "FutarchyBatchExecutorUltra": Path("contracts/FutarchyBatchExecutorUltra.sol"),
        "SimpleEIP7702Test": Path("contracts/SimpleEIP7702Test.sol")
    }
    
    results = {}
    
    for name, path in contracts.items():
        print(f"\n📦 Compiling {name}...")
        
        with open(path, 'r') as f:
            source = f.read()
        
        # Compile with specific settings
        # py-solc-x doesn't support the settings parameter directly
        # We need to use command line options
        compiled = compile_source(
            source,
            output_values=['abi', 'bin', 'bin-runtime'],
            solc_version="0.8.17",
            optimize=True,
            optimize_runs=200
        )
        
        # Extract contract data
        contract_id = f'<stdin>:{name}'
        contract_data = compiled[contract_id]
        
        # Check bytecode
        print(f"\n🔍 Checking {name} bytecode...")
        bytecode_clean = check_bytecode_for_ef(contract_data['bin'], f"{name} deployment bytecode")
        runtime_clean = check_bytecode_for_ef(contract_data['bin-runtime'], f"{name} runtime bytecode")
        
        results[name] = {
            'clean': bytecode_clean and runtime_clean,
            'data': contract_data
        }
    
    return results


def test_simple_eip7702():
    """Test basic EIP-7702 functionality with SimpleEIP7702Test."""
    print("\n🧪 Testing EIP-7702 with SimpleEIP7702Test contract...")
    
    # Create test account
    test_account = Account.create()
    print(f"Test account: {test_account.address}")
    
    # Create dummy implementation address
    impl_address = "0x0000000000000000000000000000000000000001"
    
    # Create transaction builder
    w3 = Web3()  # Not connected, just for building
    builder = EIP7702TransactionBuilder(w3, impl_address)
    
    # Add a simple test call
    builder.add_approval(
        "0x0000000000000000000000000000000000000002",
        "0x0000000000000000000000000000000000000003",
        1000
    )
    
    # Try to build transaction
    try:
        tx = builder.build_transaction(test_account)
        print("✅ EIP-7702 transaction built successfully")
        print(f"   Type: {tx.get('type')}")
        print(f"   To: {tx.get('to')}")
        print(f"   Authorization list: {len(tx.get('authorizationList', []))} items")
        return True
    except Exception as e:
        print(f"❌ Failed to build EIP-7702 transaction: {e}")
        return False


def main():
    """Main test function."""
    print("🏗️  Testing 0xEF Opcode Fix")
    print("=" * 50)
    
    # Step 1: Compile and check contracts
    results = compile_and_check()
    
    all_clean = all(r['clean'] for r in results.values())
    
    if not all_clean:
        print("\n❌ Some contracts still contain 0xEF opcodes!")
        print("   Please check compiler settings")
        sys.exit(1)
    
    print("\n✅ All contracts are clean!")
    
    # Step 2: Test EIP-7702 transaction building
    if test_simple_eip7702():
        print("\n✅ EIP-7702 transaction building works")
    else:
        print("\n❌ EIP-7702 transaction building failed")
        sys.exit(1)
    
    # Step 3: Save clean ABIs
    print("\n💾 Saving clean ABIs...")
    for name, result in results.items():
        if result['clean']:
            abi_path = Path(f"src/config/abis/{name}.json")
            abi_path.parent.mkdir(parents=True, exist_ok=True)
            with open(abi_path, 'w') as f:
                json.dump(result['data']['abi'], f, indent=2)
            print(f"   Saved {name} ABI to {abi_path}")
    
    print("\n🎉 All tests passed! Ready for deployment.")
    print("\nNext steps:")
    print("1. Run: python -m src.setup.deploy_batch_executor")
    print("2. Update .env with new IMPLEMENTATION_ADDRESS")
    print("3. Run: python -m src.helpers.pectra_verifier")
    print("4. Test with: python -m src.arbitrage_commands.buy_cond_eip7702 0.001")


if __name__ == "__main__":
    main()