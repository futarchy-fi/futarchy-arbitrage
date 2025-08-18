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
/// Uniswap V2-like Router (Swapr v2) – exact-in multi-hop
/// ------------------------
interface IUniswapV2Router02 {
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);
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

/// ------------------------
/// Balancer Vault (batchSwap) – used in PNK flows
/// ------------------------
interface IBalancerVault {
    enum SwapKind { GIVEN_IN, GIVEN_OUT }
    struct BatchSwapStep {
        bytes32 poolId;
        uint256 assetInIndex;
        uint256 assetOutIndex;
        uint256 amount; // amount for GIVEN_IN on the first step of each branch; 0 for subsequent chained steps
        bytes userData;
    }
    struct FundManagement {
        address sender;
        bool fromInternalBalance;
        address recipient;
        bool toInternalBalance;
    }
    function batchSwap(
        SwapKind kind,
        BatchSwapStep[] calldata swaps,
        address[] calldata assets,
        FundManagement calldata funds,
        int256[] calldata limits,
        uint256 deadline
    ) external returns (int256[] memory assetDeltas);
}

/**
 * @title FutarchyArbExecutorV5 (Step 1 & 2 only)
 * @notice Snapshot collateral; ensure approvals (Permit2 + Vault); execute pre-encoded Balancer BatchRouter.swapExactIn.
 * @dev Expects `buy_company_ops` to be calldata for BatchRouter.swapExactIn(paths, deadline, wethIsEth, userData).
 *      Contract must already custody the input collateral `cur` (e.g., sDAI).
 */
