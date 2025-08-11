"""Helper for simulating Balancer BatchRouter.swapExactIn (sell Company token → sDAI or buy Company token with sDAI) via Tenderly.

Assumes the sender wallet already approved the required amount of Company token or sDAI to the BatchRouter.
Only builds and simulates the swap transaction – **does not** broadcast it on-chain.

The helper exposes two public functions:

    • build_sell_gno_to_sdai_swap_tx(w3, client, amount_in_wei, min_amount_out_wei, sender)
        ↳ Returns a Tenderly-compatible transaction dict ready for simulation.

    • build_buy_gno_to_sdai_swap_tx(w3, client, amount_in_wei, min_amount_out_wei, sender)
        ↳ Returns a Tenderly-compatible transaction dict ready for simulation.

    • sell_gno_to_sdai(w3, client, amount_in_wei, min_amount_out_wei, sender)
        ↳ Convenience wrapper that builds the tx → triggers Tenderly simulation →
          pretty-prints & returns the simulation result.

Usage example::

    from decimal import Decimal
    import os
    from web3 import Web3
    from tenderly_api import TenderlyClient  # adjust import to your project layout
    from balancer_swap import sell_gno_to_sdai

    w3 = Web3(Web3.HTTPProvider(os.environ["GNOSIS_RPC_URL"]))
    client = TenderlyClient(w3)
    sender = os.environ["WALLET_ADDRESS"]

    # sell 0.1 Company token and require at least 1 sDAI out
    amt_in = w3.to_wei(Decimal("0.1"), "ether")
    min_out = w3.to_wei(Decimal("1"), "ether")

    sell_gno_to_sdai(w3, client, amt_in, min_out, sender)

The path hard-coded below is the canonical 2-hop Company token→WSTETH buffer→sDAI pool on
Gnosis at the time of writing (May 2025). Update the constants if Balancer
migrates liquidity.
"""

from __future__ import annotations

import os
import logging
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from eth_typing import ChecksumAddress
from web3 import Web3

# Removed Tenderly import - executing directly on-chain
# Keccak topic for ERC20 Transfer(address,address,uint256)
ERC20_TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Constants – update if the Balancer pool layout changes
# -----------------------------------------------------------------------------

# Tokens
COMPANY_TOKEN: ChecksumAddress = Web3.to_checksum_address("0x9c58bacc331c9aa871afd802db6379a98e80cedb")
SDAI: ChecksumAddress = Web3.to_checksum_address("0xaf204776c7245bf4147c2612bf6e5972ee483701")

# Pools (Gnosis)
BUFFER_POOL: ChecksumAddress = Web3.to_checksum_address("0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644")
FINAL_POOL: ChecksumAddress = Web3.to_checksum_address("0xd1d7fa8871d84d0e77020fc28b7cd5718c446522")

# Router selector for swapExactIn (batch router v5) – kept for reference
SWAP_EXACT_IN_SELECTOR = "0x286f580d"

# The maximum uint48 Balancer deadline used in the JS helper (2^53 − 1)
MAX_DEADLINE = 9007199254740991

# -----------------------------------------------------------------------------
# ABI loading
# -----------------------------------------------------------------------------

