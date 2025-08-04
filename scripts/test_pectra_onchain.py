#!/usr/bin/env python3
"""
Test Pectra minimal executor with on-chain transaction.

This script sends a real transaction to test the executor.
"""

import os
import sys
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from eth_utils import keccak
from eth_abi import encode

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.helpers.bundle_helpers import (
    encode_approval_call,
    get_token_balance,
    ZERO_ADDRESS
)

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

# Addresses
IMPLEMENTATION_ADDRESS = os.environ.get("FUTARCHY_BATCH_EXECUTOR_ADDRESS", "0x65eb5a03635c627a0f254707712812B234753F31")
SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]
FUTARCHY_ROUTER = os.environ["FUTARCHY_ROUTER_ADDRESS"]


def send_simple_bundle():
    """Send a simple bundle transaction on-chain."""
    print("=== Sending Simple Bundle On-Chain ===\n")
    
    # Check balance
    balance = get_token_balance(w3, SDAI_TOKEN, account.address)
    print(f"Current sDAI balance: {w3.from_wei(balance, 'ether')}")
    
    # Build a simple approval call (approve 0.001 sDAI)
    amount = w3.to_wei(0.001, 'ether')
    approval_call = encode_approval_call(SDAI_TOKEN, FUTARCHY_ROUTER, amount)
    
    # Build execute10 call with just one approval
    function_selector = keccak(text="execute10(address[10],bytes[10],uint256)")[:4]
    
    # Arrays with one call
    targets = [approval_call['target']] + [ZERO_ADDRESS] * 9
    calldatas = [approval_call['data']] + [b''] * 9
    count = 1
    
    encoded_params = encode(
        ['address[10]', 'bytes[10]', 'uint256'],
        [targets, calldatas, count]
    )
    tx_data = function_selector + encoded_params
    
    print(f"Contract: {IMPLEMENTATION_ADDRESS}")
    print(f"Approving {w3.from_wei(amount, 'ether')} sDAI to FutarchyRouter")
    
    # Build transaction (without EIP-7702, just delegate call)
    tx = {
        'from': account.address,
        'to': IMPLEMENTATION_ADDRESS,  # Direct call to implementation
        'data': tx_data,
        'gas': 300000,
        'gasPrice': w3.eth.gas_price,
        'nonce': w3.eth.get_transaction_count(account.address),
        'chainId': w3.eth.chain_id
    }
    
    print("\nTransaction details:")
    print(f"  From: {tx['from']}")
    print(f"  To: {tx['to']}")
    print(f"  Gas: {tx['gas']}")
    print(f"  Data length: {len(tx['data'])} bytes")
    
    # Sign and send
    try:
        signed_tx = account.sign_transaction(tx)
        
        print("\nSending transaction...")
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        print(f"Transaction sent: {tx_hash.hex()}")
        
        # Wait for receipt
        print("Waiting for confirmation...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt.status == 1:
            print(f"✅ Transaction successful!")
            print(f"   Gas used: {receipt.gasUsed}")
            print(f"   Block: {receipt.blockNumber}")
            
            # Check new allowance
            check_allowance()
        else:
            print(f"❌ Transaction failed!")
            print(f"   Receipt: {receipt}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


def check_allowance():
    """Check current allowance."""
    # allowance(address,address)
    selector = Web3.keccak(text="allowance(address,address)")[:4]
    data = selector + encode(['address', 'address'], [account.address, FUTARCHY_ROUTER])
    
    result = w3.eth.call({
        'to': SDAI_TOKEN,
        'data': data
    })
    
    allowance = int.from_bytes(result, 'big')
    print(f"\nCurrent sDAI allowance to FutarchyRouter: {w3.from_wei(allowance, 'ether')}")


def test_direct_execute():
    """Test executing directly without EIP-7702."""
    print("\n=== Testing Direct Execution ===\n")
    
    # First check if msg.sender == address(this) will pass
    print("Note: FutarchyBatchExecutorMinimal requires msg.sender == address(this)")
    print("This means it can only be called via EIP-7702 delegation, not directly.")
    print("The transaction above will likely fail with 'Only self' error.\n")
    
    print("For testing, you would need to:")
    print("1. Deploy a test version without the self-check")
    print("2. Or use a proper EIP-7702 implementation")
    print("3. Or create a wrapper contract that can call it")


def main():
    """Run on-chain test."""
    print("Pectra Minimal Executor On-Chain Test")
    print("=" * 50)
    
    print(f"Account: {account.address}")
    print(f"Implementation: {IMPLEMENTATION_ADDRESS}")
    print(f"Chain ID: {w3.eth.chain_id}\n")
    
    # Check initial allowance
    check_allowance()
    
    # Send transaction
    send_simple_bundle()
    
    # Additional info
    test_direct_execute()


if __name__ == "__main__":
    main()