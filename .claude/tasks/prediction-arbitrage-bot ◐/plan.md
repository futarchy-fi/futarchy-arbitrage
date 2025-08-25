Awesome—this is a clean, symmetric arbitrage you can implement with a very small, purpose‑built contract and one focused off‑chain executor. Below I give you:

1. **A new on‑chain contract** `PredictionArbExecutorV1.sol` with exactly the two entrypoints you requested:

   * `sell_conditional_arbitrage(...)`
   * `buy_conditional_arbitrage(...)`

   It reuses the same Swapr/Algebra helpers, allowance patterns, and events from your existing V5 executor, but strips out Balancer/PNK specifics. It expects the off‑chain script to decide which function to call and with what `amount`.

2. **A new off‑chain executor** `src/executor/prediction_arb_executor.py` that:

   * Reads prices for **yes\_currency <-> currency** and **no\_currency <-> currency** Swapr pools off‑chain.
   * Decides per your rule:

     * if `yes_price + no_price > 1` → call **sell** function (split then sell exact‑in both legs)
     * if `yes_price + no_price < 1` → call **buy** function (buy both legs exact‑out amount each, then merge)
   * Prefunds the contract with `{currency}` if necessary (same pattern as your current executors).
   * Uses the same EIP‑1559 fee and ABI‑adaptive build patterns as `arbitrage_executor.py`.

Both pieces follow your project’s style and naming patterns so they drop into the repo without friction.

---

## 1) Contract — `contracts/PredictionArbExecutorV1.sol`

