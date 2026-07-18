import dataclasses

import pytest

from papertrail.corpus import Corpus, build
from papertrail.simulate import HARD_PRESET, Config

CFG = Config(seed=7, months=6, n_vendors=4, n_customers=3, n_questions=30)
# The hard preset variant of the same world config: every G3 realism screw
# on. Every invariant test runs against BOTH via the parametrized fixture.
HARD_CFG = dataclasses.replace(CFG, **HARD_PRESET)


@pytest.fixture(scope="session", params=["clean", "hard"])
def corpus(request) -> Corpus:
    return build(CFG if request.param == "clean" else HARD_CFG)


@pytest.fixture(scope="session")
def hard_corpus() -> Corpus:
    return build(HARD_CFG)


@pytest.fixture(scope="session")
def default_corpus() -> Corpus:
    return build(Config())  # seed 42, default category_counts
