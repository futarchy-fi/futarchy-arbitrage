import os, time, json
from decimal import Decimal
from eth_account import Account
from src.helpers.swapr_swap import (
    w3,
    client,
    build_exact_in_tx,
    build_exact_out_tx,
    parse_simulated_swap_results as parse_simulated_swapr_results,
    parse_broadcasted_swap_results as parse_broadcasted_swapr_results,
)
from src.helpers.split_position import build_split_tx
from src.helpers.merge_position import build_merge_tx
from src.helpers.balancer_swap import (
    build_sell_gno_to_sdai_swap_tx,
    parse_simulated_swap_results as parse_simulated_balancer_results,
    parse_broadcasted_swap_results as parse_broadcasted_balancer_results,
)
from src.helpers.blockchain_sender import send_tenderly_tx_onchain
from src.helpers.conditional_sdai_liquidation import (
    build_conditional_sdai_liquidation_steps,
    build_liquidate_remaining_conditional_sdai_tx,
)

acct = Account.from_key(os.environ["PRIVATE_KEY"])

token_yes_in = w3.to_checksum_address(os.environ["SWAPR_SDAI_YES_ADDRESS"])
token_yes_out = w3.to_checksum_address(os.environ["SWAPR_GNO_YES_ADDRESS"])
token_no_in = w3.to_checksum_address(os.environ["SWAPR_SDAI_NO_ADDRESS"])
token_no_out = w3.to_checksum_address(os.environ["SWAPR_GNO_NO_ADDRESS"])

# --- Futarchy splitPosition parameters ---------------------------------------
router_addr = w3.to_checksum_address(os.environ["FUTARCHY_ROUTER_ADDRESS"])
proposal_addr = w3.to_checksum_address(os.environ["FUTARCHY_PROPOSAL_ADDRESS"])
collateral_addr = w3.to_checksum_address(os.environ["SDAI_TOKEN_ADDRESS"])
gno_collateral_addr = w3.to_checksum_address(os.environ["GNO_TOKEN_ADDRESS"])

# --------------------------------------------------------------------------- #
# On-chain sender helper                                                      #
# --------------------------------------------------------------------------- #

def _send_bundle_onchain(bundle):
    """Broadcast every tx in *bundle* with sequential nonces and return their hashes."""
    starting_nonce = w3.eth.get_transaction_count(acct.address)
    tx_hashes = []
    for i, tx in enumerate(bundle):
        tx_hash = send_tenderly_tx_onchain(tx, nonce=starting_nonce + i)
        tx_hashes.append(tx_hash)
    return tx_hashes


def build_step_1_swap_steps(split_amount_in_wei, gno_amount_in_wei, price=1000):
    if gno_amount_in_wei is None:
        deadline = int(time.time()) + 600
        amount_in_max = int(split_amount_in_wei * 10.2)
        amount_out_min = 0
        sqrt_price_limit = 0

        yes_tx = build_exact_in_tx(
            token_yes_in, token_yes_out, split_amount_in_wei, amount_out_min, acct.address
        )
        no_tx = build_exact_in_tx(
            token_no_in, token_no_out, split_amount_in_wei, amount_out_min, acct.address
        )
        return [
            (yes_tx, handle_swap("yes", "in", split_amount_in_wei)),
            (no_tx, handle_swap("no", "in", split_amount_in_wei)),
        ]
    else:
        deadline = int(time.time()) + 600
        amount_in_max = int(split_amount_in_wei * 10.2)
        amount_out_expected = gno_amount_in_wei
        amount_out_min = int(amount_out_expected * 0.9)
        sqrt_price_limit = 0

        yes_tx = build_exact_out_tx(
            token_yes_in, token_yes_out, amount_out_expected, amount_in_max, acct.address
        )
        no_tx = build_exact_out_tx(
            token_no_in, token_no_out, amount_out_expected, amount_in_max, acct.address
        )
        return [
            (yes_tx, handle_swap("yes", "out", amount_out_expected)),
            (no_tx, handle_swap("no", "out", amount_out_expected)),
        ]


def build_step_2_merge_tx(gno_amount_in_wei):
    """Return Tenderly transaction dict for FutarchyRouter.mergePositions."""
    return build_merge_tx(
        w3,
        client,
        router_addr,
        proposal_addr,
        gno_collateral_addr,
        int(gno_amount_in_wei),
        acct.address,
    )