```solidity
// SPDX-License-Identifier: MIT
pragma solidity >=0.8.24;

/// ------------------------
/// Minimal external ABIs (reused from V5 style)
/// ------------------------
interface IERC20 {
    function balanceOf(address) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
}

interface IFutarchyRouter {
    /// Split base collateral `token` into conditional YES/NO for `proposal`.
    function splitPosition(address proposal, address token, uint256 amount) external;
    /// Merge conditional collateral (YES/NO) back into base collateral `token` for `proposal`.
    /// Transfers both conditional legs from `msg.sender` and mints `token`.
    function mergePositions(address proposal, address token, uint256 amount) external;
}

/// Algebra/Swapr exact-in (single hop)
interface IAlgebraSwapRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        address recipient;
        uint256 deadline;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 limitSqrtPrice; // 0 for no limit
    }
    function exactInputSingle(ExactInputSingleParams calldata params)
        external
        payable
        returns (uint256 amountOut);
}

/// Uniswap V3-like exact-out (Swapr)
interface ISwapRouterV3ExactOutput {
    struct ExactOutputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24  fee;
        address recipient;
        uint256 deadline;
        uint256 amountOut;
        uint256 amountInMaximum;
        uint160 sqrtPriceLimitX96;
    }
    function exactOutputSingle(ExactOutputSingleParams calldata params)
        external
        payable
        returns (uint256 amountIn);
}

interface IUniswapV3Pool {
    function fee() external view returns (uint24);
}

/// ------------------------
/// PredictionArbExecutorV1
/// ------------------------
/**
 * @title PredictionArbExecutorV1
 * @notice Minimal executor for prediction-market arbitrage on conditional collateral.
 *
 * Flows (owner-only):
 *  - sell_conditional_arbitrage: split {currency} into YES/NO and sell both legs exact-in for {currency}.
 *  - buy_conditional_arbitrage: buy YES/NO conditional {currency} exact-out (amount each) and merge back to {currency}.
 *
 * Notes:
 *  - Price decisions are off-chain. This contract just executes the steps atomically.
 *  - Profit guard `min_out_final` is a signed value in {currency} units (can be negative for testing).
 */
contract PredictionArbExecutorV1 {
    // --- Ownership ---
    address public owner;
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }
    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "newOwner=0");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // --- Events (reused naming patterns from V5) ---
    event InitialCollateralSnapshot(address indexed collateral, uint256 balance);
    event MaxAllowanceEnsured(address indexed token, address indexed spender, uint256 allowance);
    event SwaprExactInExecuted(
        address indexed router,
        address indexed tokenIn,
        address indexed tokenOut,
        uint256 amountIn,
        uint256 amountOut
    );
    event SwaprExactOutExecuted(
        address indexed router,
        address indexed tokenIn,
        address indexed tokenOut,
        uint256 amountOut,
        uint256 amountIn
    );
    event ConditionalCollateralSplit(
        address indexed router,
        address indexed proposal,
        address indexed collateral,
        uint256 amount
    );
    event ConditionalCollateralMerged(
        address indexed router,
        address indexed proposal,
        address indexed collateral,
        uint256 amount
    );
    event ProfitVerified(uint256 initialBalance, uint256 finalBalance, int256 minProfit);

    // --- Helpers: approvals & swap primitives (same style as V5) ---
    function _ensureMaxAllowance(IERC20 token, address spender) internal {
        uint256 cur = token.allowance(address(this), spender);
        if (cur != type(uint256).max) {
            if (cur != 0) {
                require(token.approve(spender, 0), "approve reset failed");
            }
            require(token.approve(spender, type(uint256).max), "approve set failed");
        }
        emit MaxAllowanceEnsured(address(token), spender, token.allowance(address(this), spender));
    }

    function _swaprExactIn(
        address swapr_router,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minOut
    ) internal returns (uint256 amountOut) {
        require(swapr_router != address(0), "swapr router=0");
        require(tokenIn != address(0) && tokenOut != address(0), "token=0");
        if (amountIn == 0) return 0;
        _ensureMaxAllowance(IERC20(tokenIn), swapr_router);
        IAlgebraSwapRouter.ExactInputSingleParams memory p = IAlgebraSwapRouter.ExactInputSingleParams({
            tokenIn: tokenIn,
            tokenOut: tokenOut,
            recipient: address(this),
            deadline: block.timestamp,
            amountIn: amountIn,
            amountOutMinimum: minOut,
            limitSqrtPrice: 0
        });
        amountOut = IAlgebraSwapRouter(swapr_router).exactInputSingle(p);
        emit SwaprExactInExecuted(swapr_router, tokenIn, tokenOut, amountIn, amountOut);
    }

    function _swaprExactOut(
        address swapr_router,
        address tokenIn,
        address tokenOut,
        uint24 fee,
        uint256 amountOut,
        uint256 maxIn
    ) internal returns (uint256 amountIn) {
        require(swapr_router != address(0), "swapr router=0");
        require(tokenIn != address(0) && tokenOut != address(0), "token=0");
        if (amountOut == 0) return 0;
        _ensureMaxAllowance(IERC20(tokenIn), swapr_router);
        ISwapRouterV3ExactOutput.ExactOutputSingleParams memory p = ISwapRouterV3ExactOutput.ExactOutputSingleParams({
            tokenIn: tokenIn,
            tokenOut: tokenOut,
            fee: fee,
            recipient: address(this),
            deadline: block.timestamp,
            amountOut: amountOut,
            amountInMaximum: maxIn,
            sqrtPriceLimitX96: 0
        });
        amountIn = ISwapRouterV3ExactOutput(swapr_router).exactOutputSingle(p);
        emit SwaprExactOutExecuted(swapr_router, tokenIn, tokenOut, amountOut, amountIn);
    }

    uint24 internal constant DEFAULT_V3_FEE = 100; // 0.01%
    function _poolFeeOrDefault(address pool) internal view returns (uint24) {
        if (pool == address(0)) return DEFAULT_V3_FEE;
        try IUniswapV3Pool(pool).fee() returns (uint24 f) {
            return f == 0 ? DEFAULT_V3_FEE : f;
        } catch {
            return DEFAULT_V3_FEE;
        }
    }

    // -------------------------------------------
    //  sell_conditional_arbitrage
    //    1) snapshot base collateral
    //    2) split `currency` into YES/NO via Futarchy router
    //    3) sell both YES/NO exact-in for `currency` on Swapr
    //    4) profit guard in `currency` units (signed)
    // -------------------------------------------
    function sell_conditional_arbitrage(
        address futarchy_router,
        address proposal,
        address currency,
        address yes_currency,
        address no_currency,
        address swapr_router,
        uint256 amount_currency_in,
        int256  min_out_final
    ) external onlyOwner {
        require(futarchy_router != address(0) && proposal != address(0), "router/proposal=0");
        require(currency != address(0) && yes_currency != address(0) && no_currency != address(0), "addr=0");
        require(swapr_router != address(0), "swapr router=0");
        require(amount_currency_in > 0, "amount=0");

        // Step 0: snapshot base collateral
        uint256 initial = IERC20(currency).balanceOf(address(this));
        emit InitialCollateralSnapshot(currency, initial);

        // Step 1: split {currency} -> YES/NO {currency}
        _ensureMaxAllowance(IERC20(currency), futarchy_router);
        IFutarchyRouter(futarchy_router).splitPosition(proposal, currency, amount_currency_in);
        emit ConditionalCollateralSplit(futarchy_router, proposal, currency, amount_currency_in);

        // Defensive: ensure both legs received
        require(IERC20(yes_currency).balanceOf(address(this)) >= amount_currency_in, "insufficient YES_cur");
        require(IERC20(no_currency).balanceOf(address(this))  >= amount_currency_in, "insufficient NO_cur");

        // Step 2: sell both conditional legs exact-in back to base currency
        uint256 yesBal = IERC20(yes_currency).balanceOf(address(this));
        if (yesBal > 0) {
            _swaprExactIn(swapr_router, yes_currency, currency, yesBal, 0);
        }
        uint256 noBal = IERC20(no_currency).balanceOf(address(this));
        if (noBal > 0) {
            _swaprExactIn(swapr_router, no_currency, currency, noBal, 0);
        }

        // Step 3: profit guard in base-collateral terms
        uint256 finalBal = IERC20(currency).balanceOf(address(this));
        // signedProfit = proceeds - amount_currency_in
        require(
            finalBal <= uint256(type(int256).max) && initial <= uint256(type(int256).max),
            "balance too large"
        );
        int256 signedProfit = int256(finalBal) - int256(initial);
        require(signedProfit >= min_out_final, "min profit not met");
        emit ProfitVerified(initial, finalBal, min_out_final);
    }

    // -------------------------------------------
    //  buy_conditional_arbitrage
    //    1) snapshot base collateral
    //    2) buy YES/NO conditional {currency} exact-out = amount (each)
    //    3) merge YES/NO back to {currency}
    //    4) profit guard in {currency} units (signed)
    // -------------------------------------------
    function buy_conditional_arbitrage(
        address futarchy_router,
        address proposal,
        address currency,
        address yes_currency,
        address no_currency,
        address yes_pool,     // for fee discovery (optional; 0 => default)
        address no_pool,      // for fee discovery (optional; 0 => default)
        address swapr_router,
        uint256 amount_conditional_out,
        int256  min_out_final
    ) external onlyOwner {
        require(futarchy_router != address(0) && proposal != address(0), "router/proposal=0");
        require(currency != address(0) && yes_currency != address(0) && no_currency != address(0), "addr=0");
        require(swapr_router != address(0), "swapr router=0");
        require(amount_conditional_out > 0, "amount=0");

        // Step 0: snapshot base collateral
        uint256 initial = IERC20(currency).balanceOf(address(this));
        emit InitialCollateralSnapshot(currency, initial);

        // Step 1: buy YES/NO conditional collateral exact-out (amount each)
        uint24 yesFee = _poolFeeOrDefault(yes_pool);
        uint24 noFee  = _poolFeeOrDefault(no_pool);

        // We purposely allow large maxIn because the off-chain caller enforces price condition;
        // revert protection is provided by the final profit check.
        _swaprExactOut(swapr_router, currency, yes_currency, yesFee, amount_conditional_out, type(uint256).max);
        _swaprExactOut(swapr_router, currency, no_currency,  noFee,  amount_conditional_out, type(uint256).max);

        // Defensive: ensure we indeed hold >= amount on both legs
        require(IERC20(yes_currency).balanceOf(address(this)) >= amount_conditional_out, "insufficient YES_cur");
        require(IERC20(no_currency).balanceOf(address(this))  >= amount_conditional_out, "insufficient NO_cur");

        // Step 2: merge back to base collateral
        _ensureMaxAllowance(IERC20(yes_currency), futarchy_router);
        _ensureMaxAllowance(IERC20(no_currency),  futarchy_router);
        IFutarchyRouter(futarchy_router).mergePositions(proposal, currency, amount_conditional_out);
        emit ConditionalCollateralMerged(futarchy_router, proposal, currency, amount_conditional_out);

        // Step 3: profit guard in base-collateral terms
        uint256 finalBal = IERC20(currency).balanceOf(address(this));
        require(
            finalBal <= uint256(type(int256).max) && initial <= uint256(type(int256).max),
            "balance too large"
        );
        int256 signedProfit = int256(finalBal) - int256(initial);
        require(signedProfit >= min_out_final, "min profit not met");
        emit ProfitVerified(initial, finalBal, min_out_final);
    }

    // --- Owner withdrawals (same pattern as V5) ---
    receive() external payable {}
    function withdrawToken(IERC20 token, address to, uint256 amount) external onlyOwner {
        require(to != address(0), "to=0");
        require(token.transfer(to, amount), "transfer failed");
    }
    function sweepToken(IERC20 token, address to) external onlyOwner {
        require(to != address(0), "to=0");
        uint256 bal = token.balanceOf(address(this));
        require(token.transfer(to, bal), "transfer failed");
    }
    function withdrawETH(address payable to, uint256 amount) external onlyOwner {
        require(to != address(0), "to=0");
        (bool ok, ) = to.call{value: amount}("");
        require(ok, "eth send failed");
    }
}
```

