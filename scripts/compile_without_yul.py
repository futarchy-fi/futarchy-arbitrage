#!/usr/bin/env python3
"""
Compile Solidity contracts with Yul optimizer disabled to avoid 0xEF opcodes.

This script uses the Solidity compiler directly with standard JSON input
to have fine-grained control over optimizer settings.
"""

import subprocess
import json
import sys
from pathlib import Path
from typing import Dict, Any

def check_solc_version():
    """Check if solc is available and get version."""
    try:
        result = subprocess.run(['solc', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Found solc: {result.stdout.split()[2]}")
            return True
    except FileNotFoundError:
        pass
    
    print("❌ solc not found. Please install it:")
    print("   brew install solidity  # macOS")
    print("   apt-get install solc   # Ubuntu")
    return False


def compile_contract(contract_path: Path, contract_name: str) -> Dict[str, Any]:
    """
    Compile a Solidity contract with Yul optimizer disabled.
    
    Args:
        contract_path: Path to the Solidity source file
        contract_name: Name of the contract to extract
    
    Returns:
        Compiled contract data with ABI and bytecode
    """
    if not contract_path.exists():
        raise FileNotFoundError(f"Contract not found: {contract_path}")
    
    # Read contract source
    with open(contract_path, 'r') as f:
        source_code = f.read()
    
    # Update pragma to match available compiler
    # This is safe because we're targeting 0.8.17+ features
    source_code = source_code.replace("pragma solidity 0.8.17;", "pragma solidity ^0.8.17;")
    
    # Create standard JSON input
    input_json = {
        "language": "Solidity",
        "sources": {
            contract_path.name: {
                "content": source_code
            }
        },
        "settings": {
            "optimizer": {
                "enabled": True,
                "runs": 200,
                "details": {
                    "yul": False,  # Critical: disable Yul optimizer
                    "peephole": True,
                    "jumpdestRemover": True,
                    "orderLiterals": True,
                    "deduplicate": True,
                    "cse": True,
                    "constantOptimizer": True
                }
            },
            "outputSelection": {
                "*": {
                    "*": ["abi", "evm.bytecode", "evm.deployedBytecode", "evm.gasEstimates"]
                }
            },
            "evmVersion": "paris"  # Gnosis Chain compatible
        }
    }
    
    # Run solc with standard JSON
    print(f"📦 Compiling {contract_name} with Yul optimizer disabled...")
    
    result = subprocess.run(
        ["solc", "--standard-json"],
        input=json.dumps(input_json),
        capture_output=True,
        text=True
    )
    
    # Parse output
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"❌ Failed to parse solc output: {result.stdout}")
        print(f"❌ Error: {result.stderr}")
        sys.exit(1)
    
    # Check for errors
    if "errors" in output:
        errors = [e for e in output["errors"] if e["severity"] == "error"]
        if errors:
            print("❌ Compilation errors:")
            for error in errors:
                print(f"   {error['message']}")
            sys.exit(1)
    
    # Extract contract data
    contracts = output.get("contracts", {})
    if contract_path.name not in contracts:
        print(f"❌ No output for {contract_path.name}")
        sys.exit(1)
    
    if contract_name not in contracts[contract_path.name]:
        print(f"❌ Contract {contract_name} not found in output")
        print(f"   Available: {list(contracts[contract_path.name].keys())}")
        sys.exit(1)
    
    contract_data = contracts[contract_path.name][contract_name]
    
    return {
        'abi': contract_data['abi'],
        'bytecode': contract_data['evm']['bytecode']['object'],
        'runtime_bytecode': contract_data['evm']['deployedBytecode']['object'],
        'gas_estimates': contract_data['evm'].get('gasEstimates', {})
    }


def check_for_ef_opcodes(bytecode: str, name: str) -> bool:
    """Check if bytecode contains 0xEF opcodes."""
    # Remove 0x prefix if present
    bytecode = bytecode.replace('0x', '')
    
    # Check for 0xEF at even positions (opcode positions)
    ef_positions = []
    for i in range(0, len(bytecode), 2):
        if bytecode[i:i+2].lower() == 'ef':
            ef_positions.append(i // 2)
    
    if ef_positions:
        print(f"❌ {name} contains 0xEF opcodes at byte positions: {ef_positions}")
        return False
    
    print(f"✅ {name} is clean - no 0xEF opcodes found")
    return True


def main():
    """Main function to compile and verify contracts."""
    if not check_solc_version():
        sys.exit(1)
    
    # Contracts to compile
    contracts = [
        ("contracts/FutarchyBatchExecutor.sol", "FutarchyBatchExecutor"),
        ("contracts/SimpleEIP7702Test.sol", "SimpleEIP7702Test")
    ]
    
    results = {}
    
    for contract_path, contract_name in contracts:
        print(f"\n{'='*60}")
        path = Path(contract_path)
        
        try:
            # Compile contract
            compiled = compile_contract(path, contract_name)
            
            # Check for 0xEF opcodes
            print(f"\n🔍 Checking {contract_name} bytecode...")
            deploy_clean = check_for_ef_opcodes(compiled['bytecode'], f"{contract_name} deployment bytecode")
            runtime_clean = check_for_ef_opcodes(compiled['runtime_bytecode'], f"{contract_name} runtime bytecode")
            
            # Store results
            results[contract_name] = {
                'compiled': compiled,
                'clean': deploy_clean and runtime_clean
            }
            
            # Save ABI
            abi_path = Path(f"src/config/abis/{contract_name}.json")
            abi_path.parent.mkdir(parents=True, exist_ok=True)
            with open(abi_path, 'w') as f:
                json.dump(compiled['abi'], f, indent=2)
            print(f"\n💾 Saved ABI to {abi_path}")
            
        except Exception as e:
            print(f"❌ Error compiling {contract_name}: {e}")
            results[contract_name] = {'clean': False}
    
    # Summary
    print(f"\n{'='*60}")
    print("📊 Summary:")
    all_clean = True
    for name, result in results.items():
        status = "✅ Clean" if result.get('clean', False) else "❌ Contains 0xEF"
        print(f"   {name}: {status}")
        all_clean = all_clean and result.get('clean', False)
    
    if all_clean:
        print("\n🎉 All contracts compiled successfully without 0xEF opcodes!")
        print("\nNext steps:")
        print("1. Deploy with: python -m src.setup.deploy_batch_executor")
        print("2. Verify with: python -m src.helpers.pectra_verifier")
    else:
        print("\n⚠️  Some contracts still contain 0xEF opcodes")
        print("Check the Yul optimizer settings or contract structure")
        sys.exit(1)


if __name__ == "__main__":
    main()