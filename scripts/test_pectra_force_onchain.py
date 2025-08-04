#!/usr/bin/env python3
"""
Test Pectra minimal executor with forced on-chain execution.

This script sends real EIP-7702 transactions without simulation.
"""

import os
import sys
from decimal import Decimal
from web3 import Web3
from eth_account import Account

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.arbitrage_commands.buy_cond_eip7702_minimal import (
    build_buy_conditional_bundle_minimal,
    check_approvals
)
from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.bundle_helpers import calculate_bundle_gas_params

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

# Addresses
IMPLEMENTATION_ADDRESS = os.environ.get("FUTARCHY_BATCH_EXECUTOR_ADDRESS", "0x65eb5a03635c627a0f254707712812B234753F31")


def send_eip7702_bundle_onchain(simple_test=False):
    """Send EIP-7702 bundled transaction directly on-chain."""
    print("=== Sending EIP-7702 Bundle On-Chain ===\n")
    
    if simple_test:
        # Just do a simple approval call for testing
        print("Running simple test with just one approval call...")
        from src.helpers.bundle_helpers import encode_approval_call
        
        SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]
        FUTARCHY_ROUTER = os.environ["FUTARCHY_ROUTER_ADDRESS"]
        
        # Build single approval call
        approval_call = encode_approval_call(SDAI_TOKEN, FUTARCHY_ROUTER, 1000000)  # 0.000001 sDAI
        bundle_calls = [approval_call]
    else:
        # Check approvals
        approvals = check_approvals()
        print("Current approvals:")
        for key, status in approvals.items():
            print(f"  {key}: {'✅' if status else '❌'}")
        
        # Build bundle for small amount
        amount = Decimal("0.001")  # 0.001 sDAI
        print(f"\nBuilding bundle for {amount} sDAI...")
        
        # Build bundle without simulation results
        bundle_calls = build_buy_conditional_bundle_minimal(
            amount,
            simulation_results=None,
            skip_approvals=approvals
        )
    
    print(f"Bundle has {len(bundle_calls)} calls")
    
    # Build EIP-7702 transaction
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    
    # Add all calls to builder
    for call in bundle_calls:
        builder.add_call(call['target'], call['value'], call['data'])
    
    print("\nBuilding EIP-7702 transaction...")
    
    try:
        # Build transaction with gas params
        gas_params = calculate_bundle_gas_params(w3)
        gas_params['gas'] = 3000000  # Higher gas limit for complex bundle
        
        tx = builder.build_transaction(account, gas_params)
        
        print(f"Transaction type: {tx.get('type')}")
        print(f"To: {tx.get('to')}")
        print(f"Authorization list: {len(tx.get('authorizationList', []))} items")
        print(f"Gas: {tx.get('gas')}")
        print(f"Max fee per gas: {tx.get('maxFeePerGas')}")
        
        # Sign transaction
        print("\nSigning transaction...")
        signed_tx = account.sign_transaction(tx)
        
        # Send it!
        print("\n🚀 SENDING TRANSACTION ON-CHAIN...")
        if hasattr(signed_tx, 'rawTransaction'):
            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        elif hasattr(signed_tx, 'raw_transaction'):
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        else:
            tx_hash = w3.eth.send_raw_transaction(signed_tx)
        
        print(f"✅ Transaction sent: {tx_hash.hex()}")
        print(f"View on Gnosisscan: https://gnosisscan.io/tx/{tx_hash.hex()}")
        
        # Wait for receipt
        print("\nWaiting for confirmation...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt.status == 1:
            print(f"\n✅ TRANSACTION SUCCESSFUL!")
            print(f"Gas used: {receipt.gasUsed}")
            print(f"Block: {receipt.blockNumber}")
            print(f"Logs: {len(receipt.logs)} events")
        else:
            print(f"\n❌ TRANSACTION FAILED!")
            print(f"Status: {receipt.status}")
            
        return receipt
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Main entry point."""
    print("Pectra EIP-7702 Force On-Chain Test")
    print("=" * 50)
    print("⚠️  WARNING: This will send a real transaction!")
    print("=" * 50)
    
    print(f"\nAccount: {account.address}")
    print(f"Implementation: {IMPLEMENTATION_ADDRESS}")
    print(f"Chain ID: {w3.eth.chain_id}")
    print(f"Balance: {w3.from_wei(w3.eth.get_balance(account.address), 'ether')} xDAI\n")
    
    # Add simple test option
    import sys
    simple_test = "--simple" in sys.argv
    
    # Send transaction
    receipt = send_eip7702_bundle_onchain(simple_test=simple_test)
    
    if receipt:
        print("\n" + "=" * 50)
        print("Transaction completed!")
        print(f"Check: https://gnosisscan.io/tx/{receipt.transactionHash.hex()}")


if __name__ == "__main__":
    main()