#!/usr/bin/env python3
"""
Quick test script for Algebra tick sources (TickLens + direct tickTable).

What it does:
- Loads a .env file (defaults to .env.v2.0xa80641Bf70483A3524713A396deE0ebD642CEaEA)
- Connects to Gnosis RPC (from env) and a Swapr/Algebra pool (from env)
- Prints current tick and tickSpacing
- If a TickLens address is provided, queries:
  - getClosestActiveTicks(pool, currentTick)
  - getNextActiveTicks(pool, currentTick, N, true/false)
  - getPopulatedTicksInWord(pool, currentTick//256)
- Always tests direct bitmap read on the pool:
  - pool.tickTable(int16(word)) around current word
  - Decodes bits → raw ticks (tau = word*256 + bit) filtered by tau % tickSpacing == 0
  - Fetches ticks(tau) and prints liquidityTotal/liquidityDelta

Notes:
- Algebra uses RAW tick indexing for tickTable: word = tick // 256.
- The pool stores the bitmap; DataStorageOperator is not used here.
- Ticks ABI differs by version; we parse len(data) defensively.
"""

import argparse
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from web3 import Web3
# Web3 PoA middleware (support v5/v6/v7 import paths)
try:
    # web3.py v5/v6 style
    from web3.middleware import geth_poa_middleware as _poa_mw
    def _inject_poa(w3):
        w3.middleware_onion.inject(_poa_mw, layer=0)
except Exception:
    try:
        # web3.py v7 style
        from web3.middleware.proof_of_authority import ExtraDataToPOAMiddleware as _POAClass
        def _inject_poa(w3):
            w3.middleware_onion.inject(_POAClass, layer=0)
    except Exception:  # pragma: no cover
        def _inject_poa(w3):
            # No-op if middleware not available
            return


MIN_TICK = -887272
MAX_TICK = 887272


