#!/usr/bin/env python3
"""
Deploy FutarchyArbExecutorV4 with viaIR compilation to handle stack depth.
"""

import json
import os
from pathlib import Path
from web3 import Web3
from eth_account import Account
from solcx import compile_standard, install_solc
from datetime import datetime

# Load environment
RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

# Allow overriding from env; default to 0.8.24 (minimum required for V4)
SOLC_VERSION = os.getenv("SOLC_VERSION", "0.8.24")

# Ensure minimum version for stack depth handling
from packaging import version
if version.parse(SOLC_VERSION) < version.parse("0.8.24"):
    print(f"Warning: Solidity {SOLC_VERSION} is too old for V4. Using 0.8.24 instead.")
    SOLC_VERSION = "0.8.24"

install_solc(SOLC_VERSION)

if not RPC_URL or not PRIVATE_KEY:
    raise ValueError("RPC_URL and PRIVATE_KEY must be set")

# Connect to Gnosis
w3 = Web3(Web3.HTTPProvider(RPC_URL))
account = Account.from_key(PRIVATE_KEY)

print(f"Deploying from: {account.address}")
print(f"Balance: {w3.from_wei(w3.eth.get_balance(account.address), 'ether')} xDAI")

# Read contract source
contract_path = Path(__file__).parent.parent / "contracts" / "FutarchyArbExecutorV4.sol"
with open(contract_path, "r") as f:
    source_code = f.read()

# Compile with viaIR to handle stack depth
print("Compiling FutarchyArbExecutorV4 with viaIR...")
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
            "viaIR": True,  # Enable IR pipeline to handle stack depth
            "outputSelection": {
                "*": {
                    "*": ["abi", "metadata", "evm.bytecode", "evm.sourceMap"]
                }
            }
        }
    },
    solc_version=SOLC_VERSION
)

# Extract contract data
contract = compiled["contracts"]["FutarchyArbExecutorV4.sol"]["FutarchyArbExecutorV4"]
bytecode = contract["evm"]["bytecode"]["object"]
abi = contract["abi"]

print(f"Bytecode size: {len(bytecode) // 2} bytes")

# Deploy contract with runner address
RUNNER_ADDRESS = os.getenv("RUNNER_ADDRESS", account.address)
print(f"Runner: {RUNNER_ADDRESS}")

Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
constructor_tx = Contract.constructor(RUNNER_ADDRESS).build_transaction({
    "from": account.address,
    "gas": 3000000,
    "gasPrice": w3.eth.gas_price,
    "nonce": w3.eth.get_transaction_count(account.address),
})

# Sign and send
signed = account.sign_transaction(constructor_tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"Deploy tx sent: {tx_hash.hex()}")

# Wait for receipt
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
contract_address = receipt.contractAddress

print(f"\n✅ FutarchyArbExecutorV4 deployed to: {contract_address}")
print(f"Gas used: {receipt.gasUsed:,}")
print(f"Tx: https://gnosisscan.io/tx/{tx_hash.hex()}")

# Save deployment info
deployment_info = {
    "address": contract_address,
    "deployer": account.address,
    "tx_hash": tx_hash.hex(),
    "gas_used": receipt.gasUsed,
    "timestamp": datetime.now().isoformat(),
    "abi": abi
}

deployment_file = f"deployment_executor_v4_{int(datetime.now().timestamp())}.json"
with open(deployment_file, "w") as f:
    json.dump(deployment_info, f, indent=2)

print(f"\nDeployment info saved to: {deployment_file}")

# Update .env file with new executor address
env_file = Path(".env." + os.getenv("FUTARCHY_PROPOSAL_ADDRESS", ""))
if env_file.exists():
    print(f"\nTo update {env_file}, add:")
    print(f"export FUTARCHY_EXECUTOR_ADDRESS={contract_address}")
else:
    print(f"\nAdd to your .env file:")
    print(f"export FUTARCHY_EXECUTOR_ADDRESS={contract_address}")