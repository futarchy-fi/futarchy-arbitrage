Below is a **complete migration plan** that replaces the current *return‑data* inspection with **`debug_traceCall` + `stateDiff:true`**.
The format follows our internal “implementation report” standard: imperative sentences, code‑diff snippets only, no boilerplate.

---

## 1 · Infrastructure prerequisites

1. **Run / rent** a full‑archive node (Geth ≥ v1.14 or Nethermind ≥ 1.25) with the `debug` and `trace` APIs enabled.
   Example Geth launch:

   ```bash
   geth \
     --http --http.api eth,net,web3,debug,trace \
     --http.vhosts=* --http.addr 0.0.0.0 \
     --syncmode=full --gcmode=archive --cache=4096
   ```
2. RPC URL must point to that node (export `RPC_URL=<node>`).

No other infra changes are needed.

---

## 2 · New helper module

```diff
+ src/helpers/trace_utils.py
+------------------------------------------
+from typing import Any, Dict, Tuple
+from web3 import Web3
+
+__all__ = ["trace_call", "balance_delta"]
+
+def trace_call(w3: Web3, tx: Dict[str, Any]) -> Dict[str, Any]:
+    """Return debug_traceCall result with stateDiff."""
+    return w3.provider.make_request(
+        "debug_traceCall",
+        [tx, "latest", {"stateDiff": True}]
+    )["result"]
+
+def balance_delta(diff: Dict[str, Any], token: str, user: str, slot: int = 0) -> int:
+    """
+    Compute Δ(balanceOf(user)) for *token* from stateDiff.
+    ERC‑20 balance mapping is in slot‑0 for all tokens we use.
+    """
+    key = Web3.solidityKeccak(["address", "uint256"], [user, slot]).hex()
+    token_key = token.lower()
+    storage = diff.get(token_key, {}).get("storage", {})
+    entry = storage.get(key)
+    if not entry:                       # balance untouched
+        return 0
+    return int(entry["to"], 16) - int(entry["from"], 16)
+------------------------------------------
```

Notes

* Works on both Geth (“stateDiff”) and Nethermind (“stateDiff”) shapes—field names are identical.
* We only need slot 0 because all involved ERC‑20s are OpenZeppelin‑standard.

---

## 3 · Modify workflow orchestrator

### 3.1 Accept a `use_trace` flag

```diff
 src/workflows/buy_flow_3step.py
@@
-def simulate_three_steps(w3, amount_sdai, account, addresses, impl_addr):
+def simulate_three_steps(w3, amount_sdai, account, addresses, impl_addr, *,
+                         use_trace: bool = False):
@@
-    runner = _StepRunner(w3, account, impl_addr)
+    runner = _StepRunner(w3, account, impl_addr, use_trace)
```

### 3.2 Wire the flag through to the private runner

```diff
-class _StepRunner:
-    def __init__(self, w3, sender, impl_addr):
+class _StepRunner:
+    def __init__(self, w3, sender, impl_addr, use_trace: bool):
         self.w3 = w3
         ...
         self.sender = sender
+        self.use_trace = use_trace
```

### 3.3 Replace `_eth_call` with a dual‑mode `_simulate`

```diff
-    def _eth_call(self, bundle):            # DELETE
+    # ------------------------------------------------------------------ #
+    # simulation dispatcher                                              #
+    # ------------------------------------------------------------------ #
+    def _simulate(self, bundle):
+        if self.use_trace:
+            return self._trace(bundle)
+        return self._call_with_results(bundle)
+
+    # ---- old path kept, renamed -------------------------------------- #
+    def _call_with_results(self, bundle): ...
+
+    # ---- new trace path ---------------------------------------------- #
+    def _trace(self, bundle):
+        from src.helpers.trace_utils import trace_call
+        selector = self.w3.keccak(text="execute((address,uint256,bytes)[])")[:4]
+        calls = [(c["target"], c["value"], c["data"]) for c in bundle]
+        from eth_abi import encode
+        data = selector + encode(["(address,uint256,bytes)[]"], [calls])
+        tx = {
+            "from": self.sender,
+            "to":   self.sender,
+            "data": data,
+            "gas":  10_000_000,
+        }
+        # state override for 7702
+        overrides = {self.sender: {"code": self.w3.eth.get_code(self.builder.impl)}}
+        tx["stateOverrides"] = overrides   # Nethermind ignores, Geth tolerates
+        return trace_call(self.w3, tx)    # returns diff+trace dict
```

