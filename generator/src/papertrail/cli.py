"""CLI: python -m papertrail generate --seed 42 --out corpus/"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .corpus import build, write
from .simulate import HARD_PRESET, Config

_SCREW_DEFAULTS: dict = {"truncate_references": False, "quoted_replies": False,
                         "near_dup_invoices": 0.0, "format_drift": False}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="papertrail")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="generate a corpus")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--out", type=Path, required=True)
    g.add_argument("--months", type=int, default=12)
    g.add_argument("--vendors", type=int, default=8)
    g.add_argument("--customers", type=int, default=6)
    g.add_argument("--questions", type=int, default=None,
                   help="deprecated: flat total, split evenly across "
                        "shipped categories")
    g.add_argument("--category-counts", type=str, default=None,
                   help="per-category counts, e.g. 1=16,2=16,3=16,4=16,6=16")
    # G3 realism screws: all off unless set; --preset hard turns every
    # screw on and explicit per-flag values override the preset.
    g.add_argument("--preset", choices=["hard"], default=None,
                   help="hard: all realism screws on "
                        "(near-dup fraction 0.15)")
    g.add_argument("--truncate-references",
                   action=argparse.BooleanOptionalAction, default=None,
                   help="References keeps last 2; every 5th reply drops "
                        "threading headers")
    g.add_argument("--quoted-replies",
                   action=argparse.BooleanOptionalAction, default=None,
                   help="replies quote the previous body; quoted evidence "
                        "rows are emitted")
    g.add_argument("--near-dup-invoices", type=float, default=None,
                   metavar="FRACTION",
                   help="fraction of vendor invoices re-issued as voided "
                        "near-duplicates")
    g.add_argument("--format-drift",
                   action=argparse.BooleanOptionalAction, default=None,
                   help="money prose drifts between three formats")
    args = ap.parse_args(argv)

    extra: dict = {}
    if args.category_counts:
        extra["category_counts"] = {
            int(k): int(v) for k, v in
            (pair.split("=") for pair in args.category_counts.split(","))}
    if args.questions is not None:
        extra["n_questions"] = args.questions
    screws = dict(HARD_PRESET) if args.preset == "hard" \
        else dict(_SCREW_DEFAULTS)
    for name in _SCREW_DEFAULTS:
        value = getattr(args, name)
        if value is not None:
            screws[name] = value
    extra.update(screws)

    cfg = Config(seed=args.seed, months=args.months, n_vendors=args.vendors,
                 n_customers=args.customers, **extra)
    manifest = write(build(cfg), args.out)
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
