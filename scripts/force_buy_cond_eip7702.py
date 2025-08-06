#!/usr/bin/env python3
"""
Force buy conditional tokens on-chain without simulation.
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
    check_approvals,
    IMPLEMENTATION_ADDRESS
)
from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.bundle_helpers import calculate_bundle_gas_params

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])


def force_buy_conditional(amount: Decimal):
    """Force buy conditional tokens without simulation."""
    print(f"=== Force Buy Conditional {amount} sDAI ===\n")
    
    print(f"Account: {account.address}")
    print(f"Implementation: {IMPLEMENTATION_ADDRESS}")
    
    # Check approvals
    approvals = check_approvals()
    print("\nApprovals:")
    for key, status in approvals.items():
        print(f"  {key}: {'✅' if status else '❌'}")
    
    # Build bundle with simple exact-in swaps (no simulation)
    print(f"\nBuilding bundle for {amount} sDAI...")
    bundle_calls = build_buy_conditional_bundle_minimal(
        amount,
        simulation_results=None,  # No simulation
        skip_approvals=approvals
    )
    
    print(f"Bundle has {len(bundle_calls)} calls:")
    for i, call in enumerate(bundle_calls):
        print(f"  {i}: {call['target'][:10]}... ({len(call['data'])} bytes)")
    
    # Build EIP-7702 transaction
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    
    for call in bundle_calls:
        builder.add_call(call['target'], call['value'], call['data'])
    
    # Build and sign
    print("\nBuilding EIP-7702 transaction...")
    gas_params = calculate_bundle_gas_params(w3)
    gas_params['gas'] = 2000000  # Conservative estimate
    
    tx = builder.build_transaction(account, gas_params)
    signed_tx = account.sign_transaction(tx)
    
    # Send
    print("\nSending transaction...")
    try:
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"✅ Transaction sent: {tx_hash.hex()}")
        print(f"View on Gnosisscan: https://gnosisscan.io/tx/{tx_hash.hex()}")
        
        # Wait for receipt
        print("\nWaiting for confirmation...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt.status == 1:
            print(f"\n✅ BUY CONDITIONAL SUCCESSFUL!")
            print(f"Gas used: {receipt.gasUsed}")
            print(f"Block: {receipt.blockNumber}")
            print(f"Logs: {len(receipt.logs)} events")
            
            # Parse events
            print("\nEvents:")
            for i, log in enumerate(receipt.logs):
                print(f"  Log {i}: {log.address[:10]}... topics={len(log.topics)}")
        else:
            print(f"\n❌ Transaction failed!")
            print(f"Status: {receipt.status}")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run the forced buy."""
    print("Force Buy Conditional EIP-7702")
    print("=" * 50)
    
    # Use small amount
    amount = Decimal("0.001")  # 0.001 sDAI
    
    force_buy_conditional(amount)


if __name__ == "__main__":
    main()