POOL_MIN_ABI = [
    {
        "name": "tickSpacing",
        "outputs": [{"type": "int24", "name": ""}],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "globalState",
        "outputs": [
            {"type": "uint160", "name": "price"},
            {"type": "int24", "name": "tick"},
            {"type": "uint16", "name": "fee"},
            {"type": "uint16", "name": "timepointIndex"},
            {"type": "uint8", "name": "communityFeeToken0"},
            {"type": "uint8", "name": "communityFeeToken1"},
            {"type": "bool", "name": "unlocked"},
        ],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "ticks",
        "outputs": [
            {"type": "uint128", "name": "liquidityTotal"},
            {"type": "int128", "name": "liquidityDelta"},
            {"type": "uint256", "name": "outerFeeGrowth0Token"},
            {"type": "uint256", "name": "outerFeeGrowth1Token"},
            {"type": "int56", "name": "outerTickCumulative"},
            {"type": "uint160", "name": "outerSecondsPerLiquidity"},
            {"type": "uint32", "name": "outerSecondsSpent"},
            {"type": "bool", "name": "initialized"},
        ],
        "inputs": [{"type": "int24", "name": "tick_"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "tickTable",
        "outputs": [{"type": "uint256", "name": ""}],
        "inputs": [{"type": "int16", "name": "word"}],
        "stateMutability": "view",
        "type": "function",
    },
]

TICKLENS_MIN_ABI = [
    {
        "name": "getClosestActiveTicks",
        "inputs": [
            {"type": "address", "name": "pool"},
            {"type": "int24", "name": "targetTick"},
        ],
        "outputs": [
            {
                "components": [
                    {"name": "tick", "type": "int24"},
                    {"name": "liquidityDelta", "type": "int128"},
                    {"name": "liquidityTotal", "type": "uint128"},
                    {"name": "initialized", "type": "bool"},
                ],
                "name": "",
                "type": "tuple[2]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "getNextActiveTicks",
        "inputs": [
            {"type": "address", "name": "pool"},
            {"type": "int24", "name": "startingTick"},
            {"type": "uint256", "name": "amount"},
            {"type": "bool", "name": "upperDirection"},
        ],
        "outputs": [
            {
                "components": [
                    {"name": "tick", "type": "int24"},
                    {"name": "liquidityDelta", "type": "int128"},
                    {"name": "liquidityTotal", "type": "uint128"},
                    {"name": "initialized", "type": "bool"},
                ],
                "name": "",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "getPopulatedTicksInWord",
        "inputs": [
            {"type": "address", "name": "pool"},
            {"type": "int16", "name": "tickTableIndex"},
        ],
        "outputs": [
            {
                "components": [
                    {"name": "tick", "type": "int24"},
                    {"name": "liquidityDelta", "type": "int128"},
                    {"name": "liquidityTotal", "type": "uint128"},
                    {"name": "initialized", "type": "bool"},
                ],
                "name": "",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


def load_env_file(path: str) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not os.path.exists(path):
        return env
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"export\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            if not m:
                continue
            key, val = m.group(1), m.group(2)
            # strip surrounding quotes if present
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            env[key] = val
            # also set into process env so other libs can see it
            os.environ[key] = val
    return env


def decode_tick_entry(data) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if isinstance(data, (list, tuple)):
        L = len(data)
        if L >= 1:
            out["liquidityTotal"] = int(data[0])
        if L >= 2:
            out["liquidityDelta"] = int(data[1])
        if L >= 8:
            # Uniswap-like variant with bool at the end
            out["initialized"] = bool(data[-1])
        else:
            # Algebra variant: infer from liquidityTotal
            out["initialized"] = int(out.get("liquidityTotal", 0)) > 0
    return out


def direct_bitmap_scan(
    w3: Web3,
    pool: Any,
    current_tick: int,
    tick_spacing: int,
    words_each_side: int,
    min_liq: int,
) -> List[Dict[str, int]]:
    base_word = current_tick // 256
    min_word = MIN_TICK // 256
    max_word = MAX_TICK // 256
    seen: set[int] = set()
    out: List[Dict[str, int]] = []

    def scan_word(word_index: int) -> None:
        nonlocal out
        if word_index < min_word or word_index > max_word:
            return
        try:
            word_val = int(pool.functions.tickTable(int(word_index)).call())
        except Exception:
            word_val = 0
        if word_val == 0:
            return
        for bit in range(256):
            if (word_val >> bit) & 1 == 0:
                continue
            tau = word_index * 256 + bit
            # Enforce global int24 bounds and spacing alignment
            if tau < MIN_TICK or tau > MAX_TICK:
                continue
            if tau % tick_spacing != 0:
                continue
            if tau in seen:
                continue
            seen.add(tau)
            try:
                data = pool.functions.ticks(int(tau)).call()
                info = decode_tick_entry(data)
                info["tick"] = int(tau)
            except Exception:
                continue
            if int(info.get("liquidityTotal", 0)) >= min_liq:
                out.append(info)

    # Base, then symmetric outward (within global word bounds)
    scan_word(base_word)
    for d in range(1, max(0, words_each_side) + 1):
        scan_word(base_word + d)
        scan_word(base_word - d)
    # Present sorted by tick
    out.sort(key=lambda x: x["tick"])
    return out


def main():
    ap = argparse.ArgumentParser(description="Test Algebra TickLens and tickTable decoding")
    ap.add_argument("--env-file", default=".env.v2.0xa80641Bf70483A3524713A396deE0ebD642CEaEA", help="Path to .env to load")
    ap.add_argument("--rpc-url", default=os.environ.get("RPC_URL"), help="RPC URL (defaults to env RPC_URL)")
    ap.add_argument("--pool", default=os.environ.get("SWAPR_POOL_YES_ADDRESS"), help="Pool address (defaults to SWAPR_POOL_YES_ADDRESS)")
    ap.add_argument("--ticklens", default=os.environ.get("ALGEBRA_TICKLENS") or os.environ.get("TICKLENS_ADDRESS"), help="TickLens address (optional)")
    ap.add_argument("--words", type=int, default=12, help="Words to scan each side of current word")
    ap.add_argument("--min-liq", type=int, default=1, help="Minimum liquidityTotal to report")
    ap.add_argument("--next-n", type=int, default=16, help="TickLens: number of next ticks above/below to fetch")
    ap.add_argument("--json", action="store_true", help="Emit JSON only")
    ap.add_argument("--verbose", action="store_true", help="Print extra details")
    args = ap.parse_args()

    # Load env first so CLI defaults resolve from it
    if args.env_file:
        load_env_file(args.env_file)
        # Re-read possibly updated defaults if flags not provided
        if not args.rpc_url:
            args.rpc_url = os.environ.get("RPC_URL")
        if not args.pool:
            args.pool = os.environ.get("SWAPR_POOL_YES_ADDRESS")
        if not args.ticklens:
            args.ticklens = os.environ.get("ALGEBRA_TICKLENS") or os.environ.get("TICKLENS_ADDRESS")

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or RPC_URL in env")
    if not args.pool:
        raise SystemExit("Missing --pool or SWAPR_POOL_YES_ADDRESS in env")

    w3 = Web3(Web3.HTTPProvider(args.rpc_url, request_kwargs={"timeout": 30}))
    # Gnosis is PoA; safe to inject (supports web3 v5/v6/v7)
    _inject_poa(w3)

    pool = w3.eth.contract(address=Web3.to_checksum_address(args.pool), abi=POOL_MIN_ABI)
    try:
        tick_spacing = int(pool.functions.tickSpacing().call())
    except Exception as e:
        raise SystemExit(f"Failed to call tickSpacing(): {e}")
    try:
        gs = pool.functions.globalState().call()
        current_tick = int(gs[1])
    except Exception as e:
        raise SystemExit(f"Failed to call globalState(): {e}")

    base_word = current_tick // 256
    # Compute aligned min/max ticks for this spacing
    min_tick_aligned = -(-MIN_TICK // tick_spacing) * tick_spacing
    max_tick_aligned = (MAX_TICK // tick_spacing) * tick_spacing
    min_word = MIN_TICK // 256
    max_word = MAX_TICK // 256

    if not args.json:
        print(f"RPC: {args.rpc_url}")
        print(f"Pool: {args.pool}")
        print(f"chainId: {w3.eth.chain_id}")
        print(f"tickSpacing: {tick_spacing}")
        print(f"currentTick: {current_tick} (word {base_word})")
        print(f"min_tick: {min_tick_aligned}  max_tick: {max_tick_aligned}")
        print(f"min_word: {min_word}  max_word: {max_word}")

    # TickLens block (optional)
    lens_results: Dict[str, object] = {}
    if args.ticklens:
        lens = w3.eth.contract(address=Web3.to_checksum_address(args.ticklens), abi=TICKLENS_MIN_ABI)
        try:
            closest = lens.functions.getClosestActiveTicks(pool.address, current_tick).call()
            # tuples of (tick, liquidityDelta, liquidityTotal, initialized)
            lens_results["closest"] = [
                {
                    "tick": int(t[0]),
                    "liquidityDelta": int(t[1]),
                    "liquidityTotal": int(t[2]),
                    "initialized": bool(t[3]),
                }
                for t in closest
            ]
        except Exception as e:
            lens_results["closest_error"] = str(e)

        try:
            next_up = lens.functions.getNextActiveTicks(pool.address, current_tick, int(args.next_n), True).call()
            lens_results["next_up"] = [
                {
                    "tick": int(t[0]),
                    "liquidityDelta": int(t[1]),
                    "liquidityTotal": int(t[2]),
                    "initialized": bool(t[3]),
                }
                for t in next_up
            ]
        except Exception as e:
            lens_results["next_up_error"] = str(e)

        try:
            next_down = lens.functions.getNextActiveTicks(pool.address, current_tick, int(args.next_n), False).call()
            lens_results["next_down"] = [
                {
                    "tick": int(t[0]),
                    "liquidityDelta": int(t[1]),
                    "liquidityTotal": int(t[2]),
                    "initialized": bool(t[3]),
                }
                for t in next_down
            ]
        except Exception as e:
            lens_results["next_down_error"] = str(e)

        try:
            word_ticks = lens.functions.getPopulatedTicksInWord(pool.address, int(base_word)).call()
            lens_results["word_ticks"] = [
                {
                    "tick": int(t[0]),
                    "liquidityDelta": int(t[1]),
                    "liquidityTotal": int(t[2]),
                    "initialized": bool(t[3]),
                }
                for t in word_ticks
            ]
        except Exception as e:
            lens_results["word_ticks_error"] = str(e)
    else:
        if not args.json and args.verbose:
            print("No TickLens address provided; skipping lens tests.")

    # Direct bitmap scan around current word
    direct = direct_bitmap_scan(
        w3=w3,
        pool=pool,
        current_tick=current_tick,
        tick_spacing=tick_spacing,
        words_each_side=max(0, int(args.words)),
        min_liq=max(0, int(args.min_liq)),
    )

    result = {
        "rpc": args.rpc_url,
        "pool": args.pool,
        "tickSpacing": tick_spacing,
        "currentTick": current_tick,
        "baseWord": base_word,
        "minTick": min_tick_aligned,
        "maxTick": max_tick_aligned,
        "minWord": min_word,
        "maxWord": max_word,
        "ticklens": (args.ticklens or ""),
        "ticklens_results": lens_results,
        "direct_bitmap_results": direct,
    }

    if args.json:
        import json as _json

        print(_json.dumps(result, indent=2))
        return

    # Human-friendly output
    if lens_results:
        print("\nTickLens:")
        if "closest" in lens_results:
            below, above = lens_results["closest"] if len(lens_results["closest"]) == 2 else (None, None)
            print(f"- Closest around current: below={below} above={above}")
        else:
            print(f"- closest: {lens_results.get('closest_error', 'n/a')}")
        if "next_up" in lens_results:
            print(f"- Next up ({len(lens_results['next_up'])}): {[t['tick'] for t in lens_results['next_up'][:10]]}")
        else:
            print(f"- next_up: {lens_results.get('next_up_error', 'n/a')}")
        if "next_down" in lens_results:
            print(f"- Next down ({len(lens_results['next_down'])}): {[t['tick'] for t in lens_results['next_down'][:10]]}")
        else:
            print(f"- next_down: {lens_results.get('next_down_error', 'n/a')}")
        if "word_ticks" in lens_results:
            print(f"- Word {base_word} populated ticks: {[t['tick'] for t in lens_results['word_ticks']]}")
        else:
            print(f"- word_ticks: {lens_results.get('word_ticks_error', 'n/a')}")

    print("\nDirect pool.tickTable + ticks():")
    print(f"- Found {len(direct)} initialized ticks with liquidity >= {args.min_liq} across ±{args.words} words")
    if args.verbose:
        for t in direct[:50]:
            print(f"  tick {t['tick']}: liqTotal={t['liquidityTotal']} liqDelta={t['liquidityDelta']}")


if __name__ == "__main__":
    main()
