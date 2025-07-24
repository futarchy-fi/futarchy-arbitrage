"""
Test EIP-7702 transaction on-chain
==================================

This script deploys the implementation contract and sends a real EIP-7702
transaction to demonstrate the functionality on testnet.
"""

import os
import sys
import time
import json
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from solcx import compile_source, install_solc
from eth_utils import to_hex

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from helpers.eip7702_builder import EIP7702TransactionBuilder


def compile_contract(contract_path):
    """Compile the FutarchyBatchExecutor contract."""
    print("Compiling FutarchyBatchExecutor contract...")
    
    # Install solc if not available
    try:
        install_solc('0.8.20')
    except Exception as e:
        print(f"Note: {e}")
    
    # Read contract
    with open(contract_path, 'r') as f:
        contract_source = f.read()
    
    # Compile
    compiled_sol = compile_source(
        contract_source,
        output_values=['abi', 'bin'],
        solc_version='0.8.20'
    )
    
    # Get the contract interface
    contract_id, contract_interface = compiled_sol.popitem()
    
    return contract_interface


def deploy_implementation(w3, account, contract_interface):
    """Deploy the FutarchyBatchExecutor implementation contract."""
    print("\nDeploying FutarchyBatchExecutor implementation...")
    
    # Create contract instance
    contract = w3.eth.contract(
        abi=contract_interface['abi'],
        bytecode=contract_interface['bin']
    )
    
    # Build deployment transaction
    tx = contract.constructor().build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 2000000,
        'gasPrice': w3.eth.gas_price,
    })
    
    # Sign and send
    signed_tx = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    print(f"Deployment tx hash: {to_hex(tx_hash)}")
    print("Waiting for confirmation...")
    
    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"✓ Contract deployed at: {receipt.contractAddress}")
        return receipt.contractAddress
    else:
        raise Exception("Deployment failed")


def send_test_eip7702_transaction(w3, account, implementation_address):
    """Send a test EIP-7702 transaction."""
    print("\n=== Sending Test EIP-7702 Transaction ===")
    
    # Create builder
    builder = EIP7702TransactionBuilder(w3, implementation_address)
    
    # Add some simple test operations
    # We'll just do some approvals as they don't require actual tokens
    
    # Test token addresses (these don't need to exist for approvals)
    test_token1 = "0x1111111111111111111111111111111111111111"
    test_token2 = "0x2222222222222222222222222222222222222222"
    test_spender = "0x3333333333333333333333333333333333333333"
    
    print("Adding test operations...")
    
    # Add multiple approvals to test batching
    builder.add_approval(test_token1, test_spender, 1000)
    builder.add_approval(test_token2, test_spender, 2000)
    
    # You could also add a simple ETH transfer
    builder.add_call(
        target=account.address,  # Send to self
        value=0,  # 0 ETH
        data=b''  # Empty data
    )
    
    print(f"Total operations: {len(builder.calls)}")
    
    # Build transaction
    tx = builder.build_transaction(account)
    
    print("\nTransaction details:")
    print(f"  Type: {tx['type']}")
    print(f"  To: {tx['to']}")
    print(f"  Authorization list: {len(tx['authorizationList'])} auth(s)")
    print(f"  Data length: {len(tx['data'])} bytes")
    
    # Sign and send
    print("\nSigning and sending transaction...")
    signed_tx = account.sign_transaction(tx)
    
    try:
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"✓ Transaction sent! Hash: {to_hex(tx_hash)}")
        
        print("Waiting for confirmation...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        print(f"\nTransaction receipt:")
        print(f"  Status: {'✓ Success' if receipt.status == 1 else '✗ Failed'}")
        print(f"  Block: {receipt.blockNumber}")
        print(f"  Gas used: {receipt.gasUsed:,}")
        
        return tx_hash, receipt
        
    except Exception as e:
        print(f"✗ Transaction failed: {e}")
        return None, None


def main():
    """Main test function."""
    print("EIP-7702 On-Chain Test")
    print("=" * 50)
    
    # Check environment
    rpc_url = os.getenv("RPC_URL")
    private_key = os.getenv("PRIVATE_KEY")
    
    if not rpc_url or not private_key:
        print("\nError: Set RPC_URL and PRIVATE_KEY environment variables")
        print("For testing, use a testnet like:")
        print("  - Sepolia: https://sepolia.infura.io/v3/YOUR_KEY")
        print("  - Gnosis Chiado: https://rpc.chiadochain.net")
        return
    
    # Connect to network
    print(f"\nConnecting to: {rpc_url}")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    
    if not w3.is_connected():
        print("✗ Failed to connect to network")
        return
    
    # Get network info
    chain_id = w3.eth.chain_id
    latest_block = w3.eth.get_block('latest')
    
    print(f"✓ Connected to chain ID: {chain_id}")
    print(f"  Latest block: {latest_block.number}")
    print(f"  Gas price: {w3.from_wei(w3.eth.gas_price, 'gwei')} gwei")
    
    # Setup account
    account = Account.from_key(private_key)
    balance = w3.eth.get_balance(account.address)
    
    print(f"\nAccount: {account.address}")
    print(f"Balance: {w3.from_wei(balance, 'ether')} ETH")
    
    if balance == 0:
        print("✗ Account has no balance. Please fund it with testnet ETH.")
        return
    
    # Check if implementation is already deployed
    implementation_address = os.getenv("IMPLEMENTATION_ADDRESS")
    
    if not implementation_address:
        # Deploy implementation contract
        try:
            contract_path = os.path.join(
                os.path.dirname(__file__), 
                '..', 
                'contracts', 
                'FutarchyBatchExecutor.sol'
            )
            
            if os.path.exists(contract_path):
                contract_interface = compile_contract(contract_path)
                implementation_address = deploy_implementation(w3, account, contract_interface)
                print(f"\nSave this for future use:")
                print(f"export IMPLEMENTATION_ADDRESS={implementation_address}")
            else:
                print("\n✗ FutarchyBatchExecutor.sol not found")
                print("Using a dummy implementation address for testing")
                implementation_address = "0x" + "42" * 20
                
        except Exception as e:
            print(f"\n✗ Failed to deploy: {e}")
            print("Using a dummy implementation address for testing")
            implementation_address = "0x" + "42" * 20
    else:
        print(f"\nUsing existing implementation: {implementation_address}")
    
    # Send test transaction
    input("\nPress Enter to send test EIP-7702 transaction...")
    
    tx_hash, receipt = send_test_eip7702_transaction(w3, account, implementation_address)
    
    if tx_hash:
        print(f"\n🎉 Success! View your transaction:")
        
        # Generate explorer URL based on chain ID
        if chain_id == 1:
            explorer = "https://etherscan.io"
        elif chain_id == 100:
            explorer = "https://gnosisscan.io"
        elif chain_id == 10200:
            explorer = "https://gnosis-chiado.blockscout.com"
        elif chain_id == 11155111:
            explorer = "https://sepolia.etherscan.io"
        else:
            explorer = None
        
        if explorer:
            print(f"{explorer}/tx/{to_hex(tx_hash)}")
        
        # Save transaction details
        tx_details = {
            'chain_id': chain_id,
            'tx_hash': to_hex(tx_hash),
            'implementation': implementation_address,
            'account': account.address,
            'status': receipt.status,
            'block': receipt.blockNumber,
            'gas_used': receipt.gasUsed,
            'timestamp': int(time.time())
        }
        
        with open('eip7702_test_tx.json', 'w') as f:
            json.dump(tx_details, f, indent=2)
        
        print("\nTransaction details saved to eip7702_test_tx.json")


if __name__ == "__main__":
    main()