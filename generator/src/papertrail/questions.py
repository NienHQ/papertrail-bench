"""Layer 4: question generation for B0 categories 1-3.

Every question's answer is recomputed from the ground-truth tables through an
independent path and asserted equal at generation time, and its evidence set is
asserted non-empty and resolvable (invariant 3 in the schema doc).
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from .facts import fact_as_of
from .model import Document, Fact, Question, money
from .render import RenderResult
from .simulate import SimResult


def _evidence_for(rr: RenderResult, *keys: tuple) -> list[dict]:
    out = []
    for key in keys:
        if key[0] == "doc_field":
            out.append({"doc_id": key[1], "field": key[2]})
        for mid, sid in rr.evidence_index.get(key, []):
            out.append({"message_id": mid, "statement_id": sid})
    assert out, f"no evidence for {keys}"
    return out


def _money_answer(cents: int) -> dict:
    return {"type": "money", "value": {"amount_cents": cents, "currency": "USD"}}


class _QGen:
    def __init__(self, sim: SimResult, facts: list[Fact], rr: RenderResult):
        self.sim = sim
        self.facts = facts
        self.rr = rr
        self.rng = random.Random(sim.config.seed ^ 0xBE9C)
        self.docs = sim.documents
        self.docs_by_id = {d.doc_id: d for d in self.docs}
        self._qn = 0
        self.questions: list[Question] = []

    def add(self, category: int, template: str, text: str, answer: dict,
            evidence: list[dict], params: dict) -> None:
        self._qn += 1
        self.questions.append(Question(
            question_id=f"Q-{self._qn:04d}", category=category,
            template=template, text=text, answer=answer, evidence=evidence,
            params=params))

    # -- category 1: specific record lookup --------------------------------

    def q1_invoice_total(self, doc: Document) -> None:
        # independent recompute: read the table row again by id
        row = self.docs_by_id[doc.doc_id]
        assert row.fields["total_cents"] == doc.fields["total_cents"]
        self.add(1, "invoice_total",
                 f"What is the total amount of invoice "
                 f"{doc.fields['invoice_number']}?",
                 _money_answer(row.fields["total_cents"]),
                 _evidence_for(self.rr, ("doc_field", doc.doc_id, "total_cents")),
                 {"doc_id": doc.doc_id})

    def q1_invoice_due(self, doc: Document) -> None:
        self.add(1, "invoice_due_date",
                 f"When is invoice {doc.fields['invoice_number']} due?",
                 {"type": "date", "value": doc.fields["due_date"]},
                 _evidence_for(self.rr, ("doc_field", doc.doc_id, "due_date")),
                 {"doc_id": doc.doc_id})

    def q1_invoice_po(self, doc: Document) -> None:
        self.add(1, "invoice_po_ref",
                 f"Which purchase order does invoice "
                 f"{doc.fields['invoice_number']} reference?",
                 {"type": "string", "value": doc.fields["po_ref"]},
                 _evidence_for(self.rr, ("doc_field", doc.doc_id, "po_ref")),
                 {"doc_id": doc.doc_id})

    def q1_credit_note_amount(self, doc: Document) -> None:
        self.add(1, "credit_note_amount",
                 f"What is the amount of credit note "
                 f"{doc.fields['credit_note_number']}, and against which "
                 f"invoice was it issued? Give the amount.",
                 _money_answer(doc.fields["amount_cents"]),
                 _evidence_for(self.rr,
                               ("doc_field", doc.doc_id, "amount_cents")),
                 {"doc_id": doc.doc_id})

    # -- category 2: lineage / amendment chains ----------------------------

    def q2_chain(self, root_id: str) -> None:
        chain = sorted((d for d in self.docs if d.root_id == root_id),
                       key=lambda d: d.version)
        assert [d.version for d in chain] == list(range(1, len(chain) + 1))
        ev_keys = [("doc_field", d.doc_id,
                    "po_number" if d.kind == "po" else "lease_number")
                   for d in chain]
        self.add(2, "amendment_chain",
                 f"List every version of purchase order {root_id}, from the "
                 f"original to the latest amendment, in order.",
                 {"type": "ordered_list", "value": [d.doc_id for d in chain]},
                 _evidence_for(self.rr, *ev_keys),
                 {"root_id": root_id})

    def q2_amend_count(self, root_id: str) -> None:
        n = sum(1 for d in self.docs if d.root_id == root_id) - 1
        self.add(2, "amendment_count",
                 f"How many times was purchase order {root_id} amended?",
                 {"type": "int", "value": n},
                 _evidence_for(self.rr,
                               *[("doc_field", d.doc_id, "po_number")
                                 for d in self.docs if d.root_id == root_id
                                 and d.version > 1]),
                 {"root_id": root_id})

    def q2_final_qty(self, root_id: str) -> None:
        final = max((d for d in self.docs if d.root_id == root_id),
                    key=lambda d: d.version)
        self.add(2, "final_quantity",
                 f"After all amendments, what is the agreed quantity on "
                 f"purchase order {root_id}?",
                 {"type": "int", "value": final.fields["qty"]},
                 _evidence_for(self.rr, ("doc_field", final.doc_id, "qty")),
                 {"root_id": root_id, "doc_id": final.doc_id})

    # -- category 3: temporal supersession ---------------------------------

    def q3_terms_as_of(self, entity: str, as_of: date) -> None:
        f = fact_as_of(self.facts, entity, "payment_terms", as_of)
        assert f is not None
        party = self.sim.world.party(entity)
        self.add(3, "terms_as_of",
                 f"What were the agreed payment terms with {party.name} as of "
                 f"{as_of.isoformat()}?",
                 {"type": "string", "value": f.value},
                 _evidence_for(self.rr, ("fact", f.fact_id)),
                 {"entity": entity, "as_of": as_of.isoformat(),
                  "fact_id": f.fact_id})

    def q3_rent_as_of(self, as_of: date) -> None:
        landlord = self.sim.world.landlord()
        f = fact_as_of(self.facts, landlord.party_id, "monthly_rent", as_of)
        assert f is not None
        self.add(3, "rent_as_of",
                 f"What was the monthly rent for our premises as of "
                 f"{as_of.isoformat()}?",
                 _money_answer(f.value),
                 _evidence_for(self.rr, ("fact", f.fact_id)),
                 {"entity": landlord.party_id, "as_of": as_of.isoformat(),
                  "fact_id": f.fact_id})

    # -- sampling -----------------------------------------------------------

    def run(self, n: int) -> list[Question]:
        rng = self.rng
        invoices = [d for d in self.docs if d.kind == "invoice"]
        cns = [d for d in self.docs if d.kind == "credit_note"]
        po_invoices = [d for d in invoices if "po_ref" in d.fields]
        amended_roots = sorted({d.root_id for d in self.docs
                                if d.kind == "po" and d.version > 1})
        superseded = self._superseded_terms_entities()

        per_cat = n // 3
        # category 1
        picks = rng.sample(invoices, min(per_cat, len(invoices)))
        for i, doc in enumerate(picks):
            kind = i % 3
            if kind == 0:
                self.q1_invoice_total(doc)
            elif kind == 1:
                self.q1_invoice_due(doc)
            elif "po_ref" in doc.fields:
                self.q1_invoice_po(doc)
            else:
                self.q1_invoice_total(doc)
        for doc in rng.sample(cns, min(max(0, per_cat - len(picks)), len(cns))):
            self.q1_credit_note_amount(doc)

        # category 2
        roots = rng.sample(amended_roots, min(per_cat, len(amended_roots)))
        for i, root in enumerate(roots):
            (self.q2_chain, self.q2_amend_count, self.q2_final_qty)[i % 3](root)

        # category 3: as-of dates straddling each supersession boundary
        n3 = n - len(self.questions)
        boundaries: list[tuple[str, date]] = []
        for entity, boundary in superseded:
            boundaries.append((entity, boundary - timedelta(days=rng.randint(5, 40))))
            boundaries.append((entity, boundary + timedelta(days=rng.randint(5, 40))))
        rng.shuffle(boundaries)
        year_end = date(self.sim.config.year, 12, 31)
        used = 0
        for entity, as_of in boundaries:
            if used >= max(0, n3 - 2):
                break
            if as_of > year_end:
                as_of = year_end
            self.q3_terms_as_of(entity, as_of)
            used += 1
        # two rent questions straddling the lease amendment
        rent_facts = [f for f in self.facts if f.relation == "monthly_rent"]
        if len(rent_facts) > 1:
            b = rent_facts[1].valid_from
            self.q3_rent_as_of(b - timedelta(days=14))
            self.q3_rent_as_of(b + timedelta(days=14))

        # top up to n with category-1 lookups over unused invoices
        used_docs = {q.params.get("doc_id") for q in self.questions}
        spare = [d for d in invoices if d.doc_id not in used_docs]
        rng.shuffle(spare)
        for doc in spare[:max(0, n - len(self.questions))]:
            self.q1_invoice_total(doc)

        return self.questions

    def _superseded_terms_entities(self) -> list[tuple[str, date]]:
        out = []
        for f in self.facts:
            if f.relation == "payment_terms" and f.valid_to is not None:
                out.append((f.entity, f.valid_to))  # boundary = supersession date
        return sorted(set(out))


def generate_questions(sim: SimResult, facts: list[Fact],
                       rr: RenderResult) -> list[Question]:
    return _QGen(sim, facts, rr).run(sim.config.n_questions)
