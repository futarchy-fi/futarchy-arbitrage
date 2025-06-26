import os
from decimal import Decimal
from src.helpers.swapr_swap import w3, build_exact_in_tx, build_exact_out_tx
from src.helpers.merge_position import build_merge_tx


def build_conditional_sdai_liquidation_steps(
    liquidate_conditional_sdai_amount,
    handle_liquidate,
    handle_buy_sdai_yes,
    handle_merge_conditional_sdai,
):
    """
    Returns a list of (tx, handler) for conditional sDAI liquidation.
    To be appended to the steps list.
    """
    print(f"🔄 Building conditional sDAI liquidation steps")
    print(f"   Amount to liquidate: {liquidate_conditional_sdai_amount}")
    
    steps = []
    if liquidate_conditional_sdai_amount and liquidate_conditional_sdai_amount > 0:
        print(f"   → Positive amount detected, liquidating YES tokens")
        liq_tx = build_liquidate_remaining_conditional_sdai_tx(
            liquidate_conditional_sdai_amount, True
        )
        if liq_tx:
            print(f"   ✅ YES liquidation transaction built successfully")
            steps.append((liq_tx, handle_liquidate))
        else:
            print(f"   ❌ Failed to build YES liquidation transaction")
    else:
        abs_amount = -(liquidate_conditional_sdai_amount or 0)
        print(f"   → Non-positive amount detected ({abs_amount}), liquidating NO tokens")
        liq_txs = build_liquidate_remaining_conditional_sdai_tx(abs_amount, False)
        if liq_txs:
            print(f"   ✅ NO liquidation transactions built successfully")
            steps += [
                (liq_txs[0], handle_buy_sdai_yes),
                (liq_txs[1], handle_merge_conditional_sdai),
            ]
        else:
            print(f"   ❌ Failed to build NO liquidation transactions")
    
    print(f"   → Total liquidation steps created: {len(steps)}")
    return steps


def build_liquidate_remaining_conditional_sdai_tx(amount: float, is_yes: bool):
    """Return Tenderly tx dict swapping sDAI-Yes/No → sDAI via SwapR exact-in.

    Args:
        amount: Amount to liquidate in float format
        is_yes: True for YES tokens, False for NO tokens
    """
    print(f"🔧 Building liquidation transaction")
    print(f"   Amount: {amount}")
    print(f"   Token type: {'YES' if is_yes else 'NO'}")
    
    from eth_account import Account
    from src.helpers.swapr_swap import client
    
    try:
        acct = Account.from_key(os.environ["PRIVATE_KEY"])
        router_addr = w3.to_checksum_address(os.environ["FUTARCHY_ROUTER_ADDRESS"])
        proposal_addr = w3.to_checksum_address(os.environ["FUTARCHY_PROPOSAL_ADDRESS"])
        collateral_addr = w3.to_checksum_address(os.environ["SDAI_TOKEN_ADDRESS"])
        
        print(f"   Account address: {acct.address}")
        print(f"   Router address: {router_addr}")
        print(f"   Proposal address: {proposal_addr}")
        print(f"   Collateral address: {collateral_addr}")
        
    except Exception as e:
        print(f"   ❌ Error loading account/addresses: {e}")
        return None
    
    if amount <= 0:
        print(f"   ❌ Invalid amount: {amount} (must be > 0)")
        return None
    
    try:
        amount_in_wei = w3.to_wei(Decimal(amount), "ether")
        min_amount_out_wei = int(amount_in_wei * 0.01)  # 1% slippage
        
        print(f"   Amount in wei: {amount_in_wei}")
        print(f"   Min amount out wei: {min_amount_out_wei}")
        
        if is_yes:
            in_token = w3.to_checksum_address(os.environ["SWAPR_SDAI_YES_ADDRESS"])
            print(f"   YES token address: {in_token}")
        else:
            in_token = w3.to_checksum_address(os.environ["SWAPR_SDAI_NO_ADDRESS"])
            print(f"   NO token address: {in_token}")
            
        out_token = w3.to_checksum_address(os.environ["SDAI_TOKEN_ADDRESS"])
        print(f"   Output token (sDAI): {out_token}")
        
        print(f"   → Building exact-in swap transaction...")
        tx = build_exact_in_tx(
            in_token,
            out_token,
            amount_in_wei,
            min_amount_out_wei,
            acct.address,
            sqrt_price_limit=0,
        )
        
        if tx:
            print(f"   ✅ Transaction built successfully")
            print(f"   Transaction to: {tx.get('to', 'N/A')}")
            print(f"   Transaction data length: {len(tx.get('data', '')) // 2} bytes")
        else:
            print(f"   ❌ Failed to build transaction (returned None)")
            
        return tx
        
    except Exception as e:
        print(f"   ❌ Error building liquidation transaction: {e}")
        return None