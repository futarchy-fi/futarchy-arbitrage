#!/usr/bin/env python3
import json
import os
import time
import requests
from decimal import Decimal
from web3 import Web3
from solcx import compile_files, install_solc, get_solc_version

# Install Solidity compiler version
install_solc('0.8.19')

def compile_contract():
    """Compile the FutarchyArbitrageExecutor contract"""
    print("Compiling FutarchyArbitrageExecutor.sol...")
    
    compiled = compile_files(
        ['contracts/FutarchyArbitrageExecutor.sol'],
        output_values=['abi', 'bin', 'metadata'],
        solc_version='0.8.19',
        optimize=True,
        optimize_runs=200
    )
    
    contract_key = 'contracts/FutarchyArbitrageExecutor.sol:FutarchyArbitrageExecutor'
    contract = compiled[contract_key]
    
    # Also compile with standard JSON format for verification
    with open('contracts/FutarchyArbitrageExecutor.sol', 'r') as f:
        source_code = f.read()
    
    return contract['abi'], contract['bin'], source_code, contract.get('metadata', '')

def deploy_contract(w3, account, private_key, futarchy_router, swapr_router, balancer_vault):
    """Deploy the FutarchyArbitrageExecutor contract"""
    
    # Compile contract
    abi, bytecode, source_code, metadata = compile_contract()
    
    # Create contract instance
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    
    # Build constructor transaction
    constructor_tx = Contract.constructor(
        account,  # owner
        futarchy_router,
        swapr_router,
        balancer_vault
    ).build_transaction({
        'from': account,
        'nonce': w3.eth.get_transaction_count(account),
        'gas': 3000000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    # Sign and send transaction
    signed_tx = w3.eth.account.sign_transaction(constructor_tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    print(f"Deployment transaction sent: {tx_hash.hex()}")
    
    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    if receipt.status == 1:
        print(f"Contract deployed successfully at: {receipt.contractAddress}")
        
        # Save deployment info
        deployment_info = {
            'address': receipt.contractAddress,
            'abi': abi,
            'tx_hash': tx_hash.hex(),
            'block_number': receipt.blockNumber,
            'deployer': account,
            'source_code': source_code,
            'constructor_args': {
                'owner': account,
                'futarchy_router': futarchy_router,
                'swapr_router': swapr_router,
                'balancer_vault': balancer_vault
            }
        }
        
        with open('deployment_info.json', 'w') as f:
            json.dump(deployment_info, f, indent=2)
            
        return receipt.contractAddress, abi, source_code
    else:
        raise Exception("Deployment failed")

def verify_contract_on_gnosisscan(contract_address, source_code, constructor_args, contract_name="FutarchyArbitrageExecutor"):
    """Verify the contract on Gnosisscan"""
    print(f"\nVerifying contract on Gnosisscan...")
    
    # Gnosisscan API endpoint
    api_url = "https://api.gnosisscan.io/api"
    
    # Get API key from environment or use a placeholder
    api_key = os.getenv('GNOSISSCAN_API_KEY', 'YourGnosisscanAPIKey')
    
    if api_key == 'YourGnosisscanAPIKey':
        print("Warning: GNOSISSCAN_API_KEY not set. Please set it to verify the contract.")
        print("You can get an API key from: https://gnosisscan.io/myapikey")
        return False
    
    # Encode constructor arguments
    # Constructor takes 4 addresses: owner, futarchyRouter, swaprRouter, balancerVault
    from eth_abi import encode
    constructor_args_encoded = encode(
        ['address', 'address', 'address', 'address'],
        [
            constructor_args['owner'],
            constructor_args['futarchy_router'],
            constructor_args['swapr_router'],
            constructor_args['balancer_vault']
        ]
    ).hex()
    
    # Prepare verification parameters
    params = {
        'apikey': api_key,
        'module': 'contract',
        'action': 'verifysourcecode',
        'contractaddress': contract_address,
        'sourceCode': source_code,
        'codeformat': 'solidity-single-file',
        'contractname': contract_name,
        'compilerversion': 'v0.8.19+commit.7dd6d404',  # Specific compiler version
        'optimizationUsed': 1,
        'runs': 200,
        'constructorArguements': constructor_args_encoded,  # Note: Gnosisscan uses this spelling
        'evmversion': 'paris',  # Latest EVM version supported by 0.8.19
        'licenseType': 1  # 1 = MIT License
    }
    
    # Submit verification request
    response = requests.post(api_url, data=params)
    
    if response.status_code == 200:
        result = response.json()
        if result['status'] == '1':
            guid = result['result']
            print(f"Verification request submitted. GUID: {guid}")
            
            # Check verification status
            check_params = {
                'apikey': api_key,
                'module': 'contract',
                'action': 'checkverifystatus',
                'guid': guid
            }
            
            # Poll for verification result
            for i in range(10):
                time.sleep(5)  # Wait 5 seconds between checks
                check_response = requests.get(api_url, params=check_params)
                if check_response.status_code == 200:
                    check_result = check_response.json()
                    if check_result['status'] == '1':
                        print(f"Contract verified successfully!")
                        print(f"View on Gnosisscan: https://gnosisscan.io/address/{contract_address}#code")
                        return True
                    elif 'Pending' not in check_result.get('result', ''):
                        print(f"Verification failed: {check_result.get('result', 'Unknown error')}")
                        return False
                
            print("Verification timeout - please check manually on Gnosisscan")
            return False
        else:
            print(f"Verification submission failed: {result.get('result', 'Unknown error')}")
            return False
    else:
        print(f"Failed to submit verification: HTTP {response.status_code}")
        return False

def main():
    # Load environment variables
    rpc_url = os.getenv('RPC_URL')
    private_key = os.getenv('PRIVATE_KEY')
    futarchy_router = os.getenv('FUTARCHY_ROUTER_ADDRESS')
    swapr_router = os.getenv('SWAPR_ROUTER_ADDRESS', '0xE43ca1Dee3F0fc1e2df73A0745674545F11A59F5')  # Default Swapr router on Gnosis
    balancer_vault = os.getenv('BALANCER_VAULT_ADDRESS', '0xBA12222222228d8Ba445958a75a0704d566BF2C8')  # Default Balancer Vault
    
    if not all([rpc_url, private_key, futarchy_router]):
        raise ValueError("Missing required environment variables: RPC_URL, PRIVATE_KEY, FUTARCHY_ROUTER_ADDRESS")
    
    # Connect to network
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise Exception("Failed to connect to network")
    
    print(f"Connected to network: Chain ID {w3.eth.chain_id}")
    
    # Get account from private key
    account = w3.eth.account.from_key(private_key)
    print(f"Deploying from account: {account.address}")
    
    # Check balance
    balance = w3.eth.get_balance(account.address)
    print(f"Account balance: {Web3.from_wei(balance, 'ether')} xDAI")
    
    if balance == 0:
        raise Exception("Account has no balance for deployment")
    
    # Deploy contract
    contract_address, abi, source_code = deploy_contract(
        w3,
        account.address,
        private_key,
        futarchy_router,
        swapr_router,
        balancer_vault
    )
    
    print("\nDeployment complete!")
    print(f"Contract address: {contract_address}")
    print("Deployment info saved to deployment_info.json")
    
    # Verify deployment
    contract = w3.eth.contract(address=contract_address, abi=abi)
    print(f"\nVerifying deployment...")
    print(f"Owner: {contract.functions.owner().call()}")
    print(f"Futarchy Router: {contract.functions.futarchyRouter().call()}")
    print(f"Swapr Router: {contract.functions.swaprRouter().call()}")
    print(f"Balancer Vault: {contract.functions.balancerVault().call()}")
    
    # Verify on Gnosisscan
    constructor_args = {
        'owner': account.address,
        'futarchy_router': futarchy_router,
        'swapr_router': swapr_router,
        'balancer_vault': balancer_vault
    }
    
    verify_contract_on_gnosisscan(contract_address, source_code, constructor_args)

if __name__ == "__main__":
    main()