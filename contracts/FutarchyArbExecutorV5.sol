// SPDX-License-Identifier: MIT
pragma solidity >=0.8.24;

/**
 * @title IERC20
 * @dev Minimal interface for ERC20 tokens.
 */
interface IERC20 {
    /**
     * @dev Returns the amount of tokens owned by `account`.
     */
    function balanceOf(address account) external view returns (uint256);

    /**
     * @dev Sets `amount` as the allowance of `spender` over the caller's tokens.
     */
    function approve(address spender, uint256 amount) external returns (bool);

    /**
     * @dev Returns the remaining number of tokens that `spender` will be allowed
     * to spend on behalf of `owner` through {transferFrom}.
     */
    function allowance(address owner, address spender) external view returns (uint256);
}

/**
 * @title IFutarchyRouter
 * @dev Interface for the FutarchyRouter contract that handles split/merge operations.
 */
interface IFutarchyRouter {
    /**
     * @dev Splits a collateral token into conditional YES and NO tokens.
     * @param proposal The proposal address for the conditional market.
     * @param collateralToken The token to split (e.g., Company Token or sDAI).
     * @param amount The amount of tokens to split.
     */
    function splitPosition(address proposal, IERC20 collateralToken, uint256 amount) external;

    /**
     * @dev Merges conditional YES and NO tokens back into the base collateral token.
     * @param proposal The proposal address for the conditional market.
     * @param collateralToken The token to merge back into.
     * @param amount The amount of conditional tokens to merge.
     */
    function mergePositions(address proposal, IERC20 collateralToken, uint256 amount) external;
}

/**
 * @title ISwaprRouter
 * @dev Interface for Swapr router (Algebra/UniswapV3-compatible) for swapping conditional tokens.
 */
interface ISwaprRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 deadline;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }

    /**
     * @dev Swaps `amountIn` of one token for as much as possible of another token.
     * @param params The parameters for the swap.
     * @return amountOut The amount of output tokens received.
     */
    function exactInputSingle(ExactInputSingleParams calldata params) external payable returns (uint256 amountOut);
}

/**
 * @title FutarchyArbExecutorV5
 * @author nicscl.eth
 * @notice This contract executes arbitrage strategies on Futarchy markets,
 * specifically interacting with Balancer V3 pools and Swapr pools.
 * @dev This contract implements the complete arbitrage flow:
 * 1. Buy composite token from Balancer
 * 2. Split into conditional tokens
 * 3. Swap conditional composite tokens for conditional collateral tokens
 * 4. Merge back to base collateral
 * 5. Liquidate any remaining single-sided conditional collateral
 */
