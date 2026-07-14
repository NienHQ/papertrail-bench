"""CLI: python -m papertrail generate --seed 42 --out corpus/"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .corpus import build, write
from .simulate import Config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="papertrail")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="generate a corpus")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--out", type=Path, required=True)
    g.add_argument("--months", type=int, default=12)
    g.add_argument("--vendors", type=int, default=8)
    g.add_argument("--customers", type=int, default=6)
    g.add_argument("--questions", type=int, default=50)
    args = ap.parse_args(argv)

    cfg = Config(seed=args.seed, months=args.months, n_vendors=args.vendors,
                 n_customers=args.customers, n_questions=args.questions)
    manifest = write(build(cfg), args.out)
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
