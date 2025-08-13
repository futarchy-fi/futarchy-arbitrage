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
    event CompositeAcquired(address indexed comp, uint256 amount);
    event CompositeSplitAttempted(address indexed comp, uint256 amount, bool ok);
    event SwaprExactInExecuted(
        address indexed router,
        address indexed tokenIn,
        address indexed tokenOut,
        uint256 amountIn,
        uint256 amountOut
    );

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

    /**
     * @notice Execute Step 1 & 2.
     * @param buy_company_ops ABI-encoded BatchRouter.swapExactIn(...)
     * @param balancer_router BatchRouter entrypoint
     * @param balancer_vault  Balancer Vault (max-approved as a precaution)
     * @param comp            Composite token (unused for steps 1–2)
     * @param cur             Collateral token (e.g., sDAI) used as swap input
     * @param yes_comp        Unused (reserved)
     * @param no_comp         Unused (reserved)
     * @param yes_cur         Unused (reserved)
     * @param no_cur          Unused (reserved)
     * @param yes_pool        Unused (reserved)
     * @param no_pool         Unused (reserved)
     * @param pred_yes_pool   Unused (reserved)
     * @param pred_no_pool    Unused (reserved)
     * @param amount_sdai_in  Unused in steps 1–2; kept for forward compat
     */
    function sell_conditional_arbitrage_balancer(
        bytes calldata buy_company_ops,
        address balancer_router,
        address balancer_vault,
        address comp,
        address cur,
        address yes_comp,
        address no_comp,
        address yes_cur,
        address no_cur,
        address yes_pool,
        address no_pool,
        address pred_yes_pool,
        address pred_no_pool,
        uint256 amount_sdai_in
    ) external {
        // Treat yes_comp as futarchy_router and no_comp as proposal when provided
        address futarchy_router = yes_comp;
        address proposal = no_comp;
        // Silence still-reserved params
        (yes_cur, no_cur, yes_pool, no_pool, pred_yes_pool, pred_no_pool, amount_sdai_in);

        // --------------------------
        // Step 1: snapshot collateral
        // --------------------------
        uint256 initial_cur_balance = IERC20(cur).balanceOf(address(this));
        emit InitialCollateralSnapshot(cur, initial_cur_balance);

        // ------------------------------------------
        // Approvals required by the observed trace:
        //   - ERC20(cur) -> Permit2 (MAX)
        //   - Permit2(owner=this).approve(cur, router, MAX, MAX_EXP)
        // Also approve the Vault at ERC-20 level as a precaution.
        // ------------------------------------------
        _ensurePermit2Approvals(IERC20(cur), balancer_router);
        if (balancer_vault != address(0)) {
            _ensureMaxAllowance(IERC20(cur), balancer_vault);
        }

        // -----------------------------
        // Step 2: execute router call
        // -----------------------------
        (bool ok, ) = balancer_router.call(buy_company_ops);
        require(ok, "Balancer buy swap failed");
        emit BalancerBuyExecuted(balancer_router, buy_company_ops);

        // -----------------------------
        // Step 3: verify composite acquired
        // -----------------------------
        uint256 compBalance = IERC20(comp).balanceOf(address(this));
        emit CompositeAcquired(comp, compBalance);
        require(compBalance > 0, "Failed to acquire composite token");

        // -----------------------------
        // Step 4: split via FutarchyRouter if provided; else try token-native split (non-fatal)
        // -----------------------------
        if (futarchy_router != address(0) && proposal != address(0)) {
            // Approve router and split
            _ensureMaxAllowance(IERC20(comp), futarchy_router);
            IFutarchyRouter(futarchy_router).splitPosition(proposal, comp, compBalance);
        } else {
            // Fallback: best-effort token-native split
            (ok, ) = comp.call(abi.encodeWithSelector(ICompositeLike.split.selector, compBalance));
            emit CompositeSplitAttempted(comp, compBalance, ok);
        }
    }

    /**
     * @notice Step 1–5 variant with explicit Futarchy + Swapr details.
     * @dev Overload keeps legacy ABI intact while enabling Step 5.
     */
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
        uint256 min_yes_out,
        uint256 min_no_out,
        uint256 amount_sdai_in
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
            _swaprExactIn(swapr_router, yes_comp, yes_cur, yesCompBal, min_yes_out);
        }
        uint256 noCompBal = IERC20(no_comp).balanceOf(address(this));
        if (noCompBal > 0) {
            _swaprExactIn(swapr_router, no_comp, no_cur, noCompBal, min_no_out);
        }
        // Steps 6–8 intentionally left for follow-up (merge to base collateral, pred market legs, profit check).
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