BALANCER_ROUTER_ABI: List[Dict[str, Any]] = [
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

# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

__all__ = [
    "build_sell_gno_to_sdai_swap_tx",
    "build_buy_gno_to_sdai_swap_tx",
    "sell_gno_to_sdai",
    "parse_simulated_swap_results",
    "parse_broadcasted_swap_results",
    "_search_call_trace",
]

def _search_call_trace(node: Dict[str, Any], target: str) -> Optional[Dict[str, Any]]:
    """Depth-first search for the first call to *target* in Tenderly call-trace."""
    if node.get("to", "").lower() == target.lower():
        return node
    for child in node.get("calls", []):
        found = _search_call_trace(child, target)
        if found:
            return found
    return None



def _get_router(w3: Web3, router_addr: str | None = None):
    """Return Balancer BatchRouter contract instance.

    The address is taken from the BALANCER_ROUTER_ADDRESS env var unless
    explicitly provided.
    """
    address = router_addr or os.getenv("BALANCER_ROUTER_ADDRESS")
    if address is None:
        raise EnvironmentError("Set BALANCER_ROUTER_ADDRESS env var or pass router_addr.")
    return w3.eth.contract(address=w3.to_checksum_address(address), abi=BALANCER_ROUTER_ABI)


# -----------------------------------------------------------------------------
# Build & simulate helpers
# -----------------------------------------------------------------------------

def build_sell_gno_to_sdai_swap_tx(
    w3: Web3,
    amount_in_wei: int,
    min_amount_out_wei: int,
    sender: str,
    *,
    router_addr: str | None = None,
    deadline: int = MAX_DEADLINE,
    weth_is_eth: bool = False,
    user_data: bytes = b"",
) -> Dict[str, Any]:
    """Build swapExactIn transaction for Company token → sDAI for direct blockchain execution."""

    router = _get_router(w3, router_addr)

    # SwapPathStep[] – two hops
    steps = [
        # 1️⃣ Company token → buffer token (pool uses the same token addr for tokenOut)
        (
            BUFFER_POOL,  # pool address
            BUFFER_POOL,  # tokenOut address (router expects this redundancy)
            True,  # isBuffer
        ),
        # 2️⃣ buffer token → sDAI
        (
            FINAL_POOL,
            SDAI,
            False,
        ),
    ]

    # SwapPathExactAmountIn
    path = (
        COMPANY_TOKEN,  # tokenIn
        steps,
        int(amount_in_wei),
        int(min_amount_out_wei),
    )

    # Build the transaction directly
    tx = router.functions.swapExactIn(
        [path], int(deadline), bool(weth_is_eth), user_data
    ).build_transaction({
        'from': w3.to_checksum_address(sender),
        'gas': 500000,  # Set a reasonable gas limit
        'gasPrice': w3.eth.gas_price,
        'nonce': w3.eth.get_transaction_count(w3.to_checksum_address(sender)),
    })
    
    return tx


def build_buy_gno_to_sdai_swap_tx(
    w3: Web3,
    amount_in_wei: int,
    min_amount_out_wei: int,
    sender: str,
    *,
    router_addr: str | None = None,
    deadline: int = MAX_DEADLINE,
    weth_is_eth: bool = False,
    user_data: bytes = b"",
) -> Dict[str, Any]:
    """Encode swapExactIn calldata for **buying Company token with sDAI**."""

    # Log all function arguments
    print(f"=== build_buy_gno_to_sdai_swap_tx ARGUMENTS ===")
    print(f"amount_in_wei: {amount_in_wei}")
    print(f"amount_in_ether: {w3.from_wei(amount_in_wei, 'ether')}")
    print(f"min_amount_out_wei: {min_amount_out_wei}")
    print(f"min_amount_out_ether: {w3.from_wei(min_amount_out_wei, 'ether')}")
    print(f"sender: {sender}")
    print(f"router_addr: {router_addr}")
    print(f"deadline: {deadline}")
    print(f"weth_is_eth: {weth_is_eth}")
    print(f"user_data: {user_data}")

    router = _get_router(w3, router_addr)
    print(f"router_address: {router.address}")

    # SwapPathStep[] – two hops (reverse order)
    steps = [
        # 1️⃣ sDAI → buffer token (direct pool swap)
        (
            FINAL_POOL,
            BUFFER_POOL,
            False,
        ),
        # 2️⃣ buffer token → Company token (buffer hop)
        (
            BUFFER_POOL,
            COMPANY_TOKEN,
            True,
        ),
    ]

    # Log swap path details
    print(f"=== SWAP PATH DETAILS ===")
    print(f"SDAI token address: {SDAI}")
    print(f"Company token address: {COMPANY_TOKEN}")
    print(f"FINAL_POOL: {FINAL_POOL}")
    print(f"BUFFER_POOL: {BUFFER_POOL}")
    print(f"steps: {steps}")

    # SwapPathExactAmountIn
    path = (
        SDAI,                     # tokenIn (sDAI)
        steps,
        int(amount_in_wei),       # exactAmountIn (sDAI)
        int(min_amount_out_wei),  # minAmountOut  (Company token)
    )

    print(f"=== SWAP PATH STRUCTURE ===")
    print(f"tokenIn: {path[0]}")
    print(f"steps: {path[1]}")
    print(f"exactAmountIn: {path[2]}")
    print(f"minAmountOut: {path[3]}")
    print("============================")

    # Build the transaction directly
    tx = router.functions.swapExactIn(
        [path], int(deadline), bool(weth_is_eth), user_data
    ).build_transaction({
        'from': w3.to_checksum_address(sender),
        'gas': 500000,  # Set a reasonable gas limit
        'gasPrice': w3.eth.gas_price,
        'nonce': w3.eth.get_transaction_count(w3.to_checksum_address(sender)),
    })
    
    print(f"=== BUILT TRANSACTION ===")
    print(f"to: {tx.get('to')}")
    print(f"from: {tx.get('from')}")
    print(f"gas: {tx.get('gas')}")
    print(f"gasPrice: {tx.get('gasPrice')}")
    print(f"nonce: {tx.get('nonce')}")
    print("========================")

    return tx


def sell_gno_to_sdai(
    w3: Web3,
    amount_in_wei: int,
    min_amount_out_wei: int,
    sender: str,
    private_key: str,
    *,
    router_addr: str | None = None,
) -> Optional[str]:
    """Build and execute swap transaction directly on blockchain."""

    tx = build_sell_gno_to_sdai_swap_tx(
        w3,
        amount_in_wei,
        min_amount_out_wei,
        sender,
        router_addr=router_addr,
    )

    # Sign and send the transaction
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    logger.info(f"Transaction sent: {tx_hash.hex()}")
    logger.info(f"Waiting for confirmation...")
    
    # Wait for transaction receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    
    if receipt.status == 1:
        logger.info(f"✅ Swap successful! TX: {tx_hash.hex()}")
        logger.info(f"Gas used: {receipt.gasUsed}")
        # Parse the results from the receipt
        result = parse_broadcasted_swap_results(tx_hash.hex())
        if result:
            logger.info(f"Swapped {result['input_amount']} for {result['output_amount']}")
    else:
        logger.error(f"❌ Transaction reverted! TX: {tx_hash.hex()}")
    
    return tx_hash.hex()


# -----------------------------------------------------------------------------
# Result parsing / pretty printing
# -----------------------------------------------------------------------------

def _wei_to_eth(value: int) -> Decimal:
    return Decimal(Web3.from_wei(value, "ether"))

# --------------------------------------------------------------------------- #
# On-chain result parser (broadcasted swaps)                                  #
# --------------------------------------------------------------------------- #
def parse_broadcasted_swap_results(tx_hash: str) -> Optional[Dict[str, Decimal]]:
    """
    Given a *broadcasted* Balancer ``swapExactIn`` tx hash, return
    ``{"input_amount": Decimal, "output_amount": Decimal}``
    (values in ether units). Mirrors the semantics of the helper in
    ``swapr_swap.py`` so the same handlers work for either exchange.
    """

    w3 = _build_w3_from_env()
    router = _get_router(w3)

    tx = w3.eth.get_transaction(tx_hash)
    if not tx or tx.to.lower() != router.address.lower():
        return None

    time.sleep(5)
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    if receipt.status != 1:  # reverted / failed
        return None

    # ------------------------------------------------------------------ #
    # Decode calldata to fetch exactAmountIn                             #
    # ------------------------------------------------------------------ #
    func_obj, func_params = router.decode_function_input(tx.input)
    if func_obj.fn_name != "swapExactIn":
        return None

    paths = (
        func_params[0]                      # positional
        if not isinstance(func_params, dict)
        else next(iter(func_params.values()))  # dict
    )
    first_path = paths[0]
    exact_in_wei = first_path[2] if isinstance(first_path, (list, tuple)) else first_path["exactAmountIn"]

    # ------------------------------------------------------------------ #
    # Locate Transfer(SDAI -> sender) in logs                            #
    # ------------------------------------------------------------------ #
    sender = tx["from"]
    output_wei = 0
    for log in receipt.logs:
        if not log.topics or log.topics[0].hex().lower() != ERC20_TRANSFER_TOPIC.lower():
            continue
        if len(log.topics) < 3:
            continue
        to_addr = "0x" + log.topics[2].hex()[26:]
        if to_addr.lower() == sender.lower() and log.address.lower() in (SDAI.lower(), COMPANY_TOKEN.lower()):
            transferred = int(log.data.hex(), 16) if hasattr(log.data, "hex") else int(log.data, 16)
            output_wei += transferred

    return {
        "input_amount":  _wei_to_eth(exact_in_wei),
        "output_amount": _wei_to_eth(output_wei),
    }


def parse_simulated_swap_results(results: List[Dict[str, Any]], w3: Web3) -> Optional[Dict[str, Decimal]]:
    """Pretty-print and return {'input_amount', 'output_amount'} for each result."""
    result_dict: Optional[Dict[str, Decimal]] = None
    for idx, sim in enumerate(results):
        header = (
            "Balancer Simulation Result"
            if len(results) == 1
            else f"Balancer Simulation Result #{idx + 1}"
        )
        logger.debug("--- %s ---", header)

        if sim.get("error"):
            logger.debug("Tenderly simulation error: %s", sim["error"].get("message", "Unknown error"))
            continue
        tx = sim.get("transaction")
        if not tx:
            logger.debug("No transaction data in result.")
            continue
        if tx.get("status") is False:
            info = tx.get("transaction_info", {})
            reason = info.get("error_message", info.get("revert_reason", "N/A"))
            logger.debug("swapExactIn REVERTED. Reason: %s", reason)
            continue

        call_trace = tx.get("transaction_info", {}).get("call_trace", {})
        router = _get_router(w3)
        router_call = _search_call_trace(call_trace, router.address)
        if router_call is None:
            continue
        func, params = router.decode_function_input(router_call["input"])

        if isinstance(params, dict):
            param_val = next(iter(params.values()))
        else:
            param_val = params[0]

        if not param_val:
            logger.debug("Decoded params empty – cannot find paths.")
            continue

        first_path = param_val[0] if isinstance(param_val, (list, tuple)) else next(iter(param_val.values()))
        if isinstance(first_path, (list, tuple)):
            exact_amount_in = first_path[2]
        else:
            exact_amount_in = first_path.get("exactAmountIn") or first_path.get("amountIn")

        if exact_amount_in is None:
            continue

        decoded = w3.codec.decode(["uint256[]", "address[]", "uint256[]"],
                                  bytes.fromhex(router_call["output"][2:]))
        output_wei = decoded[2][0]
        result_dict = {
            "input_amount": _wei_to_eth(exact_amount_in),
            "output_amount": _wei_to_eth(output_wei),
        }
        logger.debug("swapExactIn succeeded.")
        logger.debug("result_dict: %s", result_dict)
        balance_changes = sim.get("balance_changes") or {}
        if balance_changes:
            logger.debug("Balance changes:")
            for token_addr, diff in balance_changes.items():
                human = _wei_to_eth(abs(int(diff)))
                sign = "+" if int(diff) > 0 else "-"
                logger.debug("  %s: %s%s", token_addr, sign, human)
        else:
            logger.debug("(No balance change info)")
    return result_dict




# -----------------------------------------------------------------------------
# CLI helper for quick testing –  `python -m balancer_swap --amount_in 0.1`
# -----------------------------------------------------------------------------

def _build_w3_from_env() -> Web3:
    """Return Web3 instance connected to the RPC endpoint in the GNOSIS_RPC_URL env var."""
    rpc_url = os.getenv("GNOSIS_RPC_URL") or os.getenv("RPC_URL")
    if rpc_url is None:
        raise EnvironmentError("Set GNOSIS_RPC_URL or RPC_URL in environment.")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    from web3.middleware import ExtraDataToPOAMiddleware

    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def main():  # pragma: no cover
    """Quick manual test for direct blockchain execution."""
    import argparse
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Execute Balancer swap directly on blockchain")
    parser.add_argument("--amount_in", type=float, default=0.1,
                        help="Token amount to swap (ether units)")
    parser.add_argument("--min_out", type=float, default=1.0,
                        help="Minimum acceptable amount out (ether units)")
    parser.add_argument("--sell_gno", type=str, choices=["true", "false"], default="true",
                        help="true (default) → sell Company token for sDAI; false → buy Company token with sDAI")
    parser.add_argument("--execute", action="store_true",
                        help="Actually execute the transaction on-chain (requires PRIVATE_KEY)")
    args = parser.parse_args()

    sender = os.getenv("WALLET_ADDRESS") or os.getenv("SENDER_ADDRESS")
    if sender is None:
        raise EnvironmentError("Set WALLET_ADDRESS or SENDER_ADDRESS env var.")

    w3 = _build_w3_from_env()
    if not w3.is_connected():
        raise ConnectionError("Could not connect to RPC endpoint.")

    amount_in_wei = w3.to_wei(Decimal(str(args.amount_in)), "ether")
    min_out_wei = w3.to_wei(Decimal(str(args.min_out)), "ether")

    if args.execute:
        # Execute on-chain
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            raise EnvironmentError("Set PRIVATE_KEY env var to execute transactions.")
        
        if args.sell_gno.lower() == "true":
            tx_hash = sell_gno_to_sdai(w3, amount_in_wei, min_out_wei, sender, private_key)
            print(f"Transaction hash: {tx_hash}")
        else:
            # Buy Company token with sDAI
            tx = build_buy_gno_to_sdai_swap_tx(
                w3, amount_in_wei, min_out_wei, sender
            )
            signed_tx = w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            print(f"Transaction sent: {tx_hash.hex()}")
            print(f"Waiting for confirmation...")
            
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                print(f"✅ Swap successful! TX: {tx_hash.hex()}")
                print(f"Gas used: {receipt.gasUsed}")
                result = parse_broadcasted_swap_results(tx_hash.hex())
                if result:
                    print(f"Swapped {result['input_amount']} for {result['output_amount']}")
            else:
                print(f"❌ Transaction reverted! TX: {tx_hash.hex()}")
    else:
        # Just build and display the transaction
        if args.sell_gno.lower() == "true":
            tx = build_sell_gno_to_sdai_swap_tx(
                w3, amount_in_wei, min_out_wei, sender
            )
        else:
            tx = build_buy_gno_to_sdai_swap_tx(
                w3, amount_in_wei, min_out_wei, sender
            )
        
        print("\n📦 Transaction Built (not executed):")
        print(f"To: {tx['to']}")
        print(f"From: {tx['from']}")
        print(f"Gas: {tx['gas']}")
        print(f"Gas Price: {w3.from_wei(tx['gasPrice'], 'gwei')} gwei")
        print(f"Value: {tx['value']}")
        print(f"\nTo execute, add --execute flag and ensure PRIVATE_KEY is set.")


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.DEBUG)
    main()
