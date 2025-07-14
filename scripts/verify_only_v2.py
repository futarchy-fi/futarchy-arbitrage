#!/usr/bin/env python3
"""
Verify already deployed FutarchyArbitrageExecutorV2 contract on Gnosisscan.
"""
import os
import json
import time
import requests
from eth_abi import encode

def encode_constructor_args(deployer_address):
    """Encode constructor arguments for verification."""
    # Constructor takes one address parameter
    encoded = encode(['address'], [deployer_address])
    return encoded.hex()

def main():
    # Load deployment info
    try:
        with open('deployment_info_v2.json', 'r') as f:
            deployment_info = json.load(f)
    except FileNotFoundError:
        print("❌ deployment_info_v2.json not found")
        exit(1)
    
    contract_address = deployment_info['address']
    deployer_address = deployment_info['deployer']
    
    print(f"🔍 Verifying contract: {contract_address}")
    print(f"👤 Deployer: {deployer_address}")
    
    # Read contract source
    with open('contracts/FutarchyArbitrageExecutorV2.sol', 'r') as f:
        source_code = f.read()
    
    # Check API key
    api_key = os.environ.get('GNOSISSCAN_API_KEY', '')
    if not api_key:
        print("❌ GNOSISSCAN_API_KEY not set")
        print("Get API key from: https://gnosisscan.io/myapikey")
        exit(1)
    
    # Encode constructor arguments
    constructor_args = encode_constructor_args(deployer_address)
    print(f"🔧 Constructor args: {constructor_args}")
    
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
        'constructorArguements': constructor_args
    }
    
    # Submit verification
    print("\n📤 Submitting verification...")
    api_url = "https://api.gnosisscan.io/api"
    
    try:
        response = requests.post(api_url, data=verification_data)
        result = response.json()
        
        if result['status'] != '1':
            print(f"❌ Verification failed: {result.get('result', 'Unknown error')}")
            print(f"Response: {result}")
            exit(1)
        
        guid = result['result']
        print(f"✅ Submitted! GUID: {guid}")
        
        # Check status
        print("⏳ Checking status...")
        for i in range(12):
            time.sleep(5)
            
            check_data = {
                'apikey': api_key,
                'module': 'contract',
                'action': 'checkverifystatus',
                'guid': guid
            }
            
            check_response = requests.get(api_url, params=check_data)
            check_result = check_response.json()
            
            print(f"Status: {check_result.get('result', 'Unknown')}")
            
            if check_result['status'] == '1':
                print(f"\n✅ Contract verified successfully!")
                print(f"🔗 View: https://gnosisscan.io/address/{contract_address}#code")
                break
            elif 'fail' in check_result.get('result', '').lower():
                print(f"❌ Verification failed: {check_result.get('result')}")
                break
                
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()