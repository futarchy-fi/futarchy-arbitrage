# ──────────────────────────────────────────────────────────────────────────────
# File: arbitrage_cli.py  (new)
# A tiny dispatcher for helpers in helpers/*_*.py
# Usage:  python arbitrage_cli.py <helper_module> [<args>…]
# ──────────────────────────────────────────────────────────────────────────────

import runpy
import sys


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python arbitrage_cli.py <helper_module> [<args>…]")
        return

    mod_name = sys.argv[1]
    helper_args = sys.argv[2:]

    # Execute the helper module as if run via "python -m helpers.<module>"
    original_argv = sys.argv[:]
    sys.argv = [mod_name] + helper_args
    try:
        runpy.run_module(mod_name, run_name="__main__")
    except ModuleNotFoundError:
        print(f"Error: Helper module '{mod_name}' not found.")
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
