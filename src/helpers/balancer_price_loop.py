from __future__ import annotations

from decimal import Decimal
import json
from typing import Tuple
import os
import time
from datetime import datetime, timezone
import requests

from web3 import Web3

from config.abis.balancer import BALANCER_VAULT_V3_ABI
from config.abis.erc20 import ERC20_ABI
from dotenv import load_dotenv
load_dotenv()


# --- CONFIGURAÇÕES EDGE FUNCTION ---
project_id = os.getenv("PROJECT_ID")
print("project_id: ", project_id)
SUPABASE_EDGE_URL = f'https://{project_id}.supabase.co/functions/v1/insert_balancer_candle'
SUPABASE_EDGE_TOKEN = f'{os.getenv("SUPABASE_EDGE_TOKEN")}'
print("SUPABASE_EDGE_TOKEN: ", SUPABASE_EDGE_TOKEN)
HEADERS = {
    "Authorization": f"Bearer {SUPABASE_EDGE_TOKEN}",
    "Content-Type": "application/json"
}

MINUTE_MS = 60_000
HOUR_MS = 3_600_000

def _get_vault(w3: Web3, vault_addr: str | None = None):
    addr = (
        vault_addr
        or "0xbA1333333333a1BA1108E8412f11850A5C319bA9"
    )
    return w3.eth.contract(address=w3.to_checksum_address(addr), abi=BALANCER_VAULT_V3_ABI)

def _decimals(w3: Web3, token_addr: str) -> int:
    return w3.eth.contract(address=token_addr, abi=ERC20_ABI).functions.decimals().call()

def get_pool_price(
    w3: Web3,
    pool_address: str,
    *,
    base_token_index: int = 0,
    vault_addr: str | None = None,
) -> Tuple[Decimal, str, str]:
    vault = _get_vault(w3, vault_addr)
    tokens, _, balances_raw, _ = vault.functions.getPoolTokenInfo(
        w3.to_checksum_address(pool_address)
    ).call()

    i = base_token_index
    j = 1 if i == 0 else 0

    bal_i = Decimal(balances_raw[i]) / (10 ** _decimals(w3, tokens[i]))
    bal_j = Decimal(balances_raw[j]) / (10 ** _decimals(w3, tokens[j]))

    return bal_j / bal_i, tokens[i], tokens[j]

def get_now_str():
    # '2025-05-03 04:00:26.536928+00'
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f+00")

def insert_candle(data):
    try:
        resp = requests.post(
            SUPABASE_EDGE_URL,
            headers=HEADERS,
            data=json.dumps(data),
            timeout=8
        )
        if resp.status_code >= 300:
            print(f"Erro Supabase ({resp.status_code}): {resp.text}")
        else:
            print(f"Inserted: {json.dumps(data)}")
    except Exception as e:
        print(f"Erro ao chamar Edge Function: {e}")

if __name__ == "__main__":
    INTERVAL_SEC = 60  # 1 minuto

    rpc_url = os.getenv("GNOSIS_RPC_URL") or os.getenv("RPC_URL")
    if rpc_url is None:
        raise RuntimeError("Must set GNOSIS_RPC_URL or RPC_URL environment variable")

    w3_cli = Web3(Web3.HTTPProvider(rpc_url))

    pool_addr_cli = os.getenv("BALANCER_POOL_ADDRESS")
    if pool_addr_cli is None:
        raise RuntimeError("Must set BALANCER_POOL_ADDRESS env var")

    print("address,interval,price,timestamp,pool_interval_id,created_at,inserted_at,updated_at")

    last_hour = None

    while True:
        try:
            price, base, quote = get_pool_price(w3_cli, pool_addr_cli)
            dt_now = datetime.now(timezone.utc)
            timestamp = int(dt_now.timestamp())
            now_str = get_now_str()
            address = pool_addr_cli
            minute_interval = MINUTE_MS
            hour_interval = HOUR_MS
            price_str = f"{price}"

            # --- Sempre insere candle de 1 minuto ---
            candle_minute = {
                "address": address,
                "interval": minute_interval,
                "price": price_str,
                "timestamp": timestamp,
                "pool_interval_id": f"{address}_{minute_interval}",
                "created_at": now_str,
            }
            insert_candle(candle_minute)

            # --- Quando der minuto zero (exemplo: 19:00), também insere candle de 1 hora ---
            if dt_now.minute == 0:
                candle_hour = {
                    "address": address,
                    "interval": hour_interval,
                    "price": price_str,
                    "timestamp": timestamp,
                    "pool_interval_id": f"{address}_{hour_interval}",
                    "created_at": now_str,
                }
                insert_candle(candle_hour)

        except Exception as e:
            print(json.dumps({"error": str(e)}))

        time.sleep(INTERVAL_SEC)
