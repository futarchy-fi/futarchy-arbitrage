#!/usr/bin/env python3
"""
Deploy and verify PredictionArbExecutorV1 to Gnosis Chain.

Mirrors scripts/deploy_executor_v5.py flow:
 - Compile with solc (via IR, optimizer 200)
 - Deploy using PRIVATE_KEY from sourced .env.* file
 - Save deployment JSON with ABI to deployments/
 - Optionally verify on Gnosisscan if GNOSIS_SCAN_API_KEY is set

Usage:
  1) source your .env.* with RPC_URL and PRIVATE_KEY
  2) python3 scripts/deploy_prediction_arb_v1.py
"""

import json
import os
import subprocess
import time
import re
from datetime import datetime
from pathlib import Path

from web3 import Web3
from eth_account import Account


CONTRACT_SRC_PATH = Path("contracts/PredictionArbExecutorV1.sol")
BUILD_DIR = Path("build")
DEPLOYMENTS_DIR = Path("deployments")
GNOSISSCAN_API_URL = "https://api.gnosisscan.io/api"
SOLC_VERSION = os.getenv("SOLC_VERSION", "0.8.24")


def require_env(var: str) -> str:
    v = os.getenv(var)
    if not v:
        raise SystemExit(f"Missing required env var: {var}")
    return v


def _eip1559_fees(w3: Web3) -> dict:
    try:
        latest = w3.eth.get_block("latest")
        base_fee = latest.get("baseFeePerGas")
    except Exception:
        base_fee = None
    if base_fee is not None:
        tip = int(os.getenv("PRIORITY_FEE_WEI", "1"))
        mult = int(os.getenv("MAX_FEE_MULTIPLIER", "2"))
        max_fee = int(base_fee) * mult + tip
        return {"maxFeePerGas": int(max_fee), "maxPriorityFeePerGas": int(tip)}
    bump = int(os.getenv("MIN_GAS_PRICE_BUMP_WEI", "1"))
    return {"gasPrice": int(w3.eth.gas_price) + bump}


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def compile_with_solc() -> dict:
    """Compile the contract using solc (via IR) and return combined-json output dict."""
    print("Compiling PredictionArbExecutorV1 with solc (viaIR, runs=200)...")

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    DEPLOYMENTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        run([
            "solc",
            "--via-ir",
            "--abi",
            "--bin",
            str(CONTRACT_SRC_PATH),
            "--optimize",
            "--optimize-runs",
            "200",
            "-o",
            str(BUILD_DIR),
            "--overwrite",
        ])
    except subprocess.CalledProcessError as e:
        print("solc abi/bin compile failed:\n" + (e.stderr or ""))
        raise

    try:
        combined = run([
            "solc",
            "--via-ir",
            "--optimize",
            "--optimize-runs",
            "200",
            "--combined-json",
            "abi,bin,metadata,srcmap",
            str(CONTRACT_SRC_PATH),
        ]).stdout
    except subprocess.CalledProcessError as e:
        print("solc combined-json failed:\n" + (e.stderr or ""))
        raise

    return json.loads(combined)


def extract_contract_artifacts(combined_json: dict) -> tuple[str, list, str, str]:
    contracts = combined_json.get("contracts", {})
    wanted_key = None
    for k in contracts.keys():
        if k.endswith(":PredictionArbExecutorV1"):
            wanted_key = k
            break
    if not wanted_key:
        raise SystemExit("PredictionArbExecutorV1 not found in solc output")

    info = contracts[wanted_key]
    bytecode = info["bin"]
    abi = info["abi"]
    if not bytecode.startswith("0x"):
        bytecode = "0x" + bytecode
    return bytecode, abi, wanted_key, "PredictionArbExecutorV1"


