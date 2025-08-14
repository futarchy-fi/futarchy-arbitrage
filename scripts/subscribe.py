#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from typing import Optional

import websockets
import requests
# --- CONFIG ---
POOL_ADDR = "0xd1d7fa8871d84d0e77020fc28b7cd5718c446522"
VAULT_ADDR = "0xBA12222222228d8Ba445958a75a0704d566BF2C8"  # Balancer Vault (Gnosis)

# topics helpers
def addr_topic(addr_hex: str) -> str:
    a = addr_hex.lower().replace("0x","")
    return "0x" + ("00"*12) + a  # 32 bytes, endereço no fim

POOL_ID_TOPIC = addr_topic(POOL_ADDR)  # poolId = 0x000..00 + poolAddress (bytes32)

# Assinaturas:
SUBSCRIBE_PAYLOADS = [
    # 1) Tudo que a PRÓPRIA pool emitir
    {
        "jsonrpc":"2.0","id":1,"method":"eth_subscribe",
        "params":["logs", {"address": POOL_ADDR}]
    },
    # 2) Tudo do VAULT (sem filtro de topics)
    {
        "jsonrpc":"2.0","id":2,"method":"eth_subscribe",
        "params":[
            "logs",
            {
                "address": VAULT_ADDR
            }
        ]
    },
]
WS_URL = "wss://fragrant-side-glitter.xdai.quiknode.pro/1766655d3ca47b48d3f1a91864a0a6d744663ca0/"
SUBSCRIBE_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "eth_subscribe",
    "params": [
        "logs",
        {"address": "0xd1d7fa8871d84d0e77020fc28b7cd5718c446522"}
    ]
}
PING_INTERVAL = float(os.getenv("PING_INTERVAL", "25"))  # segundos
MAX_BACKOFF = float(os.getenv("MAX_BACKOFF", "60"))  # segundos

LOG_FILE = "balancer_logs.txt"

def log(*args):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    message = f"[{ts}] " + " ".join(str(a) for a in args)
    print(message, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except Exception as e:
        print(f"[{ts}] Erro ao escrever no log: {e}", flush=True)

#stop_event = asyncio.Event()

# def log(*args):
#     ts = time.strftime("%Y-%m-%d %H:%M:%S")
#     print(f"[{ts}]", *args, flush=True)

async def send_optional_subscribe(ws, from_block=None):
    payloads = SUBSCRIBE_PAYLOADS if 'SUBSCRIBE_PAYLOADS' in globals() else [SUBSCRIBE_PAYLOAD]
    
    # If from_block is specified, add it to the subscription params
    if from_block is not None:
        for payload in payloads:
            if "params" in payload and len(payload["params"]) > 1:
                if isinstance(payload["params"][1], dict):
                    payload["params"][1]["fromBlock"] = hex(from_block)
    
    for payload in payloads:
        await ws.send(json.dumps(payload))
        log("Subscribe enviado:", payload)


async def ping_task(ws, stop_event):
    while not stop_event.is_set():
        try:
            await asyncio.sleep(PING_INTERVAL)
            await ws.ping()
        except Exception as e:
            log("Ping falhou:", repr(e))
            return

async def read_messages(ws, stop_event):
    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
                log("Mensagem:", json.dumps(data, ensure_ascii=False))
            except Exception:
                log("Mensagem (raw):", msg)
    except Exception as e:
        log("Leitura encerrada:", repr(e))

async def run_once(backoff: float, stop_event: asyncio.Event, from_block=None):
    async with websockets.connect(
        WS_URL,
        open_timeout=20,
        close_timeout=10,
        ping_interval=None,
        max_queue=None,
    ) as ws:
        log(f"Conectado a {WS_URL}")
        await send_optional_subscribe(ws, from_block)

        pinger = asyncio.create_task(ping_task(ws, stop_event))
        reader = asyncio.create_task(read_messages(ws, stop_event))
        stopper = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait(
            {pinger, reader, stopper},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
        # garante que exceções de tasks cancelados não "vazem"
        await asyncio.gather(*pending, return_exceptions=True)

        log("Conexão encerrada.")

async def main(past_blocks=None):
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    # Get current block and calculate from_block if past_blocks specified
    from_block = None
    if past_blocks is not None and past_blocks > 0:
        try:
            rpc_url = os.getenv("RPC_URL", "https://gnosis-rpc.publicnode.com")
            # Use JSON-RPC to get current block number
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_blockNumber",
                "params": [],
                "id": 1
            }
            response = requests.post(rpc_url, json=payload)
            current_block = int(response.json()["result"], 16)
            from_block = max(0, current_block - past_blocks)
            log(f"Subscribing from block {from_block} (current: {current_block}, past: {past_blocks})")
        except Exception as e:
            log(f"Error getting current block: {e}, subscribing from latest")

    backoff = 1.0
    while not stop_event.is_set():
        try:
            await run_once(backoff, stop_event, from_block)
            if stop_event.is_set():
                break
            log("Tentando reconectar em", round(backoff, 1), "s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
        except (OSError, websockets.InvalidURI, websockets.InvalidHandshake) as e:
            log("Erro de conexão:", repr(e))
            log("Reconnecting em", round(backoff, 1), "s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log("Erro inesperado:", repr(e))
            log("Reconnecting em", round(backoff, 1), "s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

    log("Saindo. Até mais!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebSocket subscription for Balancer pool events")
    parser.add_argument(
        "--past-blocks",
        type=int,
        default=None,
        help="Number of past blocks to subscribe from (e.g., 1000 for last 1000 blocks)"
    )
    args = parser.parse_args()
    
    if WS_URL.startswith("wss://SEU-ENDPOINT-AQUI"):
        log("Defina a variável de ambiente WS_URL com a URL do WebSocket da sua pool.")
        sys.exit(1)
    
    asyncio.run(main(args.past_blocks))
