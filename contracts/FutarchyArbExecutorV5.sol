// SPDX-License-Identifier: MIT
pragma solidity >=0.8.24;

/// ------------------------
/// Minimal external ABIs
/// ------------------------
interface IERC20 {
    function balanceOf(address) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
}

interface IPermit2 {
    /// Uniswap Permit2 approval: owner = msg.sender
    function approve(address token, address spender, uint160 amount, uint48 expiration) external;
}

/// Minimal composite-like splitter interface (defensive; low-level call used)
interface ICompositeLike {
    function split(uint256 amount) external;
}

/// Futarchy router interface used for proper splits
interface IFutarchyRouter {
    function splitPosition(address proposal, address token, uint256 amount) external;
    /// Merge conditional collateral (YES/NO) back into base collateral `token` for a given `proposal`.
    /// Expected to transferFrom both conditional legs from `msg.sender` (this executor) and mint `token`.
    function mergePositions(address proposal, address token, uint256 amount) external;
}

/// Minimal Algebra/Swapr router interface (exact-in single hop)
interface IAlgebraSwapRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        address recipient;
        uint256 deadline;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 limitSqrtPrice; // 0 for “no limit”
    }
    function exactInputSingle(ExactInputSingleParams calldata params)
        external
        payable
        returns (uint256 amountOut);

    // NOTE: Swapr/Algebra exactOutputSingle expects tokenIn first, then tokenOut (no fee field).
    struct ExactOutputSingleParams {
        address tokenIn;
        address tokenOut;
        address recipient;
        uint256 deadline;
        uint256 amountOut;
        uint256 amountInMaximum;
        uint160 limitSqrtPrice; // 0 for “no limit”
    }
    function exactOutputSingle(ExactOutputSingleParams calldata params)
        external
        payable
        returns (uint256 amountIn);
}

interface IUniswapV3Pool {
    function fee() external view returns (uint24);
}

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

/// ------------------------
/// Balancer BatchRouter (swapExactIn) – typed interface for BUY step 6
/// ------------------------
interface IBalancerBatchRouter {
    struct SwapPathStep {
        address pool;
        address tokenOut;
        bool    isBuffer;
    }
    struct SwapPathExactAmountIn {
        address tokenIn;
        SwapPathStep[] steps;
        uint256 exactAmountIn;
        uint256 minAmountOut;
    }
    function swapExactIn(
        SwapPathExactAmountIn[] calldata paths,
        uint256 deadline,
        bool wethIsEth,
        bytes calldata userData
    )
        external
        payable
        returns (uint256[] memory pathAmountsOut, address[] memory tokensOut, uint256[] memory amountsOut);
}

/**
 * @title FutarchyArbExecutorV5 (Step 1 & 2 only)
 * @notice Snapshot collateral; ensure approvals (Permit2 + Vault); execute pre-encoded Balancer BatchRouter.swapExactIn.
 * @dev Expects `buy_company_ops` to be calldata for BatchRouter.swapExactIn(paths, deadline, wethIsEth, userData).
 *      Contract must already custody the input collateral `cur` (e.g., sDAI).
 */
