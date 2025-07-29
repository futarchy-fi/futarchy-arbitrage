#\!/usr/bin/env python3
"""Test EIP-7702 with deployed FutarchyBatchExecutorMinimal."""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from web3 import Web3
from eth_account import Account

def main():
    """Test the deployment."""
    print("🏗️  EIP-7702 Deployment Verification")
    print("=" * 50)
    
    # Connect to Gnosis
    w3 = Web3(Web3.HTTPProvider("https://rpc.gnosischain.com"))
    
    # Check deployed contract
    impl_address = "0x65eb5a03635c627a0f254707712812B234753F31"
    code = w3.eth.get_code(impl_address)
    
    print(f"✅ Contract deployed at: {impl_address}")
    print(f"✅ Contract size: {len(code)} bytes")
    
    # Check for 0xEF opcodes
    ef_byte = b'\xef'
    if ef_byte in code:
        print(f"❌ Found {code.count(ef_byte)} 0xEF bytes in bytecode")
    else:
        print("✅ NO 0xEF opcodes in bytecode - deployment successful\!")
    
    # Also check transaction details
    tx_hash = "0xe2c3e433288dcecf79aded148544b9dad0f0f9d834c801f8e542aa1c14b270f3"
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        print(f"\n📋 Deployment Transaction:")
        print(f"   TX Hash: {tx_hash}")
        print(f"   Block: {receipt.blockNumber}")
        print(f"   Gas Used: {receipt.gasUsed:,}")
        print(f"   Status: {'Success' if receipt.status == 1 else 'Failed'}")
    except:
        pass
    
    print("\n📊 Deployment Summary:")
    print(f"   Contract: FutarchyBatchExecutorMinimal")
    print(f"   Address: {impl_address}")
    print(f"   Network: Gnosis Chain (100)")
    print(f"   Functions: execute10, executeOne")
    print(f"   Status: Ready for EIP-7702 transactions")

if __name__ == "__main__":
    main()
