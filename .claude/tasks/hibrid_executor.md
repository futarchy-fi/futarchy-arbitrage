# Revised plan for the 7702 executor (wired to your deployed FutarchyArbExecutorV4)

You deployed `FutarchyArbExecutorV4` at:

* **address**: `0xb74a98b75B4efde911Bb95F7a2A0E7Bc3376e15B`
* **deployer**: `0x91c612a37b8365C2db937388d7b424fe03D62850`
* **tx\_hash**: `0x26583a085cf01b432e12b4f3c5adc8fc30899f288af665fa4c905337f0d43070`
* **gas\_used**: `2,294,545`
* **timestamp**: `2025‑08‑11T14:37:25.515898`
* **ABI**: (provided; includes `runTrade`, `TradeExecuted`, `runner()`, and the full Sell/Buy flows)

Given this, here’s the revised plan and the updated module.

---

## What the module provides (unchanged in spirit, updated to your address/ABI)

1. **7702 bundle builder**: produces a single call `{to, data, value}` invoking `runTrade(Execute10Batch)` on `0xb74a…15B`. This lets you execute a Balancer `swapExactIn` through your contract’s `execute10` delta checks inside an EIP‑7702 transaction.

2. **Normal transaction paths**:
   a) **EOA → FutarchyArbExecutorV4.runTrade** (requires `sender == runner`)
   b) **EOA → Balancer BatchRouter.swapExactIn** (direct, unchanged behavior)

3. **ABI handling**: by default, the module will:

   * Load the **full ABI you provided** from `FUTARCHY_EXECUTOR_ABI_JSON` (recommended), or
   * Fall back to a **minimal ABI** (only `runTrade` and `TradeExecuted`) if you don’t supply a file.
   * Address defaults to your deployed address unless overridden.

4. **No brittle runtime patching**: we encode exact amounts into the router calldata and set:

   * `patchIndex = 255 (PATCH_NONE)`
   * `minOutOffset = 2^256 − 1`
     If you later want slippage‑bps patching via offsets, we’ll add a reliable offset encoder.

5. **Reuses Balancer pathing** from `src/trades/balancer_swap.py` so the router address, ABI and pool layout live in one place.

---

## File: `src/executor/tx_7702_executor.py` (revised)