**Why this matches your plan**

* **SELL:** `splitPosition` mints `amount` on each of YES/NO collateral; we then **exact‑in** both conditional legs to `{currency}`. Profit = proceeds − amount.
* **BUY:** Two **exact‑out** trades for `amount` of YES/NO conditional collateral each; then `mergePositions` mints back exactly `amount` `{currency}`. Profit = amount − total spent.
* No on‑chain price reads; **all price selection is off‑chain**.
* Same **events, approvals, and safety patterns** as your V5 contract, plus a signed profit guard (`min_out_final`) to keep things atomic & safe.

---

## 2) Off‑chain executor — `src/executor/prediction_arb_executor.py`

* Reads the two Swapr pools for *conditional‑currency ↔ currency* (you already have these as `SWAPR_POOL_PRED_YES_ADDRESS` and `SWAPR_POOL_PRED_NO_ADDRESS` in your config pattern).
* Normalizes orientation so prices are in `{currency}` units (inverts if the pool returns the opposite side).
* Applies your rule to decide **sell vs buy** and calls the corresponding function on the new contract.
* Prefunds the executor contract with `{currency}` when needed (same pattern as `arbitrage_executor.py`).

```py
#!/usr/bin/env python3
"""
Prediction Arbitrage Executor (off-chain decision; on-chain execution via PredictionArbExecutorV1)

Logic (off-chain):
  - Read yes_price from YES_{currency}<->{currency} pool
  - Read no_price  from  NO_{currency}<->{currency} pool
  - If yes_price + no_price > 1: call sell_conditional_arbitrage (split + sell both legs exact-in)
  - If yes_price + no_price < 1: call buy_conditional_arbitrage (buy both legs exact-out 'amount' each + merge)

Usage:
  python -m src.executor.prediction_arb_executor \
    --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF \
    --amount 0.01 \
    --min-profit -0.01 \
    --prefund
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

# Price helper (same module family your bot uses)
from helpers.swapr_price import get_pool_price as swapr_price

DEPLOYMENTS_GLOB = "deployments/deployment_prediction_arb_v1_*.json"


# ---------- Env / utils ----------
def load_env(env_file: Optional[str]) -> None:
    base_env = Path(".env")
    if base_env.exists():
        load_dotenv(base_env)
    if env_file:
        load_dotenv(env_file)


def discover_v1_address() -> Tuple[Optional[str], str]:
    for key in ["PREDICTION_ARB_EXECUTOR_V1", "PREDICTION_EXECUTOR_V1_ADDRESS"]:
        v = os.getenv(key)
        if v:
            return v, f"env ({key})"
    files = sorted(glob.glob(DEPLOYMENTS_GLOB))
    if files:
        latest = files[-1]
        try:
            with open(latest, "r") as f:
                data = json.load(f)
            addr = data.get("address")
            if addr:
                return addr, f"deployments ({latest})"
        except Exception:
            pass
    return None, "unresolved"


def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def _ether_str_to_signed_wei(value_str: str) -> int:
    d = Decimal(str(value_str))
    sign = -1 if d < 0 else 1
    scaled = int((abs(d) * Decimal(10 ** 18)).to_integral_value(rounding=None))
    return sign * scaled


def _eip1559_fees(w3: Web3) -> dict:
    try:
        base_fee = w3.eth.get_block("latest").get("baseFeePerGas")
    except Exception:
        base_fee = None
    if base_fee is not None:
        tip = int(os.getenv("PRIORITY_FEE_WEI", "1"))
        mult = int(os.getenv("MAX_FEE_MULTIPLIER", "2"))
        max_fee = int(base_fee) * mult + tip
        return {"maxFeePerGas": int(max_fee), "maxPriorityFeePerGas": int(tip)}
    else:
        gas_price = int(w3.eth.gas_price)
        bump = int(os.getenv("MIN_GAS_PRICE_BUMP_WEI", "1"))
        return {"gasPrice": gas_price + bump}


def _load_v1_abi() -> list:
    files = sorted(glob.glob(DEPLOYMENTS_GLOB))
    if files:
        latest = files[-1]
        try:
            with open(latest, "r") as f:
                data = json.load(f)
            abi = data.get("abi")
            if abi:
                print(f"Loaded V1 ABI from deployments ({latest})")
                return abi
        except Exception:
            pass
    build_abi = Path("build/PredictionArbExecutorV1.abi")
    if build_abi.exists():
        try:
            return json.loads(build_abi.read_text())
        except Exception:
            pass
    raise SystemExit("Could not load V1 ABI from deployments/ or build/. Please deploy V1 first.")


def _oriented_price(w3: Web3, pool_addr: str, want_base: str, want_quote: str) -> float:
    """
    Normalize the pool price so the result is in {want_quote} units per 1 {want_base}.
    swapr_price returns (price, base, quote) where price is assumed 'quote per 1 base'.
    If the pool order is reversed, invert.
    """
    px, base, quote = swapr_price(w3, pool_addr)
    base = w3.to_checksum_address(base)
    quote = w3.to_checksum_address(quote)
    want_base = w3.to_checksum_address(want_base)
    want_quote = w3.to_checksum_address(want_quote)
    if base == want_base and quote == want_quote:
        return float(px)
    if base == want_quote and quote == want_base:
        # invert
        return float(1.0 / float(px))
    raise SystemExit(f"Pool {pool_addr} tokens ({base}→{quote}) do not match expected pair {want_base}↔{want_quote}")


# ---------- Execution ----------
def main():
    p = argparse.ArgumentParser(description="Prediction arbitrage (off-chain logic → on-chain V1 executor)")
    p.add_argument("--env", dest="env_file", default=None, help="Path to .env file")
    p.add_argument("--amount", required=True, help="Amount of {currency} (ether units) for the arb logic")
    p.add_argument("--min-profit", dest="min_profit", default="0", help="Min profit in ether units (signed; can be negative)")
    p.add_argument("--prefund", action="store_true", help="Transfer {currency} to the executor contract if needed")
    args = p.parse_args()

    load_env(args.env_file)
    rpc_url = require_env("RPC_URL")
    private_key = require_env("PRIVATE_KEY")

    # Token & router addresses from env (consistent with project)
    currency     = require_env("SDAI_TOKEN_ADDRESS")        # base collateral (e.g., sDAI)
    yes_currency = require_env("SWAPR_SDAI_YES_ADDRESS")    # YES_{currency} token
    no_currency  = require_env("SWAPR_SDAI_NO_ADDRESS")     # NO_{currency} token

    # Pools for conditional-currency <-> currency
    yes_pool = require_env("SWAPR_POOL_PRED_YES_ADDRESS")
    no_pool  = require_env("SWAPR_POOL_PRED_NO_ADDRESS")

    # Futarchy split/merge
    fut_router = require_env("FUTARCHY_ROUTER_ADDRESS")
    proposal   = require_env("FUTARCHY_PROPOSAL_ADDRESS")

    # Swapr router
    swapr_router = require_env("SWAPR_ROUTER_ADDRESS")

    # Resolve V1 executor address
    if os.getenv("PREDICTION_ARB_EXECUTOR_V1") or os.getenv("PREDICTION_EXECUTOR_V1_ADDRESS"):
        v1_addr, src = discover_v1_address()
    else:
        v1_addr, src = discover_v1_address()
    if not v1_addr:
        raise SystemExit("Could not determine V1 executor address (set PREDICTION_ARB_EXECUTOR_V1 or keep a deployments file).")
    print(f"Resolved V1 address: {v1_addr} (source: {src})")

    # Web3 + middleware (POA safe)
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    try:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        try:
            from web3.middleware import ExtraDataToPOAMiddleware
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception:
            pass
    if not w3.is_connected():
        raise SystemExit("Failed to connect to RPC_URL")
    acct = Account.from_key(private_key)

    # Load ABI / contract
    abi = _load_v1_abi()
    v1  = w3.eth.contract(address=w3.to_checksum_address(v1_addr), abi=abi)

    # Amounts
    amount_eth = Decimal(str(args.amount))
    amount_wei = w3.to_wei(amount_eth, "ether")
    min_profit_wei = _ether_str_to_signed_wei(args.min_profit)

    # Off-chain price read & decision
    yes_px = _oriented_price(w3, yes_pool, yes_currency, currency)   # {currency} per 1 YES_{currency}
    no_px  = _oriented_price(w3, no_pool,  no_currency,  currency)   # {currency} per 1  NO_{currency}
    px_sum = Decimal(str(yes_px)) + Decimal(str(no_px))
    print(f"yes_price: {yes_px:.8f}, no_price: {no_px:.8f}, sum: {px_sum:.8f}")

    # Prefund the executor with {currency} if requested or if required
    erc20_min_abi = [
        {"constant": True, "inputs":[{"name":"owner","type":"address"}], "name":"balanceOf",
         "outputs":[{"name":"","type":"uint256"}], "stateMutability":"view","type":"function"},
        {"constant": False,"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],
         "name":"transfer","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    ]
    cur = w3.eth.contract(address=w3.to_checksum_address(currency), abi=erc20_min_abi)
    exec_bal = cur.functions.balanceOf(w3.to_checksum_address(v1_addr)).call()

    # We want the executor to have at least `amount_wei` of {currency} for either flow.
    if exec_bal < amount_wei and args.prefund:
        missing = amount_wei - exec_bal
        tx = cur.functions.transfer(w3.to_checksum_address(v1_addr), missing).build_transaction({
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": w3.eth.chain_id,
            **_eip1559_fees(w3),
        })
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        except Exception:
            tx["gas"] = 150_000
        signed = acct.sign_transaction(tx)
        raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
        h = w3.eth.send_raw_transaction(raw)
        print(f"Prefund tx: {h.hex()}")
        w3.eth.wait_for_transaction_receipt(h)

    # Common tx params
    params = {
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": w3.eth.chain_id,
        **_eip1559_fees(w3),
    }

    # Choose flow and build the transaction
    if px_sum > Decimal("1"):
        # SELL: split amount, then sell both legs exact-in
        print("Decision: SELL (sum > 1) → split & sell conditionals exact-in")
        tx = v1.functions.sell_conditional_arbitrage(
            w3.to_checksum_address(fut_router),
            w3.to_checksum_address(proposal),
            w3.to_checksum_address(currency),
            w3.to_checksum_address(yes_currency),
            w3.to_checksum_address(no_currency),
            w3.to_checksum_address(swapr_router),
            int(amount_wei),
            int(min_profit_wei),
        ).build_transaction(params)
    elif px_sum < Decimal("1"):
        # BUY: buy both legs exact-out amount, then merge
        print("Decision: BUY (sum < 1) → buy both conditionals exact-out & merge")
        tx = v1.functions.buy_conditional_arbitrage(
            w3.to_checksum_address(fut_router),
            w3.to_checksum_address(proposal),
            w3.to_checksum_address(currency),
            w3.to_checksum_address(yes_currency),
            w3.to_checksum_address(no_currency),
            w3.to_checksum_address(yes_pool),
            w3.to_checksum_address(no_pool),
            w3.to_checksum_address(swapr_router),
            int(amount_wei),
            int(min_profit_wei),
        ).build_transaction(params)
    else:
        print("No-op: yes_price + no_price == 1 (within machine precision)")
        return

    # Gas limit
    if "gas" not in tx:
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        except Exception:
            tx["gas"] = 1_500_000

    # Send
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
    txh = w3.eth.send_raw_transaction(raw).hex()
    if not txh.startswith("0x"):
        txh = "0x" + txh
    print(f"Tx sent: {txh}")
    print(f"GnosisScan:  https://gnosisscan.io/tx/{txh}")
    print(f"Blockscout:  https://gnosis.blockscout.com/tx/{txh}")
    rcpt = w3.eth.wait_for_transaction_receipt(txh)
    print(f"Success: {rcpt.status == 1}; Gas used: {rcpt.gasUsed}")


if __name__ == "__main__":
    main()
```

