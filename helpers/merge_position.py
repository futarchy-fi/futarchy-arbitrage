"""Helper for simulating FutarchyRouter.mergePositions via Tenderly.

Assumes the collateral ERC-20 is already approved for the FutarchyRouter.
Only builds and simulates the merge transaction – does **not** send it.

Usage (example):

```python
from web3 import Web3
from futarchy.experimental.config.abis.futarchy import FUTARCHY_ROUTER_ABI
from futarchy.experimental.exchanges.simulator.tenderly_api import TenderlyClient
from futarchy.experimental.exchanges.simulator.helpers.merge_position import (
    build_merge_tx,
    simulate_merge,
)

w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))
client = TenderlyClient(w3)
router_addr = w3.to_checksum_address(os.environ["FUTARCHY_ROUTER_ADDRESS"])
proposal_addr = w3.to_checksum_address(os.environ["FUTARCHY_PROPOSAL_ADDRESS"])
collateral_addr = w3.to_checksum_address(os.environ["COLLATERAL_TOKEN_ADDRESS"])
amount_wei = w3.to_wei(1, "ether")

result = simulate_merge(
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

import os
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional
from web3 import Web3

from futarchy.experimental.config.abis.futarchy import FUTARCHY_ROUTER_ABI
from .tenderly_api import TenderlyClient

logger = logging.getLogger(__name__)

__all__ = [
    "build_merge_tx",
    "simulate_merge",
    "parse_merge_results",
]


def _get_router(w3: Web3, router_addr: str):
    """Return FutarchyRouter contract instance."""
    return w3.eth.contract(address=w3.to_checksum_address(router_addr), abi=FUTARCHY_ROUTER_ABI)


def build_merge_tx(
    w3: Web3,
    client: TenderlyClient,
    router_addr: str,
    proposal_addr: str,
    collateral_addr: str,
    amount_wei: int,
    sender: str,
) -> Dict[str, Any]:
    """Encode mergePositions calldata and wrap into a Tenderly tx dict."""
    router = _get_router(w3, router_addr)
    data = router.encodeABI(
        fn_name="mergePositions",
        args=[
            w3.to_checksum_address(proposal_addr),
            w3.to_checksum_address(collateral_addr),
            int(amount_wei),
        ],
    )
    return client.build_tx(router.address, data, sender)


def simulate_merge(
    w3: Web3,
    client: TenderlyClient,
    router_addr: str,
    proposal_addr: str,
    collateral_addr: str,
    amount_wei: int,
    sender: str,
) -> Optional[Dict[str, Any]]:
    """Convenience function: build tx → simulate → return result dict."""
    tx = build_merge_tx(
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
        parse_merge_results(result["simulation_results"], w3)
    else:
        logger.debug("Simulation failed or returned no results.")
    return result


def parse_merge_results(results: List[Dict[str, Any]], w3: Web3) -> None:
    """Pretty-print each simulation result from mergePositions bundle."""
    for idx, sim in enumerate(results):
        logger.debug("--- Merge Simulation Result #%s ---", idx + 1)

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
            logger.debug("mergePositions REVERTED. Reason: %s", reason)
            continue

        logger.debug("mergePositions succeeded.")

        balance_changes = sim.get("balance_changes") or {}
        if balance_changes:
            logger.debug("Balance changes:")
            for token_addr, diff in balance_changes.items():
                human = Decimal(w3.from_wei(abs(int(diff)), "ether"))
                sign = "+" if int(diff) > 0 else "-"
                logger.debug("  %s: %s%s", token_addr, sign, human)
        else:
            logger.debug("(No balance change info)")


# ---------- CLI entry for quick testing ----------


def _build_w3_from_env() -> Web3:
    """Return a Web3 instance using RPC_URL (fallback to GNOSIS_RPC_URL)."""
    rpc_url = os.getenv("RPC_URL") or os.getenv("GNOSIS_RPC_URL")
    if rpc_url is None:
        raise EnvironmentError("Set RPC_URL or GNOSIS_RPC_URL in environment.")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    from web3.middleware import geth_poa_middleware

    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    return w3


def main():  # pragma: no cover
    """Quick manual test: python -m ...merge_position --amount 1"""
    import argparse
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Simulate FutarchyRouter.mergePositions via Tenderly")
    parser.add_argument("--amount", type=float, default=1.0, help="Collateral amount in ether to merge")
    args = parser.parse_args()

    router_addr = os.getenv("FUTARCHY_ROUTER_ADDRESS")
    proposal_addr = os.getenv("FUTARCHY_PROPOSAL_ADDRESS")
    collateral_addr = os.getenv("GNO_TOKEN_ADDRESS")
    sender = os.getenv("WALLET_ADDRESS") or os.getenv("SENDER_ADDRESS")

    missing = [n for n, v in {
        "FUTARCHY_ROUTER_ADDRESS": router_addr,
        "FUTARCHY_PROPOSAL_ADDRESS": proposal_addr,
        "GNO_TOKEN_ADDRESS": collateral_addr,
        "WALLET_ADDRESS/SENDER_ADDRESS": sender,
    }.items() if v is None]
    if missing:
        logger.debug("Missing env vars: %s", ", ".join(missing))
        return

    w3 = _build_w3_from_env()
    if not w3.is_connected():
        logger.debug("Could not connect to RPC endpoint.")
        return

    client = TenderlyClient(w3)
    amount_wei = w3.to_wei(Decimal(str(args.amount)), "ether")
    simulate_merge(
        w3,
        client,
        router_addr,
        proposal_addr,
        collateral_addr,
        amount_wei,
        sender,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
