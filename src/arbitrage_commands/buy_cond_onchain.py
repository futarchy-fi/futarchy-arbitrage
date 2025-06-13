# src/arbitrage_commands/buy_cond_onchain.py
"""
On‑chain version of buy_cond.py – **never** calls Tenderly.
Public function:
    buy_gno_yes_and_no_amounts_with_sdai(sdai_amount) -> List[HexBytes]
"""

import os
from decimal import Decimal
from eth_account import Account
from web3 import Web3, HTTPProvider
from typing import List, Dict

from helpers.swapr_swap      import w3 as _w3
from config.abis.futarchy import FUTARCHY_ROUTER_ABI
from config.abis.swapr import SWAPR_ROUTER_ABI
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

token_yes_in  = w3.to_checksum_address(os.environ["SWAPR_SDAI_YES_ADDRESS"])
token_yes_out = w3.to_checksum_address(os.environ["SWAPR_GNO_YES_ADDRESS"])
token_no_in   = w3.to_checksum_address(os.environ["SWAPR_SDAI_NO_ADDRESS"])
token_no_out  = w3.to_checksum_address(os.environ["SWAPR_GNO_NO_ADDRESS"])


# --------------------------------------------------------------------------- #
# On-chain helper functions (no Tenderly)                                     #
# --------------------------------------------------------------------------- #
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
def buy_gno_yes_and_no_amounts_with_sdai(sdai_amount: float) -> List[str]:
    """
    Execute the 3‑step trade sequence **without** simulation:
        1. split sDAI ➜ sDAI‑YES + sDAI‑NO
        2. swap both conditional legs to GNO
        3. merge conditional GNO back to plain GNO
    Returns the list of transaction hashes.
    """
    split_amount = w3.to_wei(Decimal(sdai_amount), "ether")

    # ▶ 1 split
    split_tx = build_split_tx_onchain(
        router_addr, proposal_addr,
        collateral_addr, split_amount, acct.address
    )

    # ▶ 2 both Swapr swaps (exact‑in, best‑effort)
    yes_swap = build_exact_in_tx_onchain(token_yes_in, token_yes_out,
                                         split_amount, 1, acct.address)
    no_swap  = build_exact_in_tx_onchain(token_no_in,  token_no_out,
                                         split_amount, 1, acct.address)

    # ▶ 3 merge
    merge_tx = build_merge_tx_onchain(
        router_addr, proposal_addr,
        gno_collateral, 0, acct.address
    )

    bundle = [split_tx, yes_swap, no_swap, merge_tx]
    return _send_bundle(bundle) 