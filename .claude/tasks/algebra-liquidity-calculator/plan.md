Great idea—let’s switch the “find initialized ticks & liquidity” workflow to **GraphQL-only** using the Algebra subgraph. Below I show (1) the plan at a glance, (2) ready‑to‑use GraphQL queries, and (3) a drop‑in extension to your existing `scripts/fetch_algebra_liquidity.py` that lists initialized ticks, finds the nearest boundaries, and (optionally) reconstructs the active‑liquidity ladder around the current price—all **without any on‑chain calls**.

> Why this works: the Algebra subgraph exposes a `Pool` entity with `liquidity`, `sqrtPrice`, `tick`, and token info, and a `Tick` entity with `tickIdx`, `liquidityGross` (tick is initialized iff > 0) and `liquidityNet` (the delta applied to pool liquidity when crossing the tick). ([docs.algebra.finance][1])

---

## 1) Plan (GraphQL‑only)

1. **Get pool base**: `pool(id: $pool)` → `liquidity`, `sqrtPrice`, `tick`, `token0/1 { symbol, decimals }`. This anchors the current tick and active liquidity. ([docs.algebra.finance][1])
2. **Enumerate initialized ticks**: `ticks(where: { poolAddress: $pool, liquidityGross_not: "0" })` ordered by `tickIdx`. These are your boundaries. ([docs.algebra.finance][1])
3. **Nearest boundaries** (no bitmap math): two small queries—

   * below: `tickIdx_lte: currentTick`, `orderDirection: desc`, `first: 1`
   * above: `tickIdx_gt: currentTick`, `orderDirection: asc`, `first: 1`  ([docs.algebra.finance][1])
4. **Optional active‑liquidity ladder**: starting from `pool.liquidity` at the current tick, walk outward:

   * Upward (ascending ticks): after each boundary `i`, `L := L + liquidityNet[i]`.
   * Downward (descending ticks): crossing in reverse, `L := L - liquidityNet[i]`.
     (This is the standard subgraph‑based reconstruction used in V3/Algebra analytics.) ([atiselsts.github.io][2])

---

## 2) Minimal GraphQL you can paste into any client

**Pool base**

```graphql
query PoolBase($id: ID!) {
  pool(id: $id) {
    id
    liquidity
    sqrtPrice
    tick
    token0 { id symbol decimals }
    token1 { id symbol decimals }
  }
}
```

Fields and example appear in Algebra’s “Query Examples.” ([docs.algebra.finance][1])

**All initialized ticks**

```graphql
query AllTicks($pool: String!, $skip: Int = 0, $first: Int = 1000) {
  ticks(
    where: { poolAddress: $pool, liquidityGross_not: "0" }
    orderBy: tickIdx, orderDirection: asc
    first: $first, skip: $skip
  ) {
    tickIdx
    liquidityGross
    liquidityNet
  }
}
```

`tickIdx`, `liquidityGross`, and `liquidityNet` are defined on the `Tick` entity in the Algebra schema. ([docs.algebra.finance][1])

**Nearest tick below/above current**

```graphql
query NearestBelow($pool: String!, $t: BigInt!) {
  ticks(
    where: { poolAddress: $pool, liquidityGross_not: "0", tickIdx_lte: $t }
    orderBy: tickIdx, orderDirection: desc, first: 1
  ) { tickIdx liquidityGross liquidityNet }
}
query NearestAbove($pool: String!, $t: BigInt!) {
  ticks(
    where: { poolAddress: $pool, liquidityGross_not: "0", tickIdx_gt: $t }
    orderBy: tickIdx, orderDirection: asc, first: 1
  ) { tickIdx liquidityGross liquidityNet }
}
```

Filtering/ordering by `tickIdx` with `_gt/_lte` is the standard way to find neighbors in the subgraph API. ([docs.algebra.finance][1])

---

## 3) Drop‑in extension to your script (`scripts/fetch_algebra_liquidity.py`)

Below is a targeted addition that keeps your existing subgraph plumbing and **adds three new CLI features**:

* `--list-initialized` — print all initialized ticks (`liquidityGross > 0`).
* `--nearest N` — show N nearest initialized ticks above/below the current tick.
* `--ladder WINDOW` — reconstruct active liquidity across a ±`WINDOW` tick range (no RPC).

> Paste the **new pieces** in the indicated places; no changes to your subgraph URL defaults or existing JSON output are required.

### A) New helpers (put near the other GraphQL helpers)

