#!/usr/bin/env python3
"""
Debug script for Pectra minimal executor.

This script helps diagnose issues with the bundled transaction execution.
"""

import os
import sys
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from eth_utils import keccak

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.helpers.bundle_helpers import (
    encode_approval_call,
    encode_split_position_call,
    get_token_balance,
    ZERO_ADDRESS
)
from src.helpers.eip7702_builder import EIP7702TransactionBuilder

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])

# Addresses
IMPLEMENTATION_ADDRESS = os.environ.get("FUTARCHY_BATCH_EXECUTOR_ADDRESS", "0x65eb5a03635c627a0f254707712812B234753F31")
SDAI_TOKEN = os.environ["SDAI_TOKEN_ADDRESS"]
FUTARCHY_ROUTER = os.environ["FUTARCHY_ROUTER_ADDRESS"]


def test_simple_call():
    """Test a simple single call using executeOne."""
    print("=== Testing Simple Call with executeOne ===\n")
    
    # Check current sDAI balance
    balance = get_token_balance(w3, SDAI_TOKEN, account.address)
    print(f"Current sDAI balance: {w3.from_wei(balance, 'ether')}")
    
    # Build a simple approval call
    approval_call = encode_approval_call(SDAI_TOKEN, FUTARCHY_ROUTER, 1000000)  # 0.000001 sDAI
    
    # Encode executeOne call
    function_selector = keccak(text="executeOne(address,bytes)")[:4]
    from eth_abi import encode
    encoded_params = encode(
        ['address', 'bytes'],
        [approval_call['target'], approval_call['data']]
    )
    tx_data = function_selector + encoded_params
    
    # State overrides to simulate EIP-7702
    state_overrides = {
        account.address: {
            'code': w3.eth.get_code(IMPLEMENTATION_ADDRESS)
        }
    }
    
    # Try eth_call
    print("Attempting eth_call with executeOne...")
    try:
        result = w3.eth.call({
            'from': account.address,
            'to': account.address,  # Self-call
            'data': tx_data,
            'gas': 1000000
        }, 'latest', state_overrides)
        
        print(f"✅ Call succeeded! Result: {result.hex()}")
        
    except Exception as e:
        print(f"❌ Call failed: {e}")
        if hasattr(e, 'data'):
            print(f"   Error data: {e.data}")


def test_execute10_empty():
    """Test execute10 with no actual calls."""
    print("\n=== Testing execute10 with Empty Arrays ===\n")
    
    # Build empty execute10 call
    function_selector = keccak(text="execute10(address[10],bytes[10],uint256)")[:4]
    from eth_abi import encode
    
    # Empty arrays
    targets = [ZERO_ADDRESS] * 10
    calldatas = [b''] * 10
    count = 0
    
    encoded_params = encode(
        ['address[10]', 'bytes[10]', 'uint256'],
        [targets, calldatas, count]
    )
    tx_data = function_selector + encoded_params
    
    # State overrides
    state_overrides = {
        account.address: {
            'code': w3.eth.get_code(IMPLEMENTATION_ADDRESS)
        }
    }
    
    print("Attempting eth_call with execute10 (0 calls)...")
    try:
        result = w3.eth.call({
            'from': account.address,
            'to': account.address,
            'data': tx_data,
            'gas': 1000000
        }, 'latest', state_overrides)
        
        print(f"✅ Call succeeded! Result: {result.hex()}")
        
    except Exception as e:
        print(f"❌ Call failed: {e}")


def test_execute10_single():
    """Test execute10 with a single call."""
    print("\n=== Testing execute10 with Single Call ===\n")
    
    # Build approval call
    approval_call = encode_approval_call(SDAI_TOKEN, FUTARCHY_ROUTER, 1000000)
    
    # Build execute10 call
    function_selector = keccak(text="execute10(address[10],bytes[10],uint256)")[:4]
    from eth_abi import encode
    
    # Arrays with one call
    targets = [approval_call['target']] + [ZERO_ADDRESS] * 9
    calldatas = [approval_call['data']] + [b''] * 9
    count = 1
    
    encoded_params = encode(
        ['address[10]', 'bytes[10]', 'uint256'],
        [targets, calldatas, count]
    )
    tx_data = function_selector + encoded_params
    
    # State overrides
    state_overrides = {
        account.address: {
            'code': w3.eth.get_code(IMPLEMENTATION_ADDRESS)
        }
    }
    
    print("Attempting eth_call with execute10 (1 call)...")
    try:
        result = w3.eth.call({
            'from': account.address,
            'to': account.address,
            'data': tx_data,
            'gas': 1000000
        }, 'latest', state_overrides)
        
        print(f"✅ Call succeeded! Result: {result.hex()}")
        
    except Exception as e:
        print(f"❌ Call failed: {e}")
        if hasattr(e, 'data'):
            print(f"   Error data: {e.data}")


def test_eip7702_transaction():
    """Test building a full EIP-7702 transaction."""
    print("\n=== Testing EIP-7702 Transaction Building ===\n")
    
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    
    # Add a simple approval
    builder.add_approval(SDAI_TOKEN, FUTARCHY_ROUTER, 1000000)
    
    try:
        # Build transaction
        tx = builder.build_transaction(account)
        
        print("Transaction built successfully:")
        print(f"  Type: {tx.get('type')}")
        print(f"  To: {tx.get('to')}")
        print(f"  Authorization list: {len(tx.get('authorizationList', []))} items")
        print(f"  Data length: {len(tx.get('data', ''))} bytes")
        
        # Try to estimate gas
        print("\nEstimating gas...")
        gas = builder.estimate_gas(account)
        print(f"  Estimated gas: {gas}")
        
    except Exception as e:
        print(f"❌ Failed to build transaction: {e}")
        import traceback
        traceback.print_exc()


def check_contract_methods():
    """Check what methods the contract actually has."""
    print("\n=== Checking Contract Methods ===\n")
    
    # Known function selectors
    selectors = {
        'execute10(address[10],bytes[10],uint256)': keccak(text='execute10(address[10],bytes[10],uint256)')[:4].hex(),
        'executeOne(address,bytes)': keccak(text='executeOne(address,bytes)')[:4].hex(),
        'execute((address,uint256,bytes)[])': keccak(text='execute((address,uint256,bytes)[])')[:4].hex(),
    }
    
    print("Function selectors:")
    for name, selector in selectors.items():
        print(f"  {name}: 0x{selector}")
    
    # Get contract bytecode
    code = w3.eth.get_code(IMPLEMENTATION_ADDRESS)
    code_hex = code.hex()
    
    print(f"\nChecking which selectors exist in bytecode:")
    for name, selector in selectors.items():
        if selector in code_hex:
            print(f"  ✅ Found {name}")
        else:
            print(f"  ❌ Not found {name}")


def main():
    """Run all debug tests."""
    print("Pectra Minimal Executor Debug")
    print("=" * 50)
    
    print(f"Account: {account.address}")
    print(f"Implementation: {IMPLEMENTATION_ADDRESS}")
    print(f"Chain ID: {w3.eth.chain_id}")
    
    # Run tests
    check_contract_methods()
    test_simple_call()
    test_execute10_empty()
    test_execute10_single()
    test_eip7702_transaction()


if __name__ == "__main__":
    main()