### Expected env vars (all already familiar in your repo)

* Network & wallet: `RPC_URL`, `PRIVATE_KEY`, `CHAIN_ID` (100 for Gnosis)
* Executor: `PREDICTION_ARB_EXECUTOR_V1` (or `PREDICTION_EXECUTOR_V1_ADDRESS`) **after deploy**
* Routers: `SWAPR_ROUTER_ADDRESS`, `FUTARCHY_ROUTER_ADDRESS`
* Proposal: `FUTARCHY_PROPOSAL_ADDRESS`
* Tokens (currency & conditionals):

  * `SDAI_TOKEN_ADDRESS` (base)
  * `SWAPR_SDAI_YES_ADDRESS` (YES\_{currency})
  * `SWAPR_SDAI_NO_ADDRESS` (NO\_{currency})
* Pools (conditional currency ↔ base):

  * `SWAPR_POOL_PRED_YES_ADDRESS`
  * `SWAPR_POOL_PRED_NO_ADDRESS`

> These variable names align with your `arbitrage_bot_v2.py` and env mapping.

---

## 3) Example usage

```bash
# SELL path example (auto-decided at runtime):
python -m src.executor.prediction_arb_executor \
  --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF \
  --amount 0.10 \
  --min-profit -0.002 \
  --prefund

# BUY path example (auto-decided at runtime):
python -m src.executor.prediction_arb_executor \
  --env .env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF \
  --amount 0.10 \
  --min-profit -0.002 \
  --prefund
```

