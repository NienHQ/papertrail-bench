"""Layer 4: question generation for categories 1-6.

Every non-abstention question's answer is recomputed from the ground-truth
tables through an independent path and asserted equal at generation time, and
its evidence set is asserted non-empty and resolvable (invariant 3 in the
schema doc). Abstention questions (category 6) invert both guarantees: the
referenced id or name is asserted structurally absent and the evidence set is
empty by definition.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from .facts import fact_as_of
from .model import Document, Event, Fact, Person, Question, money
from .render import RenderResult
from .simulate import SimResult
from .world import VENDOR_SUFFIXES, company_stem_pool


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

    # -- category 4: cross-thread aggregation over disputes -----------------

    def _disputes_for(self, vendor: str, year: int | None = None
                      ) -> list[Event]:
        """Independent recompute path: scan the event log directly. Filtered
        by the dispute event's year when given: multi-year corpora ask the
        question per (vendor, year) so text and answer stay honest."""
        return [e for e in self.sim.events if e.type == "INVOICE_DISPUTED"
                and e.counterparty == vendor
                and (year is None or e.event_time.year == year)]

    def _dispute_evidence(self, evs: list[Event]) -> list[dict]:
        return _evidence_for(self.rr, *[("event", e.event_id) for e in evs])

    def q4_disputed_total(self, vendor: str, year: int) -> None:
        evs = self._disputes_for(vendor, year)
        total = sum(e.payload["disputed_cents"] for e in evs)
        party = self.sim.world.party(vendor)
        self.add(4, "disputed_total",
                 f"What is the total amount we disputed with {party.name} "
                 f"in {year}?",
                 _money_answer(total), self._dispute_evidence(evs),
                 {"vendor": vendor, "year": year})

    def q4_disputed_count(self, vendor: str, year: int) -> None:
        evs = self._disputes_for(vendor, year)
        party = self.sim.world.party(vendor)
        self.add(4, "disputed_count",
                 f"How many invoices did we dispute with {party.name} "
                 f"in {year}?",
                 {"type": "int", "value": len(evs)},
                 self._dispute_evidence(evs),
                 {"vendor": vendor, "year": year})

    def q4_disputed_list(self, vendor: str, year: int) -> None:
        evs = self._disputes_for(vendor, year)  # event-log order == date order
        party = self.sim.world.party(vendor)
        self.add(4, "disputed_list",
                 f"Which invoices did we dispute with {party.name} in {year}, "
                 f"in order of dispute date?",
                 {"type": "ordered_list",
                  "value": [e.payload["invoice_ref"] for e in evs]},
                 self._dispute_evidence(evs),
                 {"vendor": vendor, "year": year})

    # -- category 5: entity resolution across addresses and employers -------

    def _pos_to_person(self, person: Person) -> list[str]:
        """PO_ISSUED event ids whose carrier message was addressed to this
        person. Recomputed from the comms ground truth (messages joined to
        the document table), not from the world's contact bookkeeping;
        a version-1 po attachment appears only on its PO_ISSUED carrier."""
        out = []
        for m in self.rr.messages:
            if not any(name == person.name for name, _ in m.to):
                continue
            for doc_id in m.attachments:
                d = self.docs_by_id[doc_id]
                if d.kind == "po" and d.version == 1:
                    out.append(d.created_event)
        return out

    def _invoices_from_person(self, person: Person) -> list[tuple]:
        """(message, invoice doc) pairs for INVOICE_ISSUED carriers sent by
        this person, in message-time order, across all their addresses and
        employers."""
        pairs = []
        for m in self.rr.messages:  # already sorted by (ts, message_id)
            if m.from_person != person.person_id:
                continue
            for doc_id in m.attachments:
                d = self.docs_by_id[doc_id]
                if d.kind == "invoice" and \
                        not d.fields.get("voided_by_correction"):
                    pairs.append((m, d))
        return pairs

    def q5_person_po_count(self, person: Person) -> bool:
        evs = self._pos_to_person(person)
        if not evs:
            return False
        # evidence: the person's own ack statement for every counted PO
        self.add(5, "person_po_count",
                 f"How many purchase orders did we send to {person.name} "
                 f"across all their addresses and companies?",
                 {"type": "int", "value": len(evs)},
                 _evidence_for(self.rr, *[("event", e) for e in evs]),
                 {"person_id": person.person_id})
        return True

    def q5_person_invoices_list(self, person: Person) -> bool:
        pairs = self._invoices_from_person(person)
        if not pairs:
            return False
        refs = []
        for m, d in pairs:
            for mid, sid in self.rr.evidence_index[
                    ("doc_field", d.doc_id, "total_cents")]:
                if mid == m.message_id:
                    refs.append({"message_id": mid, "statement_id": sid})
        assert len(refs) == len(pairs)
        self.add(5, "person_invoices_list",
                 f"Which invoices did {person.name} send us, in order?",
                 {"type": "ordered_list",
                  "value": [d.doc_id for _, d in pairs]},
                 refs, {"person_id": person.person_id})
        return True

    def q5_person_address_at(self, person: Person, party_id: str) -> bool:
        emps = [e for e in person.employments if e.party_id == party_id]
        if len(emps) != 1:
            return False
        emp = emps[0]
        addrs = [a for a in person.addresses
                 if a.from_date >= emp.from_date
                 and (emp.to_date is None or a.from_date < emp.to_date)]
        if len(addrs) != 1:
            return False  # ambiguous: address changed within this employment
        address = addrs[0].address
        evidence = self._address_evidence(person, emp, address)
        if evidence is None:
            return False
        party = self.sim.world.party(party_id)
        self.add(5, "person_address_at",
                 f"What email address did {person.name} use while at "
                 f"{party.name}?",
                 {"type": "string", "value": address},
                 evidence,
                 {"person_id": person.person_id, "party_id": party_id})
        return True

    def _address_evidence(self, person: Person, emp, address: str
                          ) -> list[dict] | None:
        """The change-announcement statement when the period started with
        one (PERSON_MOVED farewell; CONTACT_CHANGED periods are never
        sampled because they make the address question ambiguous), else a
        canonical statement from a message the person sent at that
        address."""
        for e in self.sim.events:
            if (e.type == "PERSON_MOVED"
                    and e.payload["person_id"] == person.person_id
                    and e.payload["to_party"] == emp.party_id
                    and e.event_time.date() == emp.from_date):
                return _evidence_for(self.rr, ("event", e.event_id))
        for m in self.rr.messages:
            if (m.from_person == person.person_id
                    and m.from_address == address and m.statements):
                return [{"message_id": m.message_id,
                         "statement_id": m.statements[0].statement_id}]
        return None

    # -- category 6: abstention on plausible but nonexistent ids ------------

    def _assert_absent_doc(self, doc_id: str) -> None:
        assert doc_id not in self.docs_by_id
        assert all(d.root_id != doc_id for d in self.docs)

    def q6_missing_invoice(self, inv_id: str) -> None:
        self._assert_absent_doc(inv_id)
        self.add(6, "nonexistent_invoice_total",
                 f"What is the total amount of invoice {inv_id}?",
                 {"type": "abstain", "value": None}, [],
                 {"missing_id": inv_id})

    def q6_missing_vendor_terms(self, name: str, as_of: date) -> None:
        assert all(p.name != name for p in self.sim.world.parties)
        self.add(6, "nonexistent_vendor_terms",
                 f"What were the agreed payment terms with {name} as of "
                 f"{as_of.isoformat()}?",
                 {"type": "abstain", "value": None}, [],
                 {"missing_name": name, "as_of": as_of.isoformat()})

    def q6_missing_po_chain(self, po_id: str) -> None:
        self._assert_absent_doc(po_id)
        self.add(6, "nonexistent_po_chain",
                 f"List every version of purchase order {po_id}, from the "
                 f"original to the latest amendment, in order.",
                 {"type": "abstain", "value": None}, [],
                 {"missing_id": po_id})

    # -- sampling -----------------------------------------------------------

    def run(self) -> list[Question]:
        rng = self.rng
        counts = self.sim.config.resolved_category_counts()
        # near-dup screw: voided duplicates are never sampled anywhere
        invoices = [d for d in self.docs if d.kind == "invoice"
                    and not d.fields.get("voided_by_correction")]
        cns = [d for d in self.docs if d.kind == "credit_note"]
        amended_roots = sorted({d.root_id for d in self.docs
                                if d.kind == "po" and d.version > 1})
        superseded = self._superseded_terms_entities()

        # category 1
        c1 = counts.get(1, 0)
        picks = rng.sample(invoices, min(c1, len(invoices)))
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
        for doc in rng.sample(cns, min(max(0, c1 - len(picks)), len(cns))):
            self.q1_credit_note_amount(doc)

        # category 2
        c2 = counts.get(2, 0)
        roots = rng.sample(amended_roots, min(c2, len(amended_roots)))
        for i, root in enumerate(roots):
            (self.q2_chain, self.q2_amend_count, self.q2_final_qty)[i % 3](root)

        # category 3: as-of dates straddling each supersession boundary
        c3 = counts.get(3, 0)
        boundaries: list[tuple[str, date]] = []
        for entity, boundary in superseded:
            boundaries.append((entity, boundary - timedelta(days=rng.randint(5, 40))))
            boundaries.append((entity, boundary + timedelta(days=rng.randint(5, 40))))
        rng.shuffle(boundaries)
        cfg = self.sim.config
        last_year = cfg.year + cfg.years - 1
        year_end = date(last_year, 12, 31)
        used = 0
        for entity, as_of in boundaries:
            if used >= max(0, c3 - 2):
                break
            if as_of > year_end:
                as_of = year_end
            self.q3_terms_as_of(entity, as_of)
            used += 1
        # two rent questions straddling the lease amendment
        rent_facts = [f for f in self.facts if f.relation == "monthly_rent"]
        if len(rent_facts) > 1 and c3 > 0:
            b = rent_facts[1].valid_from
            self.q3_rent_as_of(b - timedelta(days=14))
            self.q3_rent_as_of(b + timedelta(days=14))

        # category 4: (vendor, year) pairs with at least one dispute; repeat
        # templates across pairs before shrinking the count. Single-year
        # corpora reduce to the vendor list exactly as before.
        disputed_vendors = [v.party_id for v in self.sim.world.vendors()
                            if self._disputes_for(v.party_id)]
        rng.shuffle(disputed_vendors)
        q4_templates = (self.q4_disputed_total, self.q4_disputed_count,
                        self.q4_disputed_list)
        years = range(cfg.year, cfg.year + cfg.years)
        pairs = [(tmpl, v, y) for tmpl in q4_templates
                 for v in disputed_vendors for y in years
                 if self._disputes_for(v, y)]
        for tmpl, vendor, year in pairs[:counts.get(4, 0)]:
            tmpl(vendor, year)

        # category 5: keyed to people, not addresses. The moved person is
        # the interesting case and contributes up to 4 questions; contact
        # changed people cover cross-address aggregation; plain people fill.
        c5 = counts.get(5, 0)
        if c5 > 0:
            people = self.sim.world.people
            # ambiguity guard: display names are the join key in question
            # text, so they must be unique in this world
            assert len({p.name for p in people}) == len(people)
            self_id = self.sim.world.self_party.party_id
            movers = [p for p in people if len(p.employments) > 1]
            changed = [p for p in people
                       if len(p.employments) == 1 and len(p.addresses) > 1]
            plain = [p for p in people
                     if len(p.employments) == 1 and len(p.addresses) == 1
                     and p.party_id != self_id]
            planned: list[tuple] = []
            for p in movers:
                planned.append((self.q5_person_po_count, p))
                planned.append((self.q5_person_invoices_list, p))
                for emp in p.employments:
                    planned.append((self.q5_person_address_at, p,
                                    emp.party_id))
            for p in changed:
                planned.append((self.q5_person_po_count, p))
                planned.append((self.q5_person_invoices_list, p))
            for p in plain:
                planned.append((self.q5_person_po_count, p))
                planned.append((self.q5_person_invoices_list, p))
                planned.append((self.q5_person_address_at, p, p.party_id))
            emitted = 0
            for fn, *fn_args in planned:
                if emitted >= c5:
                    break
                if fn(*fn_args):
                    emitted += 1

        # category 6: ids continuing the real numbering series, names from
        # the unused portion of the company stem pool. Series restart per
        # year, so never-issued ids continue the LAST year's series.
        year = last_year
        inv_max = self._series_max(f"INV-{year}-")
        po_max = self._series_max(f"PO-{year}-")
        party_names = {p.name for p in self.sim.world.parties}
        stem_pool = company_stem_pool(len(self.sim.world.parties))
        used_stems = {s for s in stem_pool
                      if any(n.startswith(s + " ") for n in party_names)}
        unused_stems = [s for s in stem_pool if s not in used_stems]
        rng.shuffle(unused_stems)
        k_inv = k_po = 0
        for i in range(counts.get(6, 0)):
            kind = i % 3
            if kind == 1 and not unused_stems:
                kind = 2
            if kind == 0:
                k_inv += 1
                self.q6_missing_invoice(f"INV-{year}-{inv_max + k_inv:04d}")
            elif kind == 1:
                name = f"{unused_stems.pop()} {rng.choice(VENDOR_SUFFIXES)}"
                as_of = date(year, rng.randint(1, 12), rng.randint(1, 28))
                self.q6_missing_vendor_terms(name, as_of)
            else:
                k_po += 1
                self.q6_missing_po_chain(f"PO-{year}-{po_max + k_po:04d}")

        return self.questions

    def _series_max(self, prefix: str) -> int:
        ns = [int(d.root_id.removeprefix(prefix)) for d in self.docs
              if d.root_id.startswith(prefix) and d.version == 1]
        return max(ns, default=0)

    def _superseded_terms_entities(self) -> list[tuple[str, date]]:
        out = []
        for f in self.facts:
            if f.relation == "payment_terms" and f.valid_to is not None:
                out.append((f.entity, f.valid_to))  # boundary = supersession date
        return sorted(set(out))


def generate_questions(sim: SimResult, facts: list[Fact],
                       rr: RenderResult) -> list[Question]:
    return _QGen(sim, facts, rr).run()