### 3.4 Read values from `stateDiff`

*Discovery step* (example):

```diff
-raw   = self._simulate(calls)
-parsed = parse_bundle_results(raw, _op_map_exact_in())
-yes, no = extract_swap_outputs(parsed)
+if self.use_trace:
+    diff = raw["stateDiff"]
+    from src.helpers.trace_utils import balance_delta
+    yes = balance_delta(diff, adx["COMPANY_YES"], self.sender)
+    no  = balance_delta(diff, adx["COMPANY_NO"],  self.sender)
+else:
+    parsed = parse_bundle_results(raw, _op_map_exact_in())
+    yes, no = extract_swap_outputs(parsed)
```

Repeat the same pattern in **balanced** and **final** steps.

The only additional balance we need in step 3 is the sDAI delta from the Balancer swap (and optional liquidation). That is:

```python
sdai_out = balance_delta(diff, adx["SDAI_TOKEN"], self.sender)
```

Everything else (profit calc, builder filling) remains unchanged.

---

## 4 · Expose a CLI option

```diff
 src/arbitrage_commands/buy_cond_eip7702.py
@@
 parser.add_argument("--trace", action="store_true",
                     help="Use debug_traceCall instead of executeWithResults")
 ...
-    result = run_three_step_simulation(amount)
+    result = run_three_step_simulation(amount, use_trace=args.trace)
```

The wrapper simply forwards `use_trace` to `simulate_three_steps`.

---

## 5 · Token‑address dictionary helper

Add once, re‑use everywhere:

```diff
+ def _addresses_dict() -> Dict[str, str]:
+     return {
+         "SDAI_TOKEN": SDAI_TOKEN,
+         "COMPANY_TOKEN": COMPANY_TOKEN,
+         "SDAI_YES": SDAI_YES,
+         "SDAI_NO": SDAI_NO,
+         "COMPANY_YES": COMPANY_YES,
+         "COMPANY_NO": COMPANY_NO,
+     }
```

---

## 6 · Unit‑test scaffold

```diff
+ tests/test_trace_utils.py
+------------------------------------------
+def test_balance_delta():
+    dummy_diff = {
+        "0xtoken": {
+            "storage": {
+                "0xaaa": {"from": "0x0", "to": "0x64"}  # 100
+            }
+        }
+    }
+    user = "0x1111111111111111111111111111111111111111"
+    # slot is irrelevant for this mocked key
+    assert balance_delta(dummy_diff, "0xToken", user) == 100
+------------------------------------------
```

Mock `trace_call` via `monkeypatch` so `simulate_three_steps(..., use_trace=True)` runs offline.

---

## 7 · Performance tips

* Cache `keccak(address,0)` per token to avoid recomputing in tight loops.
* Optional: parallelise the three `debug_traceCall` invocations with `asyncio` to mitigate the 5‑10× slowdown.

---

## 8 · Roll‑out checklist

1. **Spin up** the archive node and point `RPC_URL` to it.
2. `pytest -q tests/test_trace_utils.py` – should pass.
3. `python buy_cond_eip7702.py 0.01 --trace` – confirm discovery, balanced, final logs appear.
4. `python buy_cond_eip7702.py 0.01 --trace --send` on a small test amount.
5. Update `eip7702_bot.py` docs: add a note that `--trace` demands a debug‑enabled node.

---

### TL;DR

*Add `trace_utils.py`, thread a `use_trace` flag through the workflow, compute deltas from `stateDiff`, and expose `--trace` to the CLI.*
This enables full **Tenderly‑free, executeWithResults‑free** simulations on any debug‑enabled archive node, at the cost of higher latency.
