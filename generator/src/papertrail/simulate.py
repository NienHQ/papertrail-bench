"""Layer 1: business event simulation.

Produces the canonical event log plus document version chains. Maintains a live
(entity, relation) -> value map so derived values inside events (e.g. invoice due
dates) agree with the fact ledger as-of the event time: the internal-consistency
rule that makes temporal questions honest.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from .model import AddressPeriod, Document, EmploymentPeriod, Event
from .world import World, _addr, build_world

TERMS_CHOICES = ["NET15", "NET30", "NET45", "NET60"]
DISPUTE_REASONS = ["quantity mismatch", "price does not match agreement",
                   "goods returned", "duplicate line item"]

# Shipped question categories and their default per-category counts.
DEFAULT_CATEGORY_COUNTS: dict[int, int] = {1: 16, 2: 16, 3: 16, 4: 16,
                                           5: 16, 6: 16}


@dataclass
class Config:
    seed: int = 42
    year: int = 2024
    months: int = 12
    n_vendors: int = 8
    n_customers: int = 6
    pos_per_vendor_month: tuple[int, int] = (2, 4)
    sales_per_customer_month: tuple[int, int] = (2, 3)
    amend_prob: float = 0.25
    second_amend_prob: float = 0.3
    credit_note_prob: float = 0.08
    dispute_prob: float = 0.12  # vendor invoices that get disputed
    renegotiate_frac: float = 0.5  # parties whose payment terms change mid-year
    # Category 5 world churn (entity resolution).
    contact_change_frac: float = 0.25  # contacts whose address changes mid-corpus
    person_move_count: int = 1  # capped by vendor count - 1
    # Per-category question counts (schema doc section 7).
    category_counts: dict[int, int] = field(
        default_factory=lambda: dict(DEFAULT_CATEGORY_COUNTS))
    # Deprecated override: a flat total split evenly across shipped
    # categories. Kept so the CLI --questions flag stays meaningful.
    n_questions: int | None = None

    def resolved_category_counts(self) -> dict[int, int]:
        if self.n_questions is not None:
            cats = sorted(DEFAULT_CATEGORY_COUNTS)
            base, extra = divmod(self.n_questions, len(cats))
            return {c: base + (1 if i < extra else 0)
                    for i, c in enumerate(cats)}
        return dict(self.category_counts)


@dataclass
class SimResult:
    config: Config
    world: World
    events: list[Event]
    documents: list[Document]


def terms_days(terms: str) -> int:
    return int(terms.removeprefix("NET"))


class _Sim:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.year_start = date(cfg.year, 1, 1)
        self.world = build_world(self.rng, cfg.n_vendors, cfg.n_customers,
                                 self.year_start)
        self.events: list[Event] = []
        self.documents: list[Document] = []
        # date-aware agreement history: (entity, relation) -> [(from_date, value)]
        # in chronological order. All agreements are scheduled BEFORE the trading
        # loop runs, so trading events that spill across month boundaries still
        # read the correct as-of value (internal-consistency rule).
        self.ledger: dict[tuple[str, str], list[tuple[date, str | int]]] = {}
        self._eid = 0
        self._po_n = 0
        self._inv_n = 0
        self._cn_n = 0
        self._day_seq: dict[date, int] = {}

    # -- plumbing ---------------------------------------------------------

    def ts(self, d: date) -> datetime:
        """Deterministic intra-day ordering: business hours, minute per event."""
        seq = self._day_seq.get(d, 0)
        self._day_seq[d] = seq + 1
        return datetime.combine(d, time(9, 0), tzinfo=timezone.utc) + timedelta(
            minutes=seq * 7)

    def emit(self, d: date, type_: str, actor: str, counterparty: str | None,
             payload: dict, refs: dict | None = None) -> Event:
        self._eid += 1
        ev = Event(event_id=f"EVT-{self._eid:06d}", event_time=self.ts(d),
                   type=type_, actor_party=actor, counterparty=counterparty,
                   payload=payload, refs=refs or {})
        self.events.append(ev)
        return ev

    def add_doc(self, kind: str, root_id: str, version: int, supersedes: str | None,
                party_id: str, issued: date, fields: dict, ev: Event) -> Document:
        doc_id = root_id if version == 1 else f"{root_id}-A{version - 1}"
        doc = Document(doc_id=doc_id, kind=kind, root_id=root_id, version=version,
                       supersedes=supersedes, party_id=party_id, issued_date=issued,
                       fields=dict(fields), created_event=ev.event_id)
        self.documents.append(doc)
        ev.refs.setdefault("doc", doc_id)
        return doc

    def set_fact(self, entity: str, relation: str, value, from_date: date) -> None:
        hist = self.ledger.setdefault((entity, relation), [])
        assert not hist or hist[-1][0] <= from_date
        hist.append((from_date, value))

    def get_fact(self, entity: str, relation: str, as_of: date):
        hist = self.ledger[(entity, relation)]
        value = None
        for from_date, v in hist:
            if from_date <= as_of:
                value = v
        assert value is not None, (entity, relation, as_of)
        return value

    def biz_day(self, month: int, lo: int = 1, hi: int = 27) -> date:
        d = date(self.cfg.year, month, self.rng.randint(lo, hi))
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    # -- scenario ---------------------------------------------------------

    def run(self) -> SimResult:
        cfg, rng, w = self.cfg, self.rng, self.world
        us = w.self_party.party_id

        # Opening agreements: payment terms per trading party, unit prices per vendor.
        vendor_items: dict[str, str] = {}
        for i, v in enumerate(w.vendors()):
            d = self.biz_day(1, 2, 10)
            terms = rng.choice(TERMS_CHOICES)
            self.emit(d, "TERMS_AGREED", v.party_id, us,
                      {"relation": "payment_terms", "value": terms})
            self.set_fact(v.party_id, "payment_terms", terms, d)
            item = w.items[i % len(w.items)]
            vendor_items[v.party_id] = item
            price = rng.randrange(300, 9000)  # cents
            d2 = self.biz_day(1, 5, 15)
            self.emit(d2, "PRICE_AGREED", v.party_id, us,
                      {"relation": f"unit_price:{item}", "value": price,
                       "item": item})
            self.set_fact(v.party_id, f"unit_price:{item}", price, d2)
        for c in w.customers():
            d = self.biz_day(1, 2, 10)
            terms = rng.choice(TERMS_CHOICES)
            self.emit(d, "TERMS_AGREED", us, c.party_id,
                      {"relation": "payment_terms", "value": terms})
            self.set_fact(c.party_id, "payment_terms", terms, d)

        # Lease: signed at year start, rent raised mid-year.
        landlord = w.landlord()
        rent = rng.randrange(150_000, 400_000)
        d = self.biz_day(1, 2, 6)
        ev = self.emit(d, "LEASE_SIGNED", landlord.party_id, us,
                       {"monthly_rent_cents": rent, "term_months": 36})
        lease_root = f"LEASE-{cfg.year}-001"
        lease = self.add_doc("lease", lease_root, 1, None, landlord.party_id, d,
                             {"lease_number": lease_root,
                              "monthly_rent_cents": rent, "term_months": 36,
                              "start_date": d.isoformat()}, ev)
        self.set_fact(landlord.party_id, "monthly_rent", rent, d)
        if cfg.months >= 7:
            d = self.biz_day(7, 1, 15)
            new_rent = rent + rng.randrange(5_000, 40_000)
            ev = self.emit(d, "LEASE_AMENDED", landlord.party_id, us,
                           {"monthly_rent_cents": new_rent},
                           {"root": lease_root})
            self.add_doc("lease", lease_root, 2, lease.doc_id, landlord.party_id,
                         d, {**lease.fields, "monthly_rent_cents": new_rent,
                             "amended_date": d.isoformat()}, ev)
            self.set_fact(landlord.party_id, "monthly_rent", new_rent, d)

        # Mid-year renegotiations (terms supersession) at staggered months.
        # Scheduled and recorded BEFORE the trading loop so cross-month spillover
        # (a PO from month m invoiced in month m+1) reads correct as-of terms.
        renegotiable = w.vendors() + w.customers()
        rng.shuffle(renegotiable)
        n_reneg = round(len(renegotiable) * cfg.renegotiate_frac)
        for i, p in enumerate(renegotiable[:n_reneg]):
            month = 4 + (i % max(1, min(6, cfg.months - 4)))
            if month > cfg.months:
                continue
            d = self.biz_day(month, 1, 12)
            old = self.get_fact(p.party_id, "payment_terms", d)
            new = rng.choice([t for t in TERMS_CHOICES if t != old])
            actor, cp = (p.party_id, us) if p.kind == "vendor" else (us, p.party_id)
            self.emit(d, "TERMS_AGREED", actor, cp,
                      {"relation": "payment_terms", "value": new,
                       "previous": old, "renegotiation": True})
            self.set_fact(p.party_id, "payment_terms", new, d)

        # Category 5 world churn: PERSON_MOVED then CONTACT_CHANGED. Drawn
        # AFTER the renegotiation scheduling so all pre-existing rng draws
        # (and therefore earlier-seed corpora) shift as little as possible,
        # and BEFORE the trading loop so date-aware contact and address
        # lookups during rendering are consistent for every event date.
        self._schedule_person_moves()
        self._schedule_contact_changes()

        # Monthly trading loop.
        for month in range(1, cfg.months + 1):
            for v in w.vendors():
                for _ in range(rng.randint(*cfg.pos_per_vendor_month)):
                    self._po_cycle(month, v.party_id, vendor_items[v.party_id])

            for c in w.customers():
                for _ in range(rng.randint(*cfg.sales_per_customer_month)):
                    self._sales_cycle(month, c.party_id)

        self.events.sort(key=lambda e: (e.event_time, e.event_id))
        return SimResult(config=cfg, world=self.world, events=self.events,
                         documents=self.documents)

    def _mid_month(self) -> int:
        """A month in the middle third of the corpus."""
        lo = self.cfg.months // 3 + 1
        hi = max(lo, (2 * self.cfg.months) // 3)
        return self.rng.randint(lo, hi)

    def _schedule_person_moves(self) -> None:
        """PERSON_MOVED: a vendor contact leaves for a different vendor.

        Closes the mover's address and employment periods, opens new ones at
        the destination (new domain address), updates person.party_id, and
        hires a replacement contact at the old vendor whose periods start at
        the move date. The destination's existing contact remains employed;
        the renderer's date-aware contact rule (most recent joiner wins)
        makes the mover the sender for the destination's mail from the move
        date on.
        """
        cfg, rng, w = self.cfg, self.rng, self.world
        us = w.self_party.party_id
        vendors = w.vendors()
        n = min(cfg.person_move_count, max(0, len(vendors) - 1))
        if n <= 0:
            return
        for src in rng.sample(vendors, n):
            mover = w.contact_for(src.party_id)
            dest = rng.choice([v for v in vendors
                               if v.party_id != src.party_id])
            d = self.biz_day(self._mid_month(), 1, 20)
            mover.addresses[-1].to_date = d
            mover.employments[-1].to_date = d
            mover.addresses.append(
                AddressPeriod(_addr(mover.name, dest.domain), d, None))
            mover.employments.append(
                EmploymentPeriod(dest.party_id, d, None))
            mover.party_id = dest.party_id
            replacement = w.hire(src, mover.role, d)
            self.emit(d, "PERSON_MOVED", src.party_id, us,
                      {"person_id": mover.person_id,
                       "from_party": src.party_id,
                       "to_party": dest.party_id,
                       "replacement_person_id": replacement.person_id})

    def _schedule_contact_changes(self) -> None:
        """CONTACT_CHANGED: same person, same domain, new local part.

        Applies to a fraction of trading-party contacts that have not moved
        (single address period starting at corpus start). Closes the current
        address period and opens a new one at the same domain with a
        different local part (first initial + last name instead of
        first.last).
        """
        cfg, rng, w = self.cfg, self.rng, self.world
        us = w.self_party.party_id
        trading = {p.party_id for p in w.vendors() + w.customers()}
        eligible = [p for p in w.people
                    if p.party_id in trading and len(p.addresses) == 1
                    and p.addresses[0].from_date == self.year_start]
        n = round(len(eligible) * cfg.contact_change_frac)
        if n <= 0:
            return
        # at least one changed contact is a vendor contact: vendor mail
        # (POs, invoices) is what the category 5 questions aggregate over
        vendor_ids = {v.party_id for v in w.vendors()}
        picks = []
        vendor_eligible = [p for p in eligible if p.party_id in vendor_ids]
        if vendor_eligible:
            picks.append(rng.choice(vendor_eligible))
        rest = [p for p in eligible if p not in picks]
        picks.extend(rng.sample(rest, min(n - len(picks), len(rest))))
        for person in picks:
            d = self.biz_day(self._mid_month(), 1, 20)
            old_address = person.addresses[-1].address
            domain = old_address.split("@", 1)[1]
            parts = person.name.lower().split()
            new_address = f"{parts[0][0]}{parts[-1]}@{domain}"
            assert new_address != old_address
            person.addresses[-1].to_date = d
            person.addresses.append(AddressPeriod(new_address, d, None))
            self.emit(d, "CONTACT_CHANGED", person.party_id, us,
                      {"person_id": person.person_id,
                       "old_address": old_address,
                       "new_address": new_address})

    def _po_cycle(self, month: int, vendor: str, item: str) -> None:
        cfg, rng = self.cfg, self.rng
        us = self.world.self_party.party_id
        # month 1 trading starts after the opening agreements (days 2-15)
        d = self.biz_day(month, 16 if month == 1 else 1)
        self._po_n += 1
        root = f"PO-{cfg.year}-{self._po_n:04d}"
        qty = rng.randrange(10, 200, 5)
        price = self.get_fact(vendor, f"unit_price:{item}", d)
        fields = {"po_number": root, "item": item, "qty": qty,
                  "unit_price_cents": price, "total_cents": qty * price}
        ev = self.emit(d, "PO_ISSUED", us, vendor, dict(fields))
        doc = self.add_doc("po", root, 1, None, vendor, d, fields, ev)

        while rng.random() < (cfg.amend_prob if doc.version == 1
                              else cfg.second_amend_prob):
            d = min(d + timedelta(days=rng.randint(2, 6)),
                    date(cfg.year, 12, 28))
            qty = max(5, qty + rng.choice([-1, 1]) * rng.randrange(5, 50, 5))
            fields = {**doc.fields, "qty": qty, "total_cents": qty * price}
            ev = self.emit(d, "PO_AMENDED", us, vendor,
                           {"qty": qty, "total_cents": qty * price},
                           {"root": root})
            doc = self.add_doc("po", root, doc.version + 1, doc.doc_id, vendor,
                               d, fields, ev)

        # Vendor invoices against the final PO state.
        d_inv = min(d + timedelta(days=rng.randint(3, 10)),
                    date(cfg.year, 12, 29))
        self._invoice_and_pay(d_inv, issuer=vendor, payer=us, party=vendor,
                              amount=doc.fields["total_cents"], po_ref=doc.doc_id)

    def _sales_cycle(self, month: int, customer: str) -> None:
        rng = self.rng
        us = self.world.self_party.party_id
        d = self.biz_day(month, 16 if month == 1 else 1)
        amount = rng.randrange(20_000, 900_000, 500)
        self._invoice_and_pay(d, issuer=us, payer=customer, party=customer,
                              amount=amount, po_ref=None)

    def _invoice_and_pay(self, d: date, issuer: str, payer: str, party: str,
                         amount: int, po_ref: str | None) -> None:
        cfg, rng = self.cfg, self.rng
        us = self.world.self_party.party_id
        self._inv_n += 1
        inv_id = f"INV-{cfg.year}-{self._inv_n:04d}"
        terms = self.get_fact(party, "payment_terms", d)
        due = d + timedelta(days=terms_days(terms))
        fields = {"invoice_number": inv_id, "issuer": issuer, "bill_to": payer,
                  "issue_date": d.isoformat(), "due_date": due.isoformat(),
                  "terms": terms, "total_cents": amount}
        if po_ref:
            fields["po_ref"] = po_ref
        ev = self.emit(d, "INVOICE_ISSUED", issuer, payer, dict(fields))
        self.add_doc("invoice", inv_id, 1, None, party, d, fields, ev)

        # Vendor-side disputes (category 4). Dispute consistency rule: a
        # credit_note resolution reuses the credit-note machinery for exactly
        # disputed_cents against this invoice, and the payment reflects it; a
        # disputed invoice never also draws the independent random credit
        # note below; a withdrawn resolution changes no amounts.
        disputed = False
        if payer == us and amount // 2 >= 1_000 \
                and rng.random() < cfg.dispute_prob:
            disputed = True
            d_disp = min(d + timedelta(days=rng.randint(2, 6)),
                         date(cfg.year, 12, 29))
            disputed_cents = rng.randrange(1_000, amount // 2 + 1)
            reason = rng.choice(DISPUTE_REASONS)
            self.emit(d_disp, "INVOICE_DISPUTED", us, issuer,
                      {"invoice_ref": inv_id, "disputed_cents": disputed_cents,
                       "reason": reason}, {"invoice": inv_id})
            d_res = min(d_disp + timedelta(days=rng.randint(3, 10)),
                        date(cfg.year, 12, 30))
            if rng.random() < 0.6:
                self._cn_n += 1
                cn_id = f"CN-{cfg.year}-{self._cn_n:04d}"
                self.emit(d_res, "DISPUTE_RESOLVED", issuer, us,
                          {"invoice_ref": inv_id, "resolution": "credit_note",
                           "credit_note_ref": cn_id}, {"invoice": inv_id})
                cn_fields = {"credit_note_number": cn_id,
                             "invoice_ref": inv_id,
                             "amount_cents": disputed_cents, "reason": reason}
                ev = self.emit(d_res, "CREDIT_NOTE_ISSUED", issuer, payer,
                               dict(cn_fields), {"invoice": inv_id})
                self.add_doc("credit_note", cn_id, 1, None, party, d_res,
                             cn_fields, ev)
                amount -= disputed_cents
            else:
                self.emit(d_res, "DISPUTE_RESOLVED", us, issuer,
                          {"invoice_ref": inv_id, "resolution": "withdrawn"},
                          {"invoice": inv_id})

        if not disputed and rng.random() < cfg.credit_note_prob:
            self._cn_n += 1
            cn_id = f"CN-{cfg.year}-{self._cn_n:04d}"
            d_cn = min(d + timedelta(days=rng.randint(2, 8)),
                       date(cfg.year, 12, 30))
            cn_amount = min(amount, rng.randrange(1_000, max(2_000, amount // 3)))
            reason = rng.choice(["damaged goods", "short delivery",
                                 "pricing error", "returned items"])
            cn_fields = {"credit_note_number": cn_id, "invoice_ref": inv_id,
                         "amount_cents": cn_amount, "reason": reason}
            ev = self.emit(d_cn, "CREDIT_NOTE_ISSUED", issuer, payer, dict(cn_fields),
                           {"invoice": inv_id})
            self.add_doc("credit_note", cn_id, 1, None, party, d_cn, cn_fields, ev)
            amount -= cn_amount

        pay_type = "PAYMENT_SENT" if payer == self.world.self_party.party_id \
            else "PAYMENT_RECEIVED"
        d_pay = min(due - timedelta(days=rng.randint(0, 5)),
                    date(cfg.year, 12, 31))
        d_pay = max(d_pay, d + timedelta(days=1))
        self.emit(d_pay, pay_type, payer, issuer,
                  {"amount_cents": amount, "invoice_ref": inv_id,
                   "method": "bank transfer"},
                  {"invoice": inv_id})


def simulate(cfg: Config) -> SimResult:
    return _Sim(cfg).run()
