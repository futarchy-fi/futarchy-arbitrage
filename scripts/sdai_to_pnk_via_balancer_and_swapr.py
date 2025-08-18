#!/usr/bin/env python3
"""
Minimal 0.01 sDAI -> PNK trade on Gnosis using:
  1) Balancer BatchRouter: sDAI -> GNO
  2) Swapr (Uniswap v2):   GNO  -> WETH -> PNK

Env vars required:
- RPC_URL or GNOSIS_RPC_URL
- PRIVATE_KEY
- BALANCER_ROUTER_ADDRESS (defaults from .env OK)
- SWAPR_ROUTER_ADDRESS    (from your .env)

Usage:
  python scripts/sdai_to_pnk_via_balancer_and_swapr.py --amount 0.01 --recipient 0xYourAddr

Notes:
- Sets amountOutMin=0 for simplicity. For production, pre-quote and set slippage.
"""

from __future__ import annotations

import os
import argparse
from decimal import Decimal

from dotenv import load_dotenv
from web3 import Web3

import sys
from pathlib import Path
# Ensure project root is importable
sys.path.append(str(Path(__file__).resolve().parents[1]))
from src.trades.balancer_swap import build_buy_gno_to_sdai_swap_tx, SDAI as TOK_SDAI


# Tokens (Gnosis)
GNO  = Web3.to_checksum_address("0x9c58bacc331c9aa871afd802db6379a98e80cedb")
WETH = Web3.to_checksum_address("0x6A023CCd1ff6F2045C3309768eAd9E68F978f6e1")
PNK  = Web3.to_checksum_address("0x37b60f4E9A31A64cCc0024dce7D0fD07eAA0F7B3")


