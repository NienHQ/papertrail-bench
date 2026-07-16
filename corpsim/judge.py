#!/usr/bin/env python3
"""CorpSim judge: score an AI system's answers against the held-out key.

Usage:
    python judge.py path/to/submission.json [--answers out/truth/answers.json]

Submission format (produced by the system under test, which must only ever see
out/docs/ and out/benchmark/questions.json):

    {"Q001": 123456.78, "Q002": ["Vendor A", "Vendor B"], "Q003": "PO-2024-0012", ...}

Scoring:
    number  — correct if within tolerance_pct of the key (default 0.1%, plus
              1 cent absolute slack); tolerance_pct 0 means exact.
    string  — case/whitespace-insensitive exact match.
    list    — set F1 against the key (normalized items); credit = F1.
Each question is worth 1 point; the report breaks scores down by category.
"""
import argparse
import json
import re
import sys


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def score_number(key, sub, tol_pct):
    try:
        v = float(str(sub).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return 0.0
    k = float(key)
    slack = max(abs(k) * tol_pct / 100.0, 0.01 if tol_pct > 0 else 0.0)
    return 1.0 if abs(v - k) <= slack else 0.0


def score_list(key, sub):
    if not isinstance(sub, (list, tuple)):
        if isinstance(sub, str):
            sub = [x for x in re.split(r"[,;\n]", sub) if x.strip()]
        else:
            return 0.0
    kset, sset = {norm(x) for x in key}, {norm(x) for x in sub}
    if not kset and not sset:
        return 1.0
    if not sset:
        return 0.0
    tp = len(kset & sset)
    prec = tp / len(sset)
    rec = tp / len(kset) if kset else 0.0
    return 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("submission")
    ap.add_argument("--answers", default="out/truth/answers.json")
    args = ap.parse_args()
    with open(args.answers) as f:
        key = {q["id"]: q for q in json.load(f)}
    with open(args.submission) as f:
        sub = json.load(f)

    by_cat, rows = {}, []
    for qid, q in sorted(key.items()):
        given = sub.get(qid)
        if given is None:
            pts = 0.0
        elif q["answer_type"] == "number":
            pts = score_number(q["answer"], given, q.get("tolerance_pct", 0.1))
        elif q["answer_type"] == "list":
            pts = score_list(q["answer"], given)
        else:
            pts = 1.0 if norm(given) == norm(q["answer"]) else 0.0
        by_cat.setdefault(q["category"], []).append(pts)
        rows.append((qid, q["category"], pts, given, q["answer"]))

    total = sum(p for _, _, p, _, _ in rows)
    print(f"\nCorpSim judge — {len(rows)} questions")
    print("=" * 60)
    for cat in sorted(by_cat):
        pts = by_cat[cat]
        print(f"  {cat:<18} {sum(pts):6.2f} / {len(pts)}")
    print("=" * 60)
    pct = 100 * total / len(rows)
    print(f"  TOTAL              {total:6.2f} / {len(rows)}   ({pct:.1f}%)\n")
    misses = [r for r in rows if r[2] < 1.0]
    if misses:
        print("Missed or partial:")
        for qid, cat, pts, given, ans in misses:
            print(f"  {qid} [{cat}] scored {pts:.2f}")
            print(f"       submitted: {json.dumps(given)[:100]}")
            print(f"       expected : {json.dumps(ans)[:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
