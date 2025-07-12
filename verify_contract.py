#!/usr/bin/env python3
import json
import os
import time
import requests
from eth_abi import encode

def verify_contract_on_gnosisscan(contract_address, source_code, constructor_args, contract_name="FutarchyArbitrageExecutor"):
    """Verify the contract on Gnosisscan"""
    print(f"\nVerifying contract on Gnosisscan...")
    print(f"Contract address: {contract_address}")
    
    # Gnosisscan API endpoint
    api_url = "https://api.gnosisscan.io/api"
    
    # Get API key from environment
    api_key = os.getenv('GNOSISSCAN_API_KEY')
    
    if not api_key:
        print("\nError: GNOSISSCAN_API_KEY not set!")
        print("Please set it with: export GNOSISSCAN_API_KEY=<your-api-key>")
        print("You can get an API key from: https://gnosisscan.io/myapikey")
        return False
    
    # Encode constructor arguments
    constructor_args_encoded = encode(
        ['address', 'address', 'address', 'address'],
        [
            constructor_args['owner'],
            constructor_args['futarchy_router'],
            constructor_args['swapr_router'],
            constructor_args['balancer_vault']
        ]
    ).hex()
    
    print(f"\nConstructor arguments encoded: {constructor_args_encoded}")
    
    # Prepare verification parameters
    params = {
        'apikey': api_key,
        'module': 'contract',
        'action': 'verifysourcecode',
        'contractaddress': contract_address,
        'sourceCode': source_code,
        'codeformat': 'solidity-single-file',
        'contractname': contract_name,
        'compilerversion': 'v0.8.19+commit.7dd6d404',
        'optimizationUsed': 0,
        'runs': 200,
        'constructorArguements': constructor_args_encoded,  # Note: Gnosisscan uses this spelling
        'evmversion': 'paris',
        'licenseType': 1  # MIT License
    }
    
    print("\nSubmitting verification request...")
    
    # Submit verification request
    response = requests.post(api_url, data=params)
    
    if response.status_code == 200:
        result = response.json()
        if result['status'] == '1':
            guid = result['result']
            print(f"Verification request submitted successfully!")
            print(f"GUID: {guid}")
            
            # Check verification status
            check_params = {
                'apikey': api_key,
                'module': 'contract',
                'action': 'checkverifystatus',
                'guid': guid
            }
            
            print("\nChecking verification status...")
            
            # Poll for verification result
            for i in range(20):  # Check for up to 100 seconds
                time.sleep(5)
                check_response = requests.get(api_url, params=check_params)
                if check_response.status_code == 200:
                    check_result = check_response.json()
                    if check_result['status'] == '1':
                        print(f"\n✅ Contract verified successfully!")
                        print(f"View on Gnosisscan: https://gnosisscan.io/address/{contract_address}#code")
                        return True
                    elif 'Pending' in check_result.get('result', ''):
                        print(f"Status: {check_result.get('result', 'Pending...')}")
                    else:
                        print(f"\n❌ Verification failed: {check_result.get('result', 'Unknown error')}")
                        return False
                else:
                    print(f"Failed to check status: HTTP {check_response.status_code}")
                
            print("\n⏱️  Verification timeout - please check manually on Gnosisscan")
            print(f"URL: https://gnosisscan.io/address/{contract_address}#code")
            return False
        else:
            print(f"\n❌ Verification submission failed: {result.get('result', 'Unknown error')}")
            return False
    else:
        print(f"\n❌ Failed to submit verification: HTTP {response.status_code}")
        print(f"Response: {response.text}")
        return False

def main():
    # Check if deployment info exists
    if not os.path.exists('deployment_info.json'):
        print("Error: deployment_info.json not found!")
        print("Please run deploy_arbitrage_executor.py first.")
        return
    
    # Load deployment info
    with open('deployment_info.json', 'r') as f:
        deployment_info = json.load(f)
    
    contract_address = deployment_info['address']
    source_code = deployment_info.get('source_code')
    constructor_args = deployment_info.get('constructor_args')
    
    if not source_code:
        # If source code not in deployment info, read from file
        with open('contracts/FutarchyArbitrageExecutor.sol', 'r') as f:
            source_code = f.read()
    
    if not constructor_args:
        # Use the values from the deployment we know about
        constructor_args = {
            'owner': '0xaA3C6959d7990CF2a50d580b1F1c2a26995573c9',
            'futarchy_router': '0x7495a583ba85875d59407781b4958ED6e0E1228f',
            'swapr_router': '0xfFB643E73f280B97809A8b41f7232AB401a04ee1',
            'balancer_vault': '0xBA12222222228d8Ba445958a75a0704d566BF2C8'
        }
        print("Using constructor arguments from known deployment:")
    
    # Verify the contract
    verify_contract_on_gnosisscan(contract_address, source_code, constructor_args)

if __name__ == "__main__":
    main()