contract FutarchyArbExecutorV5 {

    // Constants for Swapr pool fees (0.3% = 3000 in basis points * 100)
    uint24 constant SWAPR_FEE = 3000;
    uint256 constant SLIPPAGE_BPS = 100; // 1% slippage tolerance

    // FutarchyRouter for split/merge operations
    IFutarchyRouter public immutable futarchyRouter;

    // Swapr router for conditional token swaps
    ISwaprRouter public immutable swaprRouter;

    // Proposal address for the futarchy market
    address public immutable proposal;

    /**
     * @notice Constructor to set the FutarchyRouter, SwaprRouter, and proposal addresses.
     * @param _futarchyRouter The address of the FutarchyRouter contract.
     * @param _swaprRouter The address of the Swapr router contract.
     * @param _proposal The proposal address for the futarchy market.
     */
    constructor(address _futarchyRouter, address _swaprRouter, address _proposal) {
        futarchyRouter = IFutarchyRouter(_futarchyRouter);
        swaprRouter = ISwaprRouter(_swaprRouter);
        proposal = _proposal;
    }

    /**
     * @notice Executes a conditional arbitrage by buying a composite token from Balancer, splitting it, and selling the parts.
     * @dev This function uses pre-generated calldata from an off-chain helper to execute a swap on the Balancer Router.
     * It implements the complete arbitrage strategy in 8 steps.
     * @param buy_company_ops The encoded `swapExactIn` calldata for the Balancer Router.
     * @param balancer_router The address of the Balancer Batch Router.
     * @param comp The address of the composite token (e.g., Company Token).
     * @param cur The address of the collateral token (e.g., sDAI).
     * @param yes_comp The address of the 'YES' conditional composite token.
     * @param no_comp The address of the 'NO' conditional composite token.
     * @param yes_cur The address of the 'YES' conditional collateral token.
     * @param no_cur The address of the 'NO' conditional collateral token.
     * @param yes_pool The address of the 'YES' conditional pool.
     * @param no_pool The address of the 'NO' conditional pool.
     * @param pred_yes_pool The address of the 'YES' prediction market pool.
     * @param pred_no_pool The address of the 'NO' prediction market pool.
     * @param amount_sdai_in The minimum amount of collateral this contract must receive from the initial operation.
     */
    function sell_conditional_arbitrage_balancer(
        bytes calldata buy_company_ops,
        address balancer_router,
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
        // Silence unused variable warnings for pool addresses (used for tracking/events in production)
        (yes_pool, no_pool, pred_yes_pool, pred_no_pool, amount_sdai_in);

        // Step 1: Record the initial collateral balance to measure profit later.
        uint256 initial_cur_balance = IERC20(cur).balanceOf(address(this));

        // Step 2: Execute the swap on the Balancer Router to buy the composite token using sDAI.
        (bool success, ) = balancer_router.call(buy_company_ops);
        require(success, "Balancer buy swap failed");

        // Step 3: Verify the contract now holds the composite token.
        uint256 comp_balance = IERC20(comp).balanceOf(address(this));
        require(comp_balance > 0, "No composite tokens received");

        // Step 4: Split the composite token into its conditional components.
        // First approve the FutarchyRouter to spend our composite tokens
        _ensureAllowance(IERC20(comp), address(futarchyRouter), comp_balance);
        
        // Record balances before split
        uint256 yes_comp_before = IERC20(yes_comp).balanceOf(address(this));
        uint256 no_comp_before = IERC20(no_comp).balanceOf(address(this));
        
        // Execute the split
        futarchyRouter.splitPosition(proposal, IERC20(comp), comp_balance);
        
        // Verify we received the conditional tokens
        uint256 yes_comp_received = IERC20(yes_comp).balanceOf(address(this)) - yes_comp_before;
        uint256 no_comp_received = IERC20(no_comp).balanceOf(address(this)) - no_comp_before;
        require(yes_comp_received >= comp_balance && no_comp_received >= comp_balance, "Split failed: insufficient tokens received");

        // Step 5: Sell the conditional composite tokens for conditional collateral tokens.
        // Swap YES composite tokens for YES collateral tokens
        _ensureAllowance(IERC20(yes_comp), address(swaprRouter), yes_comp_received);
        uint256 yes_cur_received = _swapOnSwapr(yes_comp, yes_cur, yes_comp_received);
        
        // Swap NO composite tokens for NO collateral tokens
        _ensureAllowance(IERC20(no_comp), address(swaprRouter), no_comp_received);
        uint256 no_cur_received = _swapOnSwapr(no_comp, no_cur, no_comp_received);

        // Step 6: Merge the minimum possible amount of conditional collateral tokens back into the base collateral.
        uint256 merge_amount = yes_cur_received < no_cur_received ? yes_cur_received : no_cur_received;
        require(merge_amount > 0, "No tokens to merge");
        
        // Approve the router to spend our conditional collateral tokens
        _ensureAllowance(IERC20(yes_cur), address(futarchyRouter), merge_amount);
        _ensureAllowance(IERC20(no_cur), address(futarchyRouter), merge_amount);
        
        // Execute the merge
        futarchyRouter.mergePositions(proposal, IERC20(cur), merge_amount);

        // Step 7: Sell any remaining single-sided conditional collateral on the prediction market.
        uint256 yes_cur_remaining = yes_cur_received - merge_amount;
        uint256 no_cur_remaining = no_cur_received - merge_amount;
        
        if (yes_cur_remaining > 0) {
            // Liquidate excess YES collateral tokens directly to base collateral
            _ensureAllowance(IERC20(yes_cur), address(swaprRouter), yes_cur_remaining);
            _swapOnSwapr(yes_cur, cur, yes_cur_remaining);
        }
        
        if (no_cur_remaining > 0) {
            // Liquidate excess NO collateral tokens directly to base collateral
            _ensureAllowance(IERC20(no_cur), address(swaprRouter), no_cur_remaining);
            _swapOnSwapr(no_cur, cur, no_cur_remaining);
        }

        // Step 8: Require that the final collateral balance is greater than the initial balance, ensuring a profit.
        uint256 final_cur_balance = IERC20(cur).balanceOf(address(this));
        require(final_cur_balance > initial_cur_balance, "Arbitrage was not profitable");
    }

    /**
     * @dev Internal function to perform a swap on Swapr.
     * @param tokenIn The address of the input token.
     * @param tokenOut The address of the output token.
     * @param amountIn The amount of input tokens to swap.
     * @return amountOut The amount of output tokens received.
     */
    function _swapOnSwapr(
        address tokenIn,
        address tokenOut,
        uint256 amountIn
    ) internal returns (uint256 amountOut) {
        // Calculate minimum amount out with slippage tolerance
        uint256 amountOutMinimum = (amountIn * (10000 - SLIPPAGE_BPS)) / 10000;
        
        ISwaprRouter.ExactInputSingleParams memory params = ISwaprRouter.ExactInputSingleParams({
            tokenIn: tokenIn,
            tokenOut: tokenOut,
            fee: SWAPR_FEE,
            recipient: address(this),
            deadline: block.timestamp + 300, // 5 minutes from now
            amountIn: amountIn,
            amountOutMinimum: amountOutMinimum,
            sqrtPriceLimitX96: 0 // No price limit
        });
        
        amountOut = swaprRouter.exactInputSingle(params);
        require(amountOut >= amountOutMinimum, "Swap slippage exceeded");
    }

    /**
     * @dev Internal function to ensure sufficient allowance for a spender.
     * @param token The token to approve.
     * @param spender The address to approve.
     * @param amount The amount needed.
     */
    function _ensureAllowance(IERC20 token, address spender, uint256 amount) internal {
        uint256 current = token.allowance(address(this), spender);
        if (current < amount) {
            // Reset allowance to 0 first (some tokens require this)
            require(token.approve(spender, 0), "Failed to reset approval");
            // Set new allowance to max
            require(token.approve(spender, type(uint256).max), "Failed to approve");
        }
    }

    /**
     * @notice Allows the contract to receive ETH (if needed for gas or fees).
     */
    receive() external payable {}
}