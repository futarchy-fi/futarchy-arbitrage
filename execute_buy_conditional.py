#!/usr/bin/env python3
import json
import os
from decimal import Decimal
from web3 import Web3
from eth_abi import encode

def load_contract(w3, contract_address):
    """Load the deployed contract"""
    with open('deployment_info.json', 'r') as f:
        deployment_info = json.load(f)
    
    abi = deployment_info['abi']
    return w3.eth.contract(address=contract_address, abi=abi)

def encode_swap_data(fee, min_amount_out):
    """Encode swap data for Swapr"""
    return encode(['uint24', 'uint256'], [fee, min_amount_out])

def encode_balancer_swap_data(pool_id, min_amount_out):
    """Encode swap data for Balancer"""
    return encode(['bytes32', 'uint256'], [pool_id, min_amount_out])

def get_pool_id(w3, pool_address):
    """Get Balancer pool ID from pool address"""
    # Balancer pool ABI for getPoolId
    pool_abi = [{
        "inputs": [],
        "name": "getPoolId",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function"
    }]
    
    # Convert to checksum address
    pool_address = w3.to_checksum_address(pool_address)
    pool_contract = w3.eth.contract(address=pool_address, abi=pool_abi)
    return pool_contract.functions.getPoolId().call()

def main():
    # Load environment variables
    rpc_url = os.getenv('RPC_URL')
    private_key = os.getenv('PRIVATE_KEY')
    
    # Contract address from environment or use the newly deployed one
    executor_address = os.getenv('ARBITRAGE_EXECUTOR_ADDRESS', '0xEcd0951d23c655416CdcC4800AC69bDA9E6bCA25')
    
    # Connect to network first to use checksum conversion
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise Exception("Failed to connect to network")
    
    # Token addresses from environment (convert to checksum)
    sdai_token = w3.to_checksum_address(os.getenv('SDAI_TOKEN_ADDRESS'))
    company_token = w3.to_checksum_address(os.getenv('COMPANY_TOKEN_ADDRESS'))
    sdai_yes_token = w3.to_checksum_address(os.getenv('SWAPR_SDAI_YES_ADDRESS'))
    sdai_no_token = w3.to_checksum_address(os.getenv('SWAPR_SDAI_NO_ADDRESS'))
    company_yes_token = w3.to_checksum_address(os.getenv('SWAPR_GNO_YES_ADDRESS'))
    company_no_token = w3.to_checksum_address(os.getenv('SWAPR_GNO_NO_ADDRESS'))
    
    # Pool addresses
    balancer_pool = w3.to_checksum_address(os.getenv('BALANCER_POOL_ADDRESS'))
    
    # Amount to arbitrage (0.01 sDAI)
    amount_in = Web3.to_wei(0.01, 'ether')
    min_profit = 0  # For testing, accept any profit
    
    print(f"Setting up buy conditional arbitrage...")
    print(f"Amount: {Web3.from_wei(amount_in, 'ether')} sDAI")
    
    # Get account
    account = w3.eth.account.from_key(private_key)
    print(f"Executing from account: {account.address}")
    
    # Check sDAI balance
    sdai_abi = [{
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }, {
        "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    }]
    
    sdai_contract = w3.eth.contract(address=sdai_token, abi=sdai_abi)
    balance = sdai_contract.functions.balanceOf(account.address).call()
    print(f"sDAI balance: {Web3.from_wei(balance, 'ether')}")
    
    if balance < amount_in:
        raise Exception(f"Insufficient sDAI balance. Need {Web3.from_wei(amount_in, 'ether')}, have {Web3.from_wei(balance, 'ether')}")
    
    # Load executor contract
    executor = load_contract(w3, executor_address)
    
    # Approve executor to spend sDAI
    print(f"Approving executor to spend sDAI...")
    approve_tx = sdai_contract.functions.approve(
        executor_address,
        amount_in
    ).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 100000,
        'gasPrice': w3.eth.gas_price
    })
    
    signed_approve = w3.eth.account.sign_transaction(approve_tx, private_key)
    approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
    approve_receipt = w3.eth.wait_for_transaction_receipt(approve_hash)
    print(f"Approval tx: {approve_hash.hex()}")
    
    # Balancer pool ID (from config)
    pool_id = bytes.fromhex("d1d7fa8871d84d0e77020fc28b7cd5718c4465220000000000000000000001d7")
    print(f"Balancer pool ID: {pool_id.hex()}")
    
    # Prepare swap data
    # Swapr uses 3000 fee tier (0.3%)
    swapr_fee = 3000
    # For testing, accept any output (set minimum to 0)
    swapr_yes_swap_data = encode_swap_data(swapr_fee, 0)
    swapr_no_swap_data = encode_swap_data(swapr_fee, 0)
    balancer_swap_data = encode_balancer_swap_data(pool_id, 0)
    
    # Get proposal address
    proposal_address = os.getenv('FUTARCHY_PROPOSAL_ADDRESS')
    
    # Prepare arbitrage parameters
    params = {
        'proposalAddress': w3.to_checksum_address(proposal_address),
        'sdaiToken': sdai_token,
        'companyToken': company_token,
        'sdaiYesToken': sdai_yes_token,
        'sdaiNoToken': sdai_no_token,
        'companyYesToken': company_yes_token,
        'companyNoToken': company_no_token,
        'amountIn': amount_in,
        'minProfit': min_profit,
        'balancerSwapData': balancer_swap_data,
        'swaprYesSwapData': swapr_yes_swap_data,
        'swaprNoSwapData': swapr_no_swap_data
    }
    
    print("\nExecuting buy conditional arbitrage...")
    print(f"Parameters:")
    print(f"  sDAI amount: {Web3.from_wei(amount_in, 'ether')}")
    print(f"  Min profit: {min_profit}")
    
    # Build transaction
    tx = executor.functions.executeBuyConditionalArbitrage(
        params
    ).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 1000000,  # 1M gas should be enough
        'gasPrice': w3.eth.gas_price
    })
    
    # Sign and send transaction
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    print(f"\nTransaction sent: {tx_hash.hex()}")
    print("Waiting for confirmation...")
    
    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"\n✅ Arbitrage executed successfully!")
        print(f"Gas used: {receipt.gasUsed}")
        
        # Check for events
        if receipt.logs:
            print("\nEvents emitted:")
            for log in receipt.logs:
                print(f"  - {log}")
    else:
        print(f"\n❌ Transaction failed!")
        print(f"Receipt: {receipt}")

if __name__ == "__main__":
    main()