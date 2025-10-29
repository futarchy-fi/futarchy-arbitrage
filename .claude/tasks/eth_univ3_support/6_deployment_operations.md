# 6. Deployment & Operations

## 6.1 Contract Deployment
- Redeploy the extended `FutarchyArbExecutorV5` (with Uniswap entrypoints) and verify the bytecode on Etherscan.
- Migrate executor ownership, allowances, and funding from existing Gnosis deployments where necessary.

## 6.2 Configuration Rollout
- Publish `config/proposal_<mainnet>.json` files using the new schema (including hop metadata, slippage parameters, and pool addresses).
- Ship `.env.mainnet.<proposal>` templates alongside config artifacts for operator onboarding.

## 6.3 Runbooks & Monitoring
- Document USDS funding flows, approval checklists, and mainnet bot invocation steps under `docs/`.
- Extend dashboards/alerts to monitor Uniswap pool depth, base-fee spikes, and bot profitability on Ethereum mainnet.
- Launch with conservative `min_profit` and trade-size defaults; define gates for scaling exposure after production burn-in.
