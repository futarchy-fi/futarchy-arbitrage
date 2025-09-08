#!/usr/bin/env python3
from __future__ import annotations

"""
Deployment Links Helper

Builds a mapping between HD derivation paths (used to derive the deployer EOA)
and deployed FutarchyArbExecutorV5 contract addresses.

Data sources:
- build/wallets/deploy_v5_*.json  (deploy logs written by deploy_v5)
  - Successful runs include: {"summary": {..., "path", "deployer", ...}, "address": "0x...", "tx": "0x..."}
  - Dry-run/plan or failed runs may lack "address".
- deployments/deployment_executor_v5_*.json (discovery files)
  - Contains "address" only; no path/deployer linkage. Used for cross-checks.

CLI examples:
- List all discovered links (latest per path):
    python -m src.setup.deployment_links list

- Find latest address for a given path:
    python -m src.setup.deployment_links path --path "m/44'/60'/0'/0/5"

- Find the recorded path for a given address (if present in logs):
    python -m src.setup.deployment_links address --address 0xABC...

- Export mapping to JSON file:
    python -m src.setup.deployment_links export --out deployments/deployment_links.json
"""

import argparse
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


LOGS_GLOB = "build/wallets/deploy_v5_*.json"
DEPLOYMENTS_GLOB = "deployments/deployment_executor_v5_*.json"


@dataclass
class DeploymentLink:
    path: str
    address: str
    deployer: Optional[str]
    tx: Optional[str]
    generated_at: Optional[str]
    log_file: str

    def timestamp(self) -> float:
        # Prefer generated_at if present (ISO8601), else fallback to file mtime
        if self.generated_at:
            try:
                return datetime.fromisoformat(self.generated_at.replace("Z", "+00:00")).timestamp()
            except Exception:
                pass
        try:
            return Path(self.log_file).stat().st_mtime
        except Exception:
            return 0.0


def _load_json(path: Path) -> Optional[dict]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _is_hex_address(s: str) -> bool:
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", s or ""))


def scan_deploy_logs(logs_glob: str = LOGS_GLOB) -> List[DeploymentLink]:
    links: List[DeploymentLink] = []
    for p in sorted(Path(".").glob(logs_glob)):
        data = _load_json(p)
        if not data:
            continue
        summary = data.get("summary") if isinstance(data, dict) else None
        address = data.get("address") if isinstance(data, dict) else None
        tx = data.get("tx") if isinstance(data, dict) else None

        if not summary or not address:
            # Skip plans/failed runs without address
            continue
        path = summary.get("path")
        deployer = summary.get("deployer")
        generated_at = summary.get("generated_at")
        if not path or not _is_hex_address(address):
            continue
        links.append(
            DeploymentLink(
                path=path,
                address=address,
                deployer=deployer if isinstance(deployer, str) else None,
                tx=tx if isinstance(tx, str) else None,
                generated_at=generated_at if isinstance(generated_at, str) else None,
                log_file=str(p),
            )
        )
    return links


def latest_links_by_path(links: List[DeploymentLink]) -> Dict[str, DeploymentLink]:
    latest: Dict[str, DeploymentLink] = {}
    for link in links:
        cur = latest.get(link.path)
        if not cur or link.timestamp() >= cur.timestamp():
            latest[link.path] = link
    return latest


def find_by_path(path: str, links: Optional[List[DeploymentLink]] = None) -> Optional[DeploymentLink]:
    if links is None:
        links = scan_deploy_logs()
    candidates = [l for l in links if l.path == path]
    if not candidates:
        return None
    candidates.sort(key=lambda l: l.timestamp(), reverse=True)
    return candidates[0]


def find_by_address(address: str, links: Optional[List[DeploymentLink]] = None) -> Optional[DeploymentLink]:
    if links is None:
        links = scan_deploy_logs()
    address = address.lower()
    candidates = [l for l in links if l.address.lower() == address]
    if not candidates:
        return None
    candidates.sort(key=lambda l: l.timestamp(), reverse=True)
    return candidates[0]


def export_links(out_path: Path, links: Optional[List[DeploymentLink]] = None) -> Path:
    if links is None:
        links = scan_deploy_logs()
    latest = latest_links_by_path(links)
    payload = {
        "links": [asdict(v) for _, v in sorted(latest.items(), key=lambda kv: kv[0])],
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source": "deploy_v5 logs",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    return out_path


def main() -> int:
    p = argparse.ArgumentParser(description="Link HD paths to deployed executor addresses")
    sub = p.add_subparsers(dest="cmd")

    # list
    p_list = sub.add_parser("list", help="List latest link per path")

    # by path
    p_path = sub.add_parser("path", help="Show the latest deployed address for a given HD path")
    p_path.add_argument("--path", required=True, help="HD derivation path (e.g., m/44'/60'/0'/0/5)")

    # by address
    p_addr = sub.add_parser("address", help="Show the recorded path for a deployed address (if present in logs)")
    p_addr.add_argument("--address", required=True, help="Deployed contract address")

    # export
    p_exp = sub.add_parser("export", help="Export links to a JSON file")
    p_exp.add_argument("--out", required=True, help="Output JSON path (e.g., deployments/deployment_links.json)")

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        return 2

    if args.cmd == "list":
        links = scan_deploy_logs()
        latest = latest_links_by_path(links)
        if not latest:
            print("No successful deployment logs found under build/wallets/")
            return 0
        for path, link in sorted(latest.items(), key=lambda kv: kv[0]):
            print(f"{path} | {link.address} | deployer={link.deployer or '-'} | ts={link.generated_at or '-'} | log={link.log_file}")
        return 0

    if args.cmd == "path":
        link = find_by_path(args.path)
        if not link:
            print("Not found")
            return 1
        print(json.dumps(asdict(link), indent=2))
        return 0

    if args.cmd == "address":
        link = find_by_address(args.address)
        if not link:
            print("Not found")
            return 1
        print(json.dumps(asdict(link), indent=2))
        return 0

    if args.cmd == "export":
        out = export_links(Path(args.out))
        print(f"Wrote {out}")
        return 0

    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

