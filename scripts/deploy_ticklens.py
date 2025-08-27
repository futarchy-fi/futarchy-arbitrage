#!/usr/bin/env python3
"""
Deploy the official Algebra TickLens (no modifications) to Gnosis using
the existing repo deploy style (Web3 + PRIVATE_KEY), sourcing ABI/bytecode
from the installed npm package artifacts.

Prereqs:
- Ensure npm deps installed in ticklens-hardhat/: `cd ticklens-hardhat && npm i`
- Env: RPC_URL, PRIVATE_KEY (and optional GNOSISSCAN_API_KEY if you later verify)
- Optional: --env-file to load exports like the repo .env files

Usage:
  futarchy_env/bin/python scripts/deploy_ticklens.py \
    --env-file .env.v2.0xa80641Bf70483A3524713A396deE0ebD642CEaEA

This script focuses on deploy (no verification).
"""
import os
import re
import json
import time
from pathlib import Path
from typing import Dict

from web3 import Web3
from eth_account import Account

ARTIFACT_PATH = Path('ticklens-hardhat/node_modules/@cryptoalgebra/integral-periphery/artifacts/contracts/lens/TickLens.sol/TickLens.json')


def load_env_file(path: str) -> Dict[str, str]:
    env: Dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return env
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = re.match(r"export\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        os.environ[k] = v
        env[k] = v
    return env


def main():
    import argparse

    ap = argparse.ArgumentParser(description='Deploy Algebra TickLens (official) to Gnosis')
    ap.add_argument('--env-file', default=None, help='Path to .env-like file with export KEY=VAL lines')
    ap.add_argument('--artifact', default=str(ARTIFACT_PATH), help='Path to TickLens artifact JSON (abi + bytecode)')
    ap.add_argument('--save', default='deployments/ticklens_deployment.json', help='Where to save deployment info')
    args = ap.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    rpc_url = os.environ.get('RPC_URL') or os.environ.get('GNOSIS_RPC_URL')
    pk = os.environ.get('PRIVATE_KEY')
    if not rpc_url or not pk:
        raise SystemExit('Missing RPC_URL or PRIVATE_KEY. Source your .env first or pass --env-file.')

    if pk.startswith('0x'):
        private_key = pk
    else:
        private_key = '0x' + pk

    # Load artifact
    artifact_path = Path(args.artifact)
    if not artifact_path.exists():
        raise SystemExit(f'Artifact not found: {artifact_path}\nRun: cd ticklens-hardhat && npm i')
    art = json.loads(artifact_path.read_text())
    abi = art.get('abi')
    bytecode = art.get('bytecode') or art.get('evm', {}).get('bytecode', {}).get('object')
    if not abi or not bytecode:
        raise SystemExit('Failed to load abi/bytecode from artifact JSON')
    if not str(bytecode).startswith('0x'):
        bytecode = '0x' + str(bytecode)

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise SystemExit('Failed to connect to RPC')
    acct = Account.from_key(private_key)

    print(f'RPC: {rpc_url}')
    print(f'Deployer: {acct.address}')
    print(f'ChainId: {w3.eth.chain_id}')
    bal = w3.from_wei(w3.eth.get_balance(acct.address), 'ether')
    print(f'Balance: {bal:.6f} xDAI')

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = contract.constructor().build_transaction({
        'from': acct.address,
        'nonce': w3.eth.get_transaction_count(acct.address),
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id,
    })
    try:
        gas_est = w3.eth.estimate_gas(tx)
        tx['gas'] = int(gas_est * 1.2)
    except Exception:
        tx['gas'] = 1_000_000

    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f'Tx sent: {tx_hash.hex()}')
    print(f'Waiting for receipt...')
    rcpt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

    if rcpt.status != 1:
        raise SystemExit(f'Deployment failed, status={rcpt.status}')

    addr = rcpt.contractAddress
    print(f'TickLens deployed: {addr}')
    print(f'Gnosisscan: https://gnosisscan.io/address/{addr}')

    out = {
        'address': addr,
        'tx': tx_hash.hex(),
        'block': rcpt.blockNumber,
        'gasUsed': rcpt.gasUsed,
        'chainId': w3.eth.chain_id,
        'timestamp': int(time.time()),
        'artifact': str(artifact_path),
        'network': 'gnosis',
        'contract': 'TickLens',
    }
    Path(args.save).parent.mkdir(parents=True, exist_ok=True)
    with open(args.save, 'w') as f:
        json.dump(out, f, indent=2)
    print(f'Saved: {args.save}')
    print(f"Add to env: export TICKLENS_ADDRESS={addr}")


if __name__ == '__main__':
    main()

