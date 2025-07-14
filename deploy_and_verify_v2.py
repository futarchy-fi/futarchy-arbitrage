#!/usr/bin/env python3
"""
Deploy and verify FutarchyArbitrageExecutorV2 contract to Gnosis Chain.
Combines deployment and verification in a single script.
"""
import os
import json
import time
import requests
from web3 import Web3
from eth_account import Account
from solcx import compile_source, install_solc
from eth_abi import encode

def load_environment():
    """Load and validate environment variables."""
    required_vars = ['RPC_URL', 'PRIVATE_KEY']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        print("Make sure to source your .env file first:")
        print("source .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF")
        exit(1)
    
    w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
    if not w3.is_connected():
        print("❌ Failed to connect to RPC")
        exit(1)
        
    private_key = os.environ["PRIVATE_KEY"]
    account = Account.from_key(private_key)
    
    print(f"✅ Connected to Gnosis Chain")
    print(f"Deploying from account: {account.address}")
    print(f"Account balance: {w3.from_wei(w3.eth.get_balance(account.address), 'ether'):.6f} ETH")
    
    return w3, account

def compile_contract():
    """Compile the contract."""
    # Install specific solc version if needed
    try:
        install_solc('0.8.19')
    except:
        pass  # Already installed
    
    # Read contract source
    with open('contracts/FutarchyArbitrageExecutorV2.sol', 'r') as f:
        contract_source = f.read()
    
    print("\n📦 Compiling contract...")
    compiled = compile_source(
        contract_source,
        output_values=['abi', 'bin'],
        solc_version='0.8.19',
        optimize=True,
        optimize_runs=200
    )
    
    # Get contract interface
    contract_interface = None
    for contract_id, interface in compiled.items():
        if 'FutarchyArbitrageExecutorV2' in contract_id:
            contract_interface = interface
            break
    
    if not contract_interface:
        print("❌ Could not find FutarchyArbitrageExecutorV2 in compiled output")
        exit(1)
    
    bytecode = contract_interface['bin']
    abi = contract_interface['abi']
    
    # Add 0x prefix if missing
    if not bytecode.startswith('0x'):
        bytecode = '0x' + bytecode
    
    print(f"✅ Contract compiled successfully")
    print(f"Bytecode size: {len(bytecode)//2} bytes")
    
    return bytecode, abi, contract_source

