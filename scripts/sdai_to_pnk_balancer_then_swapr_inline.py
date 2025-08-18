#!/usr/bin/env python3
"""
Spend 0.01 sDAI to buy PNK on Gnosis using:
  1) Balancer BatchRouter.swapExactIn: sDAI -> GNO (Aave GNO buffer hop)
  2) Swapr (Uniswap v2) swap:        GNO  -> WETH -> PNK

This script inlines the minimal pieces from src/trades/balancer_swap.py so it runs standalone.

Env vars required:
  - RPC_URL or GNOSIS_RPC_URL
  - PRIVATE_KEY
  - BALANCER_ROUTER_ADDRESS (e.g., 0xE2fA4E1d17725e72cdDAfe943Ecf45dF4B9E285b)
  - SWAPR_ROUTER_ADDRESS     (from your .env)

Usage:
  python scripts/sdai_to_pnk_balancer_then_swapr_inline.py --amount 0.01 --recipient 0xYourAddr
"""

from __future__ import annotations

import os
import argparse
from decimal import Decimal

from dotenv import load_dotenv
from web3 import Web3


# ---- Constants copied from src/trades/balancer_swap.py ----
COMPANY_TOKEN = Web3.to_checksum_address("0x9c58bacc331c9aa871afd802db6379a98e80cedb")  # GNO
SDAI          = Web3.to_checksum_address("0xaf204776c7245bf4147c2612bf6e5972ee483701")
BUFFER_POOL   = Web3.to_checksum_address("0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644")
FINAL_POOL    = Web3.to_checksum_address("0xd1d7fa8871d84d0e77020fc28b7cd5718c446522")
MAX_DEADLINE  = 9007199254740991

BALANCER_ROUTER_ABI = [
    {
        "type": "function",
        "name": "swapExactIn",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "paths",
                "type": "tuple[]",
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {
                        "name": "steps",
                        "type": "tuple[]",
                        "components": [
                            {"name": "pool", "type": "address"},
                            {"name": "tokenOut", "type": "address"},
                            {"name": "isBuffer", "type": "bool"},
                        ],
                    },
                    {"name": "exactAmountIn", "type": "uint256"},
                    {"name": "minAmountOut", "type": "uint256"},
                ],
            },
            {"name": "deadline", "type": "uint256"},
            {"name": "wethIsEth", "type": "bool"},
            {"name": "userData", "type": "bytes"},
        ],
        "outputs": [
            {"name": "pathAmountsOut", "type": "uint256[]"},
            {"name": "tokensOut", "type": "address[]"},
            {"name": "amountsOut", "type": "uint256[]"},
        ],
    }
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

