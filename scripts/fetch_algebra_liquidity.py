#!/usr/bin/env python3
"""
Fetch Algebra pool liquidity via subgraph.

Usage examples:
  # Fetch using pool from the example task file
  python scripts/fetch_algebra_liquidity.py --from-example

  # Fetch by specifying pool address explicitly
  python scripts/fetch_algebra_liquidity.py --pool 0x4ff34e270ca54944955b2f595cec4cf53bdc9e0c

  # Override subgraph URL (defaults to Seer Algebra on Gnosis)
  python scripts/fetch_algebra_liquidity.py --pool 0x... \
    --subgraph-url https://app.seer.pm/subgraph?_subgraph=algebra&_chainId=100

Notes:
  - Tries querying a Pool entity first to get current liquidity.
  - Falls back to querying ticks and reporting net/minted liquidity summary if Pool entity is unavailable.
  - Address is normalized to lowercase for typical subgraph IDs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from decimal import Decimal, getcontext

# Make sure local imports (src.*) work when running as a script
from pathlib import Path
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from web3 import Web3
from src.config.abis.swapr import ALGEBRA_POOL_ABI
from src.config.abis import ERC20_ABI
from src.config.network import DEFAULT_RPC_URLS


DEFAULT_SUBGRAPH_URL = (
    "https://app.seer.pm/subgraph?_subgraph=algebra&_chainId=100"
)
DEFAULT_EXAMPLE_FILE = \
    os.path.join(".claude", "tasks", "algebra-subgraph", "example.md")


@dataclass
class PoolLiquidity:
    pool: str
    method: str
    subgraph_url: str
    current_liquidity: Optional[int] = None
    sqrt_price: Optional[int] = None
    current_tick: Optional[int] = None
    token0: Optional[str] = None
    token1: Optional[str] = None
    ticks_count: Optional[int] = None
    minted_liquidity_sum: Optional[int] = None
    burned_liquidity_sum: Optional[int] = None
    max_abs_tick_liquidity: Optional[int] = None


def _post_graphql(url: str, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    headers = {"content-type": "application/json"}
    resp = requests.post(url, json={"query": query, "variables": variables}, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        # Reraise with readable content
        raise RuntimeError(json.dumps(data["errors"], indent=2))
    return data


def _try_query_pool_entity(url: str, pool: str) -> Optional[Dict[str, Any]]:
    """
    Try common Pool entity shapes to get current liquidity.

    Returns a dict with fields if any attempt succeeds, else None.
    """
    # Normalize ID (most subgraphs use lowercase hex string for id)
    pid = pool.lower()

    attempts: List[Tuple[str, Dict[str, Any], str]] = [
        (
            # Attempt 1: single pool by id
            "query ($id: ID!) { pool(id: $id) { id liquidity sqrtPrice tick token0 { id symbol } token1 { id symbol } } }",
            {"id": pid},
            "pool_by_id",
        ),
        (
            # Attempt 2: pools list filtering by id (or address)
            "query ($id: String!) { pools(where: { id: $id }) { id liquidity sqrtPrice tick token0 { id symbol } token1 { id symbol } } }",
            {"id": pid},
            "pools_where_id",
        ),
        (
            # Attempt 3: pools filtered by address (some schemas expose `address` field)
            "query ($address: String!) { pools(where: { address: $address }) { id liquidity sqrtPrice tick token0 { id symbol } token1 { id symbol } } }",
            {"address": pid},
            "pools_where_address",
        ),
    ]

    for query, variables, tag in attempts:
        try:
            res = _post_graphql(url, query, variables)
            # try single result shape
            if res.get("data", {}).get("pool"):
                return res["data"]["pool"]
            # try list result shape
            pools = res.get("data", {}).get("pools")
            if isinstance(pools, list) and pools:
                return pools[0]
        except Exception:
            continue

    return None


def _query_ticks_summary(url: str, pool: str) -> Tuple[int, int, int, int]:
    """
    Query ticks for a pool and return summary metrics:
    - ticks_count
    - minted_liquidity_sum: sum(liquidityNet where > 0)
    - burned_liquidity_sum: -sum(liquidityNet where < 0)
    - max_abs_tick_liquidity: max(|liquidityNet|)
    """
    query = (
        "query GetTicks($skip: Int = 0, $first: Int, $where: Tick_filter, $orderBy: Tick_orderBy, "
        "$orderDirection: OrderDirection) {\n"
        "  ticks(skip: $skip, first: $first, orderBy: $orderBy, orderDirection: $orderDirection, where: $where) {\n"
        "    tickIdx\n    liquidityNet\n  }\n}"
    )

    # Paginate in case there are many ticks (though Algebra pools usually have few)
    first = 1000
    skip = 0
    total = 0
    minted_sum = 0
    burned_sum = 0
    max_abs = 0
    while True:
        variables = {
            "first": first,
            "skip": skip,
            "orderBy": "tickIdx",
            "orderDirection": "asc",
            "where": {"poolAddress": pool.lower()},
        }
        data = _post_graphql(url, query, variables)
        batch = data.get("data", {}).get("ticks", [])
        if not batch:
            break
        for t in batch:
            total += 1
            try:
                ln = int(t["liquidityNet"])  # subgraph returns string numbers
            except Exception:
                continue
            if ln > 0:
                minted_sum += ln
            elif ln < 0:
                burned_sum += -ln
            if abs(ln) > max_abs:
                max_abs = abs(ln)
        if len(batch) < first:
            break
        skip += first

    return total, minted_sum, burned_sum, max_abs


def parse_pool_from_example(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    content = open(path, "r", encoding="utf-8").read()
    m = re.search(r'"poolAddress"\s*:\s*"(0x[a-fA-F0-9]{40})"', content)
    return m.group(1) if m else None


def _erc20_decimals(w3: Web3, token_addr: str) -> Optional[int]:
    try:
        c = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
        return c.functions.decimals().call()
    except Exception:
        return None


def _erc20_symbol_or_name(w3: Web3, token_addr: str) -> str:
    try:
        c = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
        try:
            sym = c.functions.symbol().call()
            if sym:
                return sym
        except Exception:
            pass
        try:
            nm = c.functions.name().call()
            if nm:
                return nm
        except Exception:
            pass
    except Exception:
        pass
    return token_addr


def _pool_tokens_and_state(w3: Web3, pool_addr: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Return (token0, token1, sqrtPriceX96) from the pool via RPC if possible."""
    try:
        pool = w3.eth.contract(address=Web3.to_checksum_address(pool_addr), abi=ALGEBRA_POOL_ABI)
        t0 = pool.functions.token0().call()
        t1 = pool.functions.token1().call()
        sqrt_price_x96, *_ = pool.functions.globalState().call()
        return t0, t1, int(sqrt_price_x96)
    except Exception:
        return None, None, None


