// SPDX-License-Identifier: MIT
pragma solidity >=0.8.24;

/// ------------------------
/// Minimal external ABIs
/// ------------------------
interface IERC20 {
    function balanceOf(address) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
}

interface IPermit2 {
    /// Uniswap Permit2 approval: owner = msg.sender
    function approve(address token, address spender, uint160 amount, uint48 expiration) external;
}

/**
 * @title FutarchyArbExecutorV5 (Step 1 & 2 only)
 * @notice Snapshot collateral; ensure approvals (Permit2 + Vault); execute pre-encoded Balancer BatchRouter.swapExactIn.
 * @dev Expects `buy_company_ops` to be calldata for BatchRouter.swapExactIn(paths, deadline, wethIsEth, userData).
 *      Contract must already custody the input collateral `cur` (e.g., sDAI).
 */
contract FutarchyArbExecutorV5 {
    /// Uniswap Permit2 (canonical)
    address internal constant PERMIT2 = 0x000000000022d473030F116dDEE9F6B43aC78BA3;
    uint160 internal constant MAX_UINT160 = type(uint160).max;
    uint48  internal constant MAX_UINT48  = type(uint48).max;

    event InitialCollateralSnapshot(address indexed collateral, uint256 balance);
    event MaxAllowanceEnsured(address indexed token, address indexed spender, uint256 allowance);
    event Permit2AllowanceEnsured(address indexed token, address indexed spender, uint160 amount, uint48 expiration);
    event BalancerBuyExecuted(address indexed router, bytes buyOps);

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
        // Silence future-step params (reserved)
        (comp, yes_comp, no_comp, yes_cur, no_cur, yes_pool, no_pool, pred_yes_pool, pred_no_pool, amount_sdai_in);

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
    }

    receive() external payable {}
}

