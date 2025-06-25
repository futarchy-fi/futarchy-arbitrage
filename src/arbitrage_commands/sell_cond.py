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
    build_buy_gno_to_sdai_swap_tx,
    parse_simulated_swap_results as parse_simulated_balancer_results,
    parse_broadcasted_swap_results as parse_broadcasted_balancer_results,
)
from src.helpers.blockchain_sender import send_tenderly_tx_onchain

acct = Account.from_key(os.environ["PRIVATE_KEY"])

token_yes_in = w3.to_checksum_address(os.environ["SWAPR_GNO_YES_ADDRESS"])
token_yes_out = w3.to_checksum_address(os.environ["SWAPR_SDAI_YES_ADDRESS"])
token_no_in = w3.to_checksum_address(os.environ["SWAPR_GNO_NO_ADDRESS"])
token_no_out = w3.to_checksum_address(os.environ["SWAPR_SDAI_NO_ADDRESS"])

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

def build_conditional_sdai_liquidation_steps(
    liquidate_conditional_sdai_amount,
    handle_liquidate,
    handle_liquidate_sdai_yes,
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
                (liq_txs[0], handle_liquidate_sdai_yes),
                (liq_txs[1], handle_merge_conditional_sdai),
            ]
    return steps

def build_step_2_swap_steps(split_amount_in_wei, sdai_amount_in_wei, price=100):
    if sdai_amount_in_wei is None:
        amount_in_max = int(split_amount_in_wei * price * 1.002)
        amount_out_min = 0

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
        amount_in_max = int(split_amount_in_wei * price)
        amount_out_expected = sdai_amount_in_wei
        print("split_amount_in_wei: ", split_amount_in_wei)
        print("amount_in_max: ", amount_in_max)
        print("amount_out_expected: ", amount_out_expected)

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
# Simple helper: liquidate conditional sDAI (YES) back to plain sDAI          #
# --------------------------------------------------------------------------- #

def build_liquidate_remaining_conditional_sdai_tx(amount: float, is_yes: bool):
    """Return Tenderly tx dict swapping sDAI-Yes → sDAI via SwapR exact-in.

    If *is_yes* is False, this is a no-op and returns ``None``.
    """
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


# Adjust collateral amount to split as needed (currently hard-coded to 1 ether)
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
    print("handle_liquidate result:", data)
    if data:
        print("output_amount:", data["output_amount"])
        print("sdai_out before:", state["sdai_out"])
        state["sdai_out"] += data["output_amount"]
        print("sdai_out after:", state["sdai_out"])
    return state

def handle_liquidate_sdai_yes(state, sim):
    data = parse_simulated_swapr_results([sim], label="SwapR buy sDAI-YES (exact-out)", fixed="out")
    if data:
        print("output_amount:", data["output_amount"])
        print("sdai_out before:", state["sdai_out"])
        state["sdai_out"] += data["output_amount"]
        state["sdai_in"] += data["input_amount"]
        print("sdai_out after:", state["sdai_out"])
    return state

def handle_merge_conditional_sdai(state, sim):
    # data = parse_simulated_swapr_results([sim], label="SwapR merge conditional sDAI (exact-in)", fixed="in")
    # if data:
    #     state["sdai_out"] += data["output_amount"]
    return state

def handle_balancer(state, sim):
    data = parse_simulated_balancer_results([sim], w3)
    if data:
        state["gno_out"] = data["output_amount"]
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
        result = parse_simulated_swapr_results([sim], label=label, fixed=fixed_kind_lc)
        print("_handler result:", result)

        returned_amount_wei = extract_return(sim, amount_wei, fixed_kind_lc)
        if fixed_kind_lc == "in" and returned_amount_wei is not None:
            if label_kind_lc == "yes":
                state["amount_in_yes_wei"] = amount_wei
                state["amount_out_yes_wei"] = returned_amount_wei
            else:
                state["amount_in_no_wei"] = amount_wei
                state["amount_out_no_wei"] = returned_amount_wei
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

