#!/usr/bin/env python3
"""
Execute arbitrage using the multicall contract.
"""
import os
import json
import time
from decimal import Decimal
from web3 import Web3

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))

# Load ABIs
with open('deployment_info.json', 'r') as f:
    deployment_info = json.load(f)
    EXECUTOR_ABI = deployment_info['abi']

def execute_multicall(executor_address, calls, private_key):
    """Execute multicall on the arbitrage executor"""
    
    # Get account from private key
    account = w3.eth.account.from_key(private_key)
    print(f"Executing from account: {account.address}")
    
    # Get executor contract
    executor = w3.eth.contract(address=executor_address, abi=EXECUTOR_ABI)
    
    # Check owner
    owner = executor.functions.owner().call()
    print(f"Contract owner: {owner}")
    
    if owner.lower() != account.address.lower():
        raise Exception(f"Account {account.address} is not the owner of the contract")
    
    # Prepare multicall transaction
    print("\nPreparing multicall transaction...")
    
    # Convert calls to contract format
    contract_calls = []
    for call in calls:
        contract_calls.append((
            w3.to_checksum_address(call['target']),
            bytes.fromhex(call['callData'].replace('0x', ''))
        ))
    
    # Build transaction
    tx = executor.functions.multicall(contract_calls).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 2000000,  # Adjust as needed
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    # Sign and send
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    print(f"\nTransaction sent: {tx_hash.hex()}")
    print("Waiting for confirmation...")
    
    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"✅ Transaction successful!")
        print(f"Gas used: {receipt.gasUsed}")
        
        # Parse events
        logs = executor.events.MulticallExecuted().process_receipt(receipt)
        for log in logs:
            print(f"\nMulticall executed:")
            print(f"  Total calls: {log['args']['callsCount']}")
            print(f"  Successful: {log['args']['successCount']}")
        
        return receipt
    else:
        print(f"❌ Transaction failed!")
        return None

def execute_arbitrage_multicall(executor_address, calls, profit_token, min_profit, private_key):
    """Execute arbitrage using executeArbitrage function"""
    
    # Get account from private key
    account = w3.eth.account.from_key(private_key)
    print(f"Executing from account: {account.address}")
    
    # Get executor contract
    executor = w3.eth.contract(address=executor_address, abi=EXECUTOR_ABI)
    
    # Convert calls to contract format
    contract_calls = []
    for call in calls:
        contract_calls.append((
            w3.to_checksum_address(call['target']),
            bytes.fromhex(call['callData'].replace('0x', ''))
        ))
    
    # Build transaction
    tx = executor.functions.executeArbitrage(
        contract_calls,
        w3.to_checksum_address(profit_token),
        min_profit
    ).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 2000000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    # Sign and send
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    print(f"\nTransaction sent: {tx_hash.hex()}")
    print("Waiting for confirmation...")
    
    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"✅ Arbitrage successful!")
        print(f"Gas used: {receipt.gasUsed}")
        
        # Parse events
        profit_logs = executor.events.ArbitrageProfit().process_receipt(receipt)
        for log in profit_logs:
            profit = log['args']['profit']
            print(f"\n💰 Profit: {Web3.from_wei(profit, 'ether')} sDAI")
        
        return receipt
    else:
        print(f"❌ Arbitrage failed!")
        return None

def main():
    # Load configuration
    executor_address = os.getenv('ARBITRAGE_EXECUTOR_ADDRESS')
    if not executor_address:
        print("Error: ARBITRAGE_EXECUTOR_ADDRESS not set")
        return
    
    private_key = os.getenv('PRIVATE_KEY')
    if not private_key:
        print("Error: PRIVATE_KEY not set")
        return
    
    # Load multicall data
    try:
        with open('buy_conditional_multicall.json', 'r') as f:
            multicall_data = json.load(f)
    except FileNotFoundError:
        print("Error: buy_conditional_multicall.json not found")
        print("Run encode_buy_conditional_multicall.py first")
        return
    
    calls = multicall_data['calls']
    params = multicall_data['params']
    
    print(f"\n=== Executing Buy Conditional Arbitrage ===")
    print(f"Executor: {executor_address}")
    print(f"Amount: 0.01 sDAI")
    print(f"Total operations: {len(calls)}")
    
    # Option 1: Execute as regular multicall (for testing)
    # receipt = execute_multicall(executor_address, calls, private_key)
    
    # Option 2: Execute as arbitrage with profit tracking
    profit_token = params['sdai_token']
    min_profit = 0  # No minimum for testing
    
    receipt = execute_arbitrage_multicall(
        executor_address,
        calls,
        profit_token,
        min_profit,
        private_key
    )
    
    if receipt:
        print(f"\n✅ View on Gnosisscan: https://gnosisscan.io/tx/{receipt.transactionHash.hex()}")

if __name__ == "__main__":
    main()