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
        uint256 amountOut,
        uint256 maxIn
    ) internal returns (uint256 amountIn) {
        require(swapr_router != address(0), "swapr router=0");
        require(tokenIn != address(0) && tokenOut != address(0), "token=0");
        if (amountOut == 0) return 0;
        _ensureMaxAllowance(IERC20(tokenIn), swapr_router);
        IAlgebraSwapRouter.ExactOutputSingleParams memory p = IAlgebraSwapRouter.ExactOutputSingleParams({
            tokenIn: tokenIn,
            tokenOut: tokenOut,
            recipient: address(this),
            deadline: block.timestamp,
            amountOut: amountOut,
            amountInMaximum: maxIn,
            limitSqrtPrice: 0
        });
        amountIn = IAlgebraSwapRouter(swapr_router).exactOutputSingle(p);
        emit SwaprExactOutExecuted(swapr_router, tokenIn, tokenOut, amountOut, amountIn);
    }

    // Default fee tier used when pool fee discovery fails.
    // Swapr pools commonly use 0.05% (500) for conditional markets.
    uint24 internal constant DEFAULT_V3_FEE = 500; // 0.05%
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
        // We purposely allow large maxIn because the off-chain caller enforces price condition;
        // revert protection is provided by the final profit check.
        _swaprExactOut(swapr_router, currency, yes_currency, amount_conditional_out, type(uint256).max);
        _swaprExactOut(swapr_router, currency, no_currency,  amount_conditional_out, type(uint256).max);

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