* `--amount` is in **{currency} units** (e.g., sDAI).
* In **SELL**, `amount` is the split size.
* In **BUY**, `amount` is the **exact\_out target** per conditional leg (so total merge is exactly `amount` back to base).
* `--min-profit` is a **signed** guard in base units. Keep it conservative in production.

---

## 4) Notes & next steps

* **Decisions off‑chain**: No price reads on-chain; both functions revert unless the profit guard is satisfied, keeping you safe against transient pool changes.
* **Fees/slippage**: The contract uses unlimited `maxIn` for the two exact‑out buys; your off‑chain check (+profit guard) ensures non‑profitable paths revert. If you prefer hard slippage caps on-chain, we can add `max_in_yes`/`max_in_no` parameters & read fee tiers via pools (already supported).
* **Config integration**: If you want this under the JSON config/bot loop, we can:

  * Add a small `PredictionMode` to `arbitrage_bot_v2.py` that shells out to this new executor when the comparator is the sum of conditional‑currency pools instead of Balancer/GNO.
* **Tests**: You can adapt `tests/test_split_position.py` to sanity-check:

  * split emits and sufficient balances appear
  * sell/buy functions call the expected low-level helpers and Futarchy router.

This gives you a minimal, self‑contained “prediction‑only” arbitrage path that matches your plan and plugs into your existing repo structure.
