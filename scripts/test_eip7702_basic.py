#!/usr/bin/env python3
"""
Basic EIP-7702 test without execute10.

Tests if we can get any EIP-7702 transaction to work.
"""

import os
import sys
from web3 import Web3
from eth_account import Account

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

# Use PectraWrapper instead
PECTRA_WRAPPER = os.environ.get("PECTRA_WRAPPER_ADDRESS")


def test_basic_eip7702():
    """Test basic EIP-7702 with PectraWrapper."""
    print("=== Basic EIP-7702 Test ===\n")
    
    print(f"Account: {account.address}")
    print(f"Chain ID: {w3.eth.chain_id}")
    
    if not PECTRA_WRAPPER:
        print("\n❌ PECTRA_WRAPPER_ADDRESS not set in environment!")
        print("Please deploy PectraWrapper.sol and set the address.")
        return
    
    print(f"PectraWrapper: {PECTRA_WRAPPER}")
    
    # Check wrapper
    wrapper_code = w3.eth.get_code(PECTRA_WRAPPER)
    print(f"\nPectraWrapper contract:")
    print(f"  Size: {len(wrapper_code)} bytes")
    print(f"  Has code: {len(wrapper_code) > 0}")
    
    # Build simple transaction to call owner() function
    from eth_utils import keccak
    owner_selector = keccak(text="owner()")[:4]
    
    # Get nonce
    nonce = w3.eth.get_transaction_count(account.address)
    
    # Build authorization for PectraWrapper
    auth = {
        "chainId": w3.eth.chain_id,
        "address": PECTRA_WRAPPER,
        "nonce": nonce + 1
    }
    
    print(f"\nAuthorization:")
    print(f"  Implementation: {auth['address']}")
    print(f"  Nonce: {auth['nonce']}")
    
    try:
        # Sign authorization
        signed_auth = account.sign_authorization(auth)
        
        # Convert to dict
        auth_dict = {
            'chainId': signed_auth.chain_id,
            'address': signed_auth.address,
            'nonce': signed_auth.nonce,
            'yParity': signed_auth.y_parity,
            'r': signed_auth.r,
            's': signed_auth.s
        }
        
        # Build transaction to call owner()
        tx = {
            'type': 4,  # EIP-7702
            'chainId': w3.eth.chain_id,
            'nonce': nonce,
            'to': account.address,  # Call self
            'value': 0,
            'data': owner_selector,  # Just call owner()
            'authorizationList': [auth_dict],
            'gas': 200000,
            'maxFeePerGas': w3.eth.gas_price * 2,
            'maxPriorityFeePerGas': w3.to_wei(2, 'gwei')
        }
        
        print("\nTransaction:")
        print(f"  Calling: owner()")
        print(f"  Gas: {tx['gas']}")
        
        # Sign and send
        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        print(f"\n✅ Transaction sent: {tx_hash.hex()}")
        print(f"View: https://gnosisscan.io/tx/{tx_hash.hex()}")
        
        # Wait for receipt
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        
        if receipt.status == 1:
            print(f"\n✅ Success! Gas used: {receipt.gasUsed}")
            
            # Try to decode return value
            if receipt.logs:
                print(f"Logs: {len(receipt.logs)}")
        else:
            print(f"\n❌ Transaction failed!")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run the test."""
    print("Basic EIP-7702 Test")
    print("=" * 50)
    print("Testing if we can execute ANY EIP-7702 transaction.\n")
    
    test_basic_eip7702()


if __name__ == "__main__":
    main()