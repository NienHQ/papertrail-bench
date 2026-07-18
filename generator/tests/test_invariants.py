"""Machine-checked invariants from docs/ground-truth-schema.md section 9."""
from collections import defaultdict
from datetime import date, timedelta
from email import message_from_bytes
from email.policy import SMTP

from papertrail.corpus import write
from papertrail.render import render_eml
from papertrail.simulate import terms_days


def test_every_fact_has_canonical_evidence(corpus):
    rr = corpus.render_result
    for f in corpus.facts:
        occs = rr.evidence_index.get(("fact", f.fact_id), [])
        assert occs, f"fact {f.fact_id} ({f.entity} {f.relation}) has no evidence"


def test_span_integrity(corpus):
    for m in corpus.render_result.messages:
        for s in m.statements:
            start, end = s.span
            assert m.body[start:end] == s.text


def test_spans_survive_eml_roundtrip(corpus):
    world = corpus.sim.world
    docs_by_id = {d.doc_id: d for d in corpus.sim.documents}
    for m in corpus.render_result.messages:
        raw = render_eml(m, world, docs_by_id)
        parsed = message_from_bytes(raw, policy=SMTP)
        part = parsed.get_body(preferencelist=("plain",))
        decoded = part.get_content().replace("\r\n", "\n")
        assert decoded == m.body, m.message_id
        for s in m.statements:
            start, end = s.span
            assert decoded[start:end] == s.text


def test_version_chains(corpus):
    chains = defaultdict(list)
    for d in corpus.sim.documents:
        chains[d.root_id].append(d)
    events = {e.event_id: e for e in corpus.sim.events}
    for root, docs in chains.items():
        docs.sort(key=lambda d: d.version)
        assert [d.version for d in docs] == list(range(1, len(docs) + 1))
        assert docs[0].supersedes is None
        for prev, cur in zip(docs, docs[1:]):
            assert cur.supersedes == prev.doc_id
            assert (events[prev.created_event].event_time
                    <= events[cur.created_event].event_time)


def test_fact_ledger_intervals(corpus):
    by_key = defaultdict(list)
    for f in corpus.facts:
        by_key[(f.entity, f.relation)].append(f)
    for key, fs in by_key.items():
        fs.sort(key=lambda f: f.valid_from)
        open_facts = [f for f in fs if f.valid_to is None]
        assert len(open_facts) == 1, key
        for prev, cur in zip(fs, fs[1:]):
            assert prev.valid_to == cur.valid_from, key  # contiguous
    # superseded, never deleted: renegotiated entities keep both facts
    assert any(len(fs) > 1 for fs in by_key.values())


def test_alias_periods_non_overlapping(corpus):
    for p in corpus.sim.world.people:
        periods = sorted(p.addresses, key=lambda a: a.from_date)
        for prev, cur in zip(periods, periods[1:]):
            assert prev.to_date is not None and prev.to_date <= cur.from_date


def test_internal_consistency_invoice_due_dates(corpus):
    """Invoice due date == issue date + payment terms fact as-of issue."""
    from papertrail.facts import fact_as_of
    for d in corpus.sim.documents:
        if d.kind != "invoice":
            continue
        issue = date.fromisoformat(d.fields["issue_date"])
        f = fact_as_of(corpus.facts, d.party_id, "payment_terms", issue)
        assert f is not None
        assert d.fields["terms"] == f.value
        assert (date.fromisoformat(d.fields["due_date"])
                == issue + timedelta(days=terms_days(f.value)))


def test_dispute_consistency(corpus):
    """Schema doc section 4: credit_note resolutions reuse the credit-note
    machinery for exactly disputed_cents; withdrawn changes no amounts; a
    disputed invoice never also draws the independent random credit note."""
    events = corpus.sim.events
    disputes = {e.payload["invoice_ref"]: e for e in events
                if e.type == "INVOICE_DISPUTED"}
    resolutions = defaultdict(list)
    for e in events:
        if e.type == "DISPUTE_RESOLVED":
            resolutions[e.payload["invoice_ref"]].append(e)
    cns_by_invoice = defaultdict(list)
    for d in corpus.sim.documents:
        if d.kind == "credit_note":
            cns_by_invoice[d.fields["invoice_ref"]].append(d)
    payments = {e.payload["invoice_ref"]: e for e in events
                if e.type in ("PAYMENT_SENT", "PAYMENT_RECEIVED")}

    assert disputes, "corpus has no disputes; raise dispute_prob"
    for inv_ref, disp in disputes.items():
        res = resolutions[inv_ref]
        assert len(res) == 1, inv_ref
        r = res[0]
        d_disp, d_res = disp.event_time.date(), r.event_time.date()
        issue = date.fromisoformat(
            _docs_by_id(corpus)[inv_ref].fields["issue_date"])
        # 2 to 6 days after issue, clamped to year end
        assert timedelta(0) <= d_disp - issue <= timedelta(days=6)
        assert d_res >= d_disp
        cents = disp.payload["disputed_cents"]
        total = _docs_by_id(corpus)[inv_ref].fields["total_cents"]
        assert 1_000 <= cents <= total // 2
        cns = cns_by_invoice[inv_ref]
        if r.payload["resolution"] == "credit_note":
            assert [c.doc_id for c in cns] == [r.payload["credit_note_ref"]]
            assert cns[0].fields["amount_cents"] == cents
            assert payments[inv_ref].payload["amount_cents"] == total - cents
        else:
            assert r.payload["resolution"] == "withdrawn"
            assert cns == []  # no amounts changed
            assert payments[inv_ref].payload["amount_cents"] == total
    # both resolution kinds occur
    kinds = {r.payload["resolution"]
             for rs in resolutions.values() for r in rs}
    assert kinds == {"credit_note", "withdrawn"}


def _docs_by_id(corpus):
    return {d.doc_id: d for d in corpus.sim.documents}


def test_emls_parse_and_thread(corpus, tmp_path):
    write(corpus, tmp_path)
    world = corpus.sim.world
    docs_by_id = {d.doc_id: d for d in corpus.sim.documents}
    seen_mids = set()
    for m in corpus.render_result.messages:
        parsed = message_from_bytes(render_eml(m, world, docs_by_id), policy=SMTP)
        assert parsed["Message-ID"]
        seen_mids.add(parsed["Message-ID"])
        for ref in (parsed["References"] or "").split():
            assert ref in seen_mids, f"{m.message_id} references unknown {ref}"
        atts = [p.get_filename() for p in parsed.iter_attachments()]
        assert atts == [f"{d}.txt" for d in m.attachments]


def test_question_evidence_resolves(corpus):
    stmts = {(s.message_id, s.statement_id)
             for m in corpus.render_result.messages for s in m.statements}
    doc_fields = {(d.doc_id, f) for d in corpus.sim.documents for f in d.fields}
    for q in corpus.questions:
        if q.category == 6:
            # abstention: the evidence set is empty by definition
            assert q.evidence == []
            continue
        assert q.evidence
        for ev in q.evidence:
            if "message_id" in ev:
                assert (ev["message_id"], ev["statement_id"]) in stmts
            else:
                assert (ev["doc_id"], ev["field"]) in doc_fields