```python
def _query_initialized_ticks(url: str, pool: str, first: int = 1000) -> List[Dict[str, int]]:
    """
    Return all initialized ticks for a pool as a sorted list of dicts:
      [{tickIdx:int, liquidityGross:int, liquidityNet:int}, ...]
    """
    q = """
    query AllTicks($pool: String!, $skip: Int = 0, $first: Int = 1000) {
      ticks(
        where: { poolAddress: $pool, liquidityGross_not: "0" }
        orderBy: tickIdx, orderDirection: asc
        first: $first, skip: $skip
      ) { tickIdx liquidityGross liquidityNet }
    }"""
    out: List[Dict[str, int]] = []
    skip = 0
    while True:
        data = _post_graphql(url, q, {"pool": pool.lower(), "first": first, "skip": skip})
        batch = data.get("data", {}).get("ticks", [])
        if not batch:
            break
        for t in batch:
            try:
                out.append({
                    "tickIdx": int(t["tickIdx"]),
                    "liquidityGross": int(t["liquidityGross"]),
                    "liquidityNet": int(t["liquidityNet"]),
                })
            except Exception:
                continue
        if len(batch) < first:
            break
        skip += first
    return out

def _query_nearest_ticks(url: str, pool: str, current_tick: int, n: int) -> Tuple[List[Dict], List[Dict]]:
    """
    Return (below:list, above:list), each list up to N items, nearest-first.
    """
    below_q = """
    query NearestBelow($pool: String!, $t: BigInt!, $first: Int!) {
      ticks(
        where: { poolAddress: $pool, liquidityGross_not: "0", tickIdx_lte: $t }
        orderBy: tickIdx, orderDirection: desc, first: $first
      ) { tickIdx liquidityGross liquidityNet }
    }"""
    above_q = """
    query NearestAbove($pool: String!, $t: BigInt!, $first: Int!) {
      ticks(
        where: { poolAddress: $pool, liquidityGross_not: "0", tickIdx_gt: $t }
        orderBy: tickIdx, orderDirection: asc, first: $first
      ) { tickIdx liquidityGross liquidityNet }
    }"""
    p = {"pool": pool.lower(), "t": int(current_tick), "first": int(max(1, n))}
    below = _post_graphql(url, below_q, p).get("data", {}).get("ticks", [])
    above = _post_graphql(url, above_q, p).get("data", {}).get("ticks", [])
    # normalize to ints and nearest-first
    b = [{"tickIdx": int(x["tickIdx"]), "liquidityGross": int(x["liquidityGross"]), "liquidityNet": int(x["liquidityNet"])} for x in below]
    a = [{"tickIdx": int(x["tickIdx"]), "liquidityGross": int(x["liquidityGross"]), "liquidityNet": int(x["liquidityNet"])} for x in above]
    return (b, a)

def _compute_liquidity_ladder(current_tick: int, current_liquidity: int, ticks_sorted_asc: List[Dict[str,int]], window: int) -> Dict[str, List[Dict[str,int]]]:
    """
    Reconstruct active liquidity across a window of raw ticks around current_tick.
    Returns dict with 'below' and 'above' arrays of {tickIdx, L_after_cross}.
    Logic: moving upward, crossing tick i applies L := L + liquidityNet[i]; moving downward, L := L - liquidityNet[i].
    """
    below = []
    above = []
    # partition by current tick
    left = [t for t in ticks_sorted_asc if t["tickIdx"] <= current_tick and t["tickIdx"] >= current_tick - window]
    right = [t for t in ticks_sorted_asc if t["tickIdx"] > current_tick and t["tickIdx"] <= current_tick + window]

    # walk downwards (nearest first), subtract liquidityNet
    L = int(current_liquidity)
    for t in sorted(left, key=lambda x: x["tickIdx"], reverse=True):
        L = L - int(t["liquidityNet"])
        below.append({"tickIdx": t["tickIdx"], "L_after_cross": L})

    # walk upwards (nearest first), add liquidityNet
    L = int(current_liquidity)
    for t in sorted(right, key=lambda x: x["tickIdx"]):
        L = L + int(t["liquidityNet"])
        above.append({"tickIdx": t["tickIdx"], "L_after_cross": L})

    return {"below": below, "above": above}
```

### B) CLI flags (add to your `argparse` block)

```python
ap.add_argument("--list-initialized", action="store_true",
                help="List all initialized ticks (liquidityGross > 0) from the subgraph")
ap.add_argument("--nearest", type=int, default=0,
                help="Show N nearest initialized ticks above and below current tick (subgraph)")
ap.add_argument("--ladder", type=int, default=0,
                help="Reconstruct active-liquidity ladder across ±WINDOW raw ticks (subgraph only)")
```

### C) Invoke them (after you’ve populated `result` and fetched `pool_entity`)

Drop this **after** you compute `result.current_tick` and (if available) `result.current_liquidity` from the pool entity:

```python
# Subgraph-only features (no RPC)
if args.list_initialized or args.nearest > 0 or args.ladder > 0:
    # Ensure we have the pool's current tick/liquidity from subgraph
    current_tick = result.current_tick
    current_liquidity = result.current_liquidity
    if current_tick is None or current_liquidity is None:
        # Try to fetch via pool entity (again) strictly from subgraph
        pe = _try_query_pool_entity(args.subgraph_url, pool)
        if pe:
            try: current_tick = int(pe.get("tick")) if current_tick is None else current_tick
            except: pass
            try: current_liquidity = int(pe.get("liquidity")) if current_liquidity is None else current_liquidity
            except: pass

    if args.list_initialized:
        ticks = _query_initialized_ticks(args.subgraph_url, pool)
        if args.json:
            print(json.dumps({"pool": pool, "initialized_ticks_count": len(ticks), "ticks": ticks}, indent=2))
        else:
            print("\nInitialized ticks (liquidityGross>0):")
            for t in ticks:
                print(f"  tick {t['tickIdx']}: Lg={t['liquidityGross']} Lnet={t['liquidityNet']}")

    if args.nearest > 0 and current_tick is not None:
        b, a = _query_nearest_ticks(args.subgraph_url, pool, int(current_tick), int(args.nearest))
        if args.json:
            print(json.dumps({"pool": pool, "current_tick": int(current_tick), "nearest": {"below": b, "above": a}}, indent=2))
        else:
            print(f"\nNearest initialized ticks around tick={current_tick}:")
            print("  Below:")
            for t in b: print(f"    {t['tickIdx']} (Lg={t['liquidityGross']} Lnet={t['liquidityNet']})")
            print("  Above:")
            for t in a: print(f"    {t['tickIdx']} (Lg={t['liquidityGross']} Lnet={t['liquidityNet']})")

    if args.ladder > 0 and current_tick is not None and current_liquidity is not None:
        ticks = _query_initialized_ticks(args.subgraph_url, pool)
        ladder = _compute_liquidity_ladder(int(current_tick), int(current_liquidity), ticks, int(args.ladder))
        if args.json:
            print(json.dumps({"pool": pool, "current_tick": int(current_tick), "current_liquidity": int(current_liquidity),
                              "ladder_window": int(args.ladder), "ladder": ladder}, indent=2))
        else:
            print(f"\nActive-liquidity ladder around tick={current_tick} (±{args.ladder}):")
            print("  Below (crossing downward):")
            for r in ladder["below"]: print(f"    after crossing {r['tickIdx']}: L={r['L_after_cross']}")
            print("  Above (crossing upward):")
            for r in ladder["above"]: print(f"    after crossing {r['tickIdx']}: L={r['L_after_cross']}")
```

---

## 4) Usage examples (Gnosis / Seer Algebra subgraph)

```bash
# Pool base + all initialized ticks (JSON)
python scripts/fetch_algebra_liquidity.py \
  --pool 0x1328888335542433e2D5122A388045d6C76E7edd \
  --subgraph-url "https://app.seer.pm/subgraph?_subgraph=algebra&_chainId=100" \
  --list-initialized --json
```

```bash
# Nearest 8 boundaries above/below current tick (no RPC)
python scripts/fetch_algebra_liquidity.py \
  --pool 0x1328888335542433e2D5122A388045d6C76E7edd \
  --nearest 8
```

```bash
# Reconstruct active liquidity out to ±10,000 raw ticks around spot (subgraph-only)
python scripts/fetch_algebra_liquidity.py \
  --pool 0x1328888335542433e2D5122A388045d6C76E7edd \
  --ladder 10000 --json
```

---

## Notes & caveats

* **Schema**: The fields above match Algebra’s public subgraph docs (Pool & Tick). If you point to a different Algebra deployment (or a custom subgraph like Seer’s), the entity names/fields are typically the same; if they differ, adjust the selection set/filters accordingly. ([docs.algebra.finance][1])
* **Initialized vs. active**: “Initialized” is best detected by `liquidityGross > 0`. “Active” liquidity between ticks changes by `liquidityNet` when crossing each boundary; the ladder logic reflects this. ([docs.algebra.finance][1], [atiselsts.github.io][2])
* **Freshness**: Subgraphs can lag the chain a bit. For trading decisions at second‑level latency, treat subgraph data as advisory. Algebra’s docs position subgraphs specifically for analytics. ([docs.algebra.finance][3])

---

If you want, I can also factor the new GraphQL helpers into a tiny standalone `scripts/list_initialized_ticks.py` so you can call it from CI or other tooling.

[1]: https://docs.algebra.finance/algebra-integral-documentation/algebra-v1-technical-reference/subgraph/query-examples/query-examples "Query Examples | Algebra Integral"
[2]: https://atiselsts.github.io/pdfs/uniswap-v3-liquidity-math.pdf?utm_source=chatgpt.com "LIQUIDITY MATH IN UNISWAP V3 - Atis Elsts"
[3]: https://docs.algebra.finance/algebra-integral-documentation/algebra-integral-technical-reference/integration-process/subgraphs-and-analytics?utm_source=chatgpt.com "Subgraphs and analytics"