def deploy(bytecode: str, abi: list) -> tuple[str, dict, str, str]:
    rpc_url = require_env("RPC_URL")
    private_key = require_env("PRIVATE_KEY")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise SystemExit("Failed to connect to RPC_URL")

    account = Account.from_key(private_key)
    chain_id = w3.eth.chain_id

    print(f"RPC: {rpc_url}")
    print(f"Chain ID: {chain_id}")
    print(f"Deployer: {account.address}")
    bal = w3.from_wei(w3.eth.get_balance(account.address), 'ether')
    print(f"Balance: {bal} xDAI")

    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    # No constructor args
    tx = Contract.constructor().build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": chain_id,
    })
    tx.update(_eip1559_fees(w3))

    # Estimate gas with a buffer
    try:
        gas_est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(gas_est * 1.2)
    except Exception as e:
        print(f"Gas estimation failed, using fallback: {e}")
        tx["gas"] = 1_800_000

    signed = account.sign_transaction(tx)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
    tx_hash = w3.eth.send_raw_transaction(raw)
    print(f"Deploy tx: {tx_hash.hex()}")
    print(f"Gnosisscan: https://gnosisscan.io/tx/{tx_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt.status != 1:
        raise SystemExit("Deployment failed (status != 1)")

    address = receipt.contractAddress
    print(f"Deployed PredictionArbExecutorV1 at: {address}")

    # Derive constructor args (none) from tx data
    full_data = tx["data"]
    code_no_0x = bytecode[2:] if bytecode.startswith("0x") else bytecode
    data_no_0x = full_data[2:] if full_data.startswith("0x") else full_data
    constructor_args_hex = data_no_0x[len(code_no_0x):]

    return address, receipt, tx_hash.hex(), constructor_args_hex


def save_deployment(address: str, receipt: dict, tx_hash: str, abi: list):
    info = {
        "address": address,
        "tx_hash": tx_hash,
        "gas_used": receipt.gasUsed,
        "block_number": receipt.blockNumber,
        "timestamp": datetime.now().isoformat(),
        "abi": abi,
        "network": "gnosis",
        "contract": "PredictionArbExecutorV1",
    }
    out = DEPLOYMENTS_DIR / f"deployment_prediction_arb_v1_{int(time.time())}.json"
    with open(out, "w") as f:
        json.dump(info, f, indent=2)
    print(f"Saved deployment info to {out}")


def make_standard_json_input() -> str:
    source_code = CONTRACT_SRC_PATH.read_text()
    std = {
        "language": "Solidity",
        "sources": {CONTRACT_SRC_PATH.name: {"content": source_code}},
        "settings": {
            "optimizer": {"enabled": True, "runs": 200},
            "viaIR": True,
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode", "evm.deployedBytecode"]}},
        },
    }
    return json.dumps(std)


def _solc_version_tag() -> str:
    try:
        out = subprocess.run(["solc", "--version"], check=True, capture_output=True, text=True).stdout
    except Exception:
        return f"v{SOLC_VERSION}"
    m = re.search(r"Version:\s*([0-9]+\.[0-9]+\.[0-9]+\+commit\.[0-9a-fA-F]{8})", out)
    if m:
        return f"v{m.group(1)}"
    m = re.search(r"version\s*([0-9]+\.[0-9]+\.[0-9]+\+commit\.[0-9a-fA-F]{8})", out)
    if m:
        return f"v{m.group(1)}"
    return f"v{SOLC_VERSION}"


def verify_on_gnosisscan(address: str, constructor_args_hex: str) -> None:
    api_key = os.getenv("GNOSIS_SCAN_API_KEY", os.getenv("GNOSISSCAN_API_KEY", ""))
    if not api_key:
        print("GNOSIS_SCAN_API_KEY not set; skipping automatic verification.")
        return

    compiler_tag = _solc_version_tag()
    print(f"Submitting verification to Gnosisscan with {compiler_tag}...")
    standard_input = make_standard_json_input()

    def submit_once():
        payload = {
            "apikey": api_key,
            "module": "contract",
            "action": "verifysourcecode",
            "contractaddress": address,
            "sourceCode": standard_input,
            "codeformat": "solidity-standard-json-input",
            "contractname": f"{CONTRACT_SRC_PATH.name}:PredictionArbExecutorV1",
            "compilerversion": compiler_tag,
            "optimizationUsed": "1",
            "runs": "200",
            "constructorArguements": constructor_args_hex,
        }
        import requests
        return requests.post(GNOSISSCAN_API_URL, data=payload).json()

    max_submit_retries = 12
    for attempt in range(1, max_submit_retries + 1):
        try:
            j = submit_once()
        except Exception as e:
            print(f"Verification submit error (attempt {attempt}/{max_submit_retries}): {e}")
            time.sleep(5)
            continue

        status = j.get("status")
        result = j.get("result", "")
        if status == "1":
            guid = result
            print(f"Verification GUID: {guid}")
            import requests
            for i in range(24):
                time.sleep(5)
                check = requests.get(GNOSISSCAN_API_URL, params={
                    "apikey": api_key,
                    "module": "contract",
                    "action": "checkverifystatus",
                    "guid": guid,
                }).json()
                c_status = (check or {}).get("status", "0")
                c_result = (check or {}).get("result", "")
                if c_status == "1":
                    print("Contract verified successfully!")
                    print(f"https://gnosisscan.io/address/{address}#code")
                    return
                if "pending" in str(c_result).lower():
                    print(f"Pending... ({i+1}/24)")
                    continue
                print(f"Verification status: {c_result}")
                if "already verified" in str(c_result).lower():
                    print("Already verified.")
                    print(f"https://gnosisscan.io/address/{address}#code")
                    return
                break
        else:
            msg = str(result)
            if "Unable to locate ContractCode" in msg or "Contract source code already verified" in msg:
                if "already verified" in msg.lower():
                    print("Already verified.")
                    print(f"https://gnosisscan.io/address/{address}#code")
                    return
                print(f"Gnosisscan not indexed yet (attempt {attempt}/{max_submit_retries}). Waiting...")
                time.sleep(10)
                continue
            print(f"Verification submit failed: {msg}")
            break


def main():
    combined = compile_with_solc()
    bytecode, abi, key, name = extract_contract_artifacts(combined)
    address, receipt, txh, ctor_args = deploy(bytecode, abi)
    save_deployment(address, receipt, txh, abi)
    verify_on_gnosisscan(address, ctor_args)


if __name__ == "__main__":
    main()

