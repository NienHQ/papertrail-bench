#!/usr/bin/env python3
"""CorpSim self-test: generate twice, assert determinism, and verify the judge
scores the answer key itself at 100%. Run from corpsim/:  python selftest.py
"""
import filecmp
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def run(args, **kw):
    subprocess.run([sys.executable] + args, cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, **kw)


def assert_identical(a, b):
    cmp = filecmp.dircmp(a, b)
    diffs = cmp.diff_files + cmp.left_only + cmp.right_only
    assert not diffs, f"nondeterministic output in {a}: {diffs[:5]}"
    for sub in cmp.common_dirs:
        assert_identical(os.path.join(a, sub), os.path.join(b, sub))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        out1, out2 = os.path.join(tmp, "a"), os.path.join(tmp, "b")
        run(["-m", "gen.main", "--out", out1])
        run(["-m", "gen.main", "--out", out2])
        assert_identical(out1, out2)
        print("determinism: OK (two runs byte-identical)")

        key_path = os.path.join(out1, "truth", "answers.json")
        with open(key_path) as f:
            key = json.load(f)
        assert len(key) >= 40, f"only {len(key)} questions generated"
        sub_path = os.path.join(tmp, "perfect.json")
        with open(sub_path, "w") as f:
            json.dump({q["id"]: q["answer"] for q in key}, f)
        out = subprocess.run(
            [sys.executable, "judge.py", sub_path, "--answers", key_path],
            cwd=HERE, check=True, capture_output=True, text=True).stdout
        assert "(100.0%)" in out, f"judge self-test not 100%:\n{out}"
        print(f"judge self-test: OK ({len(key)} questions, 100.0%)")

        docs = os.path.join(out1, "docs")
        n = sum(len(fs) for _, _, fs in os.walk(docs))
        assert n > 4000, f"only {n} document files"
        print(f"corpus size: OK ({n} document files)")
    print("ALL OK")


if __name__ == "__main__":
    main()
