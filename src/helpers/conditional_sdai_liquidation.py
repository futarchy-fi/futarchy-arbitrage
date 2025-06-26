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
    steps = []
    if liquidate_conditional_sdai_amount and liquidate_conditional_sdai_amount > 0:
        liq_tx = build_liquidate_remaining_conditional_sdai_tx(
            liquidate_conditional_sdai_amount, True
        )
        if liq_tx:
            steps.append((liq_tx, handle_liquidate))
    else:
        liq_txs = build_liquidate_remaining_conditional_sdai_tx(
            -(liquidate_conditional_sdai_amount or 0), False
        )
        if liq_txs:
            steps += [
                (liq_txs[0], handle_buy_sdai_yes),
                (liq_txs[1], handle_merge_conditional_sdai),
            ]
    return steps


def build_liquidate_remaining_conditional_sdai_tx(amount: float, is_yes: bool):
    """Return Tenderly tx dict swapping sDAI-Yes → sDAI via SwapR exact-in.

    If *is_yes* is False, this is a no-op and returns ``None``.
    """
    from eth_account import Account
    from src.helpers.swapr_swap import client
    
    acct = Account.from_key(os.environ["PRIVATE_KEY"])
    router_addr = w3.to_checksum_address(os.environ["FUTARCHY_ROUTER_ADDRESS"])
    proposal_addr = w3.to_checksum_address(os.environ["FUTARCHY_PROPOSAL_ADDRESS"])
    collateral_addr = w3.to_checksum_address(os.environ["SDAI_TOKEN_ADDRESS"])
    
    if is_yes:
        amount_in_wei = w3.to_wei(Decimal(amount), "ether")
        min_amount_out_wei = 1  # minimal out to avoid reverting on 0

        in_token = w3.to_checksum_address(os.environ["SWAPR_SDAI_YES_ADDRESS"])
        out_token = w3.to_checksum_address(os.environ["SDAI_TOKEN_ADDRESS"])

        return build_exact_in_tx(
            in_token,
            out_token,
            amount_in_wei,
            int(amount_in_wei * 0.01),
            acct.address,
            sqrt_price_limit=0,
        )
    else:
        # Build and return two txs:
        #   1️⃣ buy exact-out <amount> sDAI-YES with plain sDAI
        #   2️⃣ merge the freshly bought sDAI-YES back into plain sDAI
        amount_out_yes_wei = w3.to_wei(Decimal(amount), "ether")
        max_in_sdai_wei = int(amount_out_yes_wei * 1.2)

        buy_tx = build_exact_out_tx(
            w3.to_checksum_address(os.environ["SDAI_TOKEN_ADDRESS"]),    # tokenIn  (sDAI)
            w3.to_checksum_address(os.environ["SWAPR_SDAI_YES_ADDRESS"]),# tokenOut (sDAI-YES)
            amount_out_yes_wei,                                          # exact-out
            max_in_sdai_wei,                                             # slippage buffer
            acct.address,
        )

        merge_tx = build_merge_tx(
            w3,
            client,
            router_addr,
            proposal_addr,
            collateral_addr,          # merge sDAI collateral
            amount_out_yes_wei,
            acct.address,
        )

        return [buy_tx, merge_tx]