```py
# SPDX-License-Identifier: MIT
"""
7702 executor & normal-tx helpers for Balancer swapExactIn, wired to the
deployed FutarchyArbExecutorV4 at 0xb74a98b75B4efde911Bb95F7a2A0E7Bc3376e15B.

Capabilities:
  • Build a 7702 bundle: single call to FutarchyArbExecutorV4.runTrade(b).
  • Send normal tx either to runTrade (contract path) or directly to the router.
  • Load the full Futarchy ABI from FUTARCHY_EXECUTOR_ABI_JSON (recommended),
    else fall back to a minimal ABI that covers runTrade + TradeExecuted.

Environment variables:
  • FUTARCHY_EXECUTOR_ADDRESS  (optional; default is the deployed address below)
  • FUTARCHY_EXECUTOR_ABI_JSON (optional; path to JSON containing {"abi": [...]})
  • BALANCER_ROUTER_ADDRESS    (required unless provided at construction)
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from web3 import Web3
from eth_typing import ChecksumAddress

# ---- Robust import of your Balancer helper ----------------------------------
# Prefer package import; fall back to top-level if project isn't packaged yet.
try:
    from trades.balancer_swap import (  # noqa
        COMPANY_TOKEN,
        SDAI,
        BUFFER_POOL,
        FINAL_POOL,
        BALANCER_ROUTER_ABI,
        MAX_DEADLINE,
        _get_router,
        build_sell_gno_to_sdai_swap_tx,
        build_buy_gno_to_sdai_swap_tx,
    )
except Exception:
    from balancer_swap import (  # type: ignore  # noqa
        COMPANY_TOKEN,
        SDAI,
        BUFFER_POOL,
        FINAL_POOL,
        BALANCER_ROUTER_ABI,
        MAX_DEADLINE,
        _get_router,
        build_sell_gno_to_sdai_swap_tx,
        build_buy_gno_to_sdai_swap_tx,
    )

logger = logging.getLogger(__name__)

# ---- Deployed FutarchyArbExecutorV4 -----------------------------------------
ARB_EXECUTOR_ADDRESS_DEFAULT = "0xb74a98b75B4efde911Bb95F7a2A0E7Bc3376e15B"

# ---- Minimal ABI (fallback) --------------------------------------------------
# Use full ABI via FUTARCHY_EXECUTOR_ABI_JSON when possible.
FUTARCHY_MIN_ABI: List[Dict[str, Any]] = [
    {
        "type": "function",
        "stateMutability": "nonpayable",
        "name": "runTrade",
        "inputs": [{
            "name": "b",
            "type": "tuple",
            "components": [
                {"name": "targets",      "type": "address[10]"},
                {"name": "calldatas",    "type": "bytes[10]"},
                {"name": "count",        "type": "uint256"},
                {"name": "tokenIn",      "type": "address"},
                {"name": "tokenOut",     "type": "address"},
                {"name": "spender",      "type": "address"},
                {"name": "amountIn",     "type": "uint256"},
                {"name": "minOut",       "type": "uint256"},
                {"name": "patchIndex",   "type": "uint8"},
                {"name": "amountOffset", "type": "uint256"},
                {"name": "minOutOffset", "type": "uint256"},
                {"name": "slippageBps",  "type": "uint16"},
            ],
        }],
        "outputs": [{"name": "out", "type": "uint256"}],
    },
    {
        "type": "event",
        "name": "TradeExecuted",
        "inputs": [
            {"indexed": True,  "name": "tokenIn",  "type": "address"},
            {"indexed": True,  "name": "tokenOut", "type": "address"},
            {"indexed": False, "name": "amountIn", "type": "uint256"},
            {"indexed": False, "name": "amountOut","type": "uint256"},
        ],
        "anonymous": False,
    },
    {
        "type": "function",
        "name": "runner",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    }
]

PATCH_NONE: int = 255
UINT256_MAX: int = (1 << 256) - 1


def _load_futarchy_abi(explicit_abi: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Prefer an explicit ABI passed by the caller, else load from FUTARCHY_EXECUTOR_ABI_JSON,
    else use the minimal ABI fallback.
    The JSON file may be either {"abi":[...]} or just [...].
    """
    if explicit_abi:
        return explicit_abi
    p = os.getenv("FUTARCHY_EXECUTOR_ABI_JSON")
    if p:
        try:
            with open(p, "r") as f:
                obj = json.load(f)
            return obj["abi"] if isinstance(obj, dict) and "abi" in obj else obj
        except Exception as e:
            logger.warning("Failed to load ABI from %s: %s. Falling back to minimal ABI.", p, e)
    return FUTARCHY_MIN_ABI


@dataclass
class Call:
    """Generic call item for a 7702 bundle."""
    to: ChecksumAddress
    data: str
    value: int = 0

    def as_dict(self) -> Dict[str, Any]:
        # Adapt this shape to your 7702 bundler if it expects different keys.
        return {"to": self.to, "data": self.data, "value": self.value}


class Execute10BatchDict(TypedDict):
    targets: List[ChecksumAddress]
    calldatas: List[str]
    count: int
    tokenIn: ChecksumAddress
    tokenOut: ChecksumAddress
    spender: ChecksumAddress
    amountIn: int
    minOut: int
    patchIndex: int
    amountOffset: int
    minOutOffset: int
    slippageBps: int


class Tx7702Executor:
    """
    Orchestrates Balancer swapExactIn calls via FutarchyArbExecutorV4.runTrade (7702 or normal),
    or directly against the Balancer BatchRouter.
    """

    def __init__(
        self,
        w3: Web3,
        arb_executor_addr: Optional[str] = None,
        router_addr: Optional[str] = None,
        *,
        arb_abi: Optional[List[Dict[str, Any]]] = None,
        deadline: int = MAX_DEADLINE,
        weth_is_eth: bool = False,
        user_data: bytes = b"",
    ) -> None:
        self.w3 = w3
        self.deadline = int(deadline)
        self.weth_is_eth = bool(weth_is_eth)
        self.user_data = user_data

        arb_addr = arb_executor_addr or os.getenv("FUTARCHY_EXECUTOR_ADDRESS") or ARB_EXECUTOR_ADDRESS_DEFAULT
        self.arb = w3.eth.contract(
            address=w3.to_checksum_address(arb_addr),
            abi=_load_futarchy_abi(arb_abi),
        )
        self.router = _get_router(w3, router_addr)

    # ------------------------- router calldata encoding -----------------------

    def _encode_router_swap_sell(self, amount_in_wei: int, min_amount_out_wei: int) -> str:
        steps = [
            (BUFFER_POOL, BUFFER_POOL, True),  # COMPANY -> buffer
            (FINAL_POOL, SDAI, False),         # buffer  -> sDAI
        ]
        path = (COMPANY_TOKEN, steps, int(amount_in_wei), int(min_amount_out_wei))
        return self.router.encodeABI(
            fn_name="swapExactIn",
            args=([path], self.deadline, self.weth_is_eth, self.user_data),
        )

    def _encode_router_swap_buy(self, amount_in_wei: int, min_amount_out_wei: int) -> str:
        steps = [
            (FINAL_POOL, BUFFER_POOL, False),  # sDAI   -> buffer
            (BUFFER_POOL, COMPANY_TOKEN, True) # buffer -> COMPANY
        ]
        path = (SDAI, steps, int(amount_in_wei), int(min_amount_out_wei))
        return self.router.encodeABI(
            fn_name="swapExactIn",
            args=([path], self.deadline, self.weth_is_eth, self.user_data),
        )

    # ------------------------- Execute10 batch builders ------------------------

    def _build_execute10_batch(
        self,
        swap_data: str,
        token_in: str,
        token_out: str,
        amount_in_wei: int,
        min_out_wei: int,
    ) -> Execute10BatchDict:
        zero = self.w3.to_checksum_address("0x" + "00" * 20)
        targets = [self.router.address] + [zero] * 9
        calldatas = [swap_data] + ["0x"] * 9
        return {
            "targets": targets,
            "calldatas": calldatas,
            "count": 1,
            "tokenIn": self.w3.to_checksum_address(token_in),
            "tokenOut": self.w3.to_checksum_address(token_out),
            "spender": self.router.address,
            "amountIn": int(amount_in_wei),
            "minOut": int(min_out_wei),
            "patchIndex": PATCH_NONE,
            "amountOffset": 0,
            "minOutOffset": UINT256_MAX,
            "slippageBps": 0,
        }

    def _build_runtrade_call(self, batch: Execute10BatchDict) -> Call:
        data = self.arb.encodeABI(fn_name="runTrade", args=[batch])
        return Call(to=self.arb.address, data=data, value=0)

    # ------------------------------ 7702 bundles -------------------------------

    def build_7702_bundle_sell(self, amount_in_wei: int, min_amount_out_wei: int) -> List[Call]:
        swap = self._encode_router_swap_sell(amount_in_wei, min_amount_out_wei)
        b = self._build_execute10_batch(swap, COMPANY_TOKEN, SDAI, amount_in_wei, min_amount_out_wei)
        return [self._build_runtrade_call(b)]

    def build_7702_bundle_buy(self, amount_in_wei: int, min_amount_out_wei: int) -> List[Call]:
        swap = self._encode_router_swap_buy(amount_in_wei, min_amount_out_wei)
        b = self._build_execute10_batch(swap, SDAI, COMPANY_TOKEN, amount_in_wei, min_amount_out_wei)
        return [self._build_runtrade_call(b)]

    # --------------------------- normal tx: runTrade ---------------------------

    def fetch_runner(self) -> Optional[str]:
        try:
            return self.arb.functions.runner().call()
        except Exception:
            return None

    def send_run_trade_sell(
        self,
        sender: str,
        private_key: str,
        amount_in_wei: int,
        min_amount_out_wei: int,
        *,
        must_be_runner: bool = True,
        gas: Optional[int] = None,
        gas_price_wei: Optional[int] = None,
        nonce: Optional[int] = None,
        chain_id: Optional[int] = None,
    ) -> str:
        if must_be_runner:
            r = self.fetch_runner()
            if r is not None and self.w3.to_checksum_address(sender) != self.w3.to_checksum_address(r):
                raise PermissionError(f"sender {sender} != runner {r}")
        swap = self._encode_router_swap_sell(amount_in_wei, min_amount_out_wei)
        b = self._build_execute10_batch(swap, COMPANY_TOKEN, SDAI, amount_in_wei, min_amount_out_wei)
        return self._send_run_trade(sender, private_key, b, gas, gas_price_wei, nonce, chain_id)

    def send_run_trade_buy(
        self,
        sender: str,
        private_key: str,
        amount_in_wei: int,
        min_amount_out_wei: int,
        *,
        must_be_runner: bool = True,
        gas: Optional[int] = None,
        gas_price_wei: Optional[int] = None,
        nonce: Optional[int] = None,
        chain_id: Optional[int] = None,
    ) -> str:
        if must_be_runner:
            r = self.fetch_runner()
            if r is not None and self.w3.to_checksum_address(sender) != self.w3.to_checksum_address(r):
                raise PermissionError(f"sender {sender} != runner {r}")
        swap = self._encode_router_swap_buy(amount_in_wei, min_amount_out_wei)
        b = self._build_execute10_batch(swap, SDAI, COMPANY_TOKEN, amount_in_wei, min_amount_out_wei)
        return self._send_run_trade(sender, private_key, b, gas, gas_price_wei, nonce, chain_id)

    def _send_run_trade(
        self,
        sender: str,
        private_key: str,
        batch: Execute10BatchDict,
        gas: Optional[int],
        gas_price_wei: Optional[int],
        nonce: Optional[int],
        chain_id: Optional[int],
    ) -> str:
        tx = self.arb.functions.runTrade(batch).build_transaction({
            "from": self.w3.to_checksum_address(sender),
            "nonce": self.w3.eth.get_transaction_count(self.w3.to_checksum_address(sender)) if nonce is None else nonce,
            "gas": gas if gas is not None else 800_000,
            "gasPrice": gas_price_wei if gas_price_wei is not None else self.w3.eth.gas_price,
            **({"chainId": chain_id} if chain_id is not None else {}),
        })
        signed = self.w3.eth.account.sign_transaction(tx, private_key)
        h = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        return h.hex()

    # ------------------------ normal tx: direct router -------------------------

    def send_direct_router_sell(
        self,
        sender: str,
        private_key: str,
        amount_in_wei: int,
        min_amount_out_wei: int,
        *,
        gas: Optional[int] = None,
        gas_price_wei: Optional[int] = None,
        nonce: Optional[int] = None,
        chain_id: Optional[int] = None,
    ) -> str:
        tx = build_sell_gno_to_sdai_swap_tx(self.w3, amount_in_wei, min_amount_out_wei, sender)
        if gas is not None:          tx["gas"] = gas
        if gas_price_wei is not None: tx["gasPrice"] = gas_price_wei
        if nonce is not None:        tx["nonce"] = nonce
        if chain_id is not None:     tx["chainId"] = chain_id
        signed = self.w3.eth.account.sign_transaction(tx, private_key)
        h = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        return h.hex()

    def send_direct_router_buy(
        self,
        sender: str,
        private_key: str,
        amount_in_wei: int,
        min_amount_out_wei: int,
        *,
        gas: Optional[int] = None,
        gas_price_wei: Optional[int] = None,
        nonce: Optional[int] = None,
        chain_id: Optional[int] = None,
    ) -> str:
        tx = build_buy_gno_to_sdai_swap_tx(self.w3, amount_in_wei, min_amount_out_wei, sender)
        if gas is not None:          tx["gas"] = gas
        if gas_price_wei is not None: tx["gasPrice"] = gas_price_wei
        if nonce is not None:        tx["nonce"] = nonce
        if chain_id is not None:     tx["chainId"] = chain_id
        signed = self.w3.eth.account.sign_transaction(tx, private_key)
        h = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        return h.hex()

    # ------------------------------- utilities --------------------------------

    def decode_trade_executed(self, receipt) -> Optional[Tuple[int, int]]:
        """Return (amountIn, amountOut) from the first TradeExecuted event, if present."""
        try:
            evts = self.arb.events.TradeExecuted().process_receipt(receipt)
            if not evts:
                return None
            e0 = evts[0]["args"]
            return int(e0["amountIn"]), int(e0["amountOut"])
        except Exception:
            return None
```

