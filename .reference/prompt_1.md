Create balancer_swap.py file with the following content, the objective is a function sell_gno_to_sdai(amountIn, minAmountOut) and a build_sell_gno_to_sdai_swap_tx(amountIn, minAmountOut) that simulate a swap on tenderly:

Relevant Router ABI:
<abi>
[{"inputs":[{"internalType":"contract IVault","name":"vault","type":"address"},{"internalType":"contract IWETH","name":"weth","type":"address"},{"internalType":"contract IPermit2","name":"permit2","type":"address"},{"internalType":"string","name":"routerVersion","type":"string"}],"stateMutability":"nonpayable","type":"constructor"},{"inputs":[{"internalType":"address","name":"target","type":"address"}],"name":"AddressEmptyCode","type":"error"},{"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"AddressInsufficientBalance","type":"error"},{"inputs":[],"name":"ErrorSelectorNotFound","type":"error"},{"inputs":[],"name":"EthTransfer","type":"error"},{"inputs":[],"name":"FailedInnerCall","type":"error"},{"inputs":[],"name":"InputLengthMismatch","type":"error"},{"inputs":[],"name":"InsufficientEth","type":"error"},{"inputs":[],"name":"ReentrancyGuardReentrantCall","type":"error"},{"inputs":[{"internalType":"uint8","name":"bits","type":"uint8"},{"internalType":"uint256","name":"value","type":"uint256"}],"name":"SafeCastOverflowedUintDowncast","type":"error"},{"inputs":[{"internalType":"address","name":"token","type":"address"}],"name":"SafeERC20FailedOperation","type":"error"},{"inputs":[{"internalType":"address","name":"sender","type":"address"}],"name":"SenderIsNotVault","type":"error"},{"inputs":[],"name":"SwapDeadline","type":"error"},{"inputs":[],"name":"TransientIndexOutOfBounds","type":"error"},{"inputs":[],"name":"getSender","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"bytes[]","name":"data","type":"bytes[]"}],"name":"multicall","outputs":[{"internalType":"bytes[]","name":"results","type":"bytes[]"}],"stateMutability":"payable","type":"function"},{"inputs":[{"components":[{"internalType":"address","name":"token","type":"address"},{"internalType":"address","name":"owner","type":"address"},{"internalType":"address","name":"spender","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"},{"internalType":"uint256","name":"nonce","type":"uint256"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"internalType":"struct IRouterCommon.PermitApproval[]","name":"permitBatch","type":"tuple[]"},{"internalType":"bytes[]","name":"permitSignatures","type":"bytes[]"},{"components":[{"components":[{"internalType":"address","name":"token","type":"address"},{"internalType":"uint160","name":"amount","type":"uint160"},{"internalType":"uint48","name":"expiration","type":"uint48"},{"internalType":"uint48","name":"nonce","type":"uint48"}],"internalType":"struct IAllowanceTransfer.PermitDetails[]","name":"details","type":"tuple[]"},{"internalType":"address","name":"spender","type":"address"},{"internalType":"uint256","name":"sigDeadline","type":"uint256"}],"internalType":"struct IAllowanceTransfer.PermitBatch","name":"permit2Batch","type":"tuple"},{"internalType":"bytes","name":"permit2Signature","type":"bytes"},{"internalType":"bytes[]","name":"multicallData","type":"bytes[]"}],"name":"permitBatchAndCall","outputs":[{"internalType":"bytes[]","name":"results","type":"bytes[]"}],"stateMutability":"payable","type":"function"},{"inputs":[{"components":[{"internalType":"contract IERC20","name":"tokenIn","type":"address"},{"components":[{"internalType":"address","name":"pool","type":"address"},{"internalType":"contract IERC20","name":"tokenOut","type":"address"},{"internalType":"bool","name":"isBuffer","type":"bool"}],"internalType":"struct IBatchRouter.SwapPathStep[]","name":"steps","type":"tuple[]"},{"internalType":"uint256","name":"exactAmountIn","type":"uint256"},{"internalType":"uint256","name":"minAmountOut","type":"uint256"}],"internalType":"struct IBatchRouter.SwapPathExactAmountIn[]","name":"paths","type":"tuple[]"},{"internalType":"address","name":"sender","type":"address"},{"internalType":"bytes","name":"userData","type":"bytes"}],"name":"querySwapExactIn","outputs":[{"internalType":"uint256[]","name":"pathAmountsOut","type":"uint256[]"},{"internalType":"address[]","name":"tokensOut","type":"address[]"},{"internalType":"uint256[]","name":"amountsOut","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"components":[{"internalType":"address","name":"sender","type":"address"},{"components":[{"internalType":"contract IERC20","name":"tokenIn","type":"address"},{"components":[{"internalType":"address","name":"pool","type":"address"},{"internalType":"contract IERC20","name":"tokenOut","type":"address"},{"internalType":"bool","name":"isBuffer","type":"bool"}],"internalType":"struct IBatchRouter.SwapPathStep[]","name":"steps","type":"tuple[]"},{"internalType":"uint256","name":"exactAmountIn","type":"uint256"},{"internalType":"uint256","name":"minAmountOut","type":"uint256"}],"internalType":"struct IBatchRouter.SwapPathExactAmountIn[]","name":"paths","type":"tuple[]"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"bool","name":"wethIsEth","type":"bool"},{"internalType":"bytes","name":"userData","type":"bytes"}],"internalType":"struct IBatchRouter.SwapExactInHookParams","name":"params","type":"tuple"}],"name":"querySwapExactInHook","outputs":[{"internalType":"uint256[]","name":"pathAmountsOut","type":"uint256[]"},{"internalType":"address[]","name":"tokensOut","type":"address[]"},{"internalType":"uint256[]","name":"amountsOut","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"components":[{"internalType":"contract IERC20","name":"tokenIn","type":"address"},{"components":[{"internalType":"address","name":"pool","type":"address"},{"internalType":"contract IERC20","name":"tokenOut","type":"address"},{"internalType":"bool","name":"isBuffer","type":"bool"}],"internalType":"struct IBatchRouter.SwapPathStep[]","name":"steps","type":"tuple[]"},{"internalType":"uint256","name":"maxAmountIn","type":"uint256"},{"internalType":"uint256","name":"exactAmountOut","type":"uint256"}],"internalType":"struct IBatchRouter.SwapPathExactAmountOut[]","name":"paths","type":"tuple[]"},{"internalType":"address","name":"sender","type":"address"},{"internalType":"bytes","name":"userData","type":"bytes"}],"name":"querySwapExactOut","outputs":[{"internalType":"uint256[]","name":"pathAmountsIn","type":"uint256[]"},{"internalType":"address[]","name":"tokensIn","type":"address[]"},{"internalType":"uint256[]","name":"amountsIn","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"components":[{"internalType":"address","name":"sender","type":"address"},{"components":[{"internalType":"contract IERC20","name":"tokenIn","type":"address"},{"components":[{"internalType":"address","name":"pool","type":"address"},{"internalType":"contract IERC20","name":"tokenOut","type":"address"},{"internalType":"bool","name":"isBuffer","type":"bool"}],"internalType":"struct IBatchRouter.SwapPathStep[]","name":"steps","type":"tuple[]"},{"internalType":"uint256","name":"maxAmountIn","type":"uint256"},{"internalType":"uint256","name":"exactAmountOut","type":"uint256"}],"internalType":"struct IBatchRouter.SwapPathExactAmountOut[]","name":"paths","type":"tuple[]"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"bool","name":"wethIsEth","type":"bool"},{"internalType":"bytes","name":"userData","type":"bytes"}],"internalType":"struct IBatchRouter.SwapExactOutHookParams","name":"params","type":"tuple"}],"name":"querySwapExactOutHook","outputs":[{"internalType":"uint256[]","name":"pathAmountsIn","type":"uint256[]"},{"internalType":"address[]","name":"tokensIn","type":"address[]"},{"internalType":"uint256[]","name":"amountsIn","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"components":[{"internalType":"contract IERC20","name":"tokenIn","type":"address"},{"components":[{"internalType":"address","name":"pool","type":"address"},{"internalType":"contract IERC20","name":"tokenOut","type":"address"},{"internalType":"bool","name":"isBuffer","type":"bool"}],"internalType":"struct IBatchRouter.SwapPathStep[]","name":"steps","type":"tuple[]"},{"internalType":"uint256","name":"exactAmountIn","type":"uint256"},{"internalType":"uint256","name":"minAmountOut","type":"uint256"}],"internalType":"struct IBatchRouter.SwapPathExactAmountIn[]","name":"paths","type":"tuple[]"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"bool","name":"wethIsEth","type":"bool"},{"internalType":"bytes","name":"userData","type":"bytes"}],"name":"swapExactIn","outputs":[{"internalType":"uint256[]","name":"pathAmountsOut","type":"uint256[]"},{"internalType":"address[]","name":"tokensOut","type":"address[]"},{"internalType":"uint256[]","name":"amountsOut","type":"uint256[]"}],"stateMutability":"payable","type":"function"},{"inputs":[{"components":[{"internalType":"address","name":"sender","type":"address"},{"components":[{"internalType":"contract IERC20","name":"tokenIn","type":"address"},{"components":[{"internalType":"address","name":"pool","type":"address"},{"internalType":"contract IERC20","name":"tokenOut","type":"address"},{"internalType":"bool","name":"isBuffer","type":"bool"}],"internalType":"struct IBatchRouter.SwapPathStep[]","name":"steps","type":"tuple[]"},{"internalType":"uint256","name":"exactAmountIn","type":"uint256"},{"internalType":"uint256","name":"minAmountOut","type":"uint256"}],"internalType":"struct IBatchRouter.SwapPathExactAmountIn[]","name":"paths","type":"tuple[]"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"bool","name":"wethIsEth","type":"bool"},{"internalType":"bytes","name":"userData","type":"bytes"}],"internalType":"struct IBatchRouter.SwapExactInHookParams","name":"params","type":"tuple"}],"name":"swapExactInHook","outputs":[{"internalType":"uint256[]","name":"pathAmountsOut","type":"uint256[]"},{"internalType":"address[]","name":"tokensOut","type":"address[]"},{"internalType":"uint256[]","name":"amountsOut","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"components":[{"internalType":"contract IERC20","name":"tokenIn","type":"address"},{"components":[{"internalType":"address","name":"pool","type":"address"},{"internalType":"contract IERC20","name":"tokenOut","type":"address"},{"internalType":"bool","name":"isBuffer","type":"bool"}],"internalType":"struct IBatchRouter.SwapPathStep[]","name":"steps","type":"tuple[]"},{"internalType":"uint256","name":"maxAmountIn","type":"uint256"},{"internalType":"uint256","name":"exactAmountOut","type":"uint256"}],"internalType":"struct IBatchRouter.SwapPathExactAmountOut[]","name":"paths","type":"tuple[]"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"bool","name":"wethIsEth","type":"bool"},{"internalType":"bytes","name":"userData","type":"bytes"}],"name":"swapExactOut","outputs":[{"internalType":"uint256[]","name":"pathAmountsIn","type":"uint256[]"},{"internalType":"address[]","name":"tokensIn","type":"address[]"},{"internalType":"uint256[]","name":"amountsIn","type":"uint256[]"}],"stateMutability":"payable","type":"function"},{"inputs":[{"components":[{"internalType":"address","name":"sender","type":"address"},{"components":[{"internalType":"contract IERC20","name":"tokenIn","type":"address"},{"components":[{"internalType":"address","name":"pool","type":"address"},{"internalType":"contract IERC20","name":"tokenOut","type":"address"},{"internalType":"bool","name":"isBuffer","type":"bool"}],"internalType":"struct IBatchRouter.SwapPathStep[]","name":"steps","type":"tuple[]"},{"internalType":"uint256","name":"maxAmountIn","type":"uint256"},{"internalType":"uint256","name":"exactAmountOut","type":"uint256"}],"internalType":"struct IBatchRouter.SwapPathExactAmountOut[]","name":"paths","type":"tuple[]"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"bool","name":"wethIsEth","type":"bool"},{"internalType":"bytes","name":"userData","type":"bytes"}],"internalType":"struct IBatchRouter.SwapExactOutHookParams","name":"params","type":"tuple"}],"name":"swapExactOutHook","outputs":[{"internalType":"uint256[]","name":"pathAmountsIn","type":"uint256[]"},{"internalType":"address[]","name":"tokensIn","type":"address[]"},{"internalType":"uint256[]","name":"amountsIn","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"version","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"},{"stateMutability":"payable","type":"receive"}]
</abi>

Function Code:
swapExactIn
"0x286f580d"
Sample Working Input:
<input>
{
  "paths": [
    {
      "exactAmountIn": "100000000000000",
      "minAmountOut": "9048241701256655",
      "steps": [
        {
          "isBuffer": true,
          "pool": "0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644",
          "tokenOut": "0x7c16f0185a26db0ae7a9377f23bc18ea7ce5d644"
        },
        {
          "isBuffer": false,
          "pool": "0xd1d7fa8871d84d0e77020fc28b7cd5718c446522",
          "tokenOut": "0xaf204776c7245bf4147c2612bf6e5972ee483701"
        }
      ],
      "tokenIn": "0x9c58bacc331c9aa871afd802db6379a98e80cedb"
    }
  ],
  "deadline": "9007199254740991",
  "wethIsEth": false,
  "userData": "0x"
}
</input>

Sample Working Output:
<output>
{
  "pathAmountsOut": [
    "9102836629643480"
  ],
  "tokensOut": [
    "0xaf204776c7245bf4147c2612bf6e5972ee483701"
  ],
  "amountsOut": [
    "9102836629643480"
  ]
}
</output>

<coding_directives>
When writing or editing Python code, always follow these guidelines:

Prioritize simplicity, clarity, and ease of understanding.

Avoid unnecessary abstractions, helper classes, or overly complex structures.

Assume inputs are valid; omit explicit error handling, edge-case checks, and custom exceptions unless specifically required.

Allow the code to crash naturally if errors occur, without explicit exception handling.

Organize code into logical, simple modules or separate files.

Clearly structure code so that the responsibilities and functionalities of each module or file are immediately obvious.

Include comments only when they meaningfully clarify the intent or logic of the code; avoid unnecessary or verbose comments.

Do not add logging, verbose messaging, or any additional output unless explicitly needed for the core functionality.

Aim for your code to resemble concise, clear examples typically found in official library documentation (e.g., web3.py, Tenderly API). The goal is always maximum clarity and minimalism.
</coding_directives>

Reference File (Copy env usage, tenderly client usage, style and structure):
<code>
"""Helper for simulating FutarchyRouter.splitPosition via Tenderly.

Assumes the collateral ERC-20 is already approved for the FutarchyRouter.
Only builds and simulates the split transaction – does **not** send it.

Usage (example):

```python
from web3 import Web3
from futarchy.experimental.config.abis.futarchy import FUTARCHY_ROUTER_ABI
from futarchy.experimental.exchanges.simulator.tenderly_api import TenderlyClient
from futarchy.experimental.exchanges.simulator.helpers.split_position import (
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
from web3 import Web3
from decimal import Decimal

from futarchy.experimental.config.abis.futarchy import FUTARCHY_ROUTER_ABI
from ..tenderly_api import TenderlyClient

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
        print("Simulation failed or returned no results.")
    return result


def parse_split_results(results: List[Dict[str, Any]], w3: Web3) -> None:
    """Pretty-print each simulation result from splitPosition bundle."""
    for idx, sim in enumerate(results):
        print(f"\n--- Split Simulation Result #{idx + 1} ---")

        if sim.get("error"):
            print("Tenderly simulation error:", sim["error"].get("message", "Unknown error"))
            continue

        tx = sim.get("transaction")
        if not tx:
            print("No transaction data in result.")
            continue

        if tx.get("status") is False:
            info = tx.get("transaction_info", {})
            reason = info.get("error_message", info.get("revert_reason", "N/A"))
            print("❌ splitPosition REVERTED. Reason:", reason)
            continue

        print("✅ splitPosition succeeded.")

        # Optional: pick up token balance diffs if Tenderly provides them
        balance_changes = sim.get("balance_changes") or {}
        if balance_changes:
            print("Balance changes:")
            for token_addr, diff in balance_changes.items():
                human = Decimal(w3.from_wei(abs(int(diff)), "ether"))
                sign = "+" if int(diff) > 0 else "-"
                print(f"  {token_addr}: {sign}{human}")
        else:
            print("(No balance change info)")


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
        print("❌ Missing env vars:", ", ".join(missing))
        return

    w3 = _build_w3_from_env()
    if not w3.is_connected():
        print("❌ Could not connect to RPC endpoint.")
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
    print("Swap transaction did NOT revert.")
    tx_info = tx.get("transaction_info", {})
    call_trace = tx_info.get("call_trace", {})
    output_hex = call_trace.get("output")
    print("output_hex = ", output_hex)


if __name__ == "__main__":  # pragma: no cover
    main()

</code>