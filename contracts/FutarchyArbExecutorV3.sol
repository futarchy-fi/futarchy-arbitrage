// SPDX-License-Identifier: MIT
pragma solidity >=0.8.20;

// ---------------------- Interfaces (ABI-aligned) ----------------------

interface IERC20 {
    function balanceOf(address) external view returns (uint256);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 value) external returns (bool);
}

interface IFutarchyRouter {
    // Matches your ABI exactly (IERC20 compiles to address)
    function splitPosition(address proposal, IERC20 collateralToken, uint256 amount) external;
    function mergePositions(address proposal, IERC20 collateralToken, uint256 amount) external;
}

// ---------------------- Executor with liquidation ----------------------

contract FutarchyArbExecutorV3 {
    // 7702 entrypoints kept for compatibility with your builder
    function execute10(
        address[10] calldata targets,
        bytes[10] calldata calldatas,
        uint256 count
    ) external payable {
        require(msg.sender == address(this), "Only self");
        require(count <= 10, "Too many calls");
        unchecked {
            for (uint256 i; i < count; i++) {
                address t = targets[i];
                if (t == address(0)) continue;
                (bool ok, bytes memory ret) = t.call(calldatas[i]);
                if (!ok) _revertWith(ret);
            }
        }
    }

    function executeOne(address target, bytes calldata data)
        external
        payable
        returns (bytes memory)
    {
        require(msg.sender == address(this), "Only self");
        (bool ok, bytes memory ret) = target.call{value: msg.value}(data);
        if (!ok) _revertWith(ret);
        return ret;
    }

    // ---- helper type for calldata patching (liquidation swaps) ----

    /// @dev A template for an exact-in swap; the contract will patch `amountIn`
    ///      (and optionally `minOut`) at the given byte offsets before calling `target`.
    struct CalldataPatch {
        address target;       // router (e.g., Swapr router)
        bytes   data;         // pre-encoded call with placeholders (32-byte words) for amount/minOut
        uint256 msgValue;     // ETH to send (usually 0)
        uint256 amountOffset; // byte offset in `data` where uint256 amountIn sits
        uint256 minOutOffset; // byte offset where uint256 minOut sits; set to type(uint256).max to skip
        uint16  slippageBps;  // if minOutOffset is used: minOut = amountIn * (10000 - bps) / 10000
    }

    // ---- Sell flow params (extended with liquidation) ----

    struct SellParams {
        // Core tokens
        IERC20 sdai;         // plain sDAI
        IERC20 gno;          // COMPANY token (e.g., GNO)
        IERC20 gnoYes;       // COMPANY_YES
        IERC20 gnoNo;        // COMPANY_NO
        IERC20 sdaiYes;      // SDAI_YES
        IERC20 sdaiNo;       // SDAI_NO

        // Futarchy
        IFutarchyRouter futarchyRouter;
        address          proposal;

        // ---- Pluggable sDAI -> GNO leg ----
        address sdaiSwapTarget;   // router (e.g., Balancer BatchRouter)
        address sdaiSwapSpender;  // spender (e.g., Balancer V3 Vault)
        bytes   sdaiSwapCalldata; // encoded router calldata (with exact amountIn)
        uint256 sdaiSwapMsgValue; // usually 0
        uint256 sdaiAmountInCap;  // cap on sDAI spent
        uint256 minGnoOut;        // min GNO expected

        // ---- Split + conditional swaps ----
        uint256 splitGnoAmount;   // GNO to split (<= GNO bought)
        address yesSwapTarget;    // router for COMPANY_YES -> SDAI_YES
        bytes   yesSwapCalldata;  // encoded exact-in swap calldata
        address noSwapTarget;     // router for COMPANY_NO  -> SDAI_NO
        bytes   noSwapCalldata;   // encoded exact-in swap calldata
        address swapSpender;      // spender for both legs
        uint256 minSdaiYesOut;    // min SDAI_YES out
        uint256 minSdaiNoOut;     // min SDAI_NO out

        // ---- Post-merge liquidation of leftover conditional sDAI ----
        address liqSwapSpender;   // spender for both liquidation swaps (e.g., Swapr router)
        CalldataPatch liqYes;     // template for SDAI_YES -> sDAI (recipient MUST be this contract)
        CalldataPatch liqNo;      // template for SDAI_NO  -> sDAI (recipient MUST be this contract)

        // ---- Global constraint ----
        int256  minNetSdai;       // require(end - start >= minNetSdai)
    }

    event SellExecuted(
        uint256 sdaiSpent,
        uint256 gnoBought,
        uint256 gnoSplit,
        uint256 sdaiYesOut,
        uint256 sdaiNoOut,
        uint256 merged,
        uint256 liqYesIn,
        uint256 liqNoIn,
        uint256 liqYesOut,
        uint256 liqNoOut,
        int256  netSdai
    );

    /// @notice Full SELL flow with dynamic merge and optional liquidation into plain sDAI.
    /// @dev Must be invoked via 7702 (so msg.sender == address(this)).
    function sellConditional(SellParams calldata p) external {
        require(msg.sender == address(this), "Only self");

        // ---- Snapshot sDAI to enforce global tolerance at the very end ----
        uint256 sdaiStart = p.sdai.balanceOf(address(this));

        // ---- (1) sDAI -> GNO (router-agnostic) ----
        if (p.sdaiSwapSpender != address(0) && p.sdaiAmountInCap > 0) {
            _ensureAllowance(p.sdai, p.sdaiSwapSpender, p.sdaiAmountInCap);
        }

        uint256 gnoBefore  = p.gno.balanceOf(address(this));
        uint256 sdaiBefore = p.sdai.balanceOf(address(this));

        _safeCall(p.sdaiSwapTarget, p.sdaiSwapCalldata, p.sdaiSwapMsgValue);

        uint256 gnoBought = p.gno.balanceOf(address(this)) - gnoBefore;
        uint256 sdaiSpent = sdaiBefore - p.sdai.balanceOf(address(this));

        require(sdaiSpent <= p.sdaiAmountInCap, "sDAI overspend");
        require(gnoBought >= p.minGnoOut,       "Low GNO out");

        // ---- (2) Split GNO into COMPANY_YES / COMPANY_NO ----
        require(p.splitGnoAmount > 0 && p.splitGnoAmount <= gnoBought, "Bad split amount");
        _ensureAllowance(p.gno, address(p.futarchyRouter), p.splitGnoAmount);

        uint256 yesBalBefore = p.gnoYes.balanceOf(address(this));
        uint256 noBalBefore  = p.gnoNo.balanceOf(address(this));

        p.futarchyRouter.splitPosition(p.proposal, p.gno, p.splitGnoAmount);

        uint256 yesMinted = p.gnoYes.balanceOf(address(this)) - yesBalBefore;
        uint256 noMinted  = p.gnoNo.balanceOf(address(this))  - noBalBefore;
        require(yesMinted >= p.splitGnoAmount && noMinted >= p.splitGnoAmount, "Under-mint");

        // ---- (3) Swap both legs to conditional sDAI (exact-in) ----
        _ensureAllowance(p.gnoYes, p.swapSpender, p.splitGnoAmount);
        _ensureAllowance(p.gnoNo,  p.swapSpender, p.splitGnoAmount);

        uint256 sdaiYesBefore = p.sdaiYes.balanceOf(address(this));
        _safeCall(p.yesSwapTarget, p.yesSwapCalldata, 0);
        uint256 yesOut = p.sdaiYes.balanceOf(address(this)) - sdaiYesBefore;
        require(yesOut >= p.minSdaiYesOut, "Low YES->sDAI");

        uint256 sdaiNoBefore = p.sdaiNo.balanceOf(address(this));
        _safeCall(p.noSwapTarget, p.noSwapCalldata, 0);
        uint256 noOut = p.sdaiNo.balanceOf(address(this)) - sdaiNoBefore;
        require(noOut >= p.minSdaiNoOut, "Low NO->sDAI");

        // ---- (4) Merge min(yesOut, noOut) back to plain sDAI ----
        uint256 mergeAmt = yesOut < noOut ? yesOut : noOut;
        require(mergeAmt > 0, "Nothing to merge");

        _ensureAllowance(p.sdaiYes, address(p.futarchyRouter), mergeAmt);
        _ensureAllowance(p.sdaiNo,  address(p.futarchyRouter), mergeAmt);
        p.futarchyRouter.mergePositions(p.proposal, p.sdai, mergeAmt);

        // ---- (5) Liquidate leftover conditional sDAI to plain sDAI ----
        uint256 leftoverYes = yesOut - mergeAmt; // remaining SDAI_YES minted in this tx
        uint256 leftoverNo  = noOut  - mergeAmt; // remaining SDAI_NO  minted in this tx

        uint256 liqYesOut;
        uint256 liqNoOut;

        if (leftoverYes > 0 && p.liqYes.target != address(0)) {
            _ensureAllowance(p.sdaiYes, p.liqSwapSpender, leftoverYes);

            // sdai delta accounting for event/debug
            uint256 sdaiBeforeLiq = p.sdai.balanceOf(address(this));

            bytes memory cd = _patchedCalldata(
                p.liqYes.data,
                p.liqYes.amountOffset,
                leftoverYes,
                p.liqYes.minOutOffset,
                p.liqYes.slippageBps
            );
            _safeCall(p.liqYes.target, cd, p.liqYes.msgValue);

            liqYesOut = p.sdai.balanceOf(address(this)) - sdaiBeforeLiq;
        }

        if (leftoverNo > 0 && p.liqNo.target != address(0)) {
            _ensureAllowance(p.sdaiNo, p.liqSwapSpender, leftoverNo);

            uint256 sdaiBeforeLiq = p.sdai.balanceOf(address(this));

            bytes memory cd = _patchedCalldata(
                p.liqNo.data,
                p.liqNo.amountOffset,
                leftoverNo,
                p.liqNo.minOutOffset,
                p.liqNo.slippageBps
            );
            _safeCall(p.liqNo.target, cd, p.liqNo.msgValue);

            liqNoOut = p.sdai.balanceOf(address(this)) - sdaiBeforeLiq;
        }

        // ---- (6) Global min-net check (AFTER liquidation) ----
        uint256 sdaiEnd = p.sdai.balanceOf(address(this));
        int256  net     = int256(sdaiEnd) - int256(sdaiStart);
        require(net >= p.minNetSdai, "Net sDAI below tolerance");

        emit SellExecuted(
            sdaiSpent, gnoBought, p.splitGnoAmount,
            yesOut, noOut, mergeAmt,
            leftoverYes, leftoverNo,
            liqYesOut, liqNoOut,
            net
        );
    }

    // ---------------------- Internals ----------------------

    function _ensureAllowance(IERC20 token, address spender, uint256 need) internal {
        if (need == 0) return;
        uint256 cur = token.allowance(address(this), spender);
        if (cur < need) {
            require(token.approve(spender, 0), "approve(0) failed");
            require(token.approve(spender, type(uint256).max), "approve(max) failed");
        }
    }

    function _safeCall(address target, bytes memory data, uint256 value) internal {
        (bool ok, bytes memory ret) = target.call{value: value}(data);
        if (!ok) _revertWith(ret);
    }

    function _patchedCalldata(
        bytes memory template,
        uint256 amountOffset,
        uint256 amountIn,
        uint256 minOutOffset,
        uint16  slippageBps
    ) internal pure returns (bytes memory cd) {
        cd = template; // calldata in params is copied to memory on access
        require(cd.length >= amountOffset + 32, "amount offset OOB");
        assembly { mstore(add(add(cd, 32), amountOffset), amountIn) }
        if (minOutOffset != type(uint256).max) {
            uint256 minOut = (slippageBps == 0)
                ? amountIn
                : (amountIn * (10000 - slippageBps)) / 10000;
            require(cd.length >= minOutOffset + 32, "minOut offset OOB");
            assembly { mstore(add(add(cd, 32), minOutOffset), minOut) }
        }
    }

    function _revertWith(bytes memory ret) private pure {
        if (ret.length == 0) revert("Call failed");
        assembly { revert(add(ret, 0x20), mload(ret)) }
    }

    receive() external payable {}
}