---

## How to wire the provided ABI cleanly

1. Save the JSON you pasted (the whole object) to:

```
src/abi/FutarchyArbExecutorV4.json
```

2. Export the path:

```
export FUTARCHY_EXECUTOR_ABI_JSON=src/abi/FutarchyArbExecutorV4.json
```

3. Optionally export the address (not necessary because the module defaults to your deployed address):

```
export FUTARCHY_EXECUTOR_ADDRESS=0xb74a98b75B4efde911Bb95F7a2A0E7Bc3376e15B
```

4. Ensure `BALANCER_ROUTER_ADDRESS` is set (or pass `router_addr=` to the constructor).

---

## Example usage (sell path)

```py
from decimal import Decimal
from web3 import Web3
from src.executor.tx_7702_executor import Tx7702Executor

w3 = Web3(Web3.HTTPProvider(os.environ["GNOSIS_RPC_URL"]))

# Defaults to your deployed address + ABI from FUTARCHY_EXECUTOR_ABI_JSON if set.
x = Tx7702Executor(w3)

# Build a 7702 bundle
amt_in = w3.to_wei(Decimal("0.1"), "ether")
min_out = w3.to_wei(Decimal("1"), "ether")
bundle = x.build_7702_bundle_sell(amt_in, min_out)
# hand `bundle[0].as_dict()` to your 7702 bundler

# Send as a normal tx to runTrade (requires sender == runner)
txh = x.send_run_trade_sell(sender=os.environ["WALLET_ADDRESS"],
                            private_key=os.environ["PRIVATE_KEY"],
                            amount_in_wei=amt_in,
                            min_amount_out_wei=min_out)
print("runTrade tx:", txh)

# Or send directly to the router
txh2 = x.send_direct_router_sell(sender=os.environ["WALLET_ADDRESS"],
                                 private_key=os.environ["PRIVATE_KEY"],
                                 amount_in_wei=amt_in,
                                 min_amount_out_wei=min_out)
print("router tx:", txh2)
```

