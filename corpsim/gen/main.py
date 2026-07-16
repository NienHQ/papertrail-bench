"""Generate the whole testbench:  python -m gen.main [--seed N] [--out DIR]"""
import argparse
import json
import os
import random
import shutil
from .core import SEED, fmt_money
from .world import build_world
from .simulate import simulate
from .render import render_all
from .truth import build_db, build_questions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "out"))
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    docs = os.path.join(out, "docs")
    truth_dir = os.path.join(out, "truth")
    bench = os.path.join(out, "benchmark")
    if os.path.exists(out):
        shutil.rmtree(out)
    for d in (docs, truth_dir, bench):
        os.makedirs(d)

    rng = random.Random(args.seed)
    world = build_world(rng)
    simulate(world, rng)
    render_all(world, docs)
    build_db(world, os.path.join(truth_dir, "corpsim.db"))
    questions = build_questions(world, rng)
    with open(os.path.join(bench, "questions.json"), "w") as f:
        json.dump([{k: q[k] for k in ("id", "category", "question", "answer_type")}
                   for q in questions], f, indent=1)
    with open(os.path.join(truth_dir, "answers.json"), "w") as f:
        json.dump(questions, f, indent=1)

    n_files = sum(len(fs) for _, _, fs in os.walk(docs))
    closing = world["bank_txns"][-1]["balance"]
    print(f"seed {args.seed} -> {out}")
    print(f"  employees          {len(world['employees'])}")
    print(f"  purchase orders    {len(world['pos'])}")
    print(f"  vendor invoices    {len(world['vendor_invoices'])}")
    print(f"  customer invoices  {len(world['customer_invoices'])}")
    print(f"  timesheets         {len(world['timesheets'])}")
    print(f"  payslips           {sum(len(r['slips']) for r in world['payroll_runs'])}")
    print(f"  bank transactions  {len(world['bank_txns'])}")
    print(f"  emails             {len(world['emails'])}")
    print(f"  anomalies planted  {len(world['anomalies'])}")
    print(f"  benchmark questions {len(questions)}")
    print(f"  document files     {n_files}")
    print(f"  closing balance    {fmt_money(closing)}")
    total_rev = sum(i['amount'] for i in world['customer_invoices'])
    print(f"  revenue invoiced   {fmt_money(total_rev)}")


if __name__ == "__main__":
    main()
