#!/usr/bin/env python3
"""
Verify FutarchyArbitrageExecutorV2 contract on Gnosisscan.
"""
import os
import json
import time
import requests
from web3 import Web3

# Load deployment info
try:
    with open('deployment_info_v2.json', 'r') as f:
        deployment_info = json.load(f)
except FileNotFoundError:
    print("Error: deployment_info_v2.json not found. Deploy contract first.")
    exit(1)

contract_address = deployment_info['address']
print(f"Verifying contract at: {contract_address}")

# Read contract source
with open('contracts/FutarchyArbitrageExecutorV2.sol', 'r') as f:
    source_code = f.read()

# Gnosisscan API endpoint
api_key = os.environ.get('GNOSISSCAN_API_KEY', '')
if not api_key:
    print("Warning: GNOSISSCAN_API_KEY not set.")
    print("Get API key from: https://gnosisscan.io/myapikey")
    print("\nSkipping automatic verification. See manual instructions below.")

# Prepare verification data
verification_data = {
    'apikey': api_key,
    'module': 'contract',
    'action': 'verifysourcecode',
    'contractaddress': contract_address,
    'sourceCode': source_code,
    'codeformat': 'solidity-single-file',
    'contractname': 'FutarchyArbitrageExecutorV2',
    'compilerversion': 'v0.8.19+commit.7dd6d404',  # Match deployment
    'optimizationUsed': '1',
    'runs': '200',
    'evmversion': 'paris',  # or 'london' depending on Gnosis
    'constructorArguements': deployment_info['deployer'][2:]  # Remove 0x prefix
}

# Submit verification
print("\nSubmitting contract for verification...")
api_url = "https://api.gnosisscan.io/api"

try:
    response = requests.post(api_url, data=verification_data)
    result = response.json()
    
    if result['status'] == '1':
        guid = result['result']
        print(f"✅ Verification submitted successfully!")
        print(f"GUID: {guid}")
        
        # Check verification status
        print("\nChecking verification status...")
        for i in range(10):
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
                print(f"\n✅ Contract verified successfully!")
                print(f"View on Gnosisscan: https://gnosisscan.io/address/{contract_address}#code")
                break
            elif 'Pending' in check_result.get('result', ''):
                print(f"Status: {check_result['result']}")
            else:
                print(f"Status: {check_result.get('result', 'Unknown')}")
                
    else:
        print(f"❌ Verification failed: {result.get('result', 'Unknown error')}")
        
except Exception as e:
    print(f"❌ Error during verification: {e}")

# Manual verification instructions
print(f"\n{'='*50}")
print("MANUAL VERIFICATION")
print(f"{'='*50}")
print("If automatic verification fails, verify manually:")
print(f"1. Go to: https://gnosisscan.io/address/{contract_address}#code")
print("2. Click 'Verify and Publish'")
print("3. Select:")
print("   - Compiler Type: Solidity (Single file)")
print("   - Compiler Version: v0.8.19+commit.7dd6d404")
print("   - License: MIT")
print("4. Paste contract source code")
print(f"5. Constructor Arguments: {deployment_info['deployer'][2:]}")
print("6. Optimization: Yes, 200 runs")
print(f"{'='*50}")