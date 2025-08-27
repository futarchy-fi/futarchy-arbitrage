# Tick Boundary Discovery Difficulties on Swapr/Algebra (Gnosis)

This note documents the attempts and findings while trying to discover initialized tick boundaries for a Swapr/Algebra pool on Gnosis, and why straightforward methods returned no results.

## Context
- RPC URL: `https://special-capable-log.xdai.quiknode.pro/...`
- Pool: `SWAPR_POOL_YES_ADDRESS = 0x1328888335542433e2D5122A388045d6C76E7edd`
- DataStorageOperator discovered: `0xAe7b5F6Bb7e79029Ff0B7AcF9FEA37fC1f461cf7`
- Observed from `globalState()`:
  - `tickSpacing = 60`
  - `current tick ≈ 47,0xx`
  - `fee ≈ 1972`
  - Pool `liquidity()` previously observed non‑zero (`≈ 4.74e18`), so liquidity exists in-range.

All commands were executed via `scripts/tick_reader.py` in `futarchy_env` with `PYTHONNOUSERSITE=1`.

## What We Tried
- Direct tick read at nearest spaced tick:
  - `ticks(47040)` returned `initialized=False` with all zero fields.
- Inner cumulatives around current tick (±5×spacing):
  - `getInnerCumulatives(bottom=46680, top=47280)` reverted — typical when one or both boundary ticks are not initialized.
- Bitmap scan on the pool (tickTable):
  - Scanned hundreds of 256‑bit words in both directions from the base compressed tick.
  - Result: `nonzero_words = 0`, `bits_seen = 0` — no initialized bits found.
- Bitmap scan on the DataStorageOperator (DSO):
  - Discovered DSO at `0xAe7b5F6…` and queried `tickTable(int16)` there.
  - Scanned extensive word ranges in both directions.
  - Result: `nonzero_words = 0`, `bits_seen = 0` — still no initialized bits.
- Event scan (parallel) over full chain range:
  - Events: `Mint`, `Burn`, `Initialize` (from the pool ABI).
  - Blocks: `0 → latest` with `--chunk-blocks 20000`, `--threads 24`, live progress.
  - Result: `event_boundaries_count = 0` — no boundaries discovered from events.

Example run output (abridged):
```
Finding nearest initialized boundaries around current tick…
[bitmap-up] ... (100.0%)
[bitmap-down] ... (100.0%)
{
  "below": [],
  "above": [],
  "bitmap_stats": { "above": {"nonzero_words": 0}, "below": {"nonzero_words": 0} }
}

Scanning events for boundary ticks…
[events] 6270/6270 (100.0%)
{
  "event_boundaries_count": 0,
  "event_boundaries": []
}
```

## Why This Can Happen (Hypotheses)
- Algebra deployment specifics:
  - Some Algebra forks keep the tick bitmap in a separate DataStorageOperator with a different interface or storage layout; others may not use a public bitmap at all.
  - The `tickTable(int16)` function may exist but remain zeroed in this deployment; initialized state might be tracked differently.
- Event model differences:
  - Pools may not emit `Mint`/`Burn` with boundary ticks the same way as standard Algebra; or events could be emitted from a different contract in this deployment (router/manager), not the pool.
  - ABI event names/signatures could differ from the verified source used to build our `ABI`.
- RPC/logs nuances:
  - Upstream provider may have gaps/filters on historical logs for this address (less likely, but possible).
- Extremely wide positions:
  - If positions are astronomically wide, boundaries could be extremely far; however, scans covered effectively the full int24 compressed range with zeros, so this is unlikely the root cause here.

## Script Enhancements Implemented
- Bitmap scanner with:
  - Pool or DSO source (`--bitmap-source {pool|dso|auto}`), progress, verbose per‑word logging, and max‑range control.
- Parallel sequential probing (`--threads`) for `ticks(t)` stepping.
- Event scanner (`--scan-events`) with parallel chunked `get_logs` and live progress.
- Safety guards to keep tick/bitmap scans within the int24 domain.

## Next Steps (Recommended)
1. Verify ABIs on a block explorer for both the pool and its DataStorageOperator:
   - Confirm the exact event signatures and whether `Mint/Burn` include `bottomTick/topTick` on THIS deployment.
   - Check if the DSO exposes a different function for the tick bitmap (e.g., alternative names or additional parameters).
2. Try alternate sources for boundaries:
   - Inspect router/manager contracts related to this pool for `Mint/IncreaseLiquidity`‑style events and scan those addresses instead.
3. Add a robust fallback strategy:
   - Adaptive coarse‑to‑fine stepping: sample every `K*spacing` ticks in parallel, then refine only around any initialized hits.
   - Optional Multicall batching (if available on Gnosis) to reduce RPC round‑trips.
4. External indexers (optional):
   - Use TheGraph/subgraph (if available for this deployment) or a lightweight local indexer to recover historical boundaries.

## Handy Commands Used
- Bitmap, DSO, max range (with progress):
```
python scripts/tick_reader.py \
  --rpc-url "$RPC_URL" --address "$SWAPR_POOL_YES_ADDRESS" \
  --find-boundaries --use-bitmap --bitmap-source dso \
  --bitmap-only --bitmap-max-words 4096 --threads 24 --progress --json
```
- Event scan, parallel, full range:
```
python scripts/tick_reader.py \
  --rpc-url "$RPC_URL" --address "$SWAPR_POOL_YES_ADDRESS" \
  --scan-events --chunk-blocks 20000 --threads 24 --progress --json
```

## Conclusion
Despite multiple approaches (direct tick reads, inner cumulatives, pool and DSO bitmaps, and parallel event scans), we did not observe any initialized tick boundaries via on‑chain reads for this specific Swapr/Algebra pool address using the current ABI. The most plausible explanations are deployment‑specific differences in where/how tick initialization is recorded (bitmap and/or events) or ABI/event mismatches. Verifying the exact pool/DSO ABIs and event behavior on a block explorer is the highest‑leverage next step.

