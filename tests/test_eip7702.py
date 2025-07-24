"""
Test script for EIP-7702 implementation
======================================

This script tests the EIP-7702 transaction builder and verifies that
we can create properly formatted transactions.
"""

import os
import sys
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from eth_utils import to_hex
import json

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.helpers.eip7702_builder import EIP7702TransactionBuilder, create_test_transaction


def test_authorization_signing():
    """Test that we can sign EIP-7702 authorizations."""
    print("\n=== Testing Authorization Signing ===")
    
    # Create a test account
    private_key = "0x" + "1" * 64  # Test private key (DO NOT USE IN PRODUCTION)
    account = Account.from_key(private_key)
    print(f"Test account address: {account.address}")
    
    # Create authorization
    auth = {
        "chainId": 100,  # Gnosis Chain
        "address": "0x0000000000000000000000000000000000000001",
        "nonce": 0
    }
    
    try:
        signed_auth = account.sign_authorization(auth)
        print(f"✓ Successfully signed authorization")
        print(f"  Chain ID: {auth['chainId']}")
        print(f"  Implementation: {auth['address']}")
        print(f"  Nonce: {auth['nonce']}")
        print(f"  Signed auth type: {type(signed_auth)}")
        print(f"  Signed auth keys: {list(signed_auth.keys()) if hasattr(signed_auth, 'keys') else 'Not a dict'}")
        
        # Check signature fields based on the actual return type
        if hasattr(signed_auth, 'yParity'):
            print(f"  Has yParity: {hasattr(signed_auth, 'yParity')}")
            print(f"  Has r: {hasattr(signed_auth, 'r')}")
            print(f"  Has s: {hasattr(signed_auth, 's')}")
        elif isinstance(signed_auth, dict):
            print(f"  Signature fields present: {all(k in signed_auth for k in ['yParity', 'r', 's'])}")
        else:
            print(f"  Signed auth attributes: {[attr for attr in dir(signed_auth) if not attr.startswith('_')]}")
        
        return True
    except Exception as e:
        print(f"✗ Failed to sign authorization: {e}")
        return False