def sell_gno_yes_and_no_amounts_to_sdai_single(
    amount,
    gno_amount=None,
    conditional_sdai_amount=None,
    liquidate_conditional_sdai_amount=None,
    *,
    broadcast=False,
    price=100,
):
    max_step = (3 if liquidate_conditional_sdai_amount and conditional_sdai_amount is not None else 2) if gno_amount is not None else 1
    steps = []
    print("max_step:", max_step)

    # ------------------------------------------------------------------ #
    # Buy GNO with the provided sDAI amount via Balancer (exact-in)      #
    # ------------------------------------------------------------------ #
    sdai_amount_in_wei = w3.to_wei(Decimal(amount), "ether")

    # Log all important arguments for the Balancer swap
    print(f"=== BALANCER SWAP ARGUMENTS ===")
    print(f"sdai_amount_in_wei: {sdai_amount_in_wei}")
    print(f"sdai_amount (ether): {amount}")
    print(f"min_gno_out_wei: 1")
    print(f"sender_address: {acct.address}")
    print(f"w3 instance: {w3}")
    print(f"client instance: {client}")
    print("===============================")

    buy_gno_tx = build_buy_gno_to_sdai_swap_tx(
        w3,
        client,
        sdai_amount_in_wei,
        1,            # min GNO out (wei)
        acct.address,
    )
    steps.append((buy_gno_tx, handle_balancer))

    if max_step >= 2:
        print("max_step >= 2")
        conditional_sdai_amount_wei = w3.to_wei(Decimal(conditional_sdai_amount), "ether") if conditional_sdai_amount else None
        split_amount_in_wei = w3.to_wei(Decimal(gno_amount), "ether")
        
        split_tx = build_split_tx(
            w3,
            client,
            router_addr,
            proposal_addr,
            gno_collateral_addr,
            split_amount_in_wei,
            acct.address,
        )
        steps.append((split_tx, handle_split))

        steps += build_step_2_swap_steps(split_amount_in_wei, None)
 

    if max_step >= 3:
        conditional_sdai_amount_wei = w3.to_wei(Decimal(conditional_sdai_amount), "ether")
        merge_tx = build_merge_tx(
            w3,
            client,
            router_addr,
            proposal_addr,
            collateral_addr,
            int(conditional_sdai_amount_wei),
            acct.address,
        )
        steps.append((merge_tx, handle_merge))

        if liquidate_conditional_sdai_amount:
            steps += build_conditional_sdai_liquidation_steps(
                liquidate_conditional_sdai_amount,
                handle_liquidate,
                handle_liquidate_sdai_yes,
                handle_merge_conditional_sdai,
        )


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
            "gno_out": Decimal("0"),
            "sdai_out": Decimal("0"),
            "sdai_in": sdai_in,
        }

        # Walk over tx hashes and matching handlers to enrich state
        for (tx_hash, (_tx_dict, handler)) in zip(tx_hashes, steps):
            # SwapR swaps expose metadata via attributes
            if hasattr(handler, "label_kind"):
                swap_res = parse_broadcasted_swapr_results(tx_hash, fixed=handler.fixed_kind)
                print("swap_res:", swap_res)
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
                print("bal_res:", bal_res)
                if bal_res:
                    state["gno_out"] += bal_res["output_amount"]

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
                print("State after handling:", state)
            else:
                print("No handler defined for this tx.")
    else:
        print("Simulation failed or returned no results.")
    return state

