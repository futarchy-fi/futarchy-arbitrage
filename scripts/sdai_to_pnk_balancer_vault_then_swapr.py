#!/usr/bin/env python3
"""
Spend small sDAI to buy PNK on Gnosis using:
  1) Balancer Vault batchSwap (GIVEN_IN): sDAI -> WETH (multi-pool route)
  2) Swapr (Uniswap v2): WETH -> PNK

Implements the exact pool route structure from a successful on-chain example.

Env vars required:
  - RPC_URL or GNOSIS_RPC_URL
  - PRIVATE_KEY
  - SWAPR_ROUTER_ADDRESS (v2 router)

Usage:
  python scripts/sdai_to_pnk_balancer_vault_then_swapr.py --amount 0.01 --recipient 0xYourAddr
"""

from __future__ import annotations

import os
import argparse
from decimal import Decimal
from typing import List, Tuple

from dotenv import load_dotenv
from web3 import Web3


# ------------------- Constants (Gnosis) ------------------- #
VAULT = Web3.to_checksum_address("0xBA12222222228d8Ba445958a75a0704d566BF2C8")
SDAI  = Web3.to_checksum_address("0xaf204776c7245bf4147c2612bf6e5972ee483701")
WETH  = Web3.to_checksum_address("0x6A023CCd1ff6F2045C3309768eAd9E68F978f6e1")
PNK   = Web3.to_checksum_address("0x37b60f4E9A31A64cCc0024dce7D0fD07eAA0F7B3")

# PoolIds from provided successful batchSwap (sDAI -> WETH)
POOL_1 = Web3.to_bytes(hexstr="0xa91c413d8516164868f6cca19573fe38f88f5982000200000000000000000157")
POOL_2 = Web3.to_bytes(hexstr="0x7e5870ac540adfd01a213c829f2231c309623eb10002000000000000000000e9")
POOL_3 = Web3.to_bytes(hexstr="0x40d2cbc586dd8df50001cdba3f65cd4bbc32d596000200000000000000000154")
POOL_4 = Web3.to_bytes(hexstr="0x480d4f66cc41a1b6784a53a10890e5ece31d75c000020000000000000000014e")
POOL_5 = Web3.to_bytes(hexstr="0xa99fd9950b5d5dceeaf4939e221dca8ca9b938ab000100000000000000000025")

# Intermediate assets in the same order as the successful tx
ASSET_1 = SDAI
ASSET_2 = Web3.to_checksum_address("0xC0d871bD13eBdf5c4ff059D8243Fb38210608bD6")
ASSET_3 = WETH
ASSET_4 = Web3.to_checksum_address("0xE0eD85F76D9C552478929fab44693E03F0899F23")
ASSET_5 = Web3.to_checksum_address("0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb")  # GNO (intermediate only)

ASSETS_ORDER: List[str] = [ASSET_1, ASSET_2, ASSET_3, ASSET_4, ASSET_5]


# ------------------- Minimal ABIs ------------------- #
VAULT_ABI = [
    {
        "name": "batchSwap",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "kind", "type": "uint8"},
            {"name": "swaps", "type": "tuple[]", "components": [
                {"name": "poolId", "type": "bytes32"},
                {"name": "assetInIndex", "type": "uint256"},
                {"name": "assetOutIndex", "type": "uint256"},
                {"name": "amount", "type": "uint256"},
                {"name": "userData", "type": "bytes"},
            ]},
            {"name": "assets", "type": "address[]"},
            {"name": "funds", "type": "tuple", "components": [
                {"name": "sender", "type": "address"},
                {"name": "fromInternalBalance", "type": "bool"},
                {"name": "recipient", "type": "address"},
                {"name": "toInternalBalance", "type": "bool"},
            ]},
            {"name": "limits", "type": "int256[]"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [
            {"name": "assetDeltas", "type": "int256[]"}
        ],
    }
]

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


