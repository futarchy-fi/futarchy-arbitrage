# src/arbitrage_commands/sell_cond_onchain.py
"""
On‑chain version of sell_cond.py – **never** calls Tenderly.
Public function:
    sell_gno_yes_and_no_amounts_to_sdai(sdai_amount) -> List[HexBytes]
"""

import os
from decimal import Decimal
from eth_account import Account
from web3 import Web3, HTTPProvider
from typing import List, Dict

from helpers.swapr_swap      import w3 as _w3
from config.abis.futarchy import FUTARCHY_ROUTER_ABI
from config.abis.swapr import SWAPR_ROUTER_ABI
from eth_typing import ChecksumAddress
import time

# --------------------------------------------------------------------------- #
# Init                                                                        #
# --------------------------------------------------------------------------- #
w3: Web3 = _w3 or Web3(HTTPProvider(os.environ["RPC_URL"]))
acct     = Account.from_key(os.environ["PRIVATE_KEY"])

router_addr      = w3.to_checksum_address(os.environ["FUTARCHY_ROUTER_ADDRESS"])
proposal_addr    = w3.to_checksum_address(os.environ["FUTARCHY_PROPOSAL_ADDRESS"])
collateral_addr  = w3.to_checksum_address(os.environ["SDAI_TOKEN_ADDRESS"])
gno_collateral   = w3.to_checksum_address(os.environ["GNO_TOKEN_ADDRESS"])

token_yes_in  = w3.to_checksum_address(os.environ["SWAPR_GNO_YES_ADDRESS"])
token_yes_out = w3.to_checksum_address(os.environ["SWAPR_SDAI_YES_ADDRESS"])
token_no_in   = w3.to_checksum_address(os.environ["SWAPR_GNO_NO_ADDRESS"])
token_no_out  = w3.to_checksum_address(os.environ["SWAPR_SDAI_NO_ADDRESS"])

# Balancer constants
GNO: ChecksumAddress = w3.to_checksum_address("0x9c58bacc331c9aa871afd802db6379a98e80cedb")
SDAI: ChecksumAddress = w3.to_checksum_address("0xaf204776c7245bf4147c2612bf6e5972ee483701")
BUFFER_POOL: ChecksumAddress = w3.to_checksum_address("0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644")
FINAL_POOL: ChecksumAddress = w3.to_checksum_address("0xd1d7fa8871d84d0e77020fc28b7cd5718c446522")
MAX_DEADLINE = 9007199254740991

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


# --------------------------------------------------------------------------- #
# On-chain helper functions (no Tenderly)                                     #
# --------------------------------------------------------------------------- #
def build_buy_gno_to_sdai_swap_tx_onchain(
    amount_in_wei: int,
    min_amount_out_wei: int,
    sender: str,
) -> Dict:
    """Build buy GNO with sDAI swap transaction without Tenderly client."""
    router_addr = os.environ["BALANCER_ROUTER_ADDRESS"]
    router = w3.eth.contract(address=w3.to_checksum_address(router_addr), abi=BALANCER_ROUTER_ABI)

    # SwapPathStep[] – two hops (reverse order for buying GNO with sDAI)
    steps = [
        # 1️⃣ sDAI → buffer token (direct pool swap)
        (FINAL_POOL, BUFFER_POOL, False),
        # 2️⃣ buffer token → GNO (buffer hop)
        (BUFFER_POOL, GNO, True),
    ]

    # SwapPathExactAmountIn
    path = (
        SDAI,                     # tokenIn (sDAI)
        steps,
        int(amount_in_wei),       # exactAmountIn (sDAI)
        int(min_amount_out_wei),  # minAmountOut  (GNO)
    )

    calldata = router.encodeABI(
        fn_name="swapExactIn",
        args=[[path], int(MAX_DEADLINE), False, b""],
    )

    return {
        "to": router.address,
        "data": calldata,
        "from": sender,
        "gas": 500000,
        "value": 0,
    }


