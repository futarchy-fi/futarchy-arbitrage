#!/usr/bin/env python3
"""
Test multicall with split position and swap operations.
"""
import os
import json
import time
from web3 import Web3
from src.config.abis import ERC20_ABI
from src.config.abis.futarchy import FUTARCHY_ROUTER_ABI
from src.config.abis.swapr import SWAPR_ROUTER_ABI

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))

# Load contract ABI
with open('deployment_info.json', 'r') as f:
    deployment_info = json.load(f)
    EXECUTOR_ABI = deployment_info['abi']

def test_split_and_swap():
    """Test split position and swap operations"""
    
    # Get addresses
    executor_address = w3.to_checksum_address(os.environ['ARBITRAGE_EXECUTOR_ADDRESS'])
    private_key = os.environ['PRIVATE_KEY']
    account = w3.eth.account.from_key(private_key)
    
    # Token addresses
    sdai_token = w3.to_checksum_address(os.environ['SDAI_TOKEN_ADDRESS'])
    sdai_yes = w3.to_checksum_address(os.environ['SWAPR_SDAI_YES_ADDRESS'])
    sdai_no = w3.to_checksum_address(os.environ['SWAPR_SDAI_NO_ADDRESS'])
    company_yes = w3.to_checksum_address(os.environ['SWAPR_GNO_YES_ADDRESS'])
    company_no = w3.to_checksum_address(os.environ['SWAPR_GNO_NO_ADDRESS'])
    
    # Router addresses
    futarchy_router = w3.to_checksum_address(os.environ['FUTARCHY_ROUTER_ADDRESS'])
    swapr_router = w3.to_checksum_address(os.environ['SWAPR_ROUTER_ADDRESS'])
    proposal = w3.to_checksum_address(os.environ['FUTARCHY_PROPOSAL_ADDRESS'])
    
    print(f"Testing split and swap from account: {account.address}")
    print(f"Executor: {executor_address}")
    
    # Get contracts
    executor = w3.eth.contract(address=executor_address, abi=EXECUTOR_ABI)
    sdai = w3.eth.contract(address=sdai_token, abi=ERC20_ABI)
    futarchy_router_contract = w3.eth.contract(address=futarchy_router, abi=FUTARCHY_ROUTER_ABI)
    swapr_router_contract = w3.eth.contract(address=swapr_router, abi=SWAPR_ROUTER_ABI)
    
    # Amount to test with
    amount_wei = int(0.01 * 10**18)  # 0.01 sDAI
    
    # Step 1: Approve and pull tokens
    print("\n1. Approving and pulling sDAI...")
    
    # Approve executor
    tx = sdai.functions.approve(executor_address, amount_wei).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 100000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"✅ Approved executor")
    
    # Pull tokens
    tx = executor.functions.pullToken(sdai_token, amount_wei).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 150000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"✅ Pulled {Web3.from_wei(amount_wei, 'ether')} sDAI")
    
    # Step 2: Build multicall for split and swap
    print("\n2. Building multicall for split position and swaps...")
    
    calls = []
    
    # Call 1: Approve FutarchyRouter
    approve_data = sdai.encodeABI(
        fn_name='approve',
        args=[futarchy_router, amount_wei]
    )
    calls.append((sdai_token, approve_data))
    
    # Call 2: Split position
    split_data = futarchy_router_contract.encodeABI(
        fn_name='splitPosition',
        args=[proposal, sdai_token, amount_wei]
    )
    calls.append((futarchy_router, split_data))
    
    # Call 3: Approve Swapr router for YES tokens
    sdai_yes_contract = w3.eth.contract(address=sdai_yes, abi=ERC20_ABI)
    approve_yes_data = sdai_yes_contract.encodeABI(
        fn_name='approve',
        args=[swapr_router, 2**256 - 1]
    )
    calls.append((sdai_yes, approve_yes_data))
    
    # Call 4: Approve Swapr router for NO tokens
    sdai_no_contract = w3.eth.contract(address=sdai_no, abi=ERC20_ABI)
    approve_no_data = sdai_no_contract.encodeABI(
        fn_name='approve',
        args=[swapr_router, 2**256 - 1]
    )
    calls.append((sdai_no, approve_no_data))
    
    print(f"Total calls: {len(calls)}")
    
    # Execute multicall
    print("\n3. Executing multicall...")
    tx = executor.functions.multicall(calls).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 500000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"✅ Multicall successful! tx: {tx_hash.hex()}")
        
        # Check balances
        yes_balance = sdai_yes_contract.functions.balanceOf(executor_address).call()
        no_balance = sdai_no_contract.functions.balanceOf(executor_address).call()
        
        print(f"\nConditional token balances:")
        print(f"  YES sDAI: {Web3.from_wei(yes_balance, 'ether')}")
        print(f"  NO sDAI: {Web3.from_wei(no_balance, 'ether')}")
        
        # Now test a swap
        if yes_balance > 0:
            print("\n4. Testing swap of YES tokens...")
            
            # Build swap parameters
            deadline = int(time.time()) + 300
            swap_params = (
                sdai_yes,           # tokenIn
                company_yes,        # tokenOut
                executor_address,   # recipient
                deadline,           # deadline
                yes_balance,        # amountIn
                0,                  # amountOutMinimum
                0                   # sqrtPriceLimitX96
            )
            
            swap_data = swapr_router_contract.encodeABI(
                fn_name='exactInputSingle',
                args=[swap_params]
            )
            
            # Execute single swap
            swap_calls = [(swapr_router, swap_data)]
            
            tx = executor.functions.multicall(swap_calls).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 500000,
                'gasPrice': w3.eth.gas_price,
                'chainId': w3.eth.chain_id
            })
            
            signed_tx = w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt.status == 1:
                print(f"✅ Swap successful! tx: {tx_hash.hex()}")
                
                # Check Company YES balance
                company_yes_contract = w3.eth.contract(address=company_yes, abi=ERC20_ABI)
                company_yes_balance = company_yes_contract.functions.balanceOf(executor_address).call()
                print(f"  Company YES tokens received: {Web3.from_wei(company_yes_balance, 'ether')}")
            else:
                print(f"❌ Swap failed!")
    else:
        print(f"❌ Multicall failed!")
    
    # Cleanup: Push all tokens back
    print("\n5. Cleanup - pushing tokens back...")
    
    # Get all token addresses
    tokens = [sdai_token, sdai_yes, sdai_no, company_yes, company_no]
    
    for token_addr in tokens:
        token_contract = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
        balance = token_contract.functions.balanceOf(executor_address).call()
        
        if balance > 0:
            tx = executor.functions.pushToken(token_addr, 2**256 - 1).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 150000,
                'gasPrice': w3.eth.gas_price,
                'chainId': w3.eth.chain_id
            })
            
            signed_tx = w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            w3.eth.wait_for_transaction_receipt(tx_hash)
            
            try:
                token_symbol = token_contract.functions.symbol().call()
            except:
                token_symbol = "tokens"
            print(f"  ✅ Pushed {Web3.from_wei(balance, 'ether')} {token_symbol}")

if __name__ == "__main__":
    test_split_and_swap()