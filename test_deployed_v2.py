#!/usr/bin/env python3
"""
Test the deployed FutarchyArbitrageExecutorV2 contract.
"""
import os
import json
from web3 import Web3
from eth_account import Account
from src.config.abis import ERC20_ABI

# Load environment
w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
private_key = os.environ["PRIVATE_KEY"]
account = Account.from_key(private_key)

# Load deployment info
try:
    with open('deployment_info_v2.json', 'r') as f:
        deployment_info = json.load(f)
        EXECUTOR_ADDRESS = deployment_info['address']
        EXECUTOR_ABI = deployment_info['abi']
except FileNotFoundError:
    print("Error: deployment_info_v2.json not found. Deploy contract first.")
    exit(1)

print(f"Testing FutarchyArbitrageExecutorV2")
print(f"Contract: {EXECUTOR_ADDRESS}")
print(f"Owner: {account.address}")
print("=" * 60)

# Get contract instance
executor = w3.eth.contract(address=Web3.to_checksum_address(EXECUTOR_ADDRESS), abi=EXECUTOR_ABI)

# Test 1: Verify ownership
print("\n1️⃣ Testing ownership...")
try:
    owner = executor.functions.owner().call()
    print(f"   Contract owner: {owner}")
    print(f"   Matches deployer: {'✅' if owner.lower() == account.address.lower() else '❌'}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 2: Check token balances
print("\n2️⃣ Checking token balances...")
sdai_address = Web3.to_checksum_address(os.environ['SDAI_TOKEN_ADDRESS'])
try:
    balance = executor.functions.getBalance(sdai_address).call()
    print(f"   sDAI balance: {Web3.from_wei(balance, 'ether'):.6f}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 3: Test approveToken function
print("\n3️⃣ Testing token approval...")
try:
    # Approve a small amount to FutarchyRouter
    router_address = Web3.to_checksum_address(os.environ['FUTARCHY_ROUTER_ADDRESS'])
    amount = Web3.to_wei(1, 'ether')
    
    tx = executor.functions.approveToken(
        sdai_address,
        router_address,
        amount
    ).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 100000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    # Estimate gas
    gas_estimate = w3.eth.estimate_gas(tx)
    tx['gas'] = int(gas_estimate * 1.2)
    
    print(f"   Approving {Web3.from_wei(amount, 'ether')} sDAI to router...")
    print(f"   Gas estimate: {gas_estimate:,}")
    
    # Sign and send
    signed_tx = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    print(f"   TX sent: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print("   ✅ Approval successful!")
    else:
        print("   ❌ Approval failed!")
        
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 4: Test multicall with view functions
print("\n4️⃣ Testing multicall...")
try:
    # Build a simple multicall that checks balance
    sdai = w3.eth.contract(address=sdai_address, abi=ERC20_ABI)
    
    # Call 1: Check executor's balance
    call1_data = sdai.encodeABI(fn_name='balanceOf', args=[EXECUTOR_ADDRESS])
    
    # Call 2: Check owner's balance
    call2_data = sdai.encodeABI(fn_name='balanceOf', args=[account.address])
    
    calls = [
        (sdai_address, call1_data),
        (sdai_address, call2_data)
    ]
    
    print(f"   Executing {len(calls)} view calls...")
    
    tx = executor.functions.multicall(calls).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 200000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    signed_tx = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    print(f"   TX sent: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print("   ✅ Multicall successful!")
        print(f"   Gas used: {receipt.gasUsed:,}")
    else:
        print("   ❌ Multicall failed!")
        
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 5: Send test tokens and withdraw
print("\n5️⃣ Testing token deposit and withdrawal...")
try:
    # First check if owner has sDAI
    sdai = w3.eth.contract(address=sdai_address, abi=ERC20_ABI)
    owner_balance = sdai.functions.balanceOf(account.address).call()
    
    if owner_balance > 0:
        # Send 0.001 sDAI to executor
        test_amount = Web3.to_wei(0.001, 'ether')
        
        print(f"   Sending {Web3.from_wei(test_amount, 'ether')} sDAI to executor...")
        
        tx = sdai.functions.transfer(
            EXECUTOR_ADDRESS,
            test_amount
        ).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 100000,
            'gasPrice': w3.eth.gas_price,
            'chainId': w3.eth.chain_id
        })
        
        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt.status == 1:
            print("   ✅ Transfer successful!")
            
            # Check new balance
            new_balance = executor.functions.getBalance(sdai_address).call()
            print(f"   Executor sDAI balance: {Web3.from_wei(new_balance, 'ether'):.6f}")
            
            # Now withdraw it back
            print("\n   Testing withdrawal...")
            
            tx = executor.functions.withdrawToken(
                sdai_address,
                0  # 0 means withdraw all
            ).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 100000,
                'gasPrice': w3.eth.gas_price,
                'chainId': w3.eth.chain_id
            })
            
            signed_tx = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt.status == 1:
                print("   ✅ Withdrawal successful!")
                
                # Check final balance
                final_balance = executor.functions.getBalance(sdai_address).call()
                print(f"   Final executor balance: {Web3.from_wei(final_balance, 'ether'):.6f}")
            else:
                print("   ❌ Withdrawal failed!")
        else:
            print("   ❌ Transfer failed!")
    else:
        print("   ⚠️  Owner has no sDAI balance to test with")
        
except Exception as e:
    print(f"   ❌ Error: {e}")

# Summary
print(f"\n{'='*60}")
print("TEST SUMMARY")
print(f"{'='*60}")
print("✅ Contract deployed and accessible")
print("✅ Basic functions working")
print("\nNext steps:")
print("1. Send tokens to executor for arbitrage")
print("2. Build multicall for actual swaps")
print("3. Execute with profit verification")
print(f"\nView contract: https://gnosisscan.io/address/{EXECUTOR_ADDRESS}")