---

## Notes specific to your deployment

* `runTrade` is **guarded by `onlyRunner`** in Solidity; the Python path enforces this by default (`must_be_runner=True`). If your runner is not the same EOA that will submit normal transactions (outside 7702), set `must_be_runner=False` or pass a different `sender`.

* The module defaults to your deployed address **0xb74a98…15B**, but you can override with `FUTARCHY_EXECUTOR_ADDRESS` or the constructor argument if you deploy new instances per environment.

* Using the **full ABI** you supplied ensures future event decoding beyond `TradeExecuted` will continue to work without code changes.

---

## What changed from the prior version

* The default **contract address** is now hard‑wired to your deployed instance, with env/arg overrides.
* The executor can **load your full ABI** from a JSON file at runtime (recommended); otherwise it falls back to a minimal ABI to keep the surface area small.
* Added **`fetch_runner()`** and optional permission check before `runTrade`.
* Imports are **robust** to both `trades.balancer_swap` and plain `balancer_swap` layouts.

---

## Open questions (to tighten integration)

1. **7702 bundler format**: What exact call envelope does your 7702 infra expect (field names and types)? If you provide the required schema, I’ll adapt `Call.as_dict()` (or add another adapter) so it’s plug‑and‑play.

2. **Runner address**: What is the configured `runner()` on `0xb74a98…15B`? Do you want the Python helper to assert equality on-chain before sending `runTrade`, or should we leave that to revert handling?

3. **Slippage policy**: Do you want dynamic on‑chain minOut via `slippageBps` + offset patching (so that `minOut` derives from `amountInUsed` on contract), or is encoding a fixed `minOut` in the router calldata sufficient for now?

4. **Router address source**: Should we keep using `BALANCER_ROUTER_ADDRESS` env, or hard‑code a canonical Gnosis router address in the module with an override? If you prefer hard‑coded, send the exact router address you’re using in production.

Answer those and I’ll finalize the module (including tests and, if useful, a tiny CLI under `python -m src.executor.tx_7702_executor`).
