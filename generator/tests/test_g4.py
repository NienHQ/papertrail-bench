"""G4 multi-year corpus: per-year numbering, cross-year chains and
spillover, and the bench publication preset. The multi-year fixture also
runs through every invariant test via the parametrized ``corpus`` fixture
in conftest; the frozen seed-42 manifest hash in test_g3 pins years=1
byte identity."""
import json
from collections import Counter, defaultdict
from datetime import date

import pytest

from papertrail.cli import main as cli_main
from papertrail.corpus import build, write
from papertrail.simulate import BENCH_PRESET, Config

from conftest import (BENCH_ENABLED, MULTI_CFG, build_seconds, corpus_for)


def _series_numbers(docs, prefix):
    return sorted(int(d.root_id.removeprefix(prefix)) for d in docs
                  if d.version == 1 and d.root_id.startswith(prefix))


def test_per_year_numbering(multiyear_corpus):
    """PO/INV/CN series restart per year: each year's series is contiguous
    from 0001 under that year's prefix, and ids never collide corpus-wide."""
    docs = multiyear_corpus.sim.documents
    cfg = multiyear_corpus.sim.config
    ids = [d.doc_id for d in docs]
    assert len(ids) == len(set(ids))
    for kind, tag in (("po", "PO"), ("invoice", "INV"), ("credit_note", "CN")):
        of_kind = [d for d in docs if d.kind == kind]
        seen_any = False
        for y in range(cfg.year, cfg.year + cfg.years):
            ns = _series_numbers(of_kind, f"{tag}-{y}-")
            if ns:
                seen_any = True
                assert ns == list(range(1, len(ns) + 1)), (tag, y)
        assert seen_any, kind
    # a year-2 PO series exists and restarts at 0001
    y2 = cfg.year + 1
    assert any(d.root_id == f"PO-{y2}-0001" for d in docs)
    assert any(d.root_id == f"INV-{y2}-0001" for d in docs)


def test_po_roots_issued_in_their_series_year(multiyear_corpus):
    """A PO root's prefix year always matches its issue year (only
    amendments, invoices, and payments spill across the boundary)."""
    for d in multiyear_corpus.sim.documents:
        if d.kind == "po" and d.version == 1:
            assert d.root_id.split("-")[1] == str(d.issued_date.year)


def test_lease_chain_continues_across_years():
    """The lease keeps ONE root chain: later-year reviews append versions
    to the year-1 root instead of opening a new series. The review is a
    per-year chance, so search a few seeds deterministically for one that
    amends in year 2 (the final year must reach the review month)."""
    hit = None
    for seed in range(7, 27):
        c = build(Config(seed=seed, years=2, months=12, n_vendors=2,
                         n_customers=1, n_questions=6))
        leases = sorted((d for d in c.sim.documents if d.kind == "lease"),
                        key=lambda d: d.version)
        if any(d.issued_date.year == 2025 for d in leases):
            hit = (c, leases)
            break
    assert hit is not None, "no seed in range produced a year-2 review"
    c, leases = hit
    assert len({d.root_id for d in leases}) == 1
    assert leases[0].root_id == "LEASE-2024-001"
    assert [d.version for d in leases] == list(range(1, len(leases) + 1))
    for prev, cur in zip(leases, leases[1:]):
        assert cur.supersedes == prev.doc_id
        assert cur.issued_date > prev.issued_date
    # rent facts follow the whole chain
    rent_facts = [f for f in c.facts if f.relation == "monthly_rent"]
    assert len(rent_facts) == len(leases)
    assert any(f.valid_from.year == 2025 for f in rent_facts)


def test_cross_year_spillover(multiyear_corpus):
    """An invoice issued in December of year 1 is paid in January (or
    later) of year 2: the trading loop clamps to the CORPUS end, not the
    scheduling year's end."""
    c = multiyear_corpus
    start = c.sim.config.year
    pays = {e.payload["invoice_ref"]: e for e in c.sim.events
            if e.type in ("PAYMENT_SENT", "PAYMENT_RECEIVED")}
    spilled = [d for d in c.sim.documents
               if d.kind == "invoice"
               and not d.fields.get("voided_by_correction")
               and d.issued_date.year == start and d.issued_date.month == 12
               and pays[d.doc_id].event_time.year == start + 1]
    assert spilled, "no December year-1 invoice paid in year 2"
    # due dates stay consistent across the boundary (also enforced by the
    # invariant suite): terms as-of issue plus terms days
    for d in spilled:
        assert date.fromisoformat(d.fields["due_date"]).year == start + 1


