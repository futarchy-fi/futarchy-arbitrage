"""Helper for simulating FutarchyRouter.splitPosition via Tenderly.

Assumes the collateral ERC-20 is already approved for the FutarchyRouter.
Only builds and simulates the split transaction – does **not** send it.

Usage (example):

```python
from web3 import Web3
from .config.abis.futarchy import FUTARCHY_ROUTER_ABI
from .exchanges.simulator.tenderly_api import TenderlyClient
from .exchanges.simulator.helpers.split_position import (
    build_split_tx,
    simulate_split,
)

w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
client = TenderlyClient(w3)
router_addr = w3.to_checksum_address(os.environ["FUTARCHY_ROUTER_ADDRESS"])
proposal_addr = w3.to_checksum_address(os.environ["FUTARCHY_PROPOSAL_ADDRESS"])
collateral_addr = w3.to_checksum_address(os.environ["COLLATERAL_TOKEN_ADDRESS"])
amount_wei = w3.to_wei(1, "ether")

result = simulate_split(
    w3,
    client,
    router_addr,
    proposal_addr,
    collateral_addr,
    amount_wei,
    os.environ["WALLET_ADDRESS"],
)
```
"""

from typing import Dict, Any, List, Optional
import os
import logging
from web3 import Web3
from decimal import Decimal

from src.config.abis.futarchy import FUTARCHY_ROUTER_ABI
from src.helpers.tenderly_api import TenderlyClient

# Initialize logger
logger = logging.getLogger(__name__)
# Basic console handler
ch = logging.StreamHandler()
logger.addHandler(ch)
logger.setLevel(logging.DEBUG)

__all__ = [
    "build_split_tx",
    "simulate_split",
    "parse_split_results",
]


def _get_router(w3: Web3, router_addr: str):
    """Return FutarchyRouter contract instance."""
    return w3.eth.contract(address=w3.to_checksum_address(router_addr), abi=FUTARCHY_ROUTER_ABI)


def build_split_tx(
    w3: Web3,
    client: TenderlyClient,
    router_addr: str,
    proposal_addr: str,
    collateral_addr: str,
    amount_wei: int,
    sender: str,
) -> Dict[str, Any]:
    """Encode splitPosition calldata and wrap into a Tenderly tx dict."""
    router = _get_router(w3, router_addr)
    data = router.encodeABI(
        fn_name="splitPosition",
        args=[
            w3.to_checksum_address(proposal_addr),
            w3.to_checksum_address(collateral_addr),
            int(amount_wei),
        ],
    )
    return client.build_tx(router.address, data, sender)


def simulate_split(
    w3: Web3,
    client: TenderlyClient,
    router_addr: str,
    proposal_addr: str,
    collateral_addr: str,
    amount_wei: int,
    sender: str,
) -> Optional[Dict[str, Any]]:
    """Convenience function: build tx → simulate → return result dict."""
    tx = build_split_tx(
        w3,
        client,
        router_addr,
        proposal_addr,
        collateral_addr,
        amount_wei,
        sender,
    )
    result = client.simulate([tx])
    if result and result.get("simulation_results"):
        parse_split_results(result["simulation_results"], w3)
    else:
        logger.debug("Simulation failed or returned no results.")
    return result


def parse_split_results(results: List[Dict[str, Any]], w3: Web3) -> None:
    """Pretty-print each simulation result from splitPosition bundle."""
    for idx, sim in enumerate(results):
        logger.debug(f"\n--- Split Simulation Result #{idx + 1} ---")

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
            logger.debug("splitPosition REVERTED. Reason: %s", reason)
            continue

        logger.debug("splitPosition succeeded.")

        # Optional: pick up token balance diffs if Tenderly provides them
        balance_changes = sim.get("balance_changes") or {}
        if balance_changes:
            logger.debug("Balance changes:")
            for token_addr, diff in balance_changes.items():
                human = Decimal(w3.from_wei(abs(int(diff)), "ether"))
                sign = "+" if int(diff) > 0 else "-"
                logger.debug(f"  {token_addr}: {sign}{human}")
        else:
            logger.debug("(No balance change info)")


# ---------- CLI entry for quick testing ----------

def _build_w3_from_env() -> Web3:
    """Return a Web3 instance using RPC_URL (fallback to GNOSIS_RPC_URL)."""
    rpc_url = os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL")
    if rpc_url is None:
        raise EnvironmentError("Set RPC_URL or GNOSIS_RPC_URL in environment.")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    # Inject POA middleware for Gnosis
    from web3.middleware import geth_poa_middleware
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    return w3


def main():  # pragma: no cover
    """Quick manual test: python -m ...split_position --amount 1"""
    import argparse
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Simulate FutarchyRouter.splitPosition via Tenderly")
    parser.add_argument("--amount", type=float, default=1.0, help="Collateral amount in ether to split")
    args = parser.parse_args()

    # Required env vars
    router_addr = os.getenv("FUTARCHY_ROUTER_ADDRESS")
    proposal_addr = os.getenv("FUTARCHY_PROPOSAL_ADDRESS")
    collateral_addr = os.getenv("COLLATERAL_TOKEN_ADDRESS")
    sender = os.getenv("WALLET_ADDRESS") or os.getenv("SENDER_ADDRESS")

    missing = [n for n, v in {
        "FUTARCHY_ROUTER_ADDRESS": router_addr,
        "FUTARCHY_PROPOSAL_ADDRESS": proposal_addr,
        "COLLATERAL_TOKEN_ADDRESS": collateral_addr,
        "WALLET_ADDRESS/SENDER_ADDRESS": sender,
    }.items() if v is None]
    if missing:
        logger.error("Missing env vars: %s", ", ".join(missing))
        return

    w3 = _build_w3_from_env()
    if not w3.is_connected():
        logger.error("Could not connect to RPC endpoint.")
        return

    client = TenderlyClient(w3)
    amount_wei = w3.to_wei(Decimal(str(args.amount)), "ether")
    results = simulate_split(
        w3,
        client,
        router_addr,
        proposal_addr,
        collateral_addr,
        amount_wei,
        sender,
    )
    
    tx = results["simulation_results"][0]["transaction"]
    # Successful transaction
    logger.debug("Split transaction did NOT revert.")
    tx_info = tx.get("transaction_info", {})
    call_trace = tx_info.get("call_trace", {})
    output_hex = call_trace.get("output")
    logger.debug("output_hex = %s", output_hex)


if __name__ == "__main__":  # pragma: no cover
    main()