def sell_gno_yes_and_no_amounts_to_sdai(amount, *, broadcast=False):
    """Calculates the best split based on multiple simulations"""
    # First simulation: No GNO swap limit
    print("STEP 1 ----------------")
    print("Running:\nsell_gno_yes_and_no_amounts_to_sdai_single({}, None, None)\n".format(amount))
    result = sell_gno_yes_and_no_amounts_to_sdai_single(
        amount, None, None
    )

    # Extract amounts from the first simulation result
    print("result:", result)

    if result.get('gno_out') is None:
        print("No GNO out in result.")
        return None

    print("STEP 2 ----------------")
    amount_out_limited = result['gno_out']
    print("amount_out_limited:", amount_out_limited)

    print("Running:\nsell_gno_yes_and_no_amounts_to_sdai_single({}, {}, None)\n".format(amount, amount_out_limited))
    result = sell_gno_yes_and_no_amounts_to_sdai_single(
        amount, amount_out_limited, None
    )
    print("result:", result)
    # Extract amounts from the second simulation result
    amount_out_yes_wei = result['amount_out_yes_wei']
    amount_out_no_wei = result['amount_out_no_wei']
    if amount_out_yes_wei > amount_out_no_wei:
        amount_out_cond_limited_wei = amount_out_no_wei
    else:
        amount_out_cond_limited_wei = amount_out_yes_wei
    amount_out_cond_limited = w3.from_wei(amount_out_cond_limited_wei, "ether")
    print("amount_out_cond_limited:", amount_out_cond_limited)


    print("STEP 3 ----------------")
    liquidate_conditional_sdai_amount_wei = amount_out_yes_wei - amount_out_no_wei
    # liquidate_conditional_sdai_amount = w3.from_wei(liquidate_conditional_sdai_amount_wei, "ether")
    if liquidate_conditional_sdai_amount_wei > 0:
        liquidate_conditional_sdai_amount = w3.from_wei(liquidate_conditional_sdai_amount_wei, "ether")
    else:
        liquidate_conditional_sdai_amount = -w3.from_wei(-liquidate_conditional_sdai_amount_wei, "ether")

    print("Running:\nsell_gno_yes_and_no_amounts_to_sdai_single({}, {}, {})\n".format(amount, amount_out_limited, liquidate_conditional_sdai_amount))
    result = sell_gno_yes_and_no_amounts_to_sdai_single(
        amount,
        amount_out_limited,
        amount_out_cond_limited,
        liquidate_conditional_sdai_amount,
        broadcast=broadcast,
    )

    # If broadcasting, we don't have simulation state; just return tx hashes
    if broadcast:
        return result  # e.g., {"tx_hashes": [...]}.

    # Extract amounts from the third simulation result (simulation mode)
    sdai_in = result['sdai_in']
    sdai_out = result['sdai_out'] + amount_out_cond_limited
    result['sdai_net'] = sdai_out - sdai_in

    print("FINAL RESULT")
    print("sDAI in:", sdai_in)
    print("sDAI out:", sdai_out)
    print("sDAI net:", sdai_out - sdai_in)
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
        # print(f"Debug: Running current main logic with amount: {amount}") # Optional debug print
        print(f"Simulating for amount: {amount}")
        result = sell_gno_yes_and_no_amounts_to_sdai(amount, broadcast=broadcast)
        # result = sell_gno_yes_and_no_amounts_to_sdai_single(amount, broadcast=broadcast)
        print(f"Result: {result}")
    elif num_script_args == 2:
        # Corresponds to the "main_legacy" block's behavior with 2 arguments
        gno_amount = float(sys.argv[2])
        # print(f"Debug: Running legacy logic with amount: {amount}, gno_amount: {gno_amount}") # Optional debug print
        print(f"Simulating for amount: {amount} with GNO amount: {gno_amount}")
        result = sell_gno_yes_and_no_amounts_to_sdai_single(
            amount, gno_amount, None, broadcast=broadcast
        )
        print(f"Result: {result}")
    elif num_script_args == 3:
        # Corresponds to the "main_legacy" block's behavior with 3 arguments
        gno_amount = float(sys.argv[2])
        conditional_sdai_amount = float(sys.argv[3])
        # print(f"Debug: Running legacy logic with amount: {amount}, gno_amount: {gno_amount}, liquidate: {conditional_sdai_amount}") # Optional debug print
        print(
            f"Simulating for amount: {amount} with GNO amount: {gno_amount}, liquidating sDAI: {conditional_sdai_amount}"
        )
        result = sell_gno_yes_and_no_amounts_to_sdai_single(
            amount,
            gno_amount,
            conditional_sdai_amount,
            broadcast=broadcast,
        )
        print(f"Result: {result}")
    elif num_script_args == 4:
        # Corresponds to the "main_legacy" block's behavior with 3 arguments
        gno_amount = float(sys.argv[2])
        conditional_sdai_amount = float(sys.argv[3])
        liquidate_conditional_sdai_amount = float(sys.argv[4])
        # print(f"Debug: Running legacy logic with amount: {amount}, gno_amount: {gno_amount}, liquidate: {liquidate_conditional_sdai_amount}") # Optional debug print
        print(
            f"Simulating for amount: {amount} with GNO amount: {gno_amount}, liquidating sDAI: {liquidate_conditional_sdai_amount}"
        )
        result = sell_gno_yes_and_no_amounts_to_sdai_single(
            amount,
            gno_amount,
            conditional_sdai_amount,
            liquidate_conditional_sdai_amount,
            broadcast=broadcast,
        )
        print(f"Result: {result}")
    else: # num_script_args > 3 or any other unexpected count
        print("Error: Invalid number of arguments.")
        print("Usage: python -m from .exchanges.simulator.simulator <amount> [<gno_amount>] [<liquidate_conditional_sdai_amount>]")
        sys.exit(1)
