#!/usr/bin/env python3
"""
Test just the split position call with EIP-7702.
"""

import os
import sys
from web3 import Web3
from eth_account import Account

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.bundle_helpers import encode_split_position_call, calculate_bundle_gas_params, get_token_balance

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

IMPLEMENTATION_ADDRESS = os.environ.get("FUTARCHY_BATCH_EXECUTOR_ADDRESS", "0x65eb5a03635c627a0f254707712812B234753F31")

# Contracts
FUTARCHY_ROUTER = os.environ["FUTARCHY_ROUTER_ADDRESS"]
PROPOSAL_ADDRESS = os.environ["FUTARCHY_PROPOSAL_ADDRESS"]
SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]


def test_split_position():
    """Test splitting sDAI into conditional tokens."""
    print("=== Testing Split Position with EIP-7702 ===\n")
    
    print(f"Account: {account.address}")
    print(f"Implementation: {IMPLEMENTATION_ADDRESS}")
    
    # Check sDAI balance
    sdai_balance = get_token_balance(w3, SDAI_TOKEN, account.address)
    print(f"sDAI balance: {w3.from_wei(sdai_balance, 'ether')}")
    
    # Amount to split (0.001 sDAI)
    amount = w3.to_wei(0.001, 'ether')
    print(f"\nSplitting {w3.from_wei(amount, 'ether')} sDAI")
    
    # Build split call
    split_call = encode_split_position_call(
        FUTARCHY_ROUTER,
        PROPOSAL_ADDRESS,
        SDAI_TOKEN,
        amount
    )
    
    print(f"Split call:")
    print(f"  Target: {split_call['target']}")
    print(f"  Data length: {len(split_call['data'])} bytes")
    
    # Build EIP-7702 transaction
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    builder.add_call(split_call['target'], split_call['value'], split_call['data'])
    
    # Build and sign
    print("\nBuilding EIP-7702 transaction...")
    gas_params = calculate_bundle_gas_params(w3)
    gas_params['gas'] = 1000000  # Reduced for single call
    
    tx = builder.build_transaction(account, gas_params)
    print(f"Transaction type: {tx['type']}")
    print(f"To: {tx['to']}")
    
    signed_tx = account.sign_transaction(tx)
    
    # Send
    print("\nSending transaction...")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"✅ Transaction sent: {tx_hash.hex()}")
    print(f"View on Gnosisscan: https://gnosisscan.io/tx/{tx_hash.hex()}")
    
    # Wait for receipt
    print("\nWaiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"\n✅ SPLIT SUCCESSFUL!")
        print(f"Gas used: {receipt.gasUsed}")
        print(f"Logs: {len(receipt.logs)} events")
    else:
        print(f"\n❌ Transaction failed!")
        
    return receipt


def main():
    """Run the test."""
    print("EIP-7702 Split Position Test")
    print("=" * 50)
    
    test_split_position()


if __name__ == "__main__":
    main()