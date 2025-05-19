#!/usr/bin/env python3
"""
Updated balancer_permit2.py

This version generates **Permit2 _batch_ signatures** and optionally submits
**permittedBatchCall** transactions to Balancer's Permit2 Batch Router.
It replaces the previous single‑permit flow that interacted directly with the
stand‑alone Permit2 contract.

Key changes
-----------
* Accept **multiple** `--tokens` and `--amounts` so you can approve several
  ERC‑20s at once (e.g. multiple collateral tokens).
* Build an **EIP‑712 PermitBatch** (array of `PermitDetails`) instead of a
  single `PermitSingle`.
* Sign the batch with the owner key; output the payload in a format ready for
  Balancer relayers or front‑end to consume.
* Optional `--broadcast` now targets the **Balancer Router** and calls
  `permittedBatchCall(permitBatch, signature, calls)` so the allowance and the
  follow‑up calls execute atomically.

Examples
~~~~~~~~
Dry‑run (no on‑chain tx, just echo signature & JSON payload)::

    python balancer_permit2.py \
        --private-key 0xYOUR_PK \
        --tokens 0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48 0xC02aaa39b223fe8d0a0e5c4f27ead9083c756cc2 \
        --amounts 100 0.5 \
        --router-address 0xBA12222222228d8Ba445958a75a0704d566BF2C8 \
        --deadline $(( $(date +%s) + 3600 )) \
        --rpc-url https://mainnet.infura.io/v3/YOUR_KEY \
        --chain-id 1

Broadcast (includes encoded Balancer Vault calls)::

    python balancer_permit2.py ... --broadcast \
        --calls-data 0xabc123 0xdef456

Note: every `calls-data` item should already be ABI‑encoded for the target
contract (e.g., Balancer Vault or other protocols) **without** the 0x‑prefixed
function selector of `permittedBatchCall`.
"""

import argparse
import json
import time
from decimal import Decimal
from pathlib import Path
from typing import List

from eth_account import Account
from eth_account.messages import encode_structured_data
from web3 import Web3
from web3.middleware import geth_poa_middleware

# The canonical Permit2 deployment – still needed for nonce look‑ups
PERMIT2_ADDRESS = "0x000000000022D473030F116dDEE9F6B43aC78BA3"

# ---- Minimal on‑chain ABIs -------------------------------------------------

PERMIT2_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "address", "name": "spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [
            {
                "components": [
                    {"internalType": "uint160", "name": "amount", "type": "uint160"},
                    {"internalType": "uint48", "name": "expiration", "type": "uint48"},
                    {"internalType": "uint48", "name": "nonce", "type": "uint48"},
                ],
                "internalType": "struct IAllowanceTransfer.PackedAllowance",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    }
]

# ---------------------------------------------------------------------------

def _load_router_abi() -> List[dict]:
    """Read the Balancer router ABI shipped with the project."""
    root = Path(__file__).resolve().parent.parent
    abi_path = root / "config" / "batch_router_abi.json"
    with abi_path.open() as fh:
        return json.load(fh)


def get_nonce(permit2, owner: str, token: str, spender: str) -> int:
    packed = permit2.functions.allowance(owner, token, spender).call()
    return packed[2]  # nonce


def build_structured_data(chain_id: int, verifying_contract: str, permit_batch: dict):
    """Compose an EIP‑712 structured‑data dict for PermitBatch."""
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "PermitDetails": [
                {"name": "token", "type": "address"},
                {"name": "amount", "type": "uint160"},
                {"name": "expiration", "type": "uint48"},
                {"name": "nonce", "type": "uint48"},
            ],
            "PermitBatch": [
                {"name": "details", "type": "PermitDetails[]"},
                {"name": "spender", "type": "address"},
                {"name": "sigDeadline", "type": "uint256"},
            ],
        },
        "domain": {
            "name": "Permit2",
            "chainId": chain_id,
            "verifyingContract": verifying_contract,
        },
        "primaryType": "PermitBatch",
        "message": permit_batch,
    }


def parse_args():
    p = argparse.ArgumentParser(description="Create (and optionally broadcast) a Permit2 batch allowance for Balancer.")
    p.add_argument("--private-key", required=True, help="Owner's private key (0x…)")
    p.add_argument("--tokens", nargs="+", required=True, help="One or more ERC‑20 token addresses")
    p.add_argument("--amounts", nargs="+", required=True, type=Decimal, help="Human‑readable amounts for each token")
    p.add_argument("--router-address", required=True, help="Balancer Router address – this will be the Permit2 *spender*")
    p.add_argument("--deadline", type=lambda x: int(x, 0), default=lambda: int(time.time()) + 3600,
                   help="Unix timestamp after which the signature is invalid (hex or int, default +1 h)")
    p.add_argument("--expiration", type=int, default=0, help="Allowance expiration (0 = never)")
    p.add_argument("--rpc-url", required=True, help="JSON‑RPC endpoint")
    p.add_argument("--chain-id", required=True, type=int, help="Chain ID (e.g. 1 for mainnet)")
    p.add_argument("--calls-data", nargs="*", default=[],
                   help="ABI‑encoded calls for permittedBatchCall – hex strings, no 0x separators inside")
    p.add_argument("--broadcast", action="store_true", help="Send the permittedBatchCall on‑chain")
    p.add_argument("--gas-price", type=int, default=None, help="Legacy gasPrice in wei (overrides EIP‑1559)")
    return p.parse_args()


