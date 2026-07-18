"""Invariant 3: every question's answer recomputes from ground truth alone."""
from datetime import date

from papertrail.facts import fact_as_of


def _docs_by_id(corpus):
    return {d.doc_id: d for d in corpus.sim.documents}


def test_question_counts_and_categories(corpus):
    cats = {q.category for q in corpus.questions}
    assert cats == {1, 2, 3, 4, 5, 6}
    assert len(corpus.questions) >= corpus.sim.config.n_questions * 0.8


def test_deprecated_n_questions_splits_evenly():
    from papertrail.simulate import Config
    assert Config(n_questions=30).resolved_category_counts() == \
        {1: 5, 2: 5, 3: 5, 4: 5, 5: 5, 6: 5}
    assert Config(n_questions=32).resolved_category_counts() == \
        {1: 6, 2: 6, 3: 5, 4: 5, 5: 5, 6: 5}
    assert Config().resolved_category_counts() == \
        {1: 16, 2: 16, 3: 16, 4: 16, 5: 16, 6: 16}


def test_answers_recompute(corpus):
    docs = _docs_by_id(corpus)
    all_docs = corpus.sim.documents
    for q in corpus.questions:
        a = q.answer
        if q.template == "invoice_total":
            assert a["value"]["amount_cents"] == \
                docs[q.params["doc_id"]].fields["total_cents"]
        elif q.template == "invoice_due_date":
            assert a["value"] == docs[q.params["doc_id"]].fields["due_date"]
        elif q.template == "invoice_po_ref":
            assert a["value"] == docs[q.params["doc_id"]].fields["po_ref"]
        elif q.template == "credit_note_amount":
            assert a["value"]["amount_cents"] == \
                docs[q.params["doc_id"]].fields["amount_cents"]
        elif q.template == "amendment_chain":
            chain = sorted((d for d in all_docs
                            if d.root_id == q.params["root_id"]),
                           key=lambda d: d.version)
            assert a["value"] == [d.doc_id for d in chain]
            assert len(a["value"]) >= 2
        elif q.template == "amendment_count":
            n = sum(1 for d in all_docs if d.root_id == q.params["root_id"]) - 1
            assert a["value"] == n >= 1
        elif q.template == "final_quantity":
            final = max((d for d in all_docs
                         if d.root_id == q.params["root_id"]),
                        key=lambda d: d.version)
            assert a["value"] == final.fields["qty"]
        elif q.template in ("terms_as_of", "rent_as_of"):
            relation = "payment_terms" if q.template == "terms_as_of" \
                else "monthly_rent"
            f = fact_as_of(corpus.facts, q.params["entity"], relation,
                           date.fromisoformat(q.params["as_of"]))
            assert f is not None and f.fact_id == q.params["fact_id"]
            expected = f.value if q.template == "terms_as_of" \
                else {"amount_cents": f.value, "currency": "USD"}
            assert a["value"] == expected
        elif q.template in ("disputed_total", "disputed_count",
                            "disputed_list"):
            evs = _vendor_disputes(corpus, q.params["vendor"])
            assert evs, q.question_id
            if q.template == "disputed_total":
                assert a["value"]["amount_cents"] == \
                    sum(e.payload["disputed_cents"] for e in evs)
            elif q.template == "disputed_count":
                assert a["value"] == len(evs)
            else:
                assert a["value"] == [e.payload["invoice_ref"] for e in evs]
        elif q.template == "person_po_count":
            person = _person(corpus, q.params["person_id"])
            addrs = {ap.address for ap in person.addresses}
            n = 0
            for m in corpus.render_result.messages:
                if not any(addr in addrs for _, addr in m.to):
                    continue
                n += sum(1 for doc_id in m.attachments
                         if docs[doc_id].kind == "po"
                         and docs[doc_id].version == 1)
            assert a["value"] == n >= 1
        elif q.template == "person_invoices_list":
            person = _person(corpus, q.params["person_id"])
            addrs = {ap.address for ap in person.addresses}
            got = [doc_id for m in corpus.render_result.messages
                   if m.from_address in addrs
                   for doc_id in m.attachments
                   if docs[doc_id].kind == "invoice"]
            assert a["value"] == got
            assert len(got) >= 1
        elif q.template == "person_address_at":
            person = _person(corpus, q.params["person_id"])
            cands = [ap for ap in person.addresses
                     if person.party_on(ap.from_date) == q.params["party_id"]]
            assert len(cands) == 1
            assert a["value"] == cands[0].address
        elif q.template in ("nonexistent_invoice_total",
                            "nonexistent_vendor_terms",
                            "nonexistent_po_chain"):
            assert a == {"type": "abstain", "value": None}
        else:
            raise AssertionError(f"untested template {q.template}")