# --------------------------------------------------------------------------- #
# Handler functions for transaction simulation steps                          #
# --------------------------------------------------------------------------- #
def handle_split(state, sim):
    return state

def handle_yes_swap(state, sim):
    data = parse_simulated_swapr_results([sim], label="SwapR YES (exact-out)", fixed="out")
    returned_amount_wei = extract_return(sim, None, "out")
    if returned_amount_wei is not None:
        state["amount_out_yes_wei"] = returned_amount_wei
    return state

def handle_no_swap(state, sim):
    data = parse_simulated_swapr_results([sim], label="SwapR NO  (exact-out)", fixed="out")
    returned_amount_wei = extract_return(sim, None, "out")
    if returned_amount_wei is not None:
        state["amount_out_no_wei"] = returned_amount_wei
    return state

def handle_merge(state, sim):
    return state

def handle_liquidate(state, sim):
    data = parse_simulated_swapr_results([sim], label="SwapR Liquidate YES→sDAI (exact-in)", fixed="in")
    if data:
        state["sdai_out"] += data["output_amount"]
    return state

def handle_buy_sdai_yes(state, sim):
    parse_simulated_swapr_results([sim], label="SwapR buy sDAI-YES (exact-out)", fixed="out")
    return state

def handle_merge_conditional_sdai(state, sim):
    # Merging conditional sDAI tokens back to regular sDAI
    return state

def handle_balancer(state, sim):
    data = parse_simulated_balancer_results([sim], w3)
    if data:
        state["sdai_out"] += data["output_amount"]
    return state

def handle_swap(label_kind: str, fixed_kind: str, amount_wei: int):
    """Return a swap handler closure for either YES or NO leg.

    *label_kind* must be ``"yes"`` or ``"no"`` and *fixed_kind* ``"in"`` or ``"out"``.
    The closure updates the corresponding ``state`` field with the amount
    returned by Tenderly (`amount_out_yes_wei` or `amount_out_no_wei`).
    """

    label_kind_lc = label_kind.lower()
    fixed_kind_lc = fixed_kind.lower()

    def _handler(state, sim):
        label = f"SwapR {label_kind.upper()} (exact-{fixed_kind_lc})"
        # Re-use existing pretty-printer util
        parse_simulated_swapr_results([sim], label=label, fixed=fixed_kind_lc)

        returned_amount_wei = extract_return(sim, amount_wei, fixed_kind_lc)
        if fixed_kind_lc == "in" and returned_amount_wei is not None:
            if label_kind_lc == "yes":
                state["amount_out_yes_wei"] = returned_amount_wei
                state["amount_in_yes_wei"] = amount_wei
            else:
                state["amount_out_no_wei"] = returned_amount_wei
                state["amount_in_no_wei"] = amount_wei
        elif fixed_kind_lc == "out" and returned_amount_wei is not None:
            if label_kind_lc == "yes":
                state["amount_in_yes_wei"] = returned_amount_wei
                state["amount_out_yes_wei"] = amount_wei
            else:
                state["amount_in_no_wei"] = returned_amount_wei
                state["amount_out_no_wei"] = amount_wei
        return state

    # expose metadata for broadcast path
    _handler.label_kind = label_kind_lc
    _handler.fixed_kind = fixed_kind_lc
    _handler.amount_wei = amount_wei
    return _handler

def extract_return(sim, amount_in_or_out_wei_local, fixed_kind):
    tx = sim.get("transaction", {})
    call_trace = tx.get("transaction_info", {}).get("call_trace", {})
    output_hex = call_trace.get("output")
    if output_hex and output_hex != "0x":
        try:
            returned_amount_wei = int(output_hex[2:], 16)
        except ValueError:
            return None
        return returned_amount_wei
    return None