def eip1559(w3: Web3) -> dict:
    try:
        base = w3.eth.get_block("latest").get("baseFeePerGas")
        tip = 1
        return {"maxFeePerGas": int(base) * 2 + tip, "maxPriorityFeePerGas": tip}
    except Exception:
        return {"gasPrice": int(w3.eth.gas_price) + 1}


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="sDAI->WETH (Balancer Vault) then WETH->PNK (Swapr)")
    ap.add_argument("--amount", default="0.01", help="sDAI amount to spend (ether units)")
    ap.add_argument("--min-weth", default="0", help="Min WETH out (ether units, default 0)")
    ap.add_argument("--min-pnk", default="0", help="Min PNK out (ether units, default 0)")
    args = ap.parse_args()

    rpc_url = os.getenv("GNOSIS_RPC_URL") or os.getenv("RPC_URL")
    if not rpc_url:
        raise SystemExit("Set GNOSIS_RPC_URL or RPC_URL in env")
    priv = require_env("PRIVATE_KEY")
    # Swapr router: prefer env; fallback to the router used in your successful tx
    swapr_router_default = "0xE43e60736b1cb4a75ad25240E2f9a62Bff65c0C0"
    swapr_env = os.getenv("SWAPR_ROUTER_ADDRESS")
    swapr_router_addr = Web3.to_checksum_address(swapr_env) if swapr_env else Web3.to_checksum_address(swapr_router_default)

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    try:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass
    if not w3.is_connected():
        raise SystemExit("Failed to connect to RPC")

    acct = w3.eth.account.from_key(priv)
    # Always send to the sender (no external recipient parameter)
    recipient = Web3.to_checksum_address(acct.address)
    amount_in_wei = w3.to_wei(Decimal(str(args.amount)), "ether")
    min_weth_wei = w3.to_wei(Decimal(str(args.min_weth)), "ether")
    min_pnk_wei  = w3.to_wei(Decimal(str(args.min_pnk)), "ether")
    # Use a far-future deadline similar to known-good Swapr txs to avoid timing issues
    univ2_deadline = 3510754692

    vault = w3.eth.contract(address=VAULT, abi=VAULT_ABI)
    sdai  = w3.eth.contract(address=SDAI, abi=ERC20_MIN_ABI)
    weth  = w3.eth.contract(address=WETH, abi=ERC20_MIN_ABI)
    router = w3.eth.contract(address=swapr_router_addr, abi=UNIV2_ROUTER_ABI)

    # 0) Approve sDAI to Vault
    nonce = w3.eth.get_transaction_count(acct.address)
    approve0 = sdai.functions.approve(VAULT, int(amount_in_wei)).build_transaction({
        "from": acct.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
    })
    approve0.update(eip1559(w3))
    try:
        approve0["gas"] = int(w3.eth.estimate_gas(approve0) * 1.2)
    except Exception:
        approve0["gas"] = 120_000
    s0 = acct.sign_transaction(approve0)
    raw0 = getattr(s0, "rawTransaction", None) or getattr(s0, "raw_transaction", None)
    h0 = w3.eth.send_raw_transaction(raw0)
    print(f"Approve sDAI->Vault: {h0.hex()}")
    w3.eth.wait_for_transaction_receipt(h0)

    # 1) Balancer Vault batchSwap: split amount across two branches, converge to WETH
    half = int(amount_in_wei // 2)
    other = int(amount_in_wei - half)
    swaps: List[Tuple] = [
        # Branch A: sDAI -> ASSET_2 -> WETH
        (POOL_1, 0, 1, half, b""),  # sDAI -> ASSET_2 (amount=half)
        (POOL_2, 1, 2, 0,   b""),   # ASSET_2 -> WETH (amount=0 for GIVEN_IN)
        # Branch B: sDAI -> ASSET_4 -> ASSET_5 -> WETH
        (POOL_3, 0, 3, other, b""), # sDAI -> ASSET_4 (amount=other)
        (POOL_4, 3, 4, 0,     b""), # ASSET_4 -> ASSET_5
        (POOL_5, 4, 2, 0,     b""), # ASSET_5 -> WETH
    ]

    assets = ASSETS_ORDER
    # limits: positive for tokens the Vault can take from sender; negative min received
    # Enforce min WETH if provided
    limits = [0] * len(assets)
    limits[0] = int(amount_in_wei)               # sDAI in
    limits[2] = -int(min_weth_wei)               # WETH minimum out (negative)

    funds = (acct.address, False, acct.address, False)
    tx1_params = {
        "from": acct.address,
        "nonce": nonce + 1,
        "chainId": w3.eth.chain_id,
        # Pre-set gas to avoid provider-side estimation (BAL#507) during build_transaction
        "gas": 1_000_000,
    }
    tx1 = vault.functions.batchSwap(
        0,              # GIVEN_IN
        swaps,
        assets,
        funds,
        limits,
        9007199254740991,
    ).build_transaction(tx1_params)
    tx1.update(eip1559(w3))
    s1 = acct.sign_transaction(tx1)
    raw1 = getattr(s1, "rawTransaction", None) or getattr(s1, "raw_transaction", None)
    h1 = w3.eth.send_raw_transaction(raw1)
    print(f"Vault batchSwap (sDAI->WETH): {h1.hex()}")
    w3.eth.wait_for_transaction_receipt(h1)

    weth_bal = weth.functions.balanceOf(acct.address).call()
    print(f"WETH received: {w3.from_wei(weth_bal, 'ether')}")
    if weth_bal == 0:
        raise SystemExit("No WETH received from Balancer swap; aborting")

    # 2) Approve WETH to Swapr
    nonce = w3.eth.get_transaction_count(acct.address)
    approve1 = weth.functions.approve(swapr_router_addr, int(weth_bal)).build_transaction({
        "from": acct.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
    })
    approve1.update(eip1559(w3))
    try:
        approve1["gas"] = int(w3.eth.estimate_gas(approve1) * 1.2)
    except Exception:
        approve1["gas"] = 120_000
    s2 = acct.sign_transaction(approve1)
    raw2 = getattr(s2, "rawTransaction", None) or getattr(s2, "raw_transaction", None)
    h2 = w3.eth.send_raw_transaction(raw2)
    print(f"Approve WETH->Swapr: {h2.hex()}")
    w3.eth.wait_for_transaction_receipt(h2)

    # 3) Swapr: WETH -> PNK
    path = [WETH, PNK]
    nonce = w3.eth.get_transaction_count(acct.address)
    # Pre-populate gas to avoid provider-side estimation reverts; always send
    swap_tx_params = {
        "from": acct.address,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
        "gas": 800_000,
    }
    swap_tx = router.functions.swapExactTokensForTokens(
        int(weth_bal),
        int(min_pnk_wei),
        path,
        recipient,
        int(univ2_deadline),
    ).build_transaction(swap_tx_params)
    swap_tx.update(eip1559(w3))
    s3 = acct.sign_transaction(swap_tx)
    raw3 = getattr(s3, "rawTransaction", None) or getattr(s3, "raw_transaction", None)
    h3 = w3.eth.send_raw_transaction(raw3)
    print(f"Swapr swap (WETH->PNK): {h3.hex()}")
    rcpt = w3.eth.wait_for_transaction_receipt(h3)
    print(f"Success: {rcpt.status == 1}; Gas used: {rcpt.gasUsed}")


if __name__ == "__main__":
    main()
