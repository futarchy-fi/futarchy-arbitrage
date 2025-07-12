#!/usr/bin/env python3
"""
Test the multicall contract with a simple operation.
"""
import os
import json
from web3 import Web3

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))

# Load contract ABI
with open('deployment_info.json', 'r') as f:
    deployment_info = json.load(f)
    EXECUTOR_ABI = deployment_info['abi']

def test_simple_multicall():
    """Test with a simple approve operation"""
    
    # Get addresses
    executor_address = w3.to_checksum_address(os.environ['ARBITRAGE_EXECUTOR_ADDRESS'])
    private_key = os.environ['PRIVATE_KEY']
    sdai_token = w3.to_checksum_address(os.environ['SDAI_TOKEN_ADDRESS'])
    
    # Get account
    account = w3.eth.account.from_key(private_key)
    print(f"Testing from account: {account.address}")
    
    # Get executor contract
    executor = w3.eth.contract(address=executor_address, abi=EXECUTOR_ABI)
    
    # First, let's approve the executor to spend a small amount of sDAI
    print(f"\n1. First approving executor to spend sDAI...")
    
    # Get sDAI contract
    from src.config.abis import ERC20_ABI
    sdai = w3.eth.contract(address=sdai_token, abi=ERC20_ABI)
    
    # Approve executor
    approve_amount = int(0.01 * 10**18)  # 0.01 sDAI
    tx = sdai.functions.approve(executor_address, approve_amount).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 100000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"✅ Approval tx: {tx_hash.hex()}")
    
    # Now test pullToken function
    print(f"\n2. Testing pullToken function...")
    
    # Check initial balance
    initial_balance = sdai.functions.balanceOf(executor_address).call()
    print(f"Executor initial sDAI balance: {Web3.from_wei(initial_balance, 'ether')}")
    
    # Pull tokens
    pull_amount = int(0.001 * 10**18)  # 0.001 sDAI
    tx = executor.functions.pullToken(sdai_token, pull_amount).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 150000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"✅ Pull token successful! tx: {tx_hash.hex()}")
        
        # Check new balance
        new_balance = sdai.functions.balanceOf(executor_address).call()
        print(f"Executor new sDAI balance: {Web3.from_wei(new_balance, 'ether')}")
        print(f"Pulled amount: {Web3.from_wei(new_balance - initial_balance, 'ether')} sDAI")
    else:
        print(f"❌ Pull token failed!")
        return
    
    # Test multicall with a simple approve operation
    print(f"\n3. Testing multicall with approve operation...")
    
    # Build a simple multicall to approve FutarchyRouter
    futarchy_router = w3.to_checksum_address(os.environ['FUTARCHY_ROUTER_ADDRESS'])
    
    # Encode approve call
    approve_data = sdai.encodeABI(
        fn_name='approve',
        args=[futarchy_router, 2**256 - 1]  # MAX approval
    )
    
    calls = [(sdai_token, approve_data)]
    
    # Execute multicall
    tx = executor.functions.multicall(calls).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 200000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"✅ Multicall successful! tx: {tx_hash.hex()}")
        
        # Parse events
        logs = executor.events.MulticallExecuted().process_receipt(receipt)
        for log in logs:
            print(f"   Calls executed: {log['args']['callsCount']}")
            print(f"   Successful: {log['args']['successCount']}")
        
        # Check allowance
        allowance = sdai.functions.allowance(executor_address, futarchy_router).call()
        print(f"   Executor->FutarchyRouter allowance: {'MAX' if allowance == 2**256-1 else Web3.from_wei(allowance, 'ether')} sDAI")
    else:
        print(f"❌ Multicall failed!")
    
    # Push tokens back
    print(f"\n4. Pushing tokens back to owner...")
    tx = executor.functions.pushToken(sdai_token, 2**256 - 1).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 150000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"✅ Push token successful! tx: {tx_hash.hex()}")
        final_balance = sdai.functions.balanceOf(executor_address).call()
        print(f"Executor final sDAI balance: {Web3.from_wei(final_balance, 'ether')}")

if __name__ == "__main__":
    test_simple_multicall()