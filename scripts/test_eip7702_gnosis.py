#!/usr/bin/env python3
"""
Test EIP-7702 on Gnosis Chain
=============================

Gnosis Chain has Pectra/EIP-7702 live since April 30, 2024!
Let's test it with a real transaction.
"""

import os
import sys
import time
from web3 import Web3
from eth_account import Account
from eth_utils import to_hex
from dotenv import load_dotenv

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.helpers.eip7702_builder import EIP7702TransactionBuilder

# Load environment
ENV_FILE = os.getenv('ENV_FILE', '.env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF')
load_dotenv(ENV_FILE, override=True)


def test_eip7702_on_gnosis():
    """Test EIP-7702 transaction on Gnosis Chain."""
    print("EIP-7702 Test on Gnosis Chain")
    print("=" * 50)
    print(f"Using environment: {ENV_FILE}")
    
    # Get RPC URL - default to Gnosis public RPC if not set
    rpc_url = os.getenv("RPC_URL", "https://rpc.gnosischain.com")
    private_key = os.getenv("PRIVATE_KEY")
    
    if not private_key:
        print("Error: PRIVATE_KEY not found in environment")
        return
    
    # Connect to Gnosis Chain
    print(f"\nConnecting to: {rpc_url}")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    
    if not w3.is_connected():
        print("Failed to connect to Gnosis Chain")
        return
    
    # Verify we're on Gnosis Chain
    chain_id = w3.eth.chain_id
    if chain_id != 100:
        print(f"Warning: Expected Gnosis Chain (100), got chain ID: {chain_id}")
    
    latest_block = w3.eth.get_block('latest')
    print(f"✓ Connected to Gnosis Chain")
    print(f"  Latest block: {latest_block.number}")
    print(f"  Block time: {latest_block.timestamp}")
    
    # Setup account
    account = Account.from_key(private_key)
    balance = w3.eth.get_balance(account.address)
    nonce = w3.eth.get_transaction_count(account.address)
    
    print(f"\nAccount: {account.address}")
    print(f"Balance: {w3.from_wei(balance, 'ether')} xDAI")
    print(f"Nonce: {nonce}")
    
    if balance == 0:
        print("\n⚠️  Account has no xDAI for gas!")
        print("Get some from: https://www.gnosisfaucet.com/")
        return
    
    # Use a simple implementation address for testing
    # This can be any address, even non-existent, for testing authorization
    implementation_address = "0x0000000000000000000000000000000000000042"
    
    print(f"\nPreparing EIP-7702 transaction...")
    print(f"Implementation: {implementation_address}")
    
    try:
        # Create builder
        builder = EIP7702TransactionBuilder(w3, implementation_address)
        
        # Add test operations - we'll use existing contract addresses from the env
        sdai_address = os.getenv("SDAI_TOKEN_ADDRESS", "0xaf204776c7245bF4147c2612BF6e5972Ee483701")
        router_address = os.getenv("FUTARCHY_ROUTER_ADDRESS", "0x91c612a37b8365c2db937388d7b424fe03d62850")
        
        print(f"\nAdding test operations:")
        
        # 1. Test approval (won't actually do anything without tokens, but tests the format)
        if sdai_address and router_address:
            builder.add_approval(sdai_address, router_address, 1000)
            print(f"  ✓ Added approval: sDAI → FutarchyRouter")
        
        # 2. Add a self-call as a simple test
        builder.add_call(
            target=account.address,
            value=0,
            data=b'hello eip7702!'  # Some test data
        )
        print(f"  ✓ Added self-call with test data")
        
        # Build transaction with conservative gas settings
        gas_price = w3.eth.gas_price
        tx = builder.build_transaction(account, gas_params={
            'gas': 500000,  # Conservative estimate
            'maxFeePerGas': gas_price * 2,
            'maxPriorityFeePerGas': w3.to_wei(1, 'gwei')
        })
        
        print(f"\n✓ Built EIP-7702 transaction:")
        print(f"  Type: {tx['type']} (EIP-7702)")
        print(f"  To: {tx['to']} (self)")
        print(f"  Operations: {len(builder.calls)}")
        print(f"  Authorization list: {len(tx['authorizationList'])}")
        print(f"  Gas limit: {tx['gas']:,}")
        print(f"  Max fee: {w3.from_wei(tx['maxFeePerGas'], 'gwei'):.2f} gwei")
        
        # Estimate actual gas needed
        print("\nEstimating gas...")
        try:
            # Remove gas fields for estimation
            estimate_tx = tx.copy()
            estimate_tx.pop('gas', None)
            estimated_gas = w3.eth.estimate_gas(estimate_tx)
            print(f"  Estimated gas: {estimated_gas:,}")
            
            # Update transaction with estimated gas + buffer
            tx['gas'] = int(estimated_gas * 1.2)
        except Exception as e:
            print(f"  Gas estimation failed: {e}")
            print(f"  Using default: {tx['gas']:,}")
        
        # Sign transaction
        print("\nSigning transaction...")
        signed_tx = account.sign_transaction(tx)
        
        # Calculate cost
        max_cost = tx['gas'] * tx['maxFeePerGas']
        print(f"\nMax transaction cost: {w3.from_wei(max_cost, 'ether'):.6f} xDAI")
        
        # Auto-send for testing
        print("\n🚀 Sending transaction...")
        
        # Send transaction
        print("\nSending transaction...")
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"✓ Transaction sent!")
        print(f"  Hash: {to_hex(tx_hash)}")
        
        # Explorer link
        print(f"\n📊 View on GnosisScan:")
        print(f"https://gnosisscan.io/tx/{to_hex(tx_hash)}")
        
        # Wait for confirmation
        print("\nWaiting for confirmation...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        
        if receipt.status == 1:
            print(f"\n✅ Transaction successful!")
            print(f"  Block: {receipt.blockNumber}")
            print(f"  Gas used: {receipt.gasUsed:,} ({receipt.gasUsed / tx['gas'] * 100:.1f}% of limit)")
            print(f"  Effective gas price: {w3.from_wei(receipt.effectiveGasPrice, 'gwei'):.2f} gwei")
            
            # Calculate actual cost
            actual_cost = receipt.gasUsed * receipt.effectiveGasPrice
            print(f"  Actual cost: {w3.from_wei(actual_cost, 'ether'):.6f} xDAI")
        else:
            print(f"\n❌ Transaction failed!")
            print(f"  Status: {receipt.status}")
        
        return receipt
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        
        # Check if it's an unsupported transaction type error
        if "unsupported" in str(e).lower() or "type" in str(e).lower():
            print("\n⚠️  This might mean:")
            print("  1. The RPC endpoint doesn't support EIP-7702 yet")
            print("  2. The gas estimation failed for type 4 transactions")
            print("  3. Try using a different RPC endpoint")
        
        import traceback
        traceback.print_exc()
        
        return None


def main():
    """Main entry point."""
    print("🚀 Gnosis Chain EIP-7702 Test")
    print("Pectra has been live on Gnosis since April 30, 2024!")
    print("")
    
    # Activate virtual environment if needed
    if 'eip7702_env' in sys.prefix:
        print("✓ Using EIP-7702 environment")
    else:
        print("⚠️  Not in eip7702_env - make sure eth-account >= 0.13.6")
    
    # Run the test
    receipt = test_eip7702_on_gnosis()
    
    if receipt and receipt.status == 1:
        print("\n🎉 Successfully sent an EIP-7702 transaction on Gnosis Chain!")
        print("This proves that Pectra/EIP-7702 is live and working!")


if __name__ == "__main__":
    main()