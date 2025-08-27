#!/usr/bin/env python3
"""
Algebra pool tick reader

Reads tick-related data from an Algebra (Uniswap v3-like) pool:
- tickSpacing
- globalState (incl. active tick)
- ticks(tick) for a chosen tick (default: closest spaced tick to the active tick)
- getInnerCumulatives(bottomTick, topTick) for a symmetric range around current tick

Also includes utilities to discover initialized ticks with liquidity:
- Scan around the current tick for initialized tick boundaries
- Filter by minimum liquidityTotal
- Find nearest initialized boundaries above/below the current tick

Usage examples:
  python scripts/tick_reader.py \
    --rpc-url https://polygon-rpc.com \
    --address 0x471d34c1973e8312154d80a3955a5b597b6a1e1b

  python scripts/tick_reader.py \
    --rpc-url https://polygon-rpc.com \
    --address 0x471d34c1973e8312154d80a3955a5b597b6a1e1b \
    --range-multiple 10

  # Force a specific tick to inspect in ticks(tick)
  python scripts/tick_reader.py --tick -200560

  # Scan for initialized ticks with liquidity around current tick
  python scripts/tick_reader.py \
    --rpc-url "$RPC_URL" --address "$POOL" \
    --scan --scan-range 400 --min-liq-total 1

  # Find nearest initialized boundaries above/below the current tick
  python scripts/tick_reader.py --find-boundaries --nearest 8

Notes on Algebra bitmap indexing (Integral):
- word index uses RAW ticks: `word = tick // 256` (floor division, works for negatives)
- each word packs 256 bits for ticks `[word*256 .. word*256+255]`
- bit index `b` corresponds to tick `tau = word*256 + b`
- Typically only ticks aligned to `tickSpacing` are set; we filter by `tau % tickSpacing == 0`
"""

import argparse
import json
import sys
from typing import Optional, List
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from web3 import Web3


DEFAULT_RPC = "https://polygon-rpc.com"
DEFAULT_POOL = "0x471d34c1973e8312154d80a3955a5b597b6a1e1b"  # WMATIC/USDC Algebra pool (Polygon)