def main():
    args = parse_args()

    w3 = Web3(Web3.HTTPProvider(args.rpc_url))
    if args.chain_id in (56, 97, 250, 100):  # POA/EIP‑1559 chains (Gnosis = 100)
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    acct = Account.from_key(args.private_key)
    owner = acct.address
    router_addr = Web3.to_checksum_address(args.router_address)

    if len(args.tokens) != len(args.amounts):
        raise ValueError("--tokens and --amounts length mismatch")

    # Initialise contracts
    permit2 = w3.eth.contract(address=Web3.to_checksum_address(PERMIT2_ADDRESS), abi=PERMIT2_ABI)
    router = w3.eth.contract(address=router_addr, abi=_load_router_abi())

    # Build PermitDetails list
    details = []
    for tkn, amt in zip(args.tokens, args.amounts):
        token = Web3.to_checksum_address(tkn)
        token_c = w3.eth.contract(address=token, abi=ERC20_ABI)
        decimals = token_c.functions.decimals().call()
        scaled = int(amt * (10 ** decimals))
        if scaled >= 2 ** 160:
            raise ValueError(f"Amount {amt} for {token} exceeds uint160.")
        nonce = get_nonce(permit2, owner, token, router_addr)
        details.append({
            "token": token,
            "amount": scaled,
            "expiration": args.expiration,
            "nonce": nonce,
        })

    permit_batch = {
        "details": details,
        "spender": router_addr,
        "sigDeadline": int(args.deadline() if callable(args.deadline) else args.deadline),
    }

    structured = build_structured_data(args.chain_id, PERMIT2_ADDRESS, permit_batch)
    encoded = encode_structured_data(structured)
    signed = acct.sign_message(encoded)
    signature_hex = signed.signature.hex()

    print("PermitBatch payload:")
    print(json.dumps(permit_batch, indent=2))
    print(f"\nSignature: {signature_hex}\n")

    if not args.broadcast:
        print("Dry‑run complete – broadcast disabled.")
        return

    # ---- Build permittedBatchCall tx --------------------------------------

    call_bytes_list = [Web3.to_bytes(hexstr=x) for x in args.calls_data]
    try:
        # Using permitBatchAndCall which takes permitBatch, signature, and calls data
        fn = router.functions.permitBatchAndCall(
            [],  # Empty permitBatch array (not used in this flow)
            [],  # Empty permitSignatures array (not used in this flow)
            permit_batch,  # Our permit batch data
            signed.signature,  # Our signature
            call_bytes_list  # Any additional calls to make
        )
    except (ValueError, AttributeError) as e:
        raise RuntimeError(f"Failed to create permitBatchAndCall transaction: {e}")

    tx = fn.build_transaction({
        "from": owner,
        "nonce": w3.eth.get_transaction_count(owner),
        "chainId": args.chain_id,
        "value": 0,
    })

    # Gas strategy
    if args.gas_price is not None:
        tx["gasPrice"] = args.gas_price
        tx.pop("maxFeePerGas", None)
        tx.pop("maxPriorityFeePerGas", None)
    else:
        # EIP‑1559 heuristic
        tx.pop("gasPrice", None)
        latest = w3.eth.get_block("latest")
        base_fee = latest.get("baseFeePerGas") or 0
        priority = w3.eth.max_priority_fee
        if priority in (None, 0):
            priority = w3.to_wei(1.5, "gwei")  # sensible default for Gnosis/Mainnet
        tx["maxPriorityFeePerGas"] = priority
        tx["maxFeePerGas"] = base_fee * 2 + priority

    # Gas estimate
    tx["gas"] = w3.eth.estimate_gas(tx)
    print(f"Estimated gas: {tx['gas']}")

    signed_tx = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    print(f"Broadcasted tx → {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"Status: {receipt.status} (1 = success) | Gas used: {receipt.gasUsed}")


if __name__ == "__main__":
    main()


#  python setup/balancer_permit2.py \
#   --private-key $PRIVATE_KEY \
#   --tokens 0xaf204776c7245bF4147c2612BF6e5972Ee483701 0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb \
#   --amounts 7.3075e29 7.3075e29 \
#   --expiration 1847516899 \
#   --router-address 0xe2fa4e1d17725e72dcdAfe943Ecf45dF4B9E285b \
#   --chain-id 100 \
#   --rpc-url https://rpc.gnosischain.com \
#   --broadcast