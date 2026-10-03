"""
main.py
=======
One entry point: **natural language in, recommended purchase JSON out.**

    python main.py "Find me a Kensington wireless mouse under $800 total."

Two components sit underneath:

1. **Shopping agent** (``intent_to_purchase.py``) — parses the request, enforces
   the user's mandate, and ranks up to three candidate purchases.
2. **Financial Firewall** (``../BackEnd-Supervisor``) — deterministic
   authorization. No language model is in this path.

This module joins them and prints the answer. Stdout carries the JSON and nothing
else, so the output can be piped straight into another program; progress notes go
to stderr.

Exit codes: ``0`` success, ``2`` bad usage or the firewall could not be imported.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import firewall_bridge  # noqa: E402  (path set up above)
from intent_to_purchase import load_config  # noqa: E402

DEFAULT_REQUEST = "Find me a Kensington wireless mouse under $800 total."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description=(
            "Shopping agent + Financial Firewall. Takes a natural-language "
            "request and prints the recommended purchases as JSON."
        ),
    )
    parser.add_argument(
        "requests", nargs="*",
        help="One or more shopping requests in plain English.",
    )
    parser.add_argument(
        "--options", type=int, default=3,
        help="How many candidate purchases the agent ranks (default 3).",
    )
    parser.add_argument(
        "--keep", type=int, default=2,
        help="How many authorized recommendations to return (default 2).",
    )
    # Firewall authorization limits. A plan's own total is what gets checked.
    parser.add_argument("--max-per-transaction",
                        default=firewall_bridge.DEFAULT_MAX_PER_TRANSACTION)
    parser.add_argument("--max-daily-spend",
                        default=firewall_bridge.DEFAULT_MAX_DAILY_SPEND)
    parser.add_argument("--confirmation-threshold",
                        default=firewall_bridge.DEFAULT_CONFIRMATION_THRESHOLD)
    parser.add_argument("--daily-spent", default="0.00")
    parser.add_argument("--offline", action="store_true",
                        help="Force the deterministic local model; never call an API.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress progress notes on stderr.")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    requests = args.requests or [DEFAULT_REQUEST]

    try:
        final, meta = firewall_bridge.run(
            requests,
            options=args.options,
            keep=args.keep,
            config=load_config(),
            stream=None,          # progress notes are handled below
            max_per_transaction=args.max_per_transaction,
            max_daily_spend=args.max_daily_spend,
            confirmation_threshold=args.confirmation_threshold,
            daily_spent=args.daily_spent,
            progress=False,       # stdout is reserved for the JSON below
            offline=args.offline,
        )
    except firewall_bridge.BridgeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    # The answer. Nothing else is ever written to stdout.
    print(json.dumps(final, indent=2, ensure_ascii=False))

    if not args.quiet:
        recommended = final["grand_total"]["items_selected"]
        print(
            f"recommended {recommended} item(s) for {len(requests)} request(s); "
            f"agent report kept at {meta.get('report_path')}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