ERC20_MIN_ABI = [
    {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

WETH = Web3.to_checksum_address("0x6A023CCd1ff6F2045C3309768eAd9E68F978f6e1")
PNK  = Web3.to_checksum_address("0x37b60f4E9A31A64cCc0024dce7D0fD07eAA0F7B3")


def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def eip1559_fee_fields(w3: Web3) -> dict:
    try:
        base = w3.eth.get_block("latest").get("baseFeePerGas")
        tip = 1
        return {"maxFeePerGas": int(base) * 2 + tip, "maxPriorityFeePerGas": tip}
    except Exception:
        return {"gasPrice": int(w3.eth.gas_price) + 1}


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="sDAI -> GNO (Balancer) -> PNK (Swapr)")
    ap.add_argument("--amount", default="0.01", help="sDAI amount to spend (ether units)")
    ap.add_argument("--recipient", default=None, help="Recipient address (defaults to your EOA)")
    args = ap.parse_args()

    rpc_url = os.getenv("GNOSIS_RPC_URL") or os.getenv("RPC_URL")
    if not rpc_url:
        raise SystemExit("Set GNOSIS_RPC_URL or RPC_URL in env")
    priv = require_env("PRIVATE_KEY")

    bal_router_addr = Web3.to_checksum_address(require_env("BALANCER_ROUTER_ADDRESS"))
    swapr_router_addr = Web3.to_checksum_address(require_env("SWAPR_ROUTER_ADDRESS"))

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

    sdai = w3.eth.contract(address=SDAI, abi=ERC20_MIN_ABI)
    gno  = w3.eth.contract(address=COMPANY_TOKEN, abi=ERC20_MIN_ABI)
    bal_router = w3.eth.contract(address=bal_router_addr, abi=BALANCER_ROUTER_ABI)
    swapr = w3.eth.contract(address=swapr_router_addr, abi=UNIV2_ROUTER_ABI)

    # 0) Approve sDAI to Balancer router
    nonce = w3.eth.get_transaction_count(acct.address)
    approve0 = sdai.functions.approve(bal_router_addr, int(amount_in_wei)).build_transaction({
        "from": acct.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
    })
    approve0.update(eip1559_fee_fields(w3))
    try:
        approve0["gas"] = int(w3.eth.estimate_gas(approve0) * 1.2)
    except Exception:
        approve0["gas"] = 120_000
    s0 = acct.sign_transaction(approve0)
    raw0 = getattr(s0, "rawTransaction", None) or getattr(s0, "raw_transaction", None)
    h0 = w3.eth.send_raw_transaction(raw0)
    print(f"Approve sDAI->Balancer: {h0.hex()}")
    w3.eth.wait_for_transaction_receipt(h0)

    # 1) Balancer BatchRouter: sDAI -> BUFFER -> GNO
    steps = [
        (FINAL_POOL, BUFFER_POOL, False),
        (BUFFER_POOL, COMPANY_TOKEN, True),
    ]
    path = (
        SDAI,
        steps,
        int(amount_in_wei),
        0,  # minAmountOut
    )
    tx1_params = {
        "from": acct.address,
        "nonce": nonce + 1,
        "chainId": w3.eth.chain_id,
        "gas": 800_000,  # pre-set to avoid provider estimation STF
    }
    tx1 = bal_router.functions.swapExactIn([path], int(MAX_DEADLINE), False, b"").build_transaction(tx1_params)
    fees = eip1559_fee_fields(w3)
    tx1.update(fees)
    if "maxFeePerGas" in tx1 and "gasPrice" in tx1:
        del tx1["gasPrice"]
    try:
        gas_est = w3.eth.estimate_gas(tx1)
        tx1["gas"] = int(gas_est * 1.2)
    except Exception:
        tx1["gas"] = 800_000
    s1 = acct.sign_transaction(tx1)
    raw1 = getattr(s1, "rawTransaction", None) or getattr(s1, "raw_transaction", None)
    h1 = w3.eth.send_raw_transaction(raw1)
    print(f"Balancer swap (sDAI->GNO): {h1.hex()}")
    w3.eth.wait_for_transaction_receipt(h1)

    gno_bal = gno.functions.balanceOf(acct.address).call()
    print(f"GNO received: {w3.from_wei(gno_bal, 'ether')}")
    if gno_bal == 0:
        raise SystemExit("No GNO received from Balancer swap; aborting")

    # 2) Approve GNO to Swapr
    nonce = w3.eth.get_transaction_count(acct.address)
    approve1 = gno.functions.approve(swapr_router_addr, int(gno_bal)).build_transaction({
        "from": acct.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
    })
    approve1.update(eip1559_fee_fields(w3))
    try:
        approve1["gas"] = int(w3.eth.estimate_gas(approve1) * 1.2)
    except Exception:
        approve1["gas"] = 120_000
    s2 = acct.sign_transaction(approve1)
    raw2 = getattr(s2, "rawTransaction", None) or getattr(s2, "raw_transaction", None)
    h2 = w3.eth.send_raw_transaction(raw2)
    print(f"Approve GNO->Swapr: {h2.hex()}")
    w3.eth.wait_for_transaction_receipt(h2)

    # 3) Swapr: GNO -> WETH -> PNK
    path2 = [COMPANY_TOKEN, WETH, PNK]
    nonce = w3.eth.get_transaction_count(acct.address)
    tx2 = swapr.functions.swapExactTokensForTokens(
        int(gno_bal),
        0,
        path2,
        recipient,
        int(deadline),
    ).build_transaction({
        "from": acct.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
    })
    tx2.update(eip1559_fee_fields(w3))
    if "gas" not in tx2:
        try:
            gas_est = w3.eth.estimate_gas(tx2)
            tx2["gas"] = int(gas_est * 1.2)
        except Exception:
            tx2["gas"] = 1_000_000
    s3 = acct.sign_transaction(tx2)
    raw3 = getattr(s3, "rawTransaction", None) or getattr(s3, "raw_transaction", None)
    h3 = w3.eth.send_raw_transaction(raw3)
    print(f"Swapr swap (GNO->PNK): {h3.hex()}")
    rcpt = w3.eth.wait_for_transaction_receipt(h3)
    print(f"Success: {rcpt.status == 1}; Gas used: {rcpt.gasUsed}")


if __name__ == "__main__":
    main()