def _person(corpus, person_id):
    return next(p for p in corpus.sim.world.people
                if p.person_id == person_id)


def _vendor_disputes(corpus, vendor):
    """Independent recompute: sorted event-log scan."""
    evs = [e for e in corpus.sim.events if e.type == "INVOICE_DISPUTED"
           and e.counterparty == vendor]
    assert evs == sorted(evs, key=lambda e: (e.event_time, e.event_id))
    return evs


def test_dispute_aggregation_evidence_covers_every_event(corpus):
    """Category 4 evidence = the canonical dispute statement of every
    contributing INVOICE_DISPUTED event."""
    stmt_targets = {}
    for m in corpus.render_result.messages:
        for s in m.statements:
            stmt_targets[(s.message_id, s.statement_id)] = s.targets
    q4 = [q for q in corpus.questions if q.category == 4]
    assert q4
    for q in q4:
        evs = _vendor_disputes(corpus, q.params["vendor"])
        cited_events = set()
        for ref in q.evidence:
            for t in stmt_targets[(ref["message_id"], ref["statement_id"])]:
                if "event" in t:
                    cited_events.add(t["event"])
        assert cited_events == {e.event_id for e in evs}


def test_abstention_ids_provably_absent(corpus):
    doc_ids = {d.doc_id for d in corpus.sim.documents}
    root_ids = {d.root_id for d in corpus.sim.documents}
    party_names = {p.name for p in corpus.sim.world.parties}
    q6 = [q for q in corpus.questions if q.category == 6]
    assert q6
    templates = {q.template for q in q6}
    assert templates == {"nonexistent_invoice_total",
                        "nonexistent_vendor_terms", "nonexistent_po_chain"}
    for q in q6:
        assert q.evidence == []
        if "missing_id" in q.params:
            assert q.params["missing_id"] not in doc_ids
            assert q.params["missing_id"] not in root_ids
            assert q.params["missing_id"] in q.text
        else:
            assert q.params["missing_name"] not in party_names
            assert q.params["missing_name"] in q.text


def test_default_config_emits_15_plus_per_category(default_corpus):
    """G1/G2 done-when: default config, seed 42, >= 15 questions in each of
    categories 1 to 6."""
    from collections import Counter
    by_cat = Counter(q.category for q in default_corpus.questions)
    assert set(by_cat) == {1, 2, 3, 4, 5, 6}
    for cat in (1, 2, 3, 4, 5, 6):
        assert by_cat[cat] >= 15, (cat, by_cat)


def test_category5_covers_the_mover(corpus):
    """The moved person is the interesting case: they anchor at least 4 of
    the category 5 questions, and their invoice list spans both employers
    (two sending addresses at two domains)."""
    movers = [p for p in corpus.sim.world.people if len(p.employments) > 1]
    assert len(movers) == 1
    mover = movers[0]
    q5 = [q for q in corpus.questions if q.category == 5]
    assert len(q5) >= 4
    mover_qs = [q for q in q5 if q.params["person_id"] == mover.person_id]
    assert len(mover_qs) >= 4
    inv_senders = {m.from_address
                   for m in corpus.render_result.messages
                   if m.from_person == mover.person_id
                   and any(d.startswith("INV-") for d in m.attachments)}
    assert len(inv_senders) == 2
    assert len({s.split("@", 1)[1] for s in inv_senders}) == 2


def test_person_names_unique(corpus):
    people = corpus.sim.world.people
    assert len({p.name for p in people}) == len(people)


def test_temporal_questions_straddle_boundaries(corpus):
    """Category 3 must include as-of dates on both sides of a supersession."""
    hits = set()
    for q in corpus.questions:
        if q.template != "terms_as_of":
            continue
        entity, as_of = q.params["entity"], date.fromisoformat(q.params["as_of"])
        chain = sorted((f for f in corpus.facts if f.entity == entity
                        and f.relation == "payment_terms"),
                       key=lambda f: f.valid_from)
        if len(chain) < 2:
            continue
        boundary = chain[0].valid_to
        hits.add("before" if as_of < boundary else "after")
    assert hits == {"before", "after"}
