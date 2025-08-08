#!/usr/bin/env python3
"""
Verify FutarchyArbExecutorV4 on Gnosisscan.
"""

import os
import json
import time
import requests
from pathlib import Path
from solcx import compile_standard, install_solc

# Contract address (V4 deployed)
CONTRACT_ADDRESS = "0xe18B6d168A8766a84612571502c0F8fd4391672c"

# Gnosis Chain ID
CHAIN_ID = 100

# Gnosisscan API (uses same format as Etherscan)
GNOSISSCAN_API_URL = "https://api.gnosisscan.io/api"
GNOSISSCAN_API_KEY = os.getenv("GNOSISSCAN_API_KEY", "")

# Solidity version used for deployment
SOLC_VERSION = "0.8.24"
install_solc(SOLC_VERSION)

print(f"Verifying FutarchyArbExecutorV4 at {CONTRACT_ADDRESS}")

# Read contract source
contract_path = Path(__file__).parent.parent / "contracts" / "FutarchyArbExecutorV4.sol"
with open(contract_path, "r") as f:
    source_code = f.read()

print(f"Contract source loaded: {len(source_code)} chars")

# Compile to get exact bytecode
print(f"Compiling with Solidity {SOLC_VERSION} (viaIR enabled)...")
compiled = compile_standard(
    {
        "language": "Solidity",
        "sources": {
            "FutarchyArbExecutorV4.sol": {
                "content": source_code
            }
        },
        "settings": {
            "optimizer": {
                "enabled": True,
                "runs": 200
            },
            "viaIR": True,  # Must match deployment
            "outputSelection": {
                "*": {
                    "*": ["abi", "metadata", "evm.bytecode", "evm.deployedBytecode"]
                }
            }
        }
    },
    solc_version=SOLC_VERSION
)

contract = compiled["contracts"]["FutarchyArbExecutorV4.sol"]["FutarchyArbExecutorV4"]
bytecode = contract["evm"]["bytecode"]["object"]
deployed_bytecode = contract["evm"]["deployedBytecode"]["object"]
abi = json.dumps(contract["abi"])
metadata = contract["metadata"]

print(f"Bytecode size: {len(bytecode) // 2} bytes")
print(f"Deployed bytecode size: {len(deployed_bytecode) // 2} bytes")

# Prepare verification payload
# Using "standard-json-input" format for complex contracts
standard_input = json.dumps({
    "language": "Solidity",
    "sources": {
        "FutarchyArbExecutorV4.sol": {
            "content": source_code
        }
    },
    "settings": {
        "optimizer": {
            "enabled": True,
            "runs": 200
        },
        "viaIR": True,
        "outputSelection": {
            "*": {
                "*": ["abi", "evm.bytecode", "evm.deployedBytecode"]
            }
        }
    }
})

# Prepare form data for Gnosisscan
verify_data = {
    "apikey": GNOSISSCAN_API_KEY,
    "module": "contract",
    "action": "verifysourcecode",
    "contractaddress": CONTRACT_ADDRESS,
    "sourceCode": standard_input,
    "codeformat": "solidity-standard-json-input",
    "contractname": "FutarchyArbExecutorV4.sol:FutarchyArbExecutorV4",
    "compilerversion": f"v{SOLC_VERSION}",
    "optimizationUsed": "1",
    "runs": "200",
    "constructorArguements": "",  # No constructor args
}

if not GNOSISSCAN_API_KEY:
    print("\n⚠️  No GNOSISSCAN_API_KEY found in environment.")
    print("You can verify manually at: https://gnosisscan.io/verifyContract")
    print("\nVerification parameters:")
    print(f"  Contract Address: {CONTRACT_ADDRESS}")
    print(f"  Compiler Version: v{SOLC_VERSION}")
    print(f"  Optimization: Yes, 200 runs")
    print(f"  viaIR: Enabled")
    print(f"  Contract Name: FutarchyArbExecutorV4")
    
    # Save verification data for manual submission
    verification_file = "verification_data_v4.json"
    with open(verification_file, "w") as f:
        json.dump({
            "address": CONTRACT_ADDRESS,
            "sourceCode": source_code,
            "standardInput": standard_input,
            "compiler": f"v{SOLC_VERSION}",
            "optimization": True,
            "runs": 200,
            "viaIR": True,
            "abi": contract["abi"],
        }, f, indent=2)
    print(f"\nVerification data saved to: {verification_file}")
    
else:
    print(f"\n🚀 Submitting verification to Gnosisscan...")
    
    try:
        response = requests.post(GNOSISSCAN_API_URL, data=verify_data)
        result = response.json()
        
        if result.get("status") == "1":
            guid = result.get("result")
            print(f"✅ Verification request submitted successfully!")
            print(f"   GUID: {guid}")
            
            # Check verification status
            print("\n⏳ Checking verification status...")
            for i in range(10):
                time.sleep(3)
                
                check_data = {
                    "apikey": GNOSISSCAN_API_KEY,
                    "module": "contract",
                    "action": "checkverifystatus",
                    "guid": guid,
                }
                
                check_response = requests.get(GNOSISSCAN_API_URL, params=check_data)
                check_result = check_response.json()
                
                if check_result.get("status") == "1":
                    print(f"✅ Contract verified successfully!")
                    print(f"   View at: https://gnosisscan.io/address/{CONTRACT_ADDRESS}#code")
                    break
                elif "pending" in check_result.get("result", "").lower():
                    print(f"   Still pending... ({i+1}/10)")
                else:
                    print(f"   Status: {check_result.get('result', 'Unknown')}")
                    if "already verified" in check_result.get("result", "").lower():
                        print(f"✅ Contract is already verified!")
                        print(f"   View at: https://gnosisscan.io/address/{CONTRACT_ADDRESS}#code")
                        break
        else:
            print(f"❌ Verification request failed:")
            print(f"   {result.get('result', 'Unknown error')}")
            
    except Exception as e:
        print(f"❌ Error submitting verification: {e}")
        print("\nYou can verify manually at: https://gnosisscan.io/verifyContract")

print("\n📋 Contract Details:")
print(f"   Address: {CONTRACT_ADDRESS}")
print(f"   Compiler: v{SOLC_VERSION}")
print(f"   Optimization: Enabled (200 runs)")
print(f"   viaIR: Enabled")
print(f"   View: https://gnosisscan.io/address/{CONTRACT_ADDRESS}")