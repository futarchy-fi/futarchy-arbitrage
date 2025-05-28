# ──────────────────────────────────────────────────────────────────────────────
# File: arbitrage_cli.py  (new)
# A tiny dispatcher for helpers in helpers/*_*.py
# Usage:  python arbitrage_cli.py <helper_module> [<args>…]
# ──────────────────────────────────────────────────────────────────────────────

import runpy
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Ensure the project root (parent of "src") is in sys.path so that
# `src.*` imports work when this CLI is executed directly.
# This works regardless of whether the current working directory is the
# project root or a subdirectory.
# --------------------------------------------------------------------------- #

# Path of this file: <project_root>/src/arbitrage_bot/arbitrage_cli.py
# project_root = parents[2] from this file (…/src/arbitrage_bot → …/src → project_root)
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python arbitrage_cli.py <helper_module> [<args>…]")
        return

    mod_name_from_user = sys.argv[1]
    helper_args = sys.argv[2:]

    # Prepend "src." if not already present
    final_mod_name = mod_name_from_user
    if not mod_name_from_user.startswith("src."):
        final_mod_name = f"src.{mod_name_from_user}"
    
    # Execute the helper module
    original_argv = sys.argv[:]
    # The target module will see sys.argv as [module_name_it_was_invoked_as, ...helper_args]
    sys.argv = [final_mod_name] + helper_args 
    try:
        runpy.run_module(final_mod_name, run_name="__main__")
    except ModuleNotFoundError:
        print(f"Error: Helper module '{final_mod_name}' (from input '{mod_name_from_user}') not found.")
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