def deploy_contract(w3, account, bytecode, abi):
    """Deploy the contract."""
    print(f"\n🚀 Deploying contract...")
    
    # Build constructor transaction
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    constructor_tx = contract.constructor(account.address).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    # Estimate gas
    try:
        gas_estimate = w3.eth.estimate_gas(constructor_tx)
        gas_limit = int(gas_estimate * 1.2)  # 20% buffer
        constructor_tx['gas'] = gas_limit
        
        deployment_cost_eth = w3.from_wei(gas_limit * constructor_tx['gasPrice'], 'ether')
        print(f"Estimated cost: {deployment_cost_eth:.6f} ETH")
        
    except Exception as e:
        print(f"⚠️  Gas estimation failed: {e}")
        constructor_tx['gas'] = 1000000  # Fallback
    
    # Deploy
    signed_tx = account.sign_transaction(constructor_tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    print(f"📤 Transaction sent: {tx_hash.hex()}")
    print(f"🔗 View on Gnosisscan: https://gnosisscan.io/tx/{tx_hash.hex()}")
    print("⏳ Waiting for confirmation...")
    
    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    
    if receipt.status != 1:
        print(f"❌ Deployment failed!")
        print(f"Transaction status: {receipt.status}")
        exit(1)
    
    contract_address = receipt.contractAddress
    print(f"\n✅ Contract deployed successfully!")
    print(f"📍 Contract address: {contract_address}")
    print(f"⛽ Gas used: {receipt.gasUsed:,}")
    print(f"🧱 Block number: {receipt.blockNumber}")
    
    # Verify deployment
    deployed_contract = w3.eth.contract(address=contract_address, abi=abi)
    owner = deployed_contract.functions.owner().call()
    print(f"👤 Owner verification: {owner.lower() == account.address.lower()}")
    
    return contract_address, receipt, tx_hash

def save_deployment_info(contract_address, receipt, tx_hash, account, abi):
    """Save deployment information."""
    deployment_info = {
        'address': contract_address,
        'abi': abi,
        'tx_hash': tx_hash.hex(),
        'block_number': receipt.blockNumber,
        'deployer': account.address,
        'gas_used': receipt.gasUsed,
        'deployment_cost_eth': float(Web3.from_wei(receipt.gasUsed * receipt.effectiveGasPrice, 'ether')),
        'timestamp': int(time.time()),
        'network': 'gnosis',
        'contract_name': 'FutarchyArbitrageExecutorV2'
    }
    
    with open('deployment_info_v2.json', 'w') as f:
        json.dump(deployment_info, f, indent=2)
    
    print(f"\n💾 Deployment info saved to deployment_info_v2.json")
    print(f"📝 Add to your .env file:")
    print(f"ARBITRAGE_EXECUTOR_V2_ADDRESS={contract_address}")
    
    return deployment_info

def encode_constructor_args(deployer_address):
    """Encode constructor arguments for verification."""
    # Constructor takes one address parameter
    encoded = encode(['address'], [deployer_address])
    return encoded.hex()

def verify_contract(contract_address, deployer_address, source_code):
    """Verify contract on Gnosisscan."""
    print(f"\n🔍 Verifying contract on Gnosisscan...")
    
    api_key = os.environ.get('GNOSISSCAN_API_KEY', '')
    if not api_key:
        print("⚠️  GNOSISSCAN_API_KEY not set. Skipping automatic verification.")
        print_manual_verification_instructions(contract_address, deployer_address)
        return False
    
    # Prepare verification data
    verification_data = {
        'apikey': api_key,
        'module': 'contract',
        'action': 'verifysourcecode',
        'contractaddress': contract_address,
        'sourceCode': source_code,
        'codeformat': 'solidity-single-file',
        'contractname': 'FutarchyArbitrageExecutorV2',
        'compilerversion': 'v0.8.19+commit.7dd6d404',
        'optimizationUsed': '1',
        'runs': '200',
        'evmversion': 'paris',
        'constructorArguements': encode_constructor_args(deployer_address)
    }
    
    try:
        # Submit verification
        api_url = "https://api.gnosisscan.io/api"
        response = requests.post(api_url, data=verification_data)
        result = response.json()
        
        if result['status'] != '1':
            print(f"❌ Verification submission failed: {result.get('result', 'Unknown error')}")
            print_manual_verification_instructions(contract_address, deployer_address)
            return False
        
        guid = result['result']
        print(f"📤 Verification submitted successfully! GUID: {guid}")
        
        # Check verification status
        print("⏳ Checking verification status...")
        for i in range(12):  # Check for up to 1 minute
            time.sleep(5)
            
            check_data = {
                'apikey': api_key,
                'module': 'contract',
                'action': 'checkverifystatus',
                'guid': guid
            }
            
            check_response = requests.get(api_url, params=check_data)
            check_result = check_response.json()
            
            if check_result['status'] == '1':
                print(f"✅ Contract verified successfully!")
                print(f"🔗 View verified contract: https://gnosisscan.io/address/{contract_address}#code")
                return True
            elif 'Pending' in check_result.get('result', ''):
                print(f"⏳ Status: {check_result['result']}")
            else:
                print(f"❌ Verification failed: {check_result.get('result', 'Unknown')}")
                print_manual_verification_instructions(contract_address, deployer_address)
                return False
        
        print("⏰ Verification timeout. Check status manually.")
        print_manual_verification_instructions(contract_address, deployer_address)
        return False
        
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        print_manual_verification_instructions(contract_address, deployer_address)
        return False

def print_manual_verification_instructions(contract_address, deployer_address):
    """Print manual verification instructions."""
    print(f"\n{'='*60}")
    print("MANUAL VERIFICATION INSTRUCTIONS")
    print(f"{'='*60}")
    print(f"1. Go to: https://gnosisscan.io/address/{contract_address}#code")
    print("2. Click 'Verify and Publish'")
    print("3. Fill in:")
    print("   - Compiler Type: Solidity (Single file)")
    print("   - Compiler Version: v0.8.19+commit.7dd6d404")
    print("   - License: MIT")
    print("4. Paste the contract source code")
    print(f"5. Constructor Arguments: {deployer_address[2:]}")
    print("6. Optimization: Yes, 200 runs")
    print(f"{'='*60}")

def main():
    """Main deployment and verification flow."""
    print("🚀 FutarchyArbitrageExecutorV2 - Deploy & Verify")
    print("=" * 50)
    
    # Load environment
    w3, account = load_environment()
    
    # Compile contract
    bytecode, abi, source_code = compile_contract()
    
    # Deploy contract
    contract_address, receipt, tx_hash = deploy_contract(w3, account, bytecode, abi)
    
    # Save deployment info
    deployment_info = save_deployment_info(contract_address, receipt, tx_hash, account, abi)
    
    # Verify contract
    verification_success = verify_contract(contract_address, account.address, source_code)
    
    # Final summary
    print(f"\n{'='*60}")
    print("DEPLOYMENT COMPLETE")
    print(f"{'='*60}")
    print(f"✅ Contract Address: {contract_address}")
    print(f"✅ Transaction: https://gnosisscan.io/tx/{tx_hash.hex()}")
    print(f"{'✅' if verification_success else '⚠️ '} Verification: {'Success' if verification_success else 'Manual required'}")
    print(f"💾 Deployment info: deployment_info_v2.json")
    
    print(f"\n🔧 NEXT STEPS:")
    print(f"1. Test deployment: python test_deployed_v2.py")
    print(f"2. Update .env: ARBITRAGE_EXECUTOR_V2_ADDRESS={contract_address}")
    print(f"3. Begin arbitrage testing")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()