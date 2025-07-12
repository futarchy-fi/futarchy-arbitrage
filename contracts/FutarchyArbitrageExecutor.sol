// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
}

interface IFutarchyRouter {
    function splitPosition(address collateralToken, uint256 amount) external;
    function mergePositions(address collateralToken, uint256 amount) external;
}

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
    
    function exactInputSingle(ExactInputSingleParams calldata params) external returns (uint256 amountOut);
}

interface IBalancerVault {
    struct SingleSwap {
        bytes32 poolId;
        uint8 kind;
        address assetIn;
        address assetOut;
        uint256 amount;
        bytes userData;
    }
    
    struct FundManagement {
        address sender;
        bool fromInternalBalance;
        address payable recipient;
        bool toInternalBalance;
    }
    
    function swap(
        SingleSwap memory singleSwap,
        FundManagement memory funds,
        uint256 limit,
        uint256 deadline
    ) external returns (uint256);
}

contract FutarchyArbitrageExecutor {
    address public immutable owner;
    address public immutable futarchyRouter;
    address public immutable swaprRouter;
    address public immutable balancerVault;
    
    uint256 private constant MAX_UINT = type(uint256).max;
    uint256 private constant DEADLINE_BUFFER = 300; // 5 minutes
    
    struct ArbitragePath {
        address tokenIn;
        address tokenOut;
        address[] intermediateTokens;
        bytes[] swapData;
        uint256 amountIn;
        uint256 minAmountOut;
    }
    
    struct ConditionalArbitrageParams {
        address sdaiToken;
        address companyToken;
        address sdaiYesToken;
        address sdaiNoToken;
        address companyYesToken;
        address companyNoToken;
        uint256 amountIn;
        uint256 minProfit;
        bytes balancerSwapData;
        bytes swaprYesSwapData;
        bytes swaprNoSwapData;
    }
    
    event ArbitrageExecuted(
        address indexed tokenIn,
        address indexed tokenOut,
        uint256 amountIn,
        uint256 amountOut,
        uint256 profit
    );
    
    event ConditionalArbitrageExecuted(
        uint256 amountIn,
        uint256 companyTokensOut,
        uint256 sdaiOut,
        uint256 profit
    );
    
    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can execute");
        _;
    }
    
    constructor(
        address _owner,
        address _futarchyRouter,
        address _swaprRouter,
        address _balancerVault
    ) {
        require(_owner != address(0), "Invalid owner");
        require(_futarchyRouter != address(0), "Invalid futarchy router");
        require(_swaprRouter != address(0), "Invalid swapr router");
        require(_balancerVault != address(0), "Invalid balancer vault");
        
        owner = _owner;
        futarchyRouter = _futarchyRouter;
        swaprRouter = _swaprRouter;
        balancerVault = _balancerVault;
    }
    
    function executeBuyConditionalArbitrage(
        ConditionalArbitrageParams calldata params
    ) external onlyOwner returns (uint256 profit) {
        // Pull sDAI from owner
        IERC20(params.sdaiToken).transferFrom(owner, address(this), params.amountIn);
        
        uint256 initialBalance = IERC20(params.sdaiToken).balanceOf(address(this));
        
        // Step 1: Split sDAI into conditional tokens
        _approveIfNeeded(params.sdaiToken, futarchyRouter, params.amountIn);
        IFutarchyRouter(futarchyRouter).splitPosition(params.sdaiToken, params.amountIn);
        
        // Step 2: Swap conditional sDAI to conditional Company tokens on Swapr
        uint256 yesBalance = IERC20(params.sdaiYesToken).balanceOf(address(this));
        uint256 noBalance = IERC20(params.sdaiNoToken).balanceOf(address(this));
        
        // Swap YES tokens
        _approveIfNeeded(params.sdaiYesToken, swaprRouter, yesBalance);
        uint256 companyYesOut = _executeSwaprSwap(
            params.sdaiYesToken,
            params.companyYesToken,
            yesBalance,
            params.swaprYesSwapData
        );
        
        // Swap NO tokens
        _approveIfNeeded(params.sdaiNoToken, swaprRouter, noBalance);
        uint256 companyNoOut = _executeSwaprSwap(
            params.sdaiNoToken,
            params.companyNoToken,
            noBalance,
            params.swaprNoSwapData
        );
        
        // Step 3: Merge conditional Company tokens
        uint256 mergeAmount = companyYesOut < companyNoOut ? companyYesOut : companyNoOut;
        _approveIfNeeded(params.companyYesToken, futarchyRouter, mergeAmount);
        _approveIfNeeded(params.companyNoToken, futarchyRouter, mergeAmount);
        IFutarchyRouter(futarchyRouter).mergePositions(params.companyToken, mergeAmount);
        
        // Step 4: Handle imbalances (liquidate excess conditional tokens)
        if (companyYesOut > mergeAmount) {
            // Excess YES tokens - swap back to sDAI
            uint256 excessYes = companyYesOut - mergeAmount;
            _approveIfNeeded(params.companyYesToken, swaprRouter, excessYes);
            _executeSwaprSwap(
                params.companyYesToken,
                params.sdaiToken,
                excessYes,
                params.swaprYesSwapData
            );
        } else if (companyNoOut > mergeAmount) {
            // Excess NO tokens - swap back to sDAI
            uint256 excessNo = companyNoOut - mergeAmount;
            _approveIfNeeded(params.companyNoToken, swaprRouter, excessNo);
            _executeSwaprSwap(
                params.companyNoToken,
                params.sdaiToken,
                excessNo,
                params.swaprNoSwapData
            );
        }
        
        // Step 5: Sell Company tokens on Balancer
        uint256 companyBalance = IERC20(params.companyToken).balanceOf(address(this));
        _approveIfNeeded(params.companyToken, balancerVault, companyBalance);
        uint256 sdaiOut = _executeBalancerSwap(
            params.companyToken,
            params.sdaiToken,
            companyBalance,
            params.balancerSwapData
        );
        
        // Calculate profit and verify minimum
        uint256 finalBalance = IERC20(params.sdaiToken).balanceOf(address(this));
        profit = finalBalance > initialBalance ? finalBalance - initialBalance : 0;
        require(profit >= params.minProfit, "Insufficient profit");
        
        // Transfer all sDAI back to owner
        IERC20(params.sdaiToken).transfer(owner, finalBalance);
        
        emit ConditionalArbitrageExecuted(params.amountIn, mergeAmount, sdaiOut, profit);
    }
    
    function executeSellConditionalArbitrage(
        ConditionalArbitrageParams calldata params
    ) external onlyOwner returns (uint256 profit) {
        // Pull Company tokens from owner
        IERC20(params.companyToken).transferFrom(owner, address(this), params.amountIn);
        
        uint256 initialSdaiBalance = IERC20(params.sdaiToken).balanceOf(owner);
        
        // Step 1: Buy sDAI with Company tokens on Balancer
        _approveIfNeeded(params.companyToken, balancerVault, params.amountIn);
        uint256 sdaiOut = _executeBalancerSwap(
            params.companyToken,
            params.sdaiToken,
            params.amountIn,
            params.balancerSwapData
        );
        
        // Step 2: Split Company tokens into conditional tokens
        _approveIfNeeded(params.companyToken, futarchyRouter, params.amountIn);
        IFutarchyRouter(futarchyRouter).splitPosition(params.companyToken, params.amountIn);
        
        // Step 3: Swap conditional Company tokens to conditional sDAI on Swapr
        uint256 companyYesBalance = IERC20(params.companyYesToken).balanceOf(address(this));
        uint256 companyNoBalance = IERC20(params.companyNoToken).balanceOf(address(this));
        
        // Swap YES tokens
        _approveIfNeeded(params.companyYesToken, swaprRouter, companyYesBalance);
        uint256 sdaiYesOut = _executeSwaprSwap(
            params.companyYesToken,
            params.sdaiYesToken,
            companyYesBalance,
            params.swaprYesSwapData
        );
        
        // Swap NO tokens
        _approveIfNeeded(params.companyNoToken, swaprRouter, companyNoBalance);
        uint256 sdaiNoOut = _executeSwaprSwap(
            params.companyNoToken,
            params.sdaiNoToken,
            companyNoBalance,
            params.swaprNoSwapData
        );
        
        // Step 4: Merge conditional sDAI tokens
        uint256 mergeAmount = sdaiYesOut < sdaiNoOut ? sdaiYesOut : sdaiNoOut;
        _approveIfNeeded(params.sdaiYesToken, futarchyRouter, mergeAmount);
        _approveIfNeeded(params.sdaiNoToken, futarchyRouter, mergeAmount);
        IFutarchyRouter(futarchyRouter).mergePositions(params.sdaiToken, mergeAmount);
        
        // Step 5: Handle imbalances
        if (sdaiYesOut > mergeAmount) {
            // Excess YES tokens - keep as sDAI
            uint256 excessYes = sdaiYesOut - mergeAmount;
            // Already in sDAI form, just transfer
        } else if (sdaiNoOut > mergeAmount) {
            // Excess NO tokens - keep as sDAI
            uint256 excessNo = sdaiNoOut - mergeAmount;
            // Already in sDAI form, just transfer
        }
        
        // Calculate final balance and profit
        uint256 finalSdaiBalance = IERC20(params.sdaiToken).balanceOf(address(this));
        uint256 totalSdaiOut = finalSdaiBalance + sdaiOut;
        
        // Verify minimum profit
        require(totalSdaiOut > params.amountIn + params.minProfit, "Insufficient profit");
        profit = totalSdaiOut - params.amountIn;
        
        // Transfer all sDAI to owner
        IERC20(params.sdaiToken).transfer(owner, finalSdaiBalance);
        
        emit ConditionalArbitrageExecuted(params.amountIn, params.amountIn, totalSdaiOut, profit);
    }
    
    function _executeSwaprSwap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        bytes calldata swapData
    ) private returns (uint256) {
        // Decode swap parameters from swapData
        (uint24 fee, uint256 amountOutMinimum) = abi.decode(swapData, (uint24, uint256));
        
        ISwaprRouter.ExactInputSingleParams memory params = ISwaprRouter.ExactInputSingleParams({
            tokenIn: tokenIn,
            tokenOut: tokenOut,
            fee: fee,
            recipient: address(this),
            deadline: block.timestamp + DEADLINE_BUFFER,
            amountIn: amountIn,
            amountOutMinimum: amountOutMinimum,
            sqrtPriceLimitX96: 0
        });
        
        return ISwaprRouter(swaprRouter).exactInputSingle(params);
    }
    
    function _executeBalancerSwap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        bytes calldata swapData
    ) private returns (uint256) {
        // Decode swap parameters
        (bytes32 poolId, uint256 minAmountOut) = abi.decode(swapData, (bytes32, uint256));
        
        IBalancerVault.SingleSwap memory singleSwap = IBalancerVault.SingleSwap({
            poolId: poolId,
            kind: 0, // GIVEN_IN
            assetIn: tokenIn,
            assetOut: tokenOut,
            amount: amountIn,
            userData: ""
        });
        
        IBalancerVault.FundManagement memory funds = IBalancerVault.FundManagement({
            sender: address(this),
            fromInternalBalance: false,
            recipient: payable(address(this)),
            toInternalBalance: false
        });
        
        return IBalancerVault(balancerVault).swap(
            singleSwap,
            funds,
            minAmountOut,
            block.timestamp + DEADLINE_BUFFER
        );
    }
    
    function _approveIfNeeded(address token, address spender, uint256 amount) private {
        uint256 currentAllowance = IERC20(token).allowance(address(this), spender);
        if (currentAllowance < amount) {
            // Reset approval to 0 first for tokens that require it
            if (currentAllowance > 0) {
                IERC20(token).approve(spender, 0);
            }
            IERC20(token).approve(spender, MAX_UINT);
        }
    }
    
    // View functions for simulation
    function simulateBuyConditional(
        ConditionalArbitrageParams calldata params
    ) external view returns (uint256 expectedProfit, bool profitable) {
        // This would be called via eth_call to simulate the arbitrage
        // Returns expected profit without executing
        // Implementation would mirror the execution logic but with calculations only
        return (0, false); // Placeholder
    }
    
    function simulateSellConditional(
        ConditionalArbitrageParams calldata params
    ) external view returns (uint256 expectedProfit, bool profitable) {
        // This would be called via eth_call to simulate the arbitrage
        // Returns expected profit without executing
        return (0, false); // Placeholder
    }
    
    // Emergency functions
    function rescueToken(address token, uint256 amount) external onlyOwner {
        IERC20(token).transfer(owner, amount);
    }
    
    function rescueETH() external onlyOwner {
        payable(owner).transfer(address(this).balance);
    }
    
    // Receive ETH
    receive() external payable {}
}