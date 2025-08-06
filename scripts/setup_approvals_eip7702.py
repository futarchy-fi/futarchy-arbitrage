#!/usr/bin/env python3
"""
Set up all necessary approvals using EIP-7702.
"""

import os
import sys
from web3 import Web3
from eth_account import Account

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.bundle_helpers import encode_approval_call, calculate_bundle_gas_params

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

IMPLEMENTATION_ADDRESS = os.environ.get("FUTARCHY_BATCH_EXECUTOR_ADDRESS", "0x65eb5a03635c627a0f254707712812B234753F31")

# Tokens and contracts
SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]
COMPANY_TOKEN = os.environ["COMPANY_TOKEN_ADDRESS"]
FUTARCHY_ROUTER = os.environ["FUTARCHY_ROUTER_ADDRESS"]
BALANCER_VAULT = os.environ["BALANCER_VAULT_ADDRESS"]

MAX_UINT256 = 2**256 - 1


def setup_approvals():
    """Set up all necessary approvals in a single EIP-7702 transaction."""
    print("=== Setting Up Approvals with EIP-7702 ===\n")
    
    print(f"Account: {account.address}")
    print(f"Implementation: {IMPLEMENTATION_ADDRESS}")
    
    # Build approval calls
    approval_calls = []
    
    # 1. sDAI to FutarchyRouter
    print("\n1. sDAI → FutarchyRouter")
    approval_calls.append(encode_approval_call(SDAI_TOKEN, FUTARCHY_ROUTER, MAX_UINT256))
    
    # 2. Company token to Balancer
    print("2. Company → Balancer Vault")
    approval_calls.append(encode_approval_call(COMPANY_TOKEN, BALANCER_VAULT, MAX_UINT256))
    
    print(f"\nTotal approval calls: {len(approval_calls)}")
    
    # Build EIP-7702 transaction
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    
    for call in approval_calls:
        builder.add_call(call['target'], call['value'], call['data'])
    
    # Build and sign transaction
    print("\nBuilding EIP-7702 transaction...")
    gas_params = calculate_bundle_gas_params(w3)
    gas_params['gas'] = 500000  # Reduced for approvals
    
    tx = builder.build_transaction(account, gas_params)
    signed_tx = account.sign_transaction(tx)
    
    # Send transaction
    print("Sending transaction...")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"✅ Transaction sent: {tx_hash.hex()}")
    print(f"View on Gnosisscan: https://gnosisscan.io/tx/{tx_hash.hex()}")
    
    # Wait for receipt
    print("\nWaiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"\n✅ APPROVALS SET SUCCESSFULLY!")
        print(f"Gas used: {receipt.gasUsed}")
        print(f"Logs: {len(receipt.logs)} events")
    else:
        print(f"\n❌ Transaction failed!")
        
    return receipt


def main():
    """Run the approval setup."""
    print("EIP-7702 Approval Setup")
    print("=" * 50)
    
    setup_approvals()


if __name__ == "__main__":
    main()