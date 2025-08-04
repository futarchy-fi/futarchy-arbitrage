#!/usr/bin/env python3
"""
Verify FutarchyBatchExecutorMinimal contract on Gnosisscan.

This script prepares the verification data for the contract.
"""

import json
import os

CONTRACT_ADDRESS = "0x65eb5a03635c627a0f254707712812B234753F31"

def generate_verification_data():
    """Generate data needed for Gnosisscan verification."""
    
    print("=== Contract Verification Data ===\n")
    print(f"Contract Address: {CONTRACT_ADDRESS}")
    print(f"Network: Gnosis Chain")
    print(f"Verification URL: https://gnosisscan.io/address/{CONTRACT_ADDRESS}#code")
    
    print("\n=== Source Code ===")
    print("File: contracts/FutarchyBatchExecutorMinimal.sol")
    
    print("\n=== Compiler Settings ===")
    compiler_settings = {
        "version": "0.8.17",
        "optimizer": {
            "enabled": True,
            "runs": 200,
            "details": {
                "yul": False,
                "yulDetails": {
                    "stackAllocation": False,
                    "optimizerSteps": ""
                }
            }
        },
        "evmVersion": "london"
    }
    
    print(json.dumps(compiler_settings, indent=2))
    
    print("\n=== Constructor Arguments ===")
    print("None (no constructor parameters)")
    
    print("\n=== Contract Source ===")
    source_path = os.path.join(os.path.dirname(__file__), '..', 'contracts', 'FutarchyBatchExecutorMinimal.sol')
    try:
        with open(source_path, 'r') as f:
            print(f.read())
    except:
        print("Could not read source file")
    
    print("\n=== Verification Steps ===")
    print("1. Go to https://gnosisscan.io/address/" + CONTRACT_ADDRESS + "#code")
    print("2. Click 'Verify and Publish'")
    print("3. Select:")
    print("   - Compiler Type: Solidity (Single file)")
    print("   - Compiler Version: v0.8.17+commit.8df45f5f")
    print("   - License: MIT")
    print("4. Paste the contract source code")
    print("5. Set optimization: Enabled with 200 runs")
    print("6. Expand 'Advanced' and disable Yul optimizer")
    print("7. Submit for verification")
    
    print("\n=== Alternative: Use Hardhat/Foundry ===")
    print("You can also verify using command line tools:")
    print("hardhat verify --network gnosis " + CONTRACT_ADDRESS)
    print("or")
    print("forge verify-contract " + CONTRACT_ADDRESS + " FutarchyBatchExecutorMinimal --chain gnosis")


def check_bytecode():
    """Check the deployed bytecode."""
    print("\n=== Bytecode Check ===")
    
    # This would need web3 connection
    print("To verify bytecode matches:")
    print("1. Get deployed bytecode from Gnosisscan")
    print("2. Compile contract locally with same settings")
    print("3. Compare runtime bytecode (excluding constructor)")


def main():
    """Generate verification data."""
    print("FutarchyBatchExecutorMinimal Contract Verification")
    print("=" * 50)
    
    generate_verification_data()
    check_bytecode()
    
    print("\n=== Next Steps ===")
    print("1. Verify the contract on Gnosisscan using the data above")
    print("2. Once verified, check that the source code matches what we expect")
    print("3. Confirm there are no 0xEF opcodes in the verified bytecode")


if __name__ == "__main__":
    main()