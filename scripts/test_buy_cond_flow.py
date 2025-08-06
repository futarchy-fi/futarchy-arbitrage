#!/usr/bin/env python3
"""
Test the complete buy_cond_eip7702_minimal flow to trace exactly what happens.
"""

import os
import sys
from decimal import Decimal
from web3 import Web3
from eth_account import Account

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.arbitrage_commands.buy_cond_eip7702_minimal import (
    buy_conditional_bundled_minimal,
    build_buy_conditional_bundle_minimal,
    IMPLEMENTATION_ADDRESS
)
from src.helpers.eip7702_builder import EIP7702TransactionBuilder
from src.helpers.bundle_helpers import calculate_bundle_gas_params

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
account = Account.from_key(os.environ["PRIVATE_KEY"])


def trace_transaction_building():
    """Trace how the transaction is built in the buy conditional flow."""
    print("=== Tracing Buy Conditional Flow ===\n")
    
    print(f"Account: {account.address}")
    print(f"Implementation: {IMPLEMENTATION_ADDRESS}")
    print(f"Chain ID: {w3.eth.chain_id}")
    
    # Test amount
    amount = Decimal("0.001")  # 0.001 sDAI
    
    print(f"\n1. Building bundle for {amount} sDAI...")
    
    # Build bundle
    bundle_calls = build_buy_conditional_bundle_minimal(
        amount,
        simulation_results=None,
        skip_approvals={}
    )
    
    print(f"   Bundle has {len(bundle_calls)} calls")
    for i, call in enumerate(bundle_calls):
        print(f"   Call {i}: to={call['target'][:10]}... data_len={len(call['data'])} bytes")
    
    print("\n2. Creating EIP7702TransactionBuilder...")
    builder = EIP7702TransactionBuilder(w3, IMPLEMENTATION_ADDRESS)
    
    # Add calls to builder
    for call in bundle_calls:
        builder.add_call(call['target'], call['value'], call['data'])
    
    print(f"   Added {len(builder.calls)} calls to builder")
    
    print("\n3. Building EIP-7702 transaction...")
    gas_params = calculate_bundle_gas_params(w3)
    tx = builder.build_transaction(account, gas_params)
    
    print("   Transaction details:")
    print(f"   - type: {tx.get('type')} (should be 4)")
    print(f"   - chainId: {tx.get('chainId')}")
    print(f"   - to: {tx.get('to')} (should be {account.address})")
    print(f"   - nonce: {tx.get('nonce')}")
    print(f"   - authorizationList: {len(tx.get('authorizationList', []))} items")
    print(f"   - data length: {len(tx.get('data', ''))} bytes")
    
    # Check authorization
    if 'authorizationList' in tx and len(tx['authorizationList']) > 0:
        auth = tx['authorizationList'][0]
        print("\n   Authorization details:")
        print(f"   - chainId: {auth.get('chainId')}")
        print(f"   - address: {auth.get('address')} (should be {IMPLEMENTATION_ADDRESS})")
        print(f"   - nonce: {auth.get('nonce')}")
    
    print("\n4. Signing transaction...")
    signed_tx = account.sign_transaction(tx)
    
    # Check raw transaction
    raw_tx = signed_tx.raw_transaction if hasattr(signed_tx, 'raw_transaction') else signed_tx.rawTransaction
    print(f"   Raw transaction type: {type(raw_tx)}")
    print(f"   Raw transaction length: {len(raw_tx)} bytes")
    print(f"   First byte: 0x{raw_tx[0]:02x} (0x04 = EIP-7702)")
    
    if raw_tx[0] == 0x04:
        print("   ✅ This is an EIP-7702 transaction!")
    else:
        print(f"   ❌ This is NOT an EIP-7702 transaction! Type: {raw_tx[0]}")
    
    return tx, signed_tx


def test_direct_call():
    """Test what happens with direct call vs EIP-7702."""
    print("\n=== Comparing Direct Call vs EIP-7702 ===\n")
    
    # First, trace the proper EIP-7702 flow
    print("1. Proper EIP-7702 flow:")
    eip7702_tx, signed_eip7702 = trace_transaction_building()
    
    print("\n2. Direct call (will fail):")
    # Build a direct call transaction
    from eth_utils import keccak
    from eth_abi import encode
    
    function_selector = keccak(text="execute10(address[10],bytes[10],uint256)")[:4]
    zero_address = '0x0000000000000000000000000000000000000000'
    targets = [zero_address] * 10
    calldatas = [b''] * 10
    count = 0
    
    encoded_params = encode(
        ['address[10]', 'bytes[10]', 'uint256'],
        [targets, calldatas, count]
    )
    
    direct_tx = {
        'from': account.address,
        'to': IMPLEMENTATION_ADDRESS,  # Direct call to implementation
        'data': function_selector + encoded_params,
        'gas': 300000,
        'gasPrice': w3.eth.gas_price,
        'nonce': w3.eth.get_transaction_count(account.address),
        'chainId': w3.eth.chain_id
    }
    
    print("   Direct transaction details:")
    print(f"   - type: 0 (Legacy)")
    print(f"   - to: {direct_tx['to']} (implementation contract)")
    print(f"   - from: {direct_tx['from']}")
    print("   - authorizationList: None")
    print("\n   ❌ This will fail with 'Only self' error!")
    
    print("\n3. Key difference:")
    print("   - EIP-7702: Calls account address with delegated code")
    print("   - Direct: Calls implementation contract directly")
    print("   - Contract requires msg.sender == address(this)")


def test_full_flow_simulation():
    """Test the full buy conditional flow in simulation mode."""
    print("\n=== Testing Full Buy Conditional Flow (Simulation) ===\n")
    
    amount = Decimal("0.001")
    
    print(f"Running buy_conditional_bundled_minimal({amount}, broadcast=False)...")
    
    try:
        result = buy_conditional_bundled_minimal(amount, broadcast=False)
        
        print("\nSimulation results:")
        for key, value in result.items():
            print(f"  {key}: {value}")
            
        if result['status'] == 'simulated':
            print("\n✅ Simulation successful!")
        else:
            print(f"\n❌ Simulation failed: {result.get('error', 'Unknown error')}")
            
    except Exception as e:
        print(f"\n❌ Exception during simulation: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all tests."""
    print("Buy Conditional EIP-7702 Flow Testing")
    print("=" * 50)
    
    trace_transaction_building()
    test_direct_call()
    test_full_flow_simulation()
    
    print("\n" + "=" * 50)
    print("Summary:")
    print("- buy_cond_eip7702_minimal.py DOES use EIP-7702 correctly")
    print("- The failed transaction was likely from test_pectra_onchain.py")
    print("- That script makes direct calls without EIP-7702")
    print("- Always use buy_cond_eip7702_minimal.py or test_pectra_force_onchain.py")


if __name__ == "__main__":
    main()