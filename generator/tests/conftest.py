import pytest

from papertrail.corpus import Corpus, build
from papertrail.simulate import Config

CFG = Config(seed=7, months=6, n_vendors=4, n_customers=3, n_questions=30)


@pytest.fixture(scope="session")
def corpus() -> Corpus:
    return build(CFG)