# Contract ABI (Algebra pool)
ABI = json.loads(
    """
    [{"inputs":[],"stateMutability":"nonpayable","type":"constructor"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"owner","type":"address"},{"indexed":true,"internalType":"int24","name":"bottomTick","type":"int24"},{"indexed":true,"internalType":"int24","name":"topTick","type":"int24"},{"indexed":false,"internalType":"uint128","name":"liquidityAmount","type":"uint128"},{"indexed":false,"internalType":"uint256","name":"amount0","type":"uint256"},{"indexed":false,"internalType":"uint256","name":"amount1","type":"uint256"}],"name":"Burn","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"owner","type":"address"},{"indexed":false,"internalType":"address","name":"recipient","type":"address"},{"indexed":true,"internalType":"int24","name":"bottomTick","type":"int24"},{"indexed":true,"internalType":"int24","name":"topTick","type":"int24"},{"indexed":false,"internalType":"uint128","name":"amount0","type":"uint128"},{"indexed":false,"internalType":"uint128","name":"amount1","type":"uint128"}],"name":"Collect","type":"event"},{"anonymous":false,"inputs":[{"indexed":false,"internalType":"uint8","name":"communityFee0New","type":"uint8"},{"indexed":false,"internalType":"uint8","name":"communityFee1New","type":"uint8"}],"name":"CommunityFee","type":"event"},{"anonymous":false,"inputs":[{"indexed":false,"internalType":"uint16","name":"fee","type":"uint16"}],"name":"Fee","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"sender","type":"address"},{"indexed":true,"internalType":"address","name":"recipient","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount0","type":"uint256"},{"indexed":false,"internalType":"uint256","name":"amount1","type":"uint256"},{"indexed":false,"internalType":"uint256","name":"paid0","type":"uint256"},{"indexed":false,"internalType":"uint256","name":"paid1","type":"uint256"}],"name":"Flash","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"virtualPoolAddress","type":"address"}],"name":"Incentive","type":"event"},{"anonymous":false,"inputs":[{"indexed":false,"internalType":"uint160","name":"price","type":"uint160"},{"indexed":false,"internalType":"int24","name":"tick","type":"int24"}],"name":"Initialize","type":"event"},{"anonymous":false,"inputs":[{"indexed":false,"internalType":"uint32","name":"liquidityCooldown","type":"uint32"}],"name":"LiquidityCooldown","type":"event"},{"anonymous":false,"inputs":[{"indexed":false,"internalType":"address","name":"sender","type":"address"},{"indexed":true,"internalType":"address","name":"owner","type":"address"},{"indexed":true,"internalType":"int24","name":"bottomTick","type":"int24"},{"indexed":true,"internalType":"int24","name":"topTick","type":"int24"},{"indexed":false,"internalType":"uint128","name":"liquidityAmount","type":"uint128"},{"indexed":false,"internalType":"uint256","name":"amount0","type":"uint256"},{"indexed":false,"internalType":"uint256","name":"amount1","type":"uint256"}],"name":"Mint","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"sender","type":"address"},{"indexed":true,"internalType":"address","name":"recipient","type":"address"},{"indexed":false,"internalType":"int256","name":"amount0","type":"int256"},{"indexed":false,"internalType":"int256","name":"amount1","type":"int256"},{"indexed":false,"internalType":"uint160","name":"price","type":"uint160"},{"indexed":false,"internalType":"uint128","name":"liquidity","type":"uint128"},{"indexed":false,"internalType":"int24","name":"tick","type":"int24"}],"name":"Swap","type":"event"},{"anonymous":false,"inputs":[{"indexed":false,"internalType":"int24","name":"newTickSpacing","type":"int24"}],"name":"TickSpacing","type":"event"},{"inputs":[],"name":"activeIncentive","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"int24","name":"bottomTick","type":"int24"},{"internalType":"int24","name":"topTick","type":"int24"},{"internalType":"uint128","name":"amount","type":"uint128"}],"name":"burn","outputs":[{"internalType":"uint256","name":"amount0","type":"uint256"},{"internalType":"uint256","name":"amount1","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"recipient","type":"address"},{"internalType":"int24","name":"bottomTick","type":"int24"},{"internalType":"int24","name":"topTick","type":"int24"},{"internalType":"uint128","name":"amount0Requested","type":"uint128"},{"internalType":"uint128","name":"amount1Requested","type":"uint128"}],"name":"collect","outputs":[{"internalType":"uint128","name":"amount0","type":"uint128"},{"internalType":"uint128","name":"amount1","type":"uint128"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"dataStorageOperator","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"factory","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"recipient","type":"address"},{"internalType":"uint256","name":"amount0","type":"uint256"},{"internalType":"uint256","name":"amount1","type":"uint256"},{"internalType":"bytes","name":"data","type":"bytes"}],"name":"flash","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"int24","name":"bottomTick","type":"int24"},{"internalType":"int24","name":"topTick","type":"int24"}],"name":"getInnerCumulatives","outputs":[{"internalType":"int56","name":"innerTickCumulative","type":"int56"},{"internalType":"uint160","name":"innerSecondsSpentPerLiquidity","type":"uint160"},{"internalType":"uint32","name":"innerSecondsSpent","type":"uint32"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"uint32[]","name":"secondsAgos","type":"uint32[]"}],"name":"getTimepoints","outputs":[{"internalType":"int56[]","name":"tickCumulatives","type":"int56[]"},{"internalType":"uint160[]","name":"secondsPerLiquidityCumulatives","type":"uint160[]"},{"internalType":"uint112[]","name":"volatilityCumulatives","type":"uint112[]"},{"internalType":"uint256[]","name":"volumePerAvgLiquiditys","type":"uint256[]"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"globalState","outputs":[{"internalType":"uint160","name":"price","type":"uint160"},{"internalType":"int24","name":"tick","type":"int24"},{"internalType":"uint16","name":"fee","type":"uint16"},{"internalType":"uint16","name":"timepointIndex","type":"uint16"},{"internalType":"uint8","name":"communityFeeToken0","type":"uint8"},{"internalType":"uint8","name":"communityFeeToken1","type":"uint8"},{"internalType":"bool","name":"unlocked","type":"bool"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"uint160","name":"initialPrice","type":"uint160"}],"name":"initialize","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"liquidity","outputs":[{"internalType":"uint128","name":"","type":"uint128"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"liquidityCooldown","outputs":[{"internalType":"uint32","name":"","type":"uint32"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"maxLiquidityPerTick","outputs":[{"internalType":"uint128","name":"","type":"uint128"}],"stateMutability":"pure","type":"function"},{"inputs":[{"internalType":"address","name":"sender","type":"address"},{"internalType":"address","name":"recipient","type":"address"},{"internalType":"int24","name":"bottomTick","type":"int24"},{"internalType":"int24","name":"topTick","type":"int24"},{"internalType":"uint128","name":"liquidityDesired","type":"uint128"},{"internalType":"bytes","name":"data","type":"bytes"}],"name":"mint","outputs":[{"internalType":"uint256","name":"amount0","type":"uint256"},{"internalType":"uint256","name":"amount1","type":"uint256"},{"internalType":"uint128","name":"liquidityActual","type":"uint128"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"bytes32","name":"","type":"bytes32"}],"name":"positions","outputs":[{"internalType":"uint128","name":"liquidity","type":"uint128"},{"internalType":"uint32","name":"lastLiquidityAddTimestamp","type":"uint32"},{"internalType":"uint256","name":"innerFeeGrowth0Token","type":"uint256"},{"internalType":"uint256","name":"innerFeeGrowth1Token","type":"uint256"},{"internalType":"uint128","name":"fees0","type":"uint128"},{"internalType":"uint128","name":"fees1","type":"uint128"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"uint8","name":"communityFee0","type":"uint8"},{"internalType":"uint8","name":"communityFee1","type":"uint8"}],"name":"setCommunityFee","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"virtualPoolAddress","type":"address"}],"name":"setIncentive","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"uint32","name":"newLiquidityCooldown","type":"uint32"}],"name":"setLiquidityCooldown","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"int24","name":"newTickSpacing","type":"int24"}],"name":"setTickSpacing","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"recipient","type":"address"},{"internalType":"bool","name":"zeroToOne","type":"bool"},{"internalType":"int256","name":"amountRequired","type":"int256"},{"internalType":"uint160","name":"limitSqrtPrice","type":"uint160"},{"internalType":"bytes","name":"data","type":"bytes"}],"name":"swap","outputs":[{"internalType":"int256","name":"amount0","type":"int256"},{"internalType":"int256","name":"amount1","type":"int256"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"internalType":"address","name":"sender","type":"address"},{"internalType":"address","name":"recipient","type":"address"},{"internalType":"bool","name":"zeroToOne","type":"bool"},{"internalType":"int256","name":"amountRequired","type":"int256"},{"internalType":"uint160","name":"limitSqrtPrice","type":"uint160"},{"internalType":"bytes","name":"data","type":"bytes"}],"name":"swapSupportingFeeOnInputTokens","outputs":[{"internalType":"int256","name":"amount0","type":"int256"},{"internalType":"int256","name":"amount1","type":"int256"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[],"name":"tickSpacing","outputs":[{"internalType":"int24","name":"","type":"int24"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"int16","name":"","type":"int16"}],"name":"tickTable","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"int24","name":"","type":"int24"}],"name":"ticks","outputs":[{"internalType":"uint128","name":"liquidityTotal","type":"uint128"},{"internalType":"int128","name":"liquidityDelta","type":"int128"},{"internalType":"uint256","name":"outerFeeGrowth0Token","type":"uint256"},{"internalType":"uint256","name":"outerFeeGrowth1Token","type":"uint256"},{"internalType":"int56","name":"outerTickCumulative","type":"int56"},{"internalType":"uint160","name":"outerSecondsPerLiquidity","type":"uint160"},{"internalType":"uint32","name":"outerSecondsSpent","type":"uint32"},{"internalType":"bool","name":"initialized","type":"bool"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"uint256","name":"index","type":"uint256"}],"name":"timepoints","outputs":[{"internalType":"bool","name":"initialized","type":"bool"},{"internalType":"uint32","name":"blockTimestamp","type":"uint32"},{"internalType":"int56","name":"tickCumulative","type":"int56"},{"internalType":"uint160","name":"secondsPerLiquidityCumulative","type":"uint160"},{"internalType":"uint88","name":"volatilityCumulative","type":"uint88"},{"internalType":"int24","name":"averageTick","type":"int24"},{"internalType":"uint144","name":"volumePerLiquidityCumulative","type":"uint144"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"totalFeeGrowth0Token","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"totalFeeGrowth1Token","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
    """
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Read Algebra pool tick-related data")
    p.add_argument("--rpc-url", default=DEFAULT_RPC, help="RPC endpoint URL (default: Polygon public RPC)")
    p.add_argument("--address", default=DEFAULT_POOL, help="Algebra pool address")
    p.add_argument("--tick", type=int, default=None, help="Specific tick to inspect via ticks(tick)")
    p.add_argument(
        "--range-multiple",
        type=int,
        default=5,
        help="Half-range in multiples of tickSpacing for getInnerCumulatives (default: 5)",
    )
    # Scan options
    p.add_argument("--scan", action="store_true", help="Scan around current tick for initialized ticks")
    p.add_argument("--scan-range", type=int, default=200, help="Scan radius in multiples of tickSpacing (default: 200)")
    p.add_argument("--direction", choices=["both", "up", "down"], default="both", help="Scan direction relative to current tick")
    p.add_argument("--min-liq-total", type=int, default=0, help="Filter to ticks where liquidityTotal >= this value (default: 0)")
    p.add_argument("--max-results", type=int, default=0, help="Stop scanning after this many matches (0 = unlimited)")
    p.add_argument("--json", action="store_true", help="Print scan results as JSON")
    p.add_argument("--find-boundaries", action="store_true", help="Find nearest initialized ticks above and below current tick")
    p.add_argument("--nearest", type=int, default=3, help="How many nearest boundaries to show per direction (default: 3)")
    # Bitmap scanning options
    p.add_argument("--use-bitmap", action="store_true", help="Use tickTable bitmap for fast scanning")
    p.add_argument("--bitmap-words", type=int, default=16, help="Initial 256-bit words per direction to scan (deprecated, see --bitmap-max-words)")
    p.add_argument("--bitmap-max-words", type=int, default=None, help="Max 256-bit words to scan per direction when using bitmap (overrides --bitmap-words)")
    p.add_argument("--bitmap-only", action="store_true", help="Only consider ticks discovered via bitmap (don’t probe sequentially)")
    p.add_argument("--bitmap-verbose", action="store_true", help="Log bitmap word scans and bit counts")
    p.add_argument("--bitmap-source", choices=["auto", "pool", "dso"], default="auto", help="Where to read tickTable from: pool, DataStorageOperator, or auto-detect")
    # Parallelism
    default_threads = min(8, (os.cpu_count() or 4))
    p.add_argument("--threads", type=int, default=default_threads, help=f"Parallel threads for scanning (default: {default_threads})")
    # Progress
    p.add_argument("--progress", action="store_true", help="Display a live progress line (stderr) during scans")
    # Event scanning
    p.add_argument("--scan-events", action="store_true", help="Scan Mint/Burn/Initialize logs to collect boundary ticks")
    p.add_argument("--from-block", type=int, default=None, help="Start block for event scan (default 0)")
    p.add_argument("--to-block", type=int, default=None, help="End block for event scan (default latest)")
    p.add_argument("--chunk-blocks", type=int, default=25000, help="Block chunk size for get_logs (default 25000)")
    p.add_argument("--event-types", default="Mint,Burn,Initialize", help="Comma-separated events to include (default Mint,Burn,Initialize)")
    return p.parse_args()


def checksum(w3: Web3, addr: str) -> str:
    try:
        return w3.to_checksum_address(addr)
    except Exception as e:
        print(f"Invalid address '{addr}': {e}")
        sys.exit(2)


def main():
    args = parse_args()

    print(f"Connecting to blockchain via {args.rpc_url}...")
    try:
        w3 = Web3(Web3.HTTPProvider(args.rpc_url))
        if not w3.is_connected():
            print("Failed to connect to the node.")
            sys.exit(1)
        print(f"Successfully connected. Current block: {w3.eth.block_number}")
    except Exception as e:
        print(f"Error connecting to Web3 provider: {e}")
        sys.exit(1)

    contract_address = checksum(w3, args.address)
    contract = w3.eth.contract(address=contract_address, abi=ABI)
    print(f"Contract loaded at address: {contract.address}")
    # DSO discovery kept for completeness but bitmap reads use pool.tickTable per Algebra specs
    dso_address = None
    dso_contract = None
    try:
        dso_address = contract.functions.dataStorageOperator().call()
        if Web3.is_address(dso_address) and int(dso_address, 16) != 0 and args.bitmap_verbose:
            print(f"[bitmap] DSO discovered: {dso_address}")
    except Exception:
        pass

    print("\n" + "=" * 50)
    try:
        print("1. Calling tickSpacing()...")
        tick_spacing = contract.functions.tickSpacing().call()
        print(f"   -> Tick Spacing: {tick_spacing}")
    except Exception as e:
        print(f"   -> Error calling tickSpacing(): {e}")
        sys.exit(1)

    print("\n" + "=" * 50)
    try:
        print("2. Calling globalState()...")
        state = contract.functions.globalState().call()
        state_labels = [
            "price",
            "tick",
            "fee",
            "timepointIndex",
            "communityFeeToken0",
            "communityFeeToken1",
            "unlocked",
        ]
        global_state = dict(zip(state_labels, state))
        current_tick: int = int(global_state["tick"])  # type: ignore

        print("   -> Global State:")
        for k, v in global_state.items():
            print(f"      - {k}: {v}")
    except Exception as e:
        print(f"   -> Error calling globalState(): {e}")
        sys.exit(1)

    # Define allowed tick range for int24 and derived compressed range
    MIN_TICK = -(2 ** 23)
    MAX_TICK = (2 ** 23) - 1
    comp_min = math.ceil(MIN_TICK / tick_spacing)
    comp_max = math.floor(MAX_TICK / tick_spacing)
    min_wp = comp_min >> 8
    max_wp = comp_max >> 8

    print("\n" + "=" * 50)
    try:
        if args.tick is not None:
            tick_to_query = int(args.tick)
        else:
            # closest spaced tick to the active tick
            tick_to_query = (current_tick // tick_spacing) * tick_spacing
        print(
            f"3. Calling ticks(tick) with the {'specified' if args.tick is not None else 'closest spaced'} tick: {tick_to_query}..."
        )
        tick_data = contract.functions.ticks(tick_to_query).call()
        tick_labels = [
            "liquidityTotal",
            "liquidityDelta",
            "outerFeeGrowth0Token",
            "outerFeeGrowth1Token",
            "outerTickCumulative",
            "outerSecondsPerLiquidity",
            "outerSecondsSpent",
            "initialized",
        ]
        tick_details = dict(zip(tick_labels, tick_data))

        print(f"   -> Details for Tick {tick_to_query}:")
        for k, v in tick_details.items():
            print(f"      - {k}: {v}")
    except Exception as e:
        print(f"   -> Error calling ticks(): {e}")

    print("\n" + "=" * 50)
    try:
        half_range = max(1, int(args.range_multiple)) * tick_spacing
        bottom_tick = ((current_tick - half_range) // tick_spacing) * tick_spacing
        top_tick = ((current_tick + half_range) // tick_spacing) * tick_spacing

        print("4. Calling getInnerCumulatives(bottomTick, topTick)...")
        print(f"   - bottomTick: {bottom_tick}")
        print(f"   - topTick:    {top_tick}")

        cumulatives_data = contract.functions.getInnerCumulatives(bottom_tick, top_tick).call()
        cumulatives_labels = [
            "innerTickCumulative",
            "innerSecondsSpentPerLiquidity",
            "innerSecondsSpent",
        ]
        cumulatives_details = dict(zip(cumulatives_labels, cumulatives_data))

        print(f"   -> Cumulative data for range [{bottom_tick}, {top_tick}]:")
        for k, v in cumulatives_details.items():
            print(f"      - {k}: {v}")
    except Exception as e:
        print(f"\n   -> Could not call getInnerCumulatives(): {e}")
        print(
            f"   -> This is often because one or both ticks in the range [{bottom_tick}, {top_tick}] have not been initialized."
        )

    # ------------------------------------------------------------------
    # Optional: Event scan for boundary ticks (Mint/Burn/Initialize)
    # Parallelized across block chunks with --threads
    # ------------------------------------------------------------------
    if args.scan_events:
        print("\n" + "=" * 50)
        print("Scanning events for boundary ticks…")
        from_block = args.from_block if args.from_block is not None else 0
        to_block = args.to_block if args.to_block is not None else w3.eth.block_number
        chunk = max(1000, int(args.chunk_blocks))
        include = set([s.strip().lower() for s in args.event_types.split(',') if s.strip()])

        # Prepare event interfaces (may be None if not present)
        events = {}
        try:
            events['mint'] = contract.events.Mint()
        except Exception:
            events['mint'] = None
        try:
            events['burn'] = contract.events.Burn()
        except Exception:
            events['burn'] = None
        try:
            events['initialize'] = contract.events.Initialize()
        except Exception:
            events['initialize'] = None

        # Build chunk list
        ranges = []
        cur = from_block
        while cur <= to_block:
            end = min(cur + chunk - 1, to_block)
            ranges.append((cur, end))
            cur = end + 1

        # Build tasks: one per (event, range)
        tasks = []
        for (name, evt) in events.items():
            if evt is None or name not in include:
                continue
            for (start, end) in ranges:
                tasks.append((name, evt, start, end))

        total_tasks = len(tasks)
        done_tasks = 0
        boundary_ticks = set()

        def _progress(label: str, done: int, total: int):
            if not args.progress:
                return
            pct = 100.0 * done / total if total else 100.0
            sys.stderr.write(f"\r[{label}] {done}/{total} ({pct:.1f}%)")
            sys.stderr.flush()

        def _finish_progress():
            if args.progress:
                sys.stderr.write("\n")
                sys.stderr.flush()

        def _scan_task(name, evt, start, end):
            out = []
            try:
                logs = w3.eth.get_logs({
                    'address': contract.address,
                    'fromBlock': int(start),
                    'toBlock': int(end),
                    'topics': [evt.signature]
                })
            except Exception:
                logs = []
            for log in logs:
                try:
                    decoded = evt.process_log(log)
                except Exception:
                    continue
                if name in ('mint', 'burn'):
                    bt = int(decoded['args'].get('bottomTick', 0))
                    tt = int(decoded['args'].get('topTick', 0))
                    out.append((bt // tick_spacing) * tick_spacing)
                    out.append((tt // tick_spacing) * tick_spacing)
                elif name == 'initialize':
                    t0 = int(decoded['args'].get('tick', 0))
                    out.append((t0 // tick_spacing) * tick_spacing)
            return out

        # Run in parallel
        if total_tasks == 0:
            print("No eligible events to scan with current options.")
        else:
            with ThreadPoolExecutor(max_workers=max(1, args.threads)) as ex:
                futs = [ex.submit(_scan_task, name, evt, start, end) for (name, evt, start, end) in tasks]
                for fut in as_completed(futs):
                    try:
                        for t in fut.result() or []:
                            boundary_ticks.add(int(t))
                    except Exception:
                        pass
                    done_tasks += 1
                    _progress('events', done_tasks, total_tasks)
            _finish_progress()

        results = sorted(boundary_ticks)
        if args.json:
            print(json.dumps({
                'current_tick': current_tick,
                'base_tick': (current_tick // tick_spacing) * tick_spacing,
                'tick_spacing': tick_spacing,
                'event_boundaries_count': len(results),
                'event_boundaries': results[:1000],
                'from_block': from_block,
                'to_block': to_block,
                'chunk_blocks': chunk,
                'threads': args.threads,
            }, indent=2))
        else:
            print(f"Found {len(results)} boundary ticks from events (showing up to 1000):")
            for t in results[:1000]:
                print(f"  tick {t}")

    # ------------------------------------------------------------------
    # Optional: Scan for initialized ticks with liquidity
    # ------------------------------------------------------------------
    if args.scan or args.find_boundaries:
        print("\n" + "=" * 50)
        def read_tick(t: int):
            data = contract.functions.ticks(int(t)).call()
            # Support both ABIs: older (8 items + initialized bool) and newer (with prevTick/nextTick)
            out = {"tick": int(t)}
            if isinstance(data, (list, tuple)):
                L = len(data)
                # Common leading fields
                if L >= 2:
                    out["liquidityTotal"] = int(data[0])
                    out["liquidityDelta"] = int(data[1])
                if L >= 4:
                    out["outerFeeGrowth0Token"] = int(data[2])
                    out["outerFeeGrowth1Token"] = int(data[3])
                if L >= 7:
                    out["outerTickCumulative"] = int(data[4])
                    out["outerSecondsPerLiquidity"] = int(data[5])
                    out["outerSecondsSpent"] = int(data[6])
                # Tail variants
                if L >= 9 and isinstance(data[7], (int,)) and isinstance(data[8], (int,)):
                    # Likely Algebra variant with prevTick, nextTick (no bool)
                    out["prevTick"] = int(data[7])
                    out["nextTick"] = int(data[8])
                    out["initialized"] = True if int(out.get("liquidityTotal", 0)) > 0 else False
                elif L >= 8:
                    # Likely Uniswap-like with initialized bool at the end
                    out["initialized"] = bool(data[-1])
                else:
                    out["initialized"] = int(out.get("liquidityTotal", 0)) > 0
            return out

        # Parallel helpers
        def _progress_update(label: str, done: int, total: int) -> None:
            if not args.progress:
                return
            pct = 100.0 * done / total if total else 100.0
            sys.stderr.write(f"\r[{label}] {done}/{total} ({pct:.1f}%)")
            sys.stderr.flush()

        def _progress_finish() -> None:
            if args.progress:
                sys.stderr.write("\n")
                sys.stderr.flush()

        def _read_ticks_parallel(ticks: List[int], threads: int, label: Optional[str] = None) -> List[dict]:
            results: List[dict] = []
            total = len(ticks)
            label = label or "ticks"
            done = 0
            if threads <= 1:
                for t in ticks:
                    try:
                        results.append(read_tick(t))
                    except Exception:
                        pass
                    done += 1
                    _progress_update(label, done, total)
                _progress_finish()
                return results
            with ThreadPoolExecutor(max_workers=max(1, threads)) as ex:
                future_to_tick = {ex.submit(read_tick, t): t for t in ticks}
                for fut in as_completed(future_to_tick):
                    try:
                        info = fut.result()
                        results.append(info)
                    except Exception:
                        pass
                    done += 1
                    _progress_update(label, done, total)
            _progress_finish()
            return results

        def _build_tick_list(start_tick: int, step: int, multiples: int) -> List[int]:
            return [start_tick + i * step * tick_spacing for i in range(1, multiples + 1)]

        # Sequential/parallel scan stepping by tickSpacing
        def scan_direction_seq(start_tick: int, step: int, multiples: int, min_liq: int, limit: int, threads: int):
            ticks = _build_tick_list(start_tick, step, multiples)
            infos = _read_ticks_parallel(ticks, threads)
            # Filter and order according to direction
            if step > 0:
                infos.sort(key=lambda x: x["tick"])  # ascending
            else:
                infos.sort(key=lambda x: x["tick"], reverse=True)  # descending (nearest first)
            found: List[dict] = []
            for info in infos:
                if info.get("initialized") and info.get("liquidityTotal", 0) >= min_liq:
                    found.append(info)
                    if limit and len(found) >= limit:
                        break
            return found

        # Bitmap-based scan helpers (Algebra Integral indexing)
        FULL_MASK_256 = (1 << 256) - 1

        def ticktable_word(word_pos: int) -> int:
            # Algebra pool tickTable(int16) packs raw ticks: word = tick // 256
            return int(contract.functions.tickTable(int(word_pos)).call())

        def _fetch_words_parallel(positions: List[int], threads: int, label: str) -> dict:
            out = {}
            total = len(positions)
            done = 0
            if threads <= 1:
                for p in positions:
                    try:
                        out[p] = ticktable_word(p)
                    except Exception:
                        out[p] = 0
                    done += 1
                    _progress_update(label, done, total)
                _progress_finish()
                return out
            with ThreadPoolExecutor(max_workers=max(1, threads)) as ex:
                futs = {ex.submit(ticktable_word, p): p for p in positions}
                for fut in as_completed(futs):
                    p = futs[fut]
                    try:
                        out[p] = fut.result()
                    except Exception:
                        out[p] = 0
                    done += 1
                    _progress_update(label, done, total)
            _progress_finish()
            return out

        def _log_bitmap_word(word_pos: int, bits: int) -> None:
            if not args.bitmap_verbose:
                return
            count = bits.bit_count() if hasattr(int, 'bit_count') else bin(bits).count('1')
            print(f"[bitmap] word {word_pos}: nonzero={bits!=0} bits={count}")

        def _mask_range(word: int, low: int, high: int) -> int:
            if high < low:
                return 0
            # mask bits [low, high]
            upper = (1 << (high + 1)) - 1
            lower = (1 << low) - 1
            return word & (upper ^ lower)

        def scan_bitmap_up(base_word: int, start_bit: int, max_words: int, min_liq: int, limit: int) -> (List[dict], dict):
            """Find initialized ticks >= current (upwards) using raw tick words. Returns (results, stats)."""
            stats = {"words_scanned": 0, "nonzero_words": 0, "bits_seen": 0}
            results: List[dict] = []
            min_word = MIN_TICK // 256
            max_word = MAX_TICK // 256
            end_wp = min(base_word + max_words, max_word)
            positions = [wp for wp in range(base_word, end_wp + 1)]
            words_map = _fetch_words_parallel(positions, args.threads, label="bitmap-up")
            for i, wp in enumerate(positions):
                word = int(words_map.get(wp, 0))
                stats["words_scanned"] += 1
                if word:
                    stats["nonzero_words"] += 1
                # Allowed bits within int24 range
                allowed_low = 0
                allowed_high = 255
                # honor start_bit for first word
                if i == 0:
                    allowed_low = max(allowed_low, start_bit)
                bits = _mask_range(word, allowed_low, allowed_high)
                _log_bitmap_word(wp, bits)

                while bits and (not limit or len(results) < limit):
                    lsb = bits & -bits
                    pos = lsb.bit_length() - 1
                    stats["bits_seen"] += 1
                    tau = wp * 256 + pos
                    # Algebra: typically only ticks aligned to tickSpacing are valid boundaries
                    if tau % tick_spacing != 0 or tau < MIN_TICK or tau > MAX_TICK:
                        bits ^= lsb
                        continue
                    t = tau
                    info = read_tick(t)
                    # Treat as valid if liquidityTotal>0 or neighbors (prev/next) suggest presence
                    if int(info.get("liquidityTotal", 0)) >= min_liq:
                        results.append(info)
                    bits ^= lsb
                    if limit and len(results) >= limit:
                        break
            return results, stats

        def scan_bitmap_down(base_word: int, start_bit: int, max_words: int, min_liq: int, limit: int) -> (List[dict], dict):
            """Find initialized ticks <= current (downwards) using raw tick words. Returns (results, stats)."""
            stats = {"words_scanned": 0, "nonzero_words": 0, "bits_seen": 0}
            results: List[dict] = []
            min_word = MIN_TICK // 256
            start_wp = max(base_word - max_words, min_word)
            positions = [wp for wp in range(base_word, start_wp - 1, -1)]
            words_map = _fetch_words_parallel(positions, args.threads, label="bitmap-down")
            for i, wp in enumerate(positions):
                word = int(words_map.get(wp, 0))
                stats["words_scanned"] += 1
                if word:
                    stats["nonzero_words"] += 1
                # Allowed bits within int24 range
                allowed_low = 0
                allowed_high = 255
                # honor start_bit for first word upper bound
                if i == 0:
                    allowed_high = min(allowed_high, start_bit)
                bits = _mask_range(word, allowed_low, allowed_high)
                _log_bitmap_word(wp, bits)

                while bits and (not limit or len(results) < limit):
                    pos = bits.bit_length() - 1  # MSB index
                    stats["bits_seen"] += 1
                    tau = wp * 256 + pos
                    if tau % tick_spacing != 0 or tau < MIN_TICK or tau > MAX_TICK:
                        bits ^= (1 << pos)
                        continue
                    t = tau
                    info = read_tick(t)
                    if int(info.get("liquidityTotal", 0)) >= min_liq:
                        results.append(info)
                    bits ^= (1 << pos)
                    if limit and len(results) >= limit:
                        break
            return results, stats

        # Compute base tick on spacing grid
        base_tick = (current_tick // tick_spacing) * tick_spacing

        if args.find_boundaries:
            print("Finding nearest initialized boundaries around current tick…")
            if args.use_bitmap:
                base_word = current_tick // 256
                start_bit = current_tick - base_word * 256
                max_words = args.bitmap_max_words if args.bitmap_max_words is not None else args.bitmap_words
                up, up_stats = scan_bitmap_up(base_word, start_bit, max_words, args.min_liq_total, args.nearest)
                down, down_stats = scan_bitmap_down(base_word, start_bit, max_words, args.min_liq_total, args.nearest)
                down = list(reversed(down))
            else:
                up = scan_direction_seq(base_tick, +1, args.scan_range, args.min_liq_total, args.nearest, args.threads)
                down = scan_direction_seq(base_tick, -1, args.scan_range, args.min_liq_total, args.nearest, args.threads)
                down = list(reversed(down))  # present from nearest to farthest below

            results = {
                "current_tick": current_tick,
                "base_tick": base_tick,
                "tick_spacing": tick_spacing,
                "below": down,
                "above": up,
            }

            if args.json:
                if args.use_bitmap:
                    results["bitmap_stats"] = {
                        "above": up_stats,
                        "below": down_stats,
                    }
                print(json.dumps(results, indent=2))
            else:
                print(f"Current tick: {current_tick} (base {base_tick}), spacing {tick_spacing}")
                if args.use_bitmap:
                    print(f"[bitmap] scanned up {up_stats['words_scanned']} words (nonzero {up_stats['nonzero_words']}, bits {up_stats['bits_seen']}); down {down_stats['words_scanned']} words (nonzero {down_stats['nonzero_words']}, bits {down_stats['bits_seen']})")
                print("Nearest below:")
                if not down:
                    print("  (none found within range)")
                for r in down:
                    print(
                        f"  tick {r['tick']}: init={r['initialized']} liqTotal={r['liquidityTotal']} liqDelta={r['liquidityDelta']}"
                    )
                print("Nearest above:")
                if not up:
                    print("  (none found within range)")
                for r in up:
                    print(
                        f"  tick {r['tick']}: init={r['initialized']} liqTotal={r['liquidityTotal']} liqDelta={r['liquidityDelta']}"
                    )

        if args.scan:
            print("Scanning around current tick for initialized ticks…")
            ticks_out: List[dict] = []
            seen = set()

            if args.use_bitmap:
                base_word = current_tick // 256
                start_bit = current_tick - base_word * 256
                max_words = args.bitmap_max_words if args.bitmap_max_words is not None else args.bitmap_words
                # include base if initialized
                if not args.bitmap_only:
                    center_info = read_tick(base_tick)
                    if center_info["initialized"] and center_info["liquidityTotal"] >= args.min_liq_total:
                        ticks_out.append(center_info)
                        seen.add(base_tick)

                if args.direction in ("both", "up"):
                    up_infos, up_stats = scan_bitmap_up(
                        base_word, start_bit, max_words, args.min_liq_total,
                        0 if args.max_results == 0 else max(0, args.max_results - len(ticks_out))
                    )
                    for info in up_infos:
                        if info["tick"] not in seen:
                            ticks_out.append(info)
                            seen.add(info["tick"])
                        if args.max_results and len(ticks_out) >= args.max_results:
                            break
                if not (args.max_results and len(ticks_out) >= args.max_results) and args.direction in ("both", "down"):
                    down_infos, down_stats = scan_bitmap_down(
                        base_word, start_bit, max_words, args.min_liq_total,
                        0 if args.max_results == 0 else max(0, args.max_results - len(ticks_out))
                    )
                    for info in down_infos:
                        if info["tick"] not in seen:
                            ticks_out.append(info)
                            seen.add(info["tick"])
                        if args.max_results and len(ticks_out) >= args.max_results:
                            break
            else:
                # include base tick
                center_info = read_tick(base_tick)
                if center_info["initialized"] and center_info["liquidityTotal"] >= args.min_liq_total:
                    ticks_out.append(center_info)
                    seen.add(base_tick)

                # scan directions per selection
                directions = []
                if args.direction in ("both", "down"):
                    directions.append(-1)
                if args.direction in ("both", "up"):
                    directions.append(+1)

                for d in directions:
                    infos = scan_direction_seq(
                        base_tick,
                        d,
                        args.scan_range,
                        args.min_liq_total,
                        0 if args.max_results == 0 else max(0, args.max_results - len(ticks_out)),
                        args.threads,
                    )
                    for info in infos:
                        if info["tick"] not in seen:
                            ticks_out.append(info)
                            seen.add(info["tick"])
                        if args.max_results and len(ticks_out) >= args.max_results:
                            break
                    if args.max_results and len(ticks_out) >= args.max_results:
                        break

            # Sort by tick
            ticks_out.sort(key=lambda x: x["tick"])

            if args.json:
                print(
                    json.dumps(
                        {
                            "current_tick": current_tick,
                            "base_tick": base_tick,
                            "tick_spacing": tick_spacing,
                            "results": ticks_out,
                            **({
                                "bitmap_stats": {
                                    "above": up_stats if 'up_stats' in locals() else None,
                                    "below": down_stats if 'down_stats' in locals() else None,
                                }
                              } if args.use_bitmap else {})
                        },
                        indent=2,
                    )
                )
            else:
                if args.use_bitmap:
                    span_desc = f"±{args.bitmap_words}*256 compressed ticks"
                else:
                    span_desc = f"±{args.scan_range}*spacing"
                print(
                    f"Found {len(ticks_out)} initialized ticks with liquidityTotal >= {args.min_liq_total} within {span_desc}"
                )
                for r in ticks_out:
                    print(
                        f"  tick {r['tick']}: liqTotal={r['liquidityTotal']} liqDelta={r['liquidityDelta']}"
                    )


if __name__ == "__main__":
    main()