def buy_gno_yes_and_no_amounts_with_sdai_single(
    amount,
    gno_amount=None,
    liquidate_conditional_sdai_amount=None,
    *,
    broadcast=False,
    price=100,
):
    split_amount_in_wei = w3.to_wei(Decimal(amount), "ether")
    if gno_amount is not None:
        gno_amount_in_wei = w3.to_wei(Decimal(gno_amount), "ether")
    else:
        gno_amount_in_wei = None

    split_tx = build_split_tx(
        w3,
        client,
        router_addr,
        proposal_addr,
        collateral_addr,
        split_amount_in_wei,
        acct.address,
    )

    steps = []
    steps.append((split_tx, handle_split))

    swap_steps = build_step_1_swap_steps(split_amount_in_wei, gno_amount_in_wei, price)
    steps.extend(swap_steps)

    merge_tx = build_merge_tx(
        w3,
        client,
        router_addr,
        proposal_addr,
        gno_collateral_addr,
        int(gno_amount_in_wei) if gno_amount_in_wei else 0,
        acct.address,
    )
    steps.append((merge_tx, handle_merge))
    if liquidate_conditional_sdai_amount:
        steps += build_conditional_sdai_liquidation_steps(
            liquidate_conditional_sdai_amount,
            handle_liquidate,
            handle_buy_sdai_yes,
            handle_merge_conditional_sdai,
    )

    gno_to_sdai_txs = []
    if gno_amount_in_wei:
        gno_to_sdai_txs.append(
            build_sell_gno_to_sdai_swap_tx(
                w3,
                client,
                gno_amount_in_wei,
                1,
                acct.address,
            )
        )
    if gno_to_sdai_txs:
        steps.append((gno_to_sdai_txs[0], handle_balancer))

    bundle = [tx for tx, _ in steps]

    if broadcast:
        tx_hashes = _send_bundle_onchain(bundle)

        # Prepare initial state analogous to simulation path
        sdai_in = Decimal(amount) + Decimal(max(-(liquidate_conditional_sdai_amount or 0), 0))
        state = {
            "amount_out_yes_wei": None,
            "amount_out_no_wei": None,
            "amount_in_yes_wei": None,
            "amount_in_no_wei": None,
            "sdai_out": Decimal("0"),
            "sdai_in": sdai_in,
        }

        # Walk over tx hashes and matching handlers to enrich state
        for (tx_hash, (_, handler)) in zip(tx_hashes, steps):
            # SwapR swaps expose metadata via attributes
            if hasattr(handler, "label_kind"):
                swap_res = parse_broadcasted_swapr_results(tx_hash, fixed=handler.fixed_kind)
                if not swap_res:
                    continue
                inp_wei = w3.to_wei(swap_res["input_amount"], "ether")
                out_wei = w3.to_wei(swap_res["output_amount"], "ether")
                if handler.label_kind == "yes":
                    state["amount_in_yes_wei"] = inp_wei
                    state["amount_out_yes_wei"] = out_wei
                else:
                    state["amount_in_no_wei"] = inp_wei
                    state["amount_out_no_wei"] = out_wei

            elif handler.__name__ == "handle_balancer":
                bal_res = parse_broadcasted_balancer_results(tx_hash)
                if bal_res:
                    state["sdai_out"] += bal_res["output_amount"]

            # Other handlers (split/merge, etc.) don't affect summary totals directly

        print("Broadcast tx hashes:", tx_hashes)
        return {"tx_hashes": tx_hashes, **state}

    result = client.simulate(bundle)
    sdai_in = Decimal(amount) + Decimal(max(-(liquidate_conditional_sdai_amount or 0), 0))
    state = {
        "amount_out_yes_wei": None,
        "amount_out_no_wei": None,
        "sdai_out": Decimal("0"),
        "sdai_in": sdai_in,
    }
    if result and result.get("simulation_results"):
        sims = result["simulation_results"]
        for idx, sim in enumerate(sims):
            if sim.get("error"):
                print(sim["error"])
                continue
            tx = sim.get("transaction", {})
            if not tx:
                print("No transaction data in result.")
                continue
            if tx.get("status") is False:
                print("Transaction REVERTED.")
                continue
            print("Swap transaction did NOT revert.")
            if idx < len(steps):
                _, handler = steps[idx]
                state = handler(state, sim)
            else:
                print("No handler defined for this tx.")
    else:
        print("Simulation failed or returned no results.")
    return state