def _price_from_sqrtX96(sqrt_price_x96: int, dec0: int, dec1: int) -> Optional[Tuple[Decimal, Decimal]]:
    """Compute price0in1 and price1in0 using decimals. Returns (p01, p10)."""
    try:
        getcontext().prec = 60
        ratio = (Decimal(sqrt_price_x96) / (1 << 96)) ** 2
        # Adjust by decimals: token1 per token0
        p01 = ratio * Decimal(10 ** (dec0 - dec1))
        if p01 == 0:
            return None
        p10 = Decimal(1) / p01
        return p01, p10
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch Algebra pool liquidity from subgraph + RPC humanization")
    ap.add_argument("--pool", help="Pool address (0x…)")
    ap.add_argument("--from-example", action="store_true", help=f"Read pool from {DEFAULT_EXAMPLE_FILE}")
    ap.add_argument("--subgraph-url", default=DEFAULT_SUBGRAPH_URL, help="GraphQL subgraph endpoint URL")
    ap.add_argument("--rpc-url", default=os.getenv("RPC_URL", DEFAULT_RPC_URLS[0]), help="RPC URL for on-chain reads")
    ap.add_argument("--json", action="store_true", help="Output JSON only")
    args = ap.parse_args()

    pool = args.pool
    if args.from_example and not pool:
        pool = parse_pool_from_example(DEFAULT_EXAMPLE_FILE)
    if not pool:
        print("Error: --pool is required (or use --from-example)")
        sys.exit(1)

    # Normalize address lowercase for IDs/filters
    pool = pool.lower()
    result = PoolLiquidity(pool=pool, method="", subgraph_url=args.subgraph_url)

    # Try pool entity first
    pool_entity = _try_query_pool_entity(args.subgraph_url, pool)
    if pool_entity:
        # Map fields defensively
        result.method = "pool_entity"
        liq = pool_entity.get("liquidity")
        result.current_liquidity = int(liq) if isinstance(liq, str) and liq.isdigit() else (
            int(liq) if isinstance(liq, (int,)) else None
        )
        # Different subgraphs may name tick/sqrt differently
        if "sqrtPrice" in pool_entity:
            try:
                result.sqrt_price = int(pool_entity["sqrtPrice"])
            except Exception:
                pass
        if "tick" in pool_entity:
            try:
                result.current_tick = int(pool_entity["tick"])
            except Exception:
                pass
        # Tokens
        t0 = pool_entity.get("token0")
        t1 = pool_entity.get("token1")
        result.token0 = (t0 or {}).get("symbol") or (t0 or {}).get("id")
        result.token1 = (t1 or {}).get("symbol") or (t1 or {}).get("id")
    else:
        result.method = "ticks_fallback"

    # Always compute tick summary as additional context (also useful if pool entity fails)
    try:
        ticks_count, minted_sum, burned_sum, max_abs = _query_ticks_summary(args.subgraph_url, pool)
        result.ticks_count = ticks_count
        result.minted_liquidity_sum = minted_sum
        result.burned_liquidity_sum = burned_sum
        result.max_abs_tick_liquidity = max_abs
    except Exception as e:
        # Non-fatal
        pass

    # Optional RPC humanization
    w3 = Web3(Web3.HTTPProvider(args.rpc_url))
    t0_addr, t1_addr, sqrt_x96_rpc = _pool_tokens_and_state(w3, pool)
    t0_dec = _erc20_decimals(w3, t0_addr) if t0_addr else None
    t1_dec = _erc20_decimals(w3, t1_addr) if t1_addr else None
    t0_sym = _erc20_symbol_or_name(w3, t0_addr) if t0_addr else None
    t1_sym = _erc20_symbol_or_name(w3, t1_addr) if t1_addr else None

    # Prefer RPC sqrtPrice if subgraph didn't provide
    if result.sqrt_price is None and sqrt_x96_rpc is not None:
        result.sqrt_price = sqrt_x96_rpc

    # Compute human-readable price if possible
    price_01 = None
    price_10 = None
    if result.sqrt_price is not None and t0_dec is not None and t1_dec is not None:
        p = _price_from_sqrtX96(result.sqrt_price, t0_dec, t1_dec)
        if p:
            price_01, price_10 = p

    if args.json:
        # Extend JSON with RPC-derived fields
        extra = {
            "token0_address": t0_addr,
            "token1_address": t1_addr,
            "token0_symbol": t0_sym,
            "token1_symbol": t1_sym,
            "token0_decimals": t0_dec,
            "token1_decimals": t1_dec,
            "price_token0_in_token1": str(price_01) if price_01 is not None else None,
            "price_token1_in_token0": str(price_10) if price_10 is not None else None,
            "rpc_url": args.rpc_url,
        }
        out = {**result.__dict__, **extra}
        print(json.dumps(out, indent=2, default=str))
        return

    # Human output (keep existing debug prints, add human-readable section)
    print("Algebra Pool Liquidity (Subgraph)")
    print("-" * 40)
    print(f"Subgraph: {result.subgraph_url}")
    print(f"Pool:     {result.pool}")
    print(f"Method:   {result.method}")
    if result.token0 or result.token1:
        print(f"Tokens:   {result.token0} / {result.token1}")
    if result.current_liquidity is not None:
        print(f"Current liquidity (raw L): {result.current_liquidity}")
    if result.sqrt_price is not None:
        print(f"sqrtPriceX96: {result.sqrt_price}")
    if result.current_tick is not None:
        print(f"tick: {result.current_tick}")
    if result.ticks_count is not None:
        print(f"Ticks: {result.ticks_count}")
    if result.minted_liquidity_sum is not None:
        print(f"Minted liquidity sum (raw L): {result.minted_liquidity_sum}")
    if result.burned_liquidity_sum is not None:
        print(f"Burned liquidity sum (raw L): {result.burned_liquidity_sum}")
    if result.max_abs_tick_liquidity is not None:
        print(f"Max |liquidityNet| across ticks (raw L): {result.max_abs_tick_liquidity}")

    print("\nHuman Readable (via RPC)")
    print("-" * 40)
    print(f"RPC: {args.rpc_url}")
    if t0_addr and t1_addr:
        print(f"token0: {t0_sym or t0_addr} ({t0_addr}) decimals={t0_dec}")
        print(f"token1: {t1_sym or t1_addr} ({t1_addr}) decimals={t1_dec}")
    else:
        print("token0/token1: unavailable from RPC")
    if price_01 is not None and price_10 is not None:
        # Show with 8 decimals for readability
        try:
            print(f"Price: 1 {t0_sym or 'token0'} = {price_01:.8f} {t1_sym or 'token1'}")
            print(f"Inverse: 1 {t1_sym or 'token1'} = {price_10:.8f} {t0_sym or 'token0'}")
        except Exception:
            print(f"Price: 1 token0 = {price_01} token1")
            print(f"Inverse: 1 token1 = {price_10} token0")
    else:
        print("Price: unavailable (missing sqrtPriceX96 or decimals)")
    # Note about liquidity units
    print("Note: Uniswap v3/Algebra liquidity (L) is not a token-denominated amount;\n"
          "      it cannot be converted to token units using decimals alone.")


if __name__ == "__main__":
    main()