def test_multiyear_supersession_chain_of_three():
    """A party renegotiated in year 1 AND year 2 carries a 3-interval
    payment-terms chain with boundaries in different years. Per-year
    renegotiation draws make this seed-dependent, so search a few seeds
    deterministically."""
    for seed in range(7, 40):
        c = build(Config(seed=seed, years=2, months=12, n_vendors=3,
                         n_customers=2, n_questions=6))
        by_entity = defaultdict(list)
        for f in c.facts:
            if f.relation == "payment_terms":
                by_entity[f.entity].append(f)
        for fs in by_entity.values():
            fs.sort(key=lambda f: f.valid_from)
            if len(fs) >= 3:
                boundaries = [f.valid_to for f in fs if f.valid_to]
                if len({b.year for b in boundaries}) >= 2:
                    for prev, cur in zip(fs, fs[1:]):
                        assert prev.valid_to == cur.valid_from
                    return
    raise AssertionError("no seed produced a cross-year 3-interval chain")


def test_terms_as_of_straddles_year2_renegotiation():
    """Category 3 draws boundaries from ALL years: with enough category-3
    budget, at least one terms_as_of pair straddles a year-2 boundary."""
    c = build(Config(seed=MULTI_CFG.seed, years=2, months=6, n_vendors=3,
                     n_customers=2,
                     category_counts={1: 2, 2: 2, 3: 20, 4: 2, 5: 2, 6: 2}))
    start = c.sim.config.year
    year2_boundaries = sorted(
        {(f.entity, f.valid_to) for f in c.facts
         if f.relation == "payment_terms" and f.valid_to is not None
         and f.valid_to.year == start + 1})
    assert year2_boundaries, "fixture drew no year-2 renegotiation"
    straddled = False
    for entity, b in year2_boundaries:
        as_ofs = [date.fromisoformat(q.params["as_of"])
                  for q in c.questions
                  if q.template == "terms_as_of"
                  and q.params["entity"] == entity]
        if any(a < b for a in as_ofs) and any(a >= b for a in as_ofs):
            straddled = True
    assert straddled


def test_multiyear_deterministic(tmp_path, multiyear_corpus):
    """Same multi-year config, same bytes; manifest records years."""
    m1 = write(multiyear_corpus, tmp_path / "a")
    m2 = write(build(MULTI_CFG), tmp_path / "b")
    assert m1["files"] == m2["files"]
    assert m1["counts"] == m2["counts"]
    assert m1["config"]["years"] == 2
    assert (tmp_path / "a" / "manifest.json").read_bytes() == \
        (tmp_path / "b" / "manifest.json").read_bytes()


def test_cli_years_and_bench_flag_composition(tmp_path):
    """--years is a plain flag; --preset bench composes with explicit
    overrides (explicit flags win, preset fills the rest)."""
    assert cli_main(["generate", "--seed", "5", "--years", "2",
                     "--months", "3", "--vendors", "2", "--customers", "1",
                     "--questions", "6",
                     "--out", str(tmp_path / "plain")]) == 0
    cfg = json.loads((tmp_path / "plain" / "manifest.json").read_text())["config"]
    assert cfg["years"] == 2 and cfg["months"] == 3

    assert cli_main(["generate", "--seed", "5", "--preset", "bench",
                     "--years", "1", "--months", "3",
                     "--vendors", "2", "--customers", "1",
                     "--questions", "6",
                     "--out", str(tmp_path / "bench_small")]) == 0
    cfg = json.loads(
        (tmp_path / "bench_small" / "manifest.json").read_text())["config"]
    assert "years" not in cfg                      # explicit 1 wins, omitted
    assert cfg["n_vendors"] == 2                   # explicit wins
    assert cfg["truncate_references"] is True      # from the preset
    assert cfg["near_dup_invoices"] == 0.15        # from the preset
    assert cfg["pos_per_vendor_month"] == [4, 6]   # from the preset
    assert cfg["n_questions"] == 6                 # explicit wins over counts


@pytest.mark.skipif(not BENCH_ENABLED,
                    reason="set PAPERTRAIL_BENCH_PRESET=1 to run the full "
                           "bench preset build")
def test_bench_preset_smoke(tmp_path):
    """Publication preset: ~15k messages, 300+ questions, generated in
    under two minutes. The same cached corpus also runs through the whole
    invariant suite via the gated 'bench' fixture param."""
    corpus = corpus_for("bench")
    assert build_seconds("bench") < 120
    manifest = write(corpus, tmp_path / "bench")
    counts = manifest["counts"]
    assert 12_000 <= counts["messages"] <= 18_000
    assert counts["questions"] >= 300
    by_cat = Counter(q.category for q in corpus.questions)
    assert set(by_cat) == {1, 2, 3, 4, 5, 6}
    assert manifest["config"]["years"] == 3
    assert manifest["config"]["n_vendors"] == 14
    assert manifest["config"]["n_customers"] == 10
    # id series span all three years
    roots = {d.root_id for d in corpus.sim.documents}
    for y in (2024, 2025, 2026):
        assert f"PO-{y}-0001" in roots
        assert f"INV-{y}-0001" in roots
