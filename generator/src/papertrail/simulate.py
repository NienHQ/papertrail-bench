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

# G3 realism screws: the config values the CLI "--preset hard" applies.
# Explicit per-flag CLI values override these.
HARD_PRESET: dict[str, object] = {
    "truncate_references": True,
    "quoted_replies": True,
    "near_dup_invoices": 0.15,
    "format_drift": True,
}

# G4 publication preset: 3 years, larger world, all screws on, 55 questions
# per category. Explicit CLI flags override individual entries. The PO and
# sales rates are part of the preset definition, tuned so the seed-42 bench
# corpus lands near 15k messages (docs/presets.md records the measurement).
BENCH_PRESET: dict[str, object] = {
    **HARD_PRESET,
    "years": 3,
    "n_vendors": 14,
    "n_customers": 10,
    "pos_per_vendor_month": (4, 6),
    "sales_per_customer_month": (3, 4),
    "category_counts": {1: 55, 2: 55, 3: 55, 4: 55, 5: 55, 6: 55},
}

# Chance that a non-opening year's lease review actually amends the rent.
LEASE_REVIEW_PROB = 0.8


@dataclass
class Config:
    seed: int = 42
    year: int = 2024  # start year of the corpus
    # Number of simulated years. Non-final years always run 12 months;
    # `months` applies to the FINAL year, so months=6, years=3 means two
    # full years plus six months. years=1 output is byte-identical to the
    # single-year generator (year 1 executes the exact same draw sequence;
    # later years append their draws strictly after).
    years: int = 1
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
    # G3 realism screws (schema doc section 6). All default OFF, and when
    # off they consume ZERO rng draws, so pre-G3 seeds stay byte-identical.
    truncate_references: bool = False  # keep last 2 refs; every 5th reply bare
    quoted_replies: bool = False  # replies quote the previous body with "> "
    near_dup_invoices: float = 0.0  # fraction of vendor invoices re-issued
    format_drift: bool = False  # money prose drifts between three formats
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
        # Multi-year bookkeeping. cur_year/cur_months track the year being
        # scheduled; last_year is the corpus end, which is what the trading
        # loop clamps against (so a December invoice of a non-final year may
        # spill into January of the next year, while the final year clamps
        # exactly as the single-year generator clamps to year end).
        self.cur_year = cfg.year
        self.cur_months = cfg.months
        self.last_year = cfg.year + cfg.years - 1
        self.world = build_world(self.rng, cfg.n_vendors, cfg.n_customers,
                                 self.year_start)
        self.events: list[Event] = []
        self.documents: list[Document] = []
        self.vendor_items: dict[str, str] = {}
        self._lease_root: str | None = None
        self._lease_doc: Document | None = None
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
        d = date(self.cur_year, month, self.rng.randint(lo, hi))
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    # -- scenario ---------------------------------------------------------

    def run(self) -> SimResult:
        cfg = self.cfg
        # Per year: a scheduling pass (agreements or reviews, churn), then
        # the monthly trading loop. Year 1 executes the exact draw sequence
        # of the single-year generator; each later year's draws come
        # strictly after all prior-year draws.
        for y in range(cfg.year, self.last_year + 1):
            self.cur_year = y
            self.cur_months = cfg.months if y == self.last_year else 12
            if y == cfg.year:
                self._opening_agreements()
            else:
                # PO/INV/CN numbering series restart per year.
                self._po_n = self._inv_n = self._cn_n = 0
                self._lease_review()
            self._schedule_renegotiations()
            self._schedule_person_moves()
            self._schedule_contact_changes()
            self._trading_year()

        self.events.sort(key=lambda e: (e.event_time, e.event_id))
        return SimResult(config=cfg, world=self.world, events=self.events,
                         documents=self.documents)

    def _opening_agreements(self) -> None:
        """Year-1 agreements: payment terms per trading party, unit prices
        per vendor, the lease (signed, then rent raised mid-year)."""
        cfg, rng, w = self.cfg, self.rng, self.world
        us = w.self_party.party_id
        for i, v in enumerate(w.vendors()):
            d = self.biz_day(1, 2, 10)
            terms = rng.choice(TERMS_CHOICES)
            self.emit(d, "TERMS_AGREED", v.party_id, us,
                      {"relation": "payment_terms", "value": terms})
            self.set_fact(v.party_id, "payment_terms", terms, d)
            item = w.items[i % len(w.items)]
            self.vendor_items[v.party_id] = item
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
        self._lease_root, self._lease_doc = lease_root, lease
        if self.cur_months >= 7:
            self._amend_lease(rent)

    def _amend_lease(self, old_rent: int) -> None:
        """Rent amendment on the SAME root chain: version numbers and the
        supersedes pointers continue across years."""
        rng, landlord = self.rng, self.world.landlord()
        prev = self._lease_doc
        d = self.biz_day(7, 1, 15)
        new_rent = old_rent + rng.randrange(5_000, 40_000)
        ev = self.emit(d, "LEASE_AMENDED", landlord.party_id,
                       self.world.self_party.party_id,
                       {"monthly_rent_cents": new_rent},
                       {"root": self._lease_root})
        self._lease_doc = self.add_doc(
            "lease", self._lease_root, prev.version + 1, prev.doc_id,
            landlord.party_id, d,
            {**prev.fields, "monthly_rent_cents": new_rent,
             "amended_date": d.isoformat()}, ev)
        self.set_fact(landlord.party_id, "monthly_rent", new_rent, d)

    def _lease_review(self) -> None:
        """Non-opening years: an annual review that amends the rent with
        probability LEASE_REVIEW_PROB (skipped when the final year is too
        short to reach the review month, mirroring the year-1 rule)."""
        if self.cur_months < 7:
            return
        if self.rng.random() >= LEASE_REVIEW_PROB:
            return
        landlord = self.world.landlord()
        old_rent = self.get_fact(landlord.party_id, "monthly_rent",
                                 date(self.cur_year, 1, 1))
        self._amend_lease(old_rent)

    def _schedule_renegotiations(self) -> None:
        """Mid-year renegotiations (terms supersession) at staggered months.
        Scheduled and recorded BEFORE the trading loop so cross-month
        spillover (a PO from month m invoiced in month m+1) reads correct
        as-of terms. Runs once per year: a party renegotiated in year 1 may
        renegotiate again in year 2, producing a 3-interval fact chain."""
        cfg, rng, w = self.cfg, self.rng, self.world
        us = w.self_party.party_id
        renegotiable = w.vendors() + w.customers()
        rng.shuffle(renegotiable)
        n_reneg = round(len(renegotiable) * cfg.renegotiate_frac)
        for i, p in enumerate(renegotiable[:n_reneg]):
            month = 4 + (i % max(1, min(6, self.cur_months - 4)))
            if month > self.cur_months:
                continue
            d = self.biz_day(month, 1, 12)
            old = self.get_fact(p.party_id, "payment_terms", d)
            new = rng.choice([t for t in TERMS_CHOICES if t != old])
            actor, cp = (p.party_id, us) if p.kind == "vendor" else (us, p.party_id)
            self.emit(d, "TERMS_AGREED", actor, cp,
                      {"relation": "payment_terms", "value": new,
                       "previous": old, "renegotiation": True})
            self.set_fact(p.party_id, "payment_terms", new, d)

    def _trading_year(self) -> None:
        cfg, rng, w = self.cfg, self.rng, self.world
        for month in range(1, self.cur_months + 1):
            for v in w.vendors():
                for _ in range(rng.randint(*cfg.pos_per_vendor_month)):
                    self._po_cycle(month, v.party_id,
                                   self.vendor_items[v.party_id])

            for c in w.customers():
                for _ in range(rng.randint(*cfg.sales_per_customer_month)):
                    self._sales_cycle(month, c.party_id)

    def _mid_month(self) -> int:
        """A month in the middle third of the current year."""
        lo = self.cur_months // 3 + 1
        hi = max(lo, (2 * self.cur_months) // 3)
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
            dest = rng.choice([v for v in vendors
                               if v.party_id != src.party_id])
            d = self.biz_day(self._mid_month(), 1, 20)
            # Year 1 keeps the original date-free pick (byte identity).
            # Later years pick the ACTING contact at the move date, so a
            # party that received a mover earlier hands over the person the
            # renderer's most-recent-joiner rule actually uses.
            mover = w.contact_for(src.party_id) \
                if self.cur_year == cfg.year \
                else w.contact_for(src.party_id, on=d)
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

        Applies to a per-year fraction of trading-party contacts that have
        not moved or changed before (single address period, open since
        before the current year). Closes the current address period and
        opens a new one at the same domain with a different local part
        (first initial + last name instead of first.last).
        """
        cfg, rng, w = self.cfg, self.rng, self.world
        us = w.self_party.party_id
        trading = {p.party_id for p in w.vendors() + w.customers()}
        cur_start = date(self.cur_year, 1, 1)
        eligible = [p for p in w.people
                    if p.party_id in trading and len(p.addresses) == 1
                    and p.addresses[0].from_date <= cur_start]
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
        root = f"PO-{self.cur_year}-{self._po_n:04d}"
        qty = rng.randrange(10, 200, 5)
        price = self.get_fact(vendor, f"unit_price:{item}", d)
        fields = {"po_number": root, "item": item, "qty": qty,
                  "unit_price_cents": price, "total_cents": qty * price}
        ev = self.emit(d, "PO_ISSUED", us, vendor, dict(fields))
        doc = self.add_doc("po", root, 1, None, vendor, d, fields, ev)

        while rng.random() < (cfg.amend_prob if doc.version == 1
                              else cfg.second_amend_prob):
            # clamped to the corpus end; max() keeps the amendment from
            # landing BEFORE the order when a weekend-shifted December PO
            # already sits past the clamp date
            d = max(d, min(d + timedelta(days=rng.randint(2, 6)),
                           date(self.last_year, 12, 28)))
            qty = max(5, qty + rng.choice([-1, 1]) * rng.randrange(5, 50, 5))
            fields = {**doc.fields, "qty": qty, "total_cents": qty * price}
            ev = self.emit(d, "PO_AMENDED", us, vendor,
                           {"qty": qty, "total_cents": qty * price},
                           {"root": root})
            doc = self.add_doc("po", root, doc.version + 1, doc.doc_id, vendor,
                               d, fields, ev)

        # Vendor invoices against the final PO state. Clamped to the CORPUS
        # end only: a December cycle of a non-final year may invoice in
        # January of the next year (its number stays in the cycle's series).
        d_inv = min(d + timedelta(days=rng.randint(3, 10)),
                    date(self.last_year, 12, 29))
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
        inv_id = f"INV-{self.cur_year}-{self._inv_n:04d}"
        terms = self.get_fact(party, "payment_terms", d)
        due = d + timedelta(days=terms_days(terms))
        fields = {"invoice_number": inv_id, "issuer": issuer, "bill_to": payer,
                  "issue_date": d.isoformat(), "due_date": due.isoformat(),
                  "terms": terms, "total_cents": amount}
        if po_ref:
            fields["po_ref"] = po_ref
        ev = self.emit(d, "INVOICE_ISSUED", issuer, payer, dict(fields))
        self.add_doc("invoice", inv_id, 1, None, party, d, fields, ev)

        # G3 near-duplicate screw. The flag check comes FIRST so the rng
        # draw only ever happens with the screw on: flags-off corpora keep
        # their exact draw sequence.
        if cfg.near_dup_invoices > 0 and payer == us \
                and rng.random() < cfg.near_dup_invoices:
            self._near_dup_invoice(d, inv_id, fields, issuer, payer, party)

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
                         date(self.last_year, 12, 29))
            disputed_cents = rng.randrange(1_000, amount // 2 + 1)
            reason = rng.choice(DISPUTE_REASONS)
            self.emit(d_disp, "INVOICE_DISPUTED", us, issuer,
                      {"invoice_ref": inv_id, "disputed_cents": disputed_cents,
                       "reason": reason}, {"invoice": inv_id})
            d_res = min(d_disp + timedelta(days=rng.randint(3, 10)),
                        date(self.last_year, 12, 30))
            if rng.random() < 0.6:
                self._cn_n += 1
                cn_id = f"CN-{self.cur_year}-{self._cn_n:04d}"
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
            cn_id = f"CN-{self.cur_year}-{self._cn_n:04d}"
            d_cn = min(d + timedelta(days=rng.randint(2, 8)),
                       date(self.last_year, 12, 30))
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
                    date(self.last_year, 12, 31))
        d_pay = max(d_pay, d + timedelta(days=1))
        self.emit(d_pay, pay_type, payer, issuer,
                  {"amount_cents": amount, "invoice_ref": inv_id,
                   "method": "bank transfer"},
                  {"invoice": inv_id})

    def _near_dup_invoice(self, d: date, orig_id: str, fields: dict,
                          issuer: str, payer: str, party: str) -> None:
        """The vendor re-sends the invoice verbatim under the next invoice
        number one day later, then voids it with a correction one day after
        that. Field content (issue date, due date, terms, total, po ref) is
        copied verbatim from the original; only the invoice number differs,
        plus the ground-truth bookkeeping fields duplicate_of and
        voided_by_correction (never rendered into the corpus). Payments
        ignore the duplicate and question samplers never touch it, but the
        duplicate does consume its number in the INV series."""
        self._inv_n += 1
        dup_id = f"INV-{self.cur_year}-{self._inv_n:04d}"
        dup_fields = {**fields, "invoice_number": dup_id,
                      "duplicate_of": orig_id, "voided_by_correction": True}
        d_dup = min(d + timedelta(days=1), date(self.last_year, 12, 30))
        ev = self.emit(d_dup, "INVOICE_ISSUED", issuer, payer,
                       dict(dup_fields))
        self.add_doc("invoice", dup_id, 1, None, party, d_dup, dup_fields, ev)
        d_corr = min(d_dup + timedelta(days=1), date(self.last_year, 12, 31))
        self.emit(d_corr, "INVOICE_CORRECTED", issuer, payer,
                  {"duplicate_ref": dup_id, "original_ref": orig_id},
                  {"invoice": dup_id})


def simulate(cfg: Config) -> SimResult:
    return _Sim(cfg).run()
