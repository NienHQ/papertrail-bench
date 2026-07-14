"""Invariant 1: same seed => byte-identical corpus."""
from papertrail.corpus import build, write
from papertrail.simulate import Config

from conftest import CFG


def test_same_seed_same_bytes(tmp_path):
    m1 = write(build(CFG), tmp_path / "a")
    m2 = write(build(CFG), tmp_path / "b")
    assert m1["files"] == m2["files"]
    assert m1["counts"] == m2["counts"]


def test_different_seed_different_corpus(tmp_path):
    m1 = write(build(CFG), tmp_path / "a")
    other = Config(**{**CFG.__dict__, "seed": CFG.seed + 1})
    m2 = write(build(other), tmp_path / "b")
    assert m1["files"] != m2["files"]
