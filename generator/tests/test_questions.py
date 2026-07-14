"""Invariant 3: every question's answer recomputes from ground truth alone."""
from datetime import date

from papertrail.facts import fact_as_of


def _docs_by_id(corpus):
    return {d.doc_id: d for d in corpus.sim.documents}


def test_question_counts_and_categories(corpus):
    cats = {q.category for q in corpus.questions}
    assert cats == {1, 2, 3}
    assert len(corpus.questions) >= corpus.sim.config.n_questions * 0.8


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
        else:
            raise AssertionError(f"untested template {q.template}")


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