def build_exact_in_tx_onchain(
    token_in: str,
    token_out: str,
    amount_in_wei: int,
    amount_out_min_wei: int,
    sender: str,
) -> Dict:
    """Build exactInputSingle transaction without Tenderly client."""
    router_addr = os.environ["SWAPR_ROUTER_ADDRESS"]
    router = w3.eth.contract(address=w3.to_checksum_address(router_addr), abi=SWAPR_ROUTER_ABI)
    
    params = (
        w3.to_checksum_address(token_in),
        w3.to_checksum_address(token_out),
        w3.to_checksum_address(sender),
        int(time.time()) + 600,  # deadline
        int(amount_in_wei),
        int(amount_out_min_wei),
        0,  # sqrt_price_limit
    )
    data = router.encodeABI(fn_name="exactInputSingle", args=[params])
    
    return {
        "to": router.address,
        "data": data,
        "from": sender,
        "gas": 500000,
        "value": 0,
    }


def build_split_tx_onchain(
    router_addr: str,
    proposal_addr: str,
    collateral_addr: str,
    amount_wei: int,
    sender: str,
) -> Dict:
    """Build splitPosition transaction without Tenderly client."""
    router = w3.eth.contract(address=w3.to_checksum_address(router_addr), abi=FUTARCHY_ROUTER_ABI)
    data = router.encodeABI(
        fn_name="splitPosition",
        args=[
            w3.to_checksum_address(proposal_addr),
            w3.to_checksum_address(collateral_addr),
            int(amount_wei),
        ],
    )
    return {
        "to": router.address,
        "data": data,
        "from": sender,
        "gas": 500000,
        "value": 0,
    }


def build_merge_tx_onchain(
    router_addr: str,
    proposal_addr: str,
    collateral_addr: str,
    amount_wei: int,
    sender: str,
) -> Dict:
    """Build mergePositions transaction without Tenderly client."""
    router = w3.eth.contract(address=w3.to_checksum_address(router_addr), abi=FUTARCHY_ROUTER_ABI)
    data = router.encodeABI(
        fn_name="mergePositions",
        args=[
            w3.to_checksum_address(proposal_addr),
            w3.to_checksum_address(collateral_addr),
            int(amount_wei),
        ],
    )
    return {
        "to": router.address,
        "data": data,
        "from": sender,
        "gas": 500000,
        "value": 0,
    }


# --------------------------------------------------------------------------- #
# Core helper – sign & send                                                   #
# --------------------------------------------------------------------------- #
def _send_bundle(bundle: List[Dict]) -> List[str]:
    """Sign and send every tx in *bundle* using sequential nonces."""
    start_nonce = w3.eth.get_transaction_count(acct.address)
    gas_price   = w3.eth.gas_price
    hashes: List[str] = []

    for i, tx in enumerate(bundle):
        tx_for_signing = {
            **tx,
            "chainId": w3.eth.chain_id,
            "gasPrice": gas_price,
            "nonce": start_nonce + i,
        }
        signed = acct.sign_transaction(tx_for_signing)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        hashes.append(tx_hash.hex())

    return hashes


# --------------------------------------------------------------------------- #
# Public entry‑point                                                          #
# --------------------------------------------------------------------------- #
def sell_gno_yes_and_no_amounts_to_sdai(sdai_amount: float) -> List[str]:
    """
    Execute the sell trade sequence **without** simulation:
        1. buy GNO with sDAI via Balancer
        2. split GNO into conditional GNO
        3. swap both conditional GNO legs to conditional sDAI
        4. merge conditional sDAI back to plain sDAI
    Returns the list of transaction hashes.
    """
    sdai_amount_wei = w3.to_wei(Decimal(sdai_amount), "ether")

    # ▶ 1 buy GNO with sDAI via Balancer
    buy_gno_tx = build_buy_gno_to_sdai_swap_tx_onchain(
        sdai_amount_wei, 1, acct.address
    )

    # ▶ 2 split the resulting GNO (using 0 for amount to use available balance)
    split_tx = build_split_tx_onchain(
        router_addr, proposal_addr,
        gno_collateral, 0, acct.address
    )

    # ▶ 3 swap both conditional GNO to conditional sDAI (exact‑in, best‑effort)
    # We use 0 as the input amount to swap all available conditional GNO
    yes_swap = build_exact_in_tx_onchain(token_yes_in, token_yes_out,
                                         0, 1, acct.address)
    no_swap  = build_exact_in_tx_onchain(token_no_in,  token_no_out,
                                         0, 1, acct.address)

    # ▶ 4 merge conditional sDAI back to plain sDAI
    merge_tx = build_merge_tx_onchain(
        router_addr, proposal_addr,
        collateral_addr, 0, acct.address
    )

    bundle = [buy_gno_tx, split_tx, yes_swap, no_swap, merge_tx]
    return _send_bundle(bundle) 