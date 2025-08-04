#!/usr/bin/env python3
"""
Debug EIP-7702 transaction sending.

This script traces the entire process of creating and sending an EIP-7702 transaction.
"""

import os
import sys
import json
from web3 import Web3
from eth_account import Account
from eth_utils import keccak, to_hex
from eth_abi import encode

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

IMPLEMENTATION_ADDRESS = os.environ.get("FUTARCHY_BATCH_EXECUTOR_ADDRESS", "0x65eb5a03635c627a0f254707712812B234753F31")


def debug_eip7702_transaction():
    """Debug the EIP-7702 transaction creation and sending process."""
    print("=== Debugging EIP-7702 Transaction ===\n")
    
    print(f"Account: {account.address}")
    print(f"Implementation: {IMPLEMENTATION_ADDRESS}")
    print(f"Chain ID: {w3.eth.chain_id}")
    
    # Get current nonce
    nonce = w3.eth.get_transaction_count(account.address)
    print(f"Current nonce: {nonce}")
    
    # Build authorization
    print("\n1. Building Authorization...")
    auth = {
        "chainId": w3.eth.chain_id,
        "address": IMPLEMENTATION_ADDRESS,
        "nonce": nonce + 1  # Important: nonce + 1 for self-authorization
    }
    print(f"Authorization object: {json.dumps(auth, indent=2)}")
    
    # Sign authorization
    print("\n2. Signing Authorization...")
    try:
        signed_auth = account.sign_authorization(auth)
        print(f"Signed authorization type: {type(signed_auth)}")
        print(f"Has required attributes: chain_id={hasattr(signed_auth, 'chain_id')}, "
              f"address={hasattr(signed_auth, 'address')}, nonce={hasattr(signed_auth, 'nonce')}, "
              f"y_parity={hasattr(signed_auth, 'y_parity')}, r={hasattr(signed_auth, 'r')}, s={hasattr(signed_auth, 's')}")
        
        # Convert to dict
        auth_dict = {
            'chainId': signed_auth.chain_id,
            'address': signed_auth.address,
            'nonce': signed_auth.nonce,
            'yParity': signed_auth.y_parity,
            'r': signed_auth.r,
            's': signed_auth.s
        }
        # Convert bytes to hex for display
        auth_dict_display = {}
        for k, v in auth_dict.items():
            if isinstance(v, bytes):
                auth_dict_display[k] = '0x' + v.hex()
            elif isinstance(v, int):
                auth_dict_display[k] = str(v)
            else:
                auth_dict_display[k] = str(v)
        print(f"\nAuthorization dict: {json.dumps(auth_dict_display, indent=2)}")
    except Exception as e:
        print(f"ERROR signing authorization: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Build simple call data (execute10 with empty arrays)
    print("\n3. Building Call Data...")
    function_selector = keccak(text="execute10(address[10],bytes[10],uint256)")[:4]
    zero_address = '0x0000000000000000000000000000000000000000'
    targets = [zero_address] * 10
    calldatas = [b''] * 10
    count = 0
    
    encoded_params = encode(
        ['address[10]', 'bytes[10]', 'uint256'],
        [targets, calldatas, count]
    )
    call_data = function_selector + encoded_params
    print(f"Call data length: {len(call_data)} bytes")
    print(f"Call data (first 20 bytes): {call_data[:20].hex()}")
    
    # Build transaction
    print("\n4. Building Transaction...")
    tx = {
        'type': 4,  # EIP-7702
        'chainId': w3.eth.chain_id,
        'nonce': nonce,
        'to': account.address,  # Call self
        'value': 0,
        'data': call_data,
        'authorizationList': [auth_dict],
        'gas': 500000,
        'maxFeePerGas': w3.eth.gas_price * 2,
        'maxPriorityFeePerGas': w3.to_wei(2, 'gwei')
    }
    
    print(f"Transaction object:")
    print(f"  type: {tx['type']} (should be 4 for EIP-7702)")
    print(f"  chainId: {tx['chainId']}")
    print(f"  nonce: {tx['nonce']}")
    print(f"  to: {tx['to']} (should be self)")
    print(f"  authorizationList: {len(tx['authorizationList'])} items")
    
    # Sign transaction
    print("\n5. Signing Transaction...")
    try:
        signed_tx = account.sign_transaction(tx)
        print(f"Signed transaction type: {type(signed_tx)}")
        
        # Check what attributes the signed transaction has
        if hasattr(signed_tx, '__dict__'):
            print(f"Signed tx attributes: {list(signed_tx.__dict__.keys())}")
        
        # Get raw transaction
        if hasattr(signed_tx, 'raw_transaction'):
            raw_tx = signed_tx.raw_transaction
        elif hasattr(signed_tx, 'rawTransaction'):
            raw_tx = signed_tx.rawTransaction
        else:
            raw_tx = signed_tx
            
        print(f"Raw transaction type: {type(raw_tx)}")
        print(f"Raw transaction length: {len(raw_tx)} bytes")
        
        # Try to decode the transaction type from raw bytes
        if isinstance(raw_tx, bytes) and len(raw_tx) > 0:
            first_byte = raw_tx[0]
            print(f"First byte of raw tx: 0x{first_byte:02x}")
            if first_byte >= 0x00 and first_byte <= 0x7f:
                print("  -> This indicates an EIP-2718 typed transaction")
                print(f"  -> Transaction type: {first_byte}")
                if first_byte == 4:
                    print("  -> ✅ This is an EIP-7702 transaction!")
                else:
                    print(f"  -> ❌ Expected type 4, got type {first_byte}")
            else:
                print("  -> This indicates a legacy transaction (type 0)")
                
    except Exception as e:
        print(f"ERROR signing transaction: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Send transaction
    print("\n6. Sending Transaction...")
    try:
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        print(f"✅ Transaction sent: {tx_hash.hex()}")
        print(f"View on Gnosisscan: https://gnosisscan.io/tx/{tx_hash.hex()}")
        
        # Wait for receipt
        print("\nWaiting for confirmation...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        
        print(f"\nTransaction receipt:")
        print(f"  Status: {'✅ Success' if receipt.status == 1 else '❌ Failed'}")
        print(f"  Gas used: {receipt.gasUsed}")
        print(f"  Block: {receipt.blockNumber}")
        
        # Get transaction details
        tx_details = w3.eth.get_transaction(tx_hash)
        print(f"\nTransaction details from chain:")
        print(f"  Type: {tx_details.get('type', 'Not specified')}")
        print(f"  To: {tx_details.get('to')}")
        if 'authorizationList' in tx_details:
            print(f"  Authorization list: {len(tx_details['authorizationList'])} items")
        else:
            print(f"  Authorization list: Not found in transaction")
            
    except Exception as e:
        print(f"ERROR sending transaction: {e}")
        import traceback
        traceback.print_exc()


def check_web3_version():
    """Check web3.py version and EIP-7702 support."""
    print("\n=== Checking Web3 Version ===")
    try:
        import web3
        print(f"web3.py version: {web3.__version__}")
        
        # Check if web3 knows about transaction type 4
        from web3._utils.transactions import TRANSACTION_TYPES
        if hasattr(web3._utils.transactions, 'TRANSACTION_TYPES'):
            print(f"Known transaction types: {TRANSACTION_TYPES}")
        else:
            print("Cannot find TRANSACTION_TYPES in web3")
            
    except Exception as e:
        print(f"Error checking web3 version: {e}")


def check_eth_account_version():
    """Check eth-account version and capabilities."""
    print("\n=== Checking eth-account Version ===")
    try:
        import eth_account
        print(f"eth-account version: {eth_account.__version__}")
        
        # Check if sign_authorization exists
        if hasattr(Account, 'sign_authorization'):
            print("✅ Account.sign_authorization method exists")
        else:
            print("❌ Account.sign_authorization method NOT found")
            
        # Check what transaction types eth-account supports
        from eth_account._utils.typed_transactions import TypedTransaction
        if hasattr(TypedTransaction, 'transaction_type'):
            print("TypedTransaction class found")
            
    except Exception as e:
        print(f"Error checking eth-account: {e}")


def main():
    """Run all debug checks."""
    print("EIP-7702 Transaction Debugging")
    print("=" * 50)
    
    check_web3_version()
    check_eth_account_version()
    
    print("\n" + "=" * 50)
    debug_eip7702_transaction()


if __name__ == "__main__":
    main()