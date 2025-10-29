# 5. Tooling & Funding Updates

## 5.1 Wallet CLI Extensions
- Extend `src/setup/cli.py fund-erc20` commands to support TSLAON, USDC, and USDS with correct decimal formatting and human-readable summaries.
- Provide helper subcommands to approve `SwapRouter02` and `FutarchyRouter` for relevant tokens on mainnet wallets and executor contracts.

## 5.2 State Sync Scripts
- Update `src/setup/fetch_market_data.py` (and related scripts) to ingest Supabase metadata into the new config schema, populating `POOL_*` keys and Uniswap hop data.
- Add a dedicated `scripts/healthcheck_univ3.py` to poll liquidity, tick ranges, and Quoter responses for configured markets.