ERC20_MIN_ABI = [
    {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

UNIV2_ROUTER_ABI = [
    {
        "name": "swapExactTokensForTokens",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    }
]


def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def _eip1559(w3: Web3) -> dict:
    try:
        base = w3.eth.get_block("latest").get("baseFeePerGas")
        tip = 1
        return {"maxFeePerGas": int(base) * 2 + tip, "maxPriorityFeePerGas": tip}
    except Exception:
        return {"gasPrice": int(w3.eth.gas_price) + 1}


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Buy PNK with sDAI via Balancer+Swapr")
    parser.add_argument("--amount", default="0.01", help="sDAI amount to spend (ether units)")
    parser.add_argument("--recipient", default=None, help="Recipient (defaults to your EOA)")
    parser.add_argument("--path", nargs="*", default=[GNO, WETH, PNK], help="Swapr path for GNO->PNK")
    args = parser.parse_args()

    rpc_url = os.getenv("GNOSIS_RPC_URL") or os.getenv("RPC_URL")
    if not rpc_url:
        raise SystemExit("Set GNOSIS_RPC_URL or RPC_URL in env")
    priv = require_env("PRIVATE_KEY")
    swapr_router_addr = Web3.to_checksum_address(require_env("SWAPR_ROUTER_ADDRESS"))
    bal_router_addr = os.getenv("BALANCER_ROUTER_ADDRESS")  # optional

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    try:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass
    if not w3.is_connected():
        raise SystemExit("Failed to connect to RPC")

    acct = w3.eth.account.from_key(priv)
    recipient = Web3.to_checksum_address(args.recipient or acct.address)
    amount_in_wei = w3.to_wei(Decimal(str(args.amount)), "ether")
    deadline = int(w3.eth.get_block("latest").timestamp) + 1200

    # Contracts
    sdai = w3.eth.contract(address=Web3.to_checksum_address(TOK_SDAI), abi=ERC20_MIN_ABI)
    gno  = w3.eth.contract(address=Web3.to_checksum_address(GNO), abi=ERC20_MIN_ABI)
    swapr = w3.eth.contract(address=swapr_router_addr, abi=UNIV2_ROUTER_ABI)

    # 0) Approve sDAI to Balancer router
    nonce = w3.eth.get_transaction_count(acct.address)
    approve0 = sdai.functions.approve(Web3.to_checksum_address(bal_router_addr or require_env("BALANCER_ROUTER_ADDRESS")), int(amount_in_wei)).build_transaction({
        "from": acct.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
    })
    approve0.update(_eip1559(w3))
    try:
        approve0["gas"] = int(w3.eth.estimate_gas(approve0) * 1.2)
    except Exception:
        approve0["gas"] = 120_000
    s0 = acct.sign_transaction(approve0)
    raw0 = getattr(s0, "rawTransaction", None) or getattr(s0, "raw_transaction", None)
    h0 = w3.eth.send_raw_transaction(raw0)
    print(f"Approve sDAI->Balancer: {h0.hex()}")
    w3.eth.wait_for_transaction_receipt(h0)

    # 1) Balancer: sDAI -> GNO
    bal_tx = build_buy_gno_to_sdai_swap_tx(
        w3,
        amount_in_wei=int(amount_in_wei),
        min_amount_out_wei=0,
        sender=acct.address,
        router_addr=bal_router_addr,
    )
    # build_buy_gno_to_sdai_swap_tx included nonce/gas; ensure fees
    fee_fields = _eip1559(w3)
    bal_tx.update(fee_fields)
    # Remove legacy gasPrice if using EIP-1559
    if ("maxFeePerGas" in bal_tx or "maxPriorityFeePerGas" in bal_tx) and "gasPrice" in bal_tx:
        del bal_tx["gasPrice"]
    s1 = acct.sign_transaction(bal_tx)
    raw1 = getattr(s1, "rawTransaction", None) or getattr(s1, "raw_transaction", None)
    h1 = w3.eth.send_raw_transaction(raw1)
    print(f"Balancer swap (sDAI->GNO): {h1.hex()}")
    w3.eth.wait_for_transaction_receipt(h1)

    # 2) Approve GNO to Swapr
    gno_bal = gno.functions.balanceOf(acct.address).call()
    if gno_bal == 0:
        raise SystemExit("No GNO received from Balancer swap; cannot continue")
    nonce = w3.eth.get_transaction_count(acct.address)
    approve1 = gno.functions.approve(swapr_router_addr, int(gno_bal)).build_transaction({
        "from": acct.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
    })
    approve1.update(_eip1559(w3))
    try:
        approve1["gas"] = int(w3.eth.estimate_gas(approve1) * 1.2)
    except Exception:
        approve1["gas"] = 120_000
    s2 = acct.sign_transaction(approve1)
    raw2 = getattr(s2, "rawTransaction", None) or getattr(s2, "raw_transaction", None)
    h2 = w3.eth.send_raw_transaction(raw2)
    print(f"Approve GNO->Swapr: {h2.hex()}")
    w3.eth.wait_for_transaction_receipt(h2)

    # 3) Swapr: GNO -> ... -> PNK
    path = [Web3.to_checksum_address(x) for x in (args.path if isinstance(args.path[0], str) else [GNO, WETH, PNK])]
    nonce = w3.eth.get_transaction_count(acct.address)
    swap_tx = swapr.functions.swapExactTokensForTokens(
        int(gno_bal),
        0,  # minOut
        path,
        recipient,
        int(deadline),
    ).build_transaction({
        "from": acct.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
    })
    swap_tx.update(_eip1559(w3))
    if "gas" not in swap_tx:
        try:
            gas_est = w3.eth.estimate_gas(swap_tx)
            swap_tx["gas"] = int(gas_est * 1.2)
        except Exception:
            swap_tx["gas"] = 1_000_000
    s3 = acct.sign_transaction(swap_tx)
    raw3 = getattr(s3, "rawTransaction", None) or getattr(s3, "raw_transaction", None)
    h3 = w3.eth.send_raw_transaction(raw3)
    print(f"Swapr swap (GNO->PNK): {h3.hex()}")
    rcpt = w3.eth.wait_for_transaction_receipt(h3)
    print(f"Success: {rcpt.status == 1}; Gas used: {rcpt.gasUsed}")


if __name__ == "__main__":
    main()
