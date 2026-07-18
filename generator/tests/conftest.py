import dataclasses
import os
import time

import pytest

from papertrail.corpus import Corpus, build
from papertrail.simulate import BENCH_PRESET, HARD_PRESET, Config

CFG = Config(seed=7, months=6, n_vendors=4, n_customers=3, n_questions=30)
# The hard preset variant of the same world config: every G3 realism screw
# on. Every invariant test runs against BOTH via the parametrized fixture.
HARD_CFG = dataclasses.replace(CFG, **HARD_PRESET)
# G4 multi-year fixture: two years (one full year plus six months), clean.
# Runs through the entire invariant suite via the same fixture.
MULTI_CFG = Config(seed=7, years=2, months=6, n_vendors=3, n_customers=2,
                   n_questions=30)
# G4 publication preset. Building it takes a few seconds, so the fixture
# param (and the smoke test in test_g4.py) is gated behind an env flag;
# normal pytest runs stay fast.
BENCH_CFG = Config(seed=42, **BENCH_PRESET)
BENCH_ENABLED = os.environ.get("PAPERTRAIL_BENCH_PRESET") == "1"

_CONFIGS = {"clean": CFG, "hard": HARD_CFG, "multiyear": MULTI_CFG,
            "bench": BENCH_CFG}
_CORPORA: dict[str, Corpus] = {}
_BUILD_SECONDS: dict[str, float] = {}


def corpus_for(name: str) -> Corpus:
    """Session-cached build so the parametrized invariant suite and the
    targeted G4 tests share one corpus per config."""
    if name not in _CORPORA:
        t0 = time.monotonic()
        _CORPORA[name] = build(_CONFIGS[name])
        _BUILD_SECONDS[name] = time.monotonic() - t0
    return _CORPORA[name]


def build_seconds(name: str) -> float:
    corpus_for(name)
    return _BUILD_SECONDS[name]


@pytest.fixture(scope="session",
                params=["clean", "hard", "multiyear"]
                + (["bench"] if BENCH_ENABLED else []))
def corpus(request) -> Corpus:
    return corpus_for(request.param)


@pytest.fixture(scope="session")
def hard_corpus() -> Corpus:
    return corpus_for("hard")


@pytest.fixture(scope="session")
def multiyear_corpus() -> Corpus:
    return corpus_for("multiyear")


@pytest.fixture(scope="session")
def default_corpus() -> Corpus:
    return build(Config())  # seed 42, default category_counts