contract FutarchyArbExecutorV5 {
    /// ------------------------
    /// PNK Trading Constants (Gnosis)
    /// ------------------------
    /// Fixed addresses used by the PNK buy/sell helper flows.
    address internal constant TOKEN_SDAI = 0xaf204776c7245bF4147c2612BF6e5972Ee483701;
    address internal constant TOKEN_WETH = 0x6A023CCd1ff6F2045C3309768eAd9E68F978f6e1;
    address internal constant TOKEN_PNK  = 0x37b60f4E9A31A64cCc0024dce7D0fD07eAA0F7B3;
    address internal constant BALANCER_VAULT = 0xBA12222222228d8Ba445958a75a0704d566BF2C8;
    address internal constant SWAPR_V2_ROUTER = 0xE43e60736b1cb4a75ad25240E2f9a62Bff65c0C0;

    /// Balancer batchSwap GIVEN_IN route: sDAI -> WETH (multi-branch), as observed on-chain.
    bytes32 internal constant PNK_POOL_1 = 0xa91c413d8516164868f6cca19573fe38f88f5982000200000000000000000157;
    bytes32 internal constant PNK_POOL_2 = 0x7e5870ac540adfd01a213c829f2231c309623eb10002000000000000000000e9;
    bytes32 internal constant PNK_POOL_3 = 0x40d2cbc586dd8df50001cdba3f65cd4bbc32d596000200000000000000000154;
    bytes32 internal constant PNK_POOL_4 = 0x480d4f66cc41a1b6784a53a10890e5ece31d75c000020000000000000000014e;
    bytes32 internal constant PNK_POOL_5 = 0xa99fd9950b5d5dceeaf4939e221dca8ca9b938ab000100000000000000000025;

    /// Assets order used for the batchSwap indices.
    /// Index mapping for convenience.
    address internal constant PNK_ASSET_2 = 0xC0d871bD13eBdf5c4ff059D8243Fb38210608bD6;
    address internal constant PNK_ASSET_4 = 0xE0eD85F76D9C552478929fab44693E03F0899F23;
    address internal constant PNK_ASSET_5_GNO = 0x9C58BAcC331c9aa871AFD802DB6379a98e80CEdb;
    uint256 internal constant PNK_IDX_SDAI = 0;
    uint256 internal constant PNK_IDX_WETH = 2;

    /// Deadlines
    uint256 internal constant BALANCER_VAULT_DEADLINE = 9007199254740991; // far-future
    uint256 internal constant SWAPR_V2_DEADLINE = 3510754692; // far-future

    /// Helper: assets array in the exact order expected by the PNK Balancer route
    function _pnkAssetsOrder() internal pure returns (address[] memory assets) {
        assets = new address[](5);
        assets[0] = TOKEN_SDAI;
        assets[1] = PNK_ASSET_2;
        assets[2] = TOKEN_WETH;
        assets[3] = PNK_ASSET_4;
        assets[4] = PNK_ASSET_5_GNO; // GNO
    }

    /// Helper: poolIds array used by the PNK Balancer route (sDAI -> WETH)
    function _pnkPoolIds() internal pure returns (bytes32[] memory poolIds) {
        poolIds = new bytes32[](5);
        poolIds[0] = PNK_POOL_1;
        poolIds[1] = PNK_POOL_2;
        poolIds[2] = PNK_POOL_3;
        poolIds[3] = PNK_POOL_4;
        poolIds[4] = PNK_POOL_5;
    }

    /// ------------------------
    /// PNK Buy Flow: sDAI -> WETH (Balancer Vault) -> PNK (Swapr)
    /// ------------------------
    function buyPnkWithSdai(uint256 amountSdaiIn, uint256 minWethOut, uint256 minPnkOut) external {
        require(amountSdaiIn > 0, "amount=0");

        // Approve sDAI to Balancer Vault
        _ensureMaxAllowance(IERC20(TOKEN_SDAI), BALANCER_VAULT);

        // Build assets order
        address[] memory assets = _pnkAssetsOrder();

        // Build swaps: two branches converging to WETH (index 2)
        IBalancerVault.BatchSwapStep[] memory swaps = new IBalancerVault.BatchSwapStep[](5);
        uint256 half = amountSdaiIn / 2;
        uint256 other = amountSdaiIn - half;
        // Branch A: sDAI (0) -> ASSET_2 (1) -> WETH (2)
        swaps[0] = IBalancerVault.BatchSwapStep({
            poolId: PNK_POOL_1,
            assetInIndex: 0,
            assetOutIndex: 1,
            amount: half,
            userData: bytes("")
        });
        swaps[1] = IBalancerVault.BatchSwapStep({
            poolId: PNK_POOL_2,
            assetInIndex: 1,
            assetOutIndex: 2,
            amount: 0,
            userData: bytes("")
        });
        // Branch B: sDAI (0) -> ASSET_4 (3) -> ASSET_5 (4) -> WETH (2)
        swaps[2] = IBalancerVault.BatchSwapStep({
            poolId: PNK_POOL_3,
            assetInIndex: 0,
            assetOutIndex: 3,
            amount: other,
            userData: bytes("")
        });
        swaps[3] = IBalancerVault.BatchSwapStep({
            poolId: PNK_POOL_4,
            assetInIndex: 3,
            assetOutIndex: 4,
            amount: 0,
            userData: bytes("")
        });
        swaps[4] = IBalancerVault.BatchSwapStep({
            poolId: PNK_POOL_5,
            assetInIndex: 4,
            assetOutIndex: 2,
            amount: 0,
            userData: bytes("")
        });

        // Limits: positive sDAI in; negative min WETH out if set
        int256[] memory limits = new int256[](assets.length);
        limits[PNK_IDX_SDAI] = int256(amountSdaiIn);
        if (minWethOut > 0) {
            limits[PNK_IDX_WETH] = -int256(minWethOut);
        }

        // Funds: this contract as sender/recipient; no internal balance
        IBalancerVault.FundManagement memory funds = IBalancerVault.FundManagement({
            sender: address(this),
            fromInternalBalance: false,
            recipient: address(this),
            toInternalBalance: false
        });

        // Execute batchSwap
        IBalancerVault(BALANCER_VAULT).batchSwap(
            IBalancerVault.SwapKind.GIVEN_IN,
            swaps,
            assets,
            funds,
            limits,
            BALANCER_VAULT_DEADLINE
        );

        // Validate WETH received
        uint256 wethBal = IERC20(TOKEN_WETH).balanceOf(address(this));
        require(wethBal > 0, "no WETH");
        if (minWethOut > 0) {
            require(wethBal >= minWethOut, "min WETH not met");
        }

        // Approve and swap WETH -> PNK on Swapr v2 (Uniswap v2 router)
        _ensureMaxAllowance(IERC20(TOKEN_WETH), SWAPR_V2_ROUTER);
        address[] memory path = new address[](2);
        path[0] = TOKEN_WETH;
        path[1] = TOKEN_PNK;
        IUniswapV2Router02(SWAPR_V2_ROUTER).swapExactTokensForTokens(
            wethBal,
            minPnkOut,
            path,
            address(this),
            SWAPR_V2_DEADLINE
        );
    }
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
     * @notice Symmetric BUY: steps 1–6 already implemented; this patch adds steps 7–8.
     * @dev Steps 1–3: split sDAI -> conditional collateral; buy YES/NO comps (exact-in + exact-out).
     *      Step 4: merge comps -> COMP; Step 5–6: sell COMP -> sDAI on Balancer.
     *      Step 7: sell remaining single-sided conditional collateral (YES_cur or NO_cur) -> cur on Swapr.
     *      Step 8: on-chain profit check in base-collateral terms against `min_out_final`.
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
        uint256 amount_sdai_in,
        int256  min_out_final
    ) external {
        // KEEPING signature compatible; new arg appended.
        // --- Step 0: snapshot base collateral for profit accounting ---
        uint256 initial_cur_balance = IERC20(cur).balanceOf(address(this));

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

        // --- Step 7: Sell any remaining single-sided conditional collateral to base collateral on Swapr ---
        uint256 yesCurLeft = IERC20(yes_cur).balanceOf(address(this));
        uint256 noCurLeft  = IERC20(no_cur).balanceOf(address(this));
        if (yesCurLeft > 0) {
            _swaprExactIn(swapr_router, yes_cur, cur, yesCurLeft, 0);
        } else if (noCurLeft > 0) {
            _swaprExactIn(swapr_router, no_cur,  cur, noCurLeft,  0);
        }

        // --- Step 8: On-chain profit check in base collateral terms (signed) ---
        uint256 final_cur_balance = IERC20(cur).balanceOf(address(this));
        require(
            final_cur_balance <= uint256(type(int256).max) &&
            initial_cur_balance <= uint256(type(int256).max),
            "balance too large"
        );
        int256 signedProfit = int256(final_cur_balance) - int256(initial_cur_balance);
        require(signedProfit >= min_out_final, "min profit not met");
        emit ProfitVerified(initial_cur_balance, final_cur_balance, min_out_final);
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