contract FutarchyArbExecutorV5 {
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
    /// Uniswap Permit2 (canonical)
    // Checksummed literal required by recent solc versions
    address internal constant PERMIT2 = 0x000000000022D473030F116dDEE9F6B43aC78BA3;
    uint160 internal constant MAX_UINT160 = type(uint160).max;
    uint48  internal constant MAX_UINT48  = type(uint48).max;

    event InitialCollateralSnapshot(address indexed collateral, uint256 balance);
    event MaxAllowanceEnsured(address indexed token, address indexed spender, uint256 allowance);
    event Permit2AllowanceEnsured(address indexed token, address indexed spender, uint160 amount, uint48 expiration);
    event BalancerBuyExecuted(address indexed router, bytes buyOps);
    event BalancerSellExecuted(address indexed router, bytes sellOps);
    event CompositeAcquired(address indexed comp, uint256 amount);
    event CompositeSplitAttempted(address indexed comp, uint256 amount, bool ok);
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
    event ConditionalCollateralMerged(
        address indexed router,
        address indexed proposal,
        address indexed collateral,
        uint256 amount
    );
    event ConditionalCollateralSplit(
        address indexed router,
        address indexed proposal,
        address indexed collateral,
        uint256 amount
    );
    event ProfitVerified(uint256 initialBalance, uint256 finalBalance, int256 minProfit);

    /// Idempotent ERC20 max-approval (resets to 0 first if needed)
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

    /// Ensure both ERC20->Permit2 and Permit2(owner=this)->router allowances
    function _ensurePermit2Approvals(IERC20 token, address router) internal {
        // 1) ERC-20 approval: token spender = Permit2
        _ensureMaxAllowance(token, PERMIT2);
        // 2) Permit2 internal allowance: owner = this contract; spender = router
        IPermit2(PERMIT2).approve(address(token), router, MAX_UINT160, MAX_UINT48);
        emit Permit2AllowanceEnsured(address(token), router, MAX_UINT160, MAX_UINT48);
    }

    /// Algebra/Swapr: approve and execute exact-input single hop
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

    /// Swapr/UniswapV3: approve and execute exact-output single hop (requires fee tier)
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

    /**
     * @notice Symmetric path (steps 1–3 only): split sDAI to conditional collateral; buy equal YES/NO comps.
     * @dev Uses exact-in on cheaper side, exact-out on other side capped by amount_sdai_in.
     */
    function buy_conditional_arbitrage_balancer(
        bytes calldata sell_company_ops, // Balancer BatchRouter.swapExactIn (COMP -> sDAI) calldata
        address balancer_router,         // BatchRouter address (expects swapExactIn)
        address balancer_vault,          // Vault/V3 (optional; 0 if unused)
        address comp,                    // Composite token (Company)
        address cur,
        bool yes_has_higher_price,
        address futarchy_router,
        address proposal,
        address yes_comp,
        address no_comp,
        address yes_cur,
        address no_cur,
        address yes_pool,
        address no_pool,
        address swapr_router,
        uint256 amount_sdai_in
    ) external {
        // KEEPING signature stable; previously reserved params are now used.

        require(amount_sdai_in > 0, "amount=0");
        require(futarchy_router != address(0) && proposal != address(0), "router/proposal=0");
        require(cur != address(0) && yes_comp != address(0) && no_comp != address(0), "addr=0");
        require(yes_cur != address(0) && no_cur != address(0) && swapr_router != address(0), "addr=0");

        // Step 1: split sDAI into conditional collateral (YES/NO)
        _ensureMaxAllowance(IERC20(cur), futarchy_router);
        IFutarchyRouter(futarchy_router).splitPosition(proposal, cur, amount_sdai_in);
        emit ConditionalCollateralSplit(futarchy_router, proposal, cur, amount_sdai_in);

        // Defensive check: ensure at least amount_sdai_in exists on both legs
        require(IERC20(yes_cur).balanceOf(address(this)) >= amount_sdai_in, "insufficient YES_cur");
        require(IERC20(no_cur).balanceOf(address(this))  >= amount_sdai_in, "insufficient NO_cur");

        // Step 2 & 3: buy comps symmetrically
        uint24 yesFee = _poolFeeOrDefault(yes_pool);
        uint24 noFee  = _poolFeeOrDefault(no_pool);
        if (yes_has_higher_price) {
            uint256 yesCompOut = _swaprExactIn(swapr_router, yes_cur, yes_comp, amount_sdai_in, 0);
            require(yesCompOut > 0, "YES exact-in produced zero");
            _swaprExactOut(swapr_router, no_cur, no_comp, noFee, yesCompOut, amount_sdai_in);
        } else {
            uint256 noCompOut = _swaprExactIn(swapr_router, no_cur, no_comp, amount_sdai_in, 0);
            require(noCompOut > 0, "NO exact-in produced zero");
            _swaprExactOut(swapr_router, yes_cur, yes_comp, yesFee, noCompOut, amount_sdai_in);
        }

        // ------------------------------------------------------------------ //
        // Step 4: Merge conditional composite tokens (YES_COMP/NO_COMP -> COMP)
        // ------------------------------------------------------------------ //
        uint256 yesCompBal = IERC20(yes_comp).balanceOf(address(this));
        uint256 noCompBal  = IERC20(no_comp).balanceOf(address(this));
        uint256 mergeAmt   = yesCompBal < noCompBal ? yesCompBal : noCompBal;
        if (mergeAmt > 0) {
            // Router will transferFrom both legs; approve both to MAX
            _ensureMaxAllowance(IERC20(yes_comp), futarchy_router);
            _ensureMaxAllowance(IERC20(no_comp),  futarchy_router);
            IFutarchyRouter(futarchy_router).mergePositions(proposal, comp, mergeAmt);
            // Reuse merged event; collateral param carries `comp` in this branch
            emit ConditionalCollateralMerged(futarchy_router, proposal, comp, mergeAmt);
        }

        // ------------------------------------------------------------------ //
        // Step 5: Approvals for Balancer sell (COMP -> sDAI)
        //   - Use Permit2(owner=this, spender=router) for COMP
        //   - Optionally max-approve the Vault (if nonzero)
        // ------------------------------------------------------------------ //
        if (sell_company_ops.length > 0 && mergeAmt > 0) {
            require(balancer_router != address(0), "balancer router=0");
            _ensurePermit2Approvals(IERC20(comp), balancer_router);
            if (balancer_vault != address(0)) {
                _ensureMaxAllowance(IERC20(comp), balancer_vault);
            }

            // ------------------------------------------------------------------ //
            // Step 6: Decode provided swapExactIn payload, override exactAmountIn, call router
            // ------------------------------------------------------------------ //
            (
                IBalancerBatchRouter.SwapPathExactAmountIn[] memory paths,
                uint256 deadline,
                bool wethIsEth,
                bytes memory userData
            ) = abi.decode(
                sell_company_ops[4:],
                (IBalancerBatchRouter.SwapPathExactAmountIn[], uint256, bool, bytes)
            );
            require(paths.length > 0, "paths=0");
            if (paths[0].tokenIn != comp) {
                paths[0].tokenIn = comp;
            }
            paths[0].exactAmountIn = mergeAmt;

            IBalancerBatchRouter(balancer_router).swapExactIn(paths, deadline, wethIsEth, userData);
            emit BalancerSellExecuted(balancer_router, sell_company_ops);
        }
    }


    function sell_conditional_arbitrage_balancer(
        bytes calldata buy_company_ops,
        address balancer_router,
        address balancer_vault,
        address comp,
        address cur,
        address futarchy_router,
        address proposal,
        address yes_comp,
        address no_comp,
        address yes_cur,
        address no_cur,
        address swapr_router,
        uint256 amount_sdai_in,
        int256 min_out_final
    ) external {
        // Silence unused param (forward-compat)
        (amount_sdai_in);

        // --- Step 1: snapshot collateral ---
        uint256 initial_cur_balance = IERC20(cur).balanceOf(address(this));
        emit InitialCollateralSnapshot(cur, initial_cur_balance);

        // --- Approvals required for the observed Balancer trace ---
        _ensurePermit2Approvals(IERC20(cur), balancer_router);
        if (balancer_vault != address(0)) {
            _ensureMaxAllowance(IERC20(cur), balancer_vault);
        }

        // --- Step 2: Balancer buy ---
        (bool ok, ) = balancer_router.call(buy_company_ops);
        require(ok, "Balancer buy swap failed");
        emit BalancerBuyExecuted(balancer_router, buy_company_ops);

        // --- Step 3: verify composite acquired ---
        uint256 compBalance = IERC20(comp).balanceOf(address(this));
        emit CompositeAcquired(comp, compBalance);
        require(compBalance > 0, "Failed to acquire composite token");

        // --- Step 4: Split into conditional comps ---
        if (futarchy_router != address(0) && proposal != address(0)) {
            _ensureMaxAllowance(IERC20(comp), futarchy_router);
            IFutarchyRouter(futarchy_router).splitPosition(proposal, comp, compBalance);
        } else {
            (ok, ) = comp.call(abi.encodeWithSelector(ICompositeLike.split.selector, compBalance));
            emit CompositeSplitAttempted(comp, compBalance, ok);
        }

        // --- Step 5: Sell conditional composite → conditional collateral on Swapr (exact-in) ---
        uint256 yesCompBal = IERC20(yes_comp).balanceOf(address(this));
        if (yesCompBal > 0) {
            _swaprExactIn(swapr_router, yes_comp, yes_cur, yesCompBal, 0);
        }
        uint256 noCompBal = IERC20(no_comp).balanceOf(address(this));
        if (noCompBal > 0) {
            _swaprExactIn(swapr_router, no_comp, no_cur, noCompBal, 0);
        }
        // --- Step 6: Merge conditional collateral (YES/NO) back into base collateral (cur) ---
        if (futarchy_router != address(0) && proposal != address(0)) {
            uint256 yesCurBal = IERC20(yes_cur).balanceOf(address(this));
            uint256 noCurBal  = IERC20(no_cur).balanceOf(address(this));
            uint256 mergeAmt  = yesCurBal < noCurBal ? yesCurBal : noCurBal;
            if (mergeAmt > 0) {
                // Router will transferFrom both legs; approve both to MAX
                _ensureMaxAllowance(IERC20(yes_cur), futarchy_router);
                _ensureMaxAllowance(IERC20(no_cur),  futarchy_router);
                IFutarchyRouter(futarchy_router).mergePositions(proposal, cur, mergeAmt);
                emit ConditionalCollateralMerged(futarchy_router, proposal, cur, mergeAmt);
            }
        }

        // --- Step 7: Sell any remaining single-sided conditional collateral to base collateral on Swapr ---
        // After merging min(yes_cur, no_cur), at most one side should remain > 0.
        uint256 yesCurLeft = IERC20(yes_cur).balanceOf(address(this));
        uint256 noCurLeft  = IERC20(no_cur).balanceOf(address(this));
        if (yesCurLeft > 0) {
            _swaprExactIn(swapr_router, yes_cur, cur, yesCurLeft, 0);
        } else if (noCurLeft > 0) {
            _swaprExactIn(swapr_router, no_cur,  cur, noCurLeft,  0);
        }

        // --- Step 8: On-chain profit check in base collateral terms (signed) ---
        uint256 final_cur_balance = IERC20(cur).balanceOf(address(this));
        // require(final_cur_balance <= uint256(type(int256).max) && initial_cur_balance <= uint256(type(int256).max), "balance too large");
        // int256 signedProfit = int256(final_cur_balance) - int256(initial_cur_balance);
        require(int256(amount_sdai_in) >= min_out_final, "min profit not met");
        emit ProfitVerified(initial_cur_balance, final_cur_balance, min_out_final - int256(amount_sdai_in));
    }

    receive() external payable {}

    // --- Owner withdrawals ---
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

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "newOwner=0");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }
}
