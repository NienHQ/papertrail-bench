"""CLI: python -m papertrail generate --seed 42 --out corpus/"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .corpus import build, write
from .simulate import BENCH_PRESET, HARD_PRESET, Config

_SCREW_DEFAULTS: dict = {"truncate_references": False, "quoted_replies": False,
                         "near_dup_invoices": 0.0, "format_drift": False}
# Scale knobs a preset may set; explicit CLI values win over the preset,
# the preset wins over these fallbacks.
_SCALE_DEFAULTS: dict = {"years": 1, "months": 12,
                         "n_vendors": 8, "n_customers": 6}

_PRESETS: dict[str, dict] = {"hard": HARD_PRESET, "bench": BENCH_PRESET}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="papertrail")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="generate a corpus")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--out", type=Path, required=True)
    g.add_argument("--year", type=int, default=2024,
                   help="start year of the corpus (default 2024)")
    g.add_argument("--years", type=int, default=None,
                   help="number of simulated years (default 1). Non-final "
                        "years always run 12 months; --months applies to "
                        "the FINAL year, so --months 6 --years 3 means two "
                        "full years plus six months")
    g.add_argument("--months", type=int, default=None,
                   help="months simulated in the final year (default 12)")
    g.add_argument("--vendors", type=int, default=None)
    g.add_argument("--customers", type=int, default=None)
    g.add_argument("--questions", type=int, default=None,
                   help="deprecated: flat total, split evenly across "
                        "shipped categories")
    g.add_argument("--category-counts", type=str, default=None,
                   help="per-category counts, e.g. 1=16,2=16,3=16,4=16,6=16")
    # Presets: hard turns every G3 realism screw on; bench is the
    # publication configuration (3 years, larger world, all screws on,
    # 55 questions per category). Explicit flags override preset values.
    g.add_argument("--preset", choices=["hard", "bench"], default=None,
                   help="hard: all realism screws on (near-dup fraction "
                        "0.15); bench: hard plus years 3, vendors 14, "
                        "customers 10, 55 questions per category "
                        "(see docs/presets.md)")
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

    preset = dict(_PRESETS[args.preset]) if args.preset else {}

    extra: dict = {}
    # scale: explicit flag > preset > default
    flag_names = {"years": "years", "months": "months",
                  "n_vendors": "vendors", "n_customers": "customers"}
    for name, default in _SCALE_DEFAULTS.items():
        value = getattr(args, flag_names[name])
        extra[name] = value if value is not None \
            else preset.get(name, default)
    for name in ("pos_per_vendor_month", "sales_per_customer_month"):
        if name in preset:
            extra[name] = preset[name]
    # questions: explicit counts > deprecated flat total > preset counts
    if args.category_counts:
        extra["category_counts"] = {
            int(k): int(v) for k, v in
            (pair.split("=") for pair in args.category_counts.split(","))}
    elif args.questions is not None:
        extra["n_questions"] = args.questions
    elif "category_counts" in preset:
        extra["category_counts"] = dict(preset["category_counts"])
    # screws: explicit flag > preset > off
    for name, off in _SCREW_DEFAULTS.items():
        value = getattr(args, name)
        if value is None:
            value = preset.get(name, off)
        extra[name] = value

    cfg = Config(seed=args.seed, year=args.year, **extra)
    manifest = write(build(cfg), args.out)
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