def test_transaction_builder():
    """Test the EIP-7702 transaction builder."""
    print("\n=== Testing Transaction Builder ===")
    
    # Setup - use a mock provider for chain_id
    from web3.providers import BaseProvider
    
    class MockProvider(BaseProvider):
        def make_request(self, method, params):
            if method == "eth_chainId":
                return {"jsonrpc": "2.0", "id": 1, "result": "0x64"}  # 100 in hex
            elif method == "eth_getTransactionCount":
                return {"jsonrpc": "2.0", "id": 1, "result": "0x0"}  # nonce 0
            elif method == "eth_gasPrice":
                return {"jsonrpc": "2.0", "id": 1, "result": "0x4a817c800"}  # 20 gwei
            elif method == "eth_getBlockByNumber":
                return {"jsonrpc": "2.0", "id": 1, "result": {"baseFeePerGas": "0x3b9aca00"}}  # 1 gwei
            raise NotImplementedError(f"Mock provider doesn't support {method}")
    
    w3 = Web3(MockProvider())
    implementation_address = "0x1234567890123456789012345678901234567890"
    private_key = "0x" + "1" * 64
    account = Account.from_key(private_key)
    
    # Create builder
    builder = EIP7702TransactionBuilder(w3, implementation_address)
    
    # Add some test calls
    print("Adding test calls...")
    
    # 1. Add approval
    builder.add_approval(
        token="0xaf204776c7245bF4147c2612BF6e5972Ee483701",  # sDAI on Gnosis
        spender="0x1111111111111111111111111111111111111111",
        amount=2**256 - 1
    )
    print("✓ Added approval call")
    
    # 2. Add split position
    builder.add_futarchy_split(
        router="0x2222222222222222222222222222222222222222",
        proposal="0x3333333333333333333333333333333333333333",
        collateral="0xaf204776c7245bF4147c2612BF6e5972Ee483701",
        amount=w3.to_wei(1, 'ether')
    )
    print("✓ Added split position call")
    
    # 3. Add Swapr swap
    import time
    builder.add_swapr_exact_in(
        router="0x4444444444444444444444444444444444444444",
        token_in="0x5555555555555555555555555555555555555555",
        token_out="0x6666666666666666666666666666666666666666",
        amount_in=w3.to_wei(1, 'ether'),
        amount_out_min=0,
        recipient=account.address,
        deadline=int(time.time()) + 600
    )
    print("✓ Added Swapr swap call")
    
    print(f"\nTotal calls added: {len(builder.calls)}")
    
    # Build batch call data
    try:
        call_data = builder.build_batch_call_data()
        print(f"✓ Built batch call data (length: {len(call_data)} bytes)")
        print(f"  Function selector: {to_hex(call_data[:4])}")
    except Exception as e:
        print(f"✗ Failed to build call data: {e}")
        return False
    
    # Build authorization
    try:
        signed_auth = builder.build_authorization(account, nonce=0)
        print(f"✓ Built and signed authorization")
    except Exception as e:
        print(f"✗ Failed to build authorization: {e}")
        return False
    
    # Build complete transaction
    try:
        
        tx = builder.build_transaction(account, gas_params={
            'gas': 1000000,
            'maxFeePerGas': w3.to_wei(20, 'gwei'),
            'maxPriorityFeePerGas': w3.to_wei(2, 'gwei')
        })
        
        print(f"✓ Built complete EIP-7702 transaction")
        print(f"  Type: {tx.get('type')}")
        print(f"  To: {tx.get('to')}")
        print(f"  Chain ID: {tx.get('chainId')}")
        print(f"  Authorization list length: {len(tx.get('authorizationList', []))}")
        print(f"  Data length: {len(tx.get('data', ''))} bytes")
        
        # Verify transaction structure
        assert tx['type'] == 4, "Transaction type should be 4"
        assert tx['to'] == account.address, "Transaction should be sent to self"
        assert len(tx['authorizationList']) == 1, "Should have one authorization"
        
        return True
        
    except Exception as e:
        print(f"✗ Failed to build transaction: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_simple_transaction():
    """Test creating a simple test transaction."""
    print("\n=== Testing Simple Transaction Creation ===")
    
    from web3.providers import BaseProvider
    
    class MockProvider(BaseProvider):
        def make_request(self, method, params):
            if method == "eth_chainId":
                return {"jsonrpc": "2.0", "id": 1, "result": "0x64"}  # 100 in hex
            elif method == "eth_getTransactionCount":
                return {"jsonrpc": "2.0", "id": 1, "result": "0x0"}  # nonce 0
            elif method == "eth_gasPrice":
                return {"jsonrpc": "2.0", "id": 1, "result": "0x4a817c800"}  # 20 gwei
            elif method == "eth_getBlockByNumber":
                return {"jsonrpc": "2.0", "id": 1, "result": {"baseFeePerGas": "0x3b9aca00"}}  # 1 gwei
            raise NotImplementedError(f"Mock provider doesn't support {method}")
    
    w3 = Web3(MockProvider())
    implementation_address = "0x1234567890123456789012345678901234567890"
    private_key = "0x" + "1" * 64
    account = Account.from_key(private_key)
    
    try:
        tx = create_test_transaction(w3, implementation_address, account)
        print(f"✓ Created test transaction")
        print(f"  Transaction type: {tx['type']}")
        print(f"  Has authorization: {'authorizationList' in tx}")
        return True
    except Exception as e:
        print(f"✗ Failed to create test transaction: {e}")
        return False


def test_call_encoding():
    """Test encoding of individual calls."""
    print("\n=== Testing Call Encoding ===")
    
    from eth_utils import keccak
    from eth_abi import encode
    
    # Test approve encoding
    function_selector = keccak(text="approve(address,uint256)")[:4]
    spender = "0x1111111111111111111111111111111111111111"
    amount = 2**256 - 1
    
    encoded_params = encode(['address', 'uint256'], [spender, amount])
    data = function_selector + encoded_params
    
    print(f"✓ Encoded approve call")
    print(f"  Function selector: {to_hex(function_selector)}")
    print(f"  Total data length: {len(data)} bytes")
    
    # Test splitPosition encoding
    function_selector = keccak(text="splitPosition(address,address,uint256)")[:4]
    proposal = "0x2222222222222222222222222222222222222222"
    collateral = "0x3333333333333333333333333333333333333333"
    amount = 1000000000000000000  # 1 ether in wei
    
    encoded_params = encode(['address', 'address', 'uint256'], [proposal, collateral, amount])
    data = function_selector + encoded_params
    
    print(f"✓ Encoded splitPosition call")
    print(f"  Function selector: {to_hex(function_selector)}")
    print(f"  Total data length: {len(data)} bytes")
    
    return True


def main():
    """Run all tests."""
    print("EIP-7702 Implementation Tests")
    print("=" * 50)
    
    tests = [
        ("Authorization Signing", test_authorization_signing),
        ("Call Encoding", test_call_encoding),
        ("Transaction Builder", test_transaction_builder),
        ("Simple Transaction", test_simple_transaction),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ Test '{test_name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("Test Summary:")
    print("=" * 50)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{test_name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    # Check eth-account version
    print("\n" + "=" * 50)
    print("Environment Info:")
    print("=" * 50)
    try:
        import eth_account
        print(f"eth-account version: {eth_account.__version__}")
        
        # Check if sign_authorization exists
        if hasattr(Account, 'sign_authorization'):
            print("✓ sign_authorization method available")
        else:
            print("✗ sign_authorization method NOT available")
            print("  This suggests eth-account version is too old")
            print("  Required: >= 0.11.0")
    except Exception as e:
        print(f"Error checking eth-account: {e}")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)