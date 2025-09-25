# 1. Discovery & Prerequisites

## 1.1 Inventory Production Contracts
- Record deployed mainnet contracts in Supabase and env templates:
  - `FutarchyFactory` — `0xf9369c0F7a84CAC3b7Ef78c837cF7313309D3678`
  - `FutarchyProposal` template — `0x0956b70AC0Eca45DB9661a1cEE96B2e7062d8a1C`
  - `FutarchyRealityProxy` — `0xa638F22cDD13013494971b0e1325718AA45280dc`
  - `FutarchyRouter` — `0xAc9Bf8EbA6Bd31f8E8c76f8E8B2AAd0BD93f98Dc`
- Once YES/NO markets are instantiated, collect their Uniswap V3 pool IDs and persist them via Supabase metadata for config generation.

## 1.2 Token Metadata Audit
- Fetch and document decimals, symbols, and allowances for TSLAON, USDC, USDS, and conditional YES/NO tokens.
- Update decimal-handling helpers to account for USDC’s 6 decimals alongside 18-decimal assets.
- Map USDS mint/redeem or bridge routes to automate bot funding.

## 1.3 Liquidity Path Validation
- Confirm Uniswap V3 pools that back the spot hop:
  - TSLAON/USDC (0.30% fee tier) — `0x31227b50eCCDC9C589826AA2D9E7C5619B1895Da`
  - USDC/USDS (0.05% fee tier) — `0x8AEE53B873176D9F938D24a53A8aE5cF36276464`
- Evaluate depth, tick liquidity, and historical slippage to set baseline trade sizes and cushions.

## 1.4 Operational Inputs
- Secure high-uptime Ethereum mainnet RPC endpoints (HTTP + optional WS) and dedicated funded wallets.
- Catalog core Uniswap V3 infrastructure for downstream helpers:
  - Factory — `0x1F98431c8aD98523631AE4a59f267346ea31F984`
  - SwapRouter02 — `0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45`
  - QuoterV2 — `0x61fFE014bA17989E743c5F6cB21bF9697530B21e`
  - Permit2 — `0x000000000022D473030F116dDEE9F6B43aC78BA3`
  - NonfungiblePositionManager — `0xC36442b4a4522E871399CD717aBDD847Ab11FE88`
- Tune gas oracle strategy (EIP-1559 multipliers, base fee caps) for mainnet conditions.