def buy_gno_yes_and_no_amounts_with_sdai(amount, *, broadcast=False):
    """Calculates the best split based on multiple simulations"""
    # First simulation: No GNO swap limit
    result = buy_gno_yes_and_no_amounts_with_sdai_single(
        amount, None, None
    )

    # Extract amounts from the first simulation result
    amount_out_yes_wei = result['amount_out_yes_wei']
    amount_out_no_wei = result['amount_out_no_wei']

    # Step 2: Determine the limiting amount between YES and NO tokens
    if amount_out_yes_wei > amount_out_no_wei:
        amount_out_limited_wei = amount_out_no_wei
    else:
        amount_out_limited_wei = amount_out_yes_wei

    amount_out_limited = w3.from_wei(amount_out_limited_wei, "ether")  # gno_amount in ETH

    # Run second simulation with GNO amount limit
    result = buy_gno_yes_and_no_amounts_with_sdai_single(
        amount, amount_out_limited, None
    )

    # Extract amounts from the second simulation result
    amount_out_yes_wei = result['amount_out_yes_wei']
    amount_out_no_wei = result['amount_out_no_wei']
    if amount_out_yes_wei > amount_out_no_wei:
        amount_out_cond_limited_wei = amount_out_no_wei
    else:
        amount_out_cond_limited_wei = amount_out_yes_wei
    # amount_out_cond_limited = w3.from_wei(amount_out_cond_limited_wei, "ether")
    # Step 3: Calculate conditional sDAI liquidation amount
    amount_in_yes_wei = result['amount_in_yes_wei']
    amount_in_no_wei = result['amount_in_no_wei']
    liquidate_conditional_sdai_amount_wei = amount_in_yes_wei - amount_in_no_wei
    if liquidate_conditional_sdai_amount_wei > 0:
        liquidate_conditional_sdai_amount = w3.from_wei(liquidate_conditional_sdai_amount_wei, "ether")
    else:
        liquidate_conditional_sdai_amount = -w3.from_wei(-liquidate_conditional_sdai_amount_wei, "ether")

    # Run final simulation with liquidation amount
    result = buy_gno_yes_and_no_amounts_with_sdai_single(
        amount,
        amount_out_limited,
        liquidate_conditional_sdai_amount,
        broadcast=broadcast,
    )

    # If broadcasting, we don't have simulation state; just return tx hashes
    if broadcast:
        return result  # e.g., {"tx_hashes": [...]}.

    # Extract amounts from the third simulation result (simulation mode)
    sdai_in = result['sdai_in']
    sdai_out = result['sdai_out']
    result['sdai_net'] = sdai_out - sdai_in
    # Calculate net sDAI for final result
    print(f"sDAI in: {sdai_in}, out: {sdai_out}, net: {sdai_out - sdai_in}")
    return result

if __name__ == "__main__":
    import sys

    SEND_FLAG = {"--send", "-s"}
    broadcast = any(flag in sys.argv for flag in SEND_FLAG)
    sys.argv = [arg for arg in sys.argv if arg not in SEND_FLAG]
    num_script_args = len(sys.argv) - 1

    if num_script_args == 0:
        print("Usage: python -m from .exchanges.simulator.simulator <amount> [<gno_amount>] [<liquidate_conditional_sdai_amount>]")
        sys.exit(1)
    
    # All valid paths require at least the first argument 'amount'
    amount = float(sys.argv[1])

    if num_script_args == 1:
        # Corresponds to the original "main" block's behavior (1 argument)
        print(f"Simulating for amount: {amount}")
        result = buy_gno_yes_and_no_amounts_with_sdai(amount, broadcast=broadcast)
        print(f"Result: {result}")
    elif num_script_args == 2:
        # Corresponds to the "main_legacy" block's behavior with 2 arguments
        gno_amount = float(sys.argv[2])
        print(f"Simulating for amount: {amount} with GNO amount: {gno_amount}")
        result = buy_gno_yes_and_no_amounts_with_sdai_single(
            amount, gno_amount, None, broadcast=broadcast
        )
        print(f"Result: {result}")
    elif num_script_args == 3:
        # Corresponds to the "main_legacy" block's behavior with 3 arguments
        gno_amount = float(sys.argv[2])
        liquidate_conditional_sdai_amount = float(sys.argv[3])
        print(
            f"Simulating for amount: {amount} with GNO amount: {gno_amount}, liquidating sDAI: {liquidate_conditional_sdai_amount}"
        )
        result = buy_gno_yes_and_no_amounts_with_sdai_single(
            amount,
            gno_amount,
            liquidate_conditional_sdai_amount,
            broadcast=broadcast,
        )
        print(f"Result: {result}")
    else: # num_script_args > 3 or any other unexpected count
        print("Error: Invalid number of arguments.")
        print("Usage: python -m from .exchanges.simulator.simulator <amount> [<gno_amount>] [<liquidate_conditional_sdai_amount>]")
        sys.exit(1)
