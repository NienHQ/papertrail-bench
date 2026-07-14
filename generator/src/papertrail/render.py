"""Layer 3: render the event log into email correspondence.

Each event type has a communication script producing one or more messages.
Message bodies are assembled from statements; each statement's character span in
the decoded text/plain body is recorded, with the ground-truth targets it asserts.
Statements with empty targets are deliberate distractors (e.g. a renegotiation
*request* before the agreement).

B0 renders clean corpora: full References chains, canonical occurrences only,
text/plain attachments. Realism screws land in B1 without schema changes.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .model import Document, Event, Message, Person, StatementOccurrence, Thread, money
from .simulate import SimResult
from .world import World

GREETINGS = ["Hi {first},", "Hello {first},", "Dear {first},", "{first},"]
CLOSINGS = ["Best regards", "Regards", "Thanks", "Kind regards", "Best"]


@dataclass
class RenderResult:
    threads: list[Thread]
    messages: list[Message]
    # target key -> [(message_id, statement_id)]; keys: ("fact", id),
    # ("event", id), ("doc_field", doc_id, field)
    evidence_index: dict[tuple, list[tuple[str, str]]] = field(default_factory=dict)


class _BodyBuilder:
    """Assembles a body string while recording statement spans."""

    def __init__(self, message_id: str):
        self.message_id = message_id
        self.parts: list[str] = []
        self.pos = 0
        self.statements: list[StatementOccurrence] = []
        self._sid = 0

    def raw(self, text: str) -> None:
        self.parts.append(text)
        self.pos += len(text)

    def statement(self, text: str, targets: list[dict]) -> None:
        self._sid += 1
        sid = f"{self.message_id}-S{self._sid}"
        start = self.pos
        self.raw(text)
        self.statements.append(StatementOccurrence(
            statement_id=sid, message_id=self.message_id,
            span=(start, start + len(text)), occurrence="canonical",
            targets=targets, text=text))
        self.raw("\n")

    def build(self) -> str:
        return "".join(self.parts)


class _Renderer:
    def __init__(self, sim: SimResult, event_fact: dict[str, str], seed: int):
        self.sim = sim
        self.world: World = sim.world
        self.event_fact = event_fact
        self.rng = random.Random(seed ^ 0x5AFE)
        self.threads: list[Thread] = []
        self.messages: list[Message] = []
        self.evidence_index: dict[tuple, list[tuple[str, str]]] = {}
        self._tid = 0
        self._mid = 0
        self.docs_by_id = {d.doc_id: d for d in sim.documents}
        # thread reuse: one thread per business object chain / negotiation
        self.threads_by_key: dict[str, Thread] = {}
        self.last_msg_in_thread: dict[str, Message] = {}
        # bare message id -> full RFC5322 Message-ID header (sender's domain)
        self.header_mid: dict[str, str] = {}

    # -- plumbing ---------------------------------------------------------

    def new_thread(self, key: str, subject: str) -> Thread:
        self._tid += 1
        t = Thread(thread_id=f"THR-{self._tid:04d}", subject=subject,
                   participants=[])
        self.threads.append(t)
        self.threads_by_key[key] = t
        return t

    def compose(self, thread_key: str, subject: str, ts: datetime,
                sender: Person, to: list[Person],
                write_body, attachments: list[str] | None = None) -> Message:
        thread = self.threads_by_key.get(thread_key)
        is_reply = thread is not None
        if thread is None:
            thread = self.new_thread(thread_key, subject)
        prev = self.last_msg_in_thread.get(thread.thread_id)
        self._mid += 1
        mid = f"MSG-{self._mid:06d}"
        self.header_mid[mid] = \
            f"<{mid}@{self.world.party(sender.party_id).domain}>"
        d = ts.date()
        b = _BodyBuilder(mid)
        recipient = to[0]
        b.raw(self.rng.choice(GREETINGS).format(first=recipient.first) + "\n\n")
        write_body(b)
        b.raw(f"\n{self.rng.choice(CLOSINGS)},\n{sender.first}\n"
              f"{self.world.party(sender.party_id).name}\n")
        msg = Message(
            message_id=mid, thread_id=thread.thread_id, ts=ts,
            from_person=sender.person_id, from_address=sender.address_on(d),
            from_name=sender.name,
            to=[(p.name, p.address_on(d)) for p in to],
            subject=(f"Re: {thread.subject}" if is_reply else subject),
            in_reply_to=self.header_mid[prev.message_id] if prev else None,
            references=(prev.references + [self.header_mid[prev.message_id]])
            if prev else [],
            attachments=list(attachments or []),
            body=b.build(), statements=b.statements)
        self.messages.append(msg)
        self.last_msg_in_thread[thread.thread_id] = msg
        for p in [sender] + to:
            if p.person_id not in thread.participants:
                thread.participants.append(p.person_id)
        for s in b.statements:
            for t in s.targets:
                self.evidence_index.setdefault(_target_key(t), []).append(
                    (mid, s.statement_id))
        return msg

    def us(self, role: str) -> Person:
        return self.world.contact_for(self.world.self_party.party_id, role)

    def them(self, party_id: str) -> Person:
        return self.world.contact_for(party_id)

    def reply_ts(self, ts: datetime) -> datetime:
        return ts + timedelta(hours=self.rng.randint(2, 30))

    # -- event scripts ----------------------------------------------------

    def render(self) -> RenderResult:
        for ev in self.sim.events:
            getattr(self, f"_ev_{ev.type.lower()}")(ev)
        self.messages.sort(key=lambda m: (m.ts, m.message_id))
        return RenderResult(threads=self.threads, messages=self.messages,
                            evidence_index=self.evidence_index)

    def _ev_terms_agreed(self, ev: Event) -> None:
        w = self.world
        entity = ev.actor_party if ev.actor_party != w.self_party.party_id \
            else ev.counterparty
        party = w.party(entity)
        contact, ours = self.them(entity), self.us("accounts payable" if
                                                   party.kind == "vendor"
                                                   else "accounts receivable")
        fact_t = {"fact": self.event_fact[ev.event_id]}
        value = ev.payload["value"]
        terms_txt = f"NET {value.removeprefix('NET')}"
        key = f"terms:{entity}:{ev.event_id}"
        if ev.payload.get("renegotiation"):
            prev = ev.payload["previous"]
            subj = f"Payment terms review - {party.name}" \
                if party.kind == "customer" else \
                f"Payment terms review - {w.self_party.name}"
            requester, approver = (contact, ours) if party.kind == "vendor" \
                else (ours, contact)
            self.compose(
                key, subj, ev.event_time - timedelta(days=2), requester,
                [approver],
                lambda b: b.statement(
                    f"Given our trading volume this year, we would like to "
                    f"revise payment terms from {prev.removeprefix('NET')} to "
                    f"{value.removeprefix('NET')} days going forward.", []))
            self.compose(
                key, subj, ev.event_time, approver, [requester],
                lambda b: b.statement(
                    f"Confirmed - payment terms between {w.self_party.name} and "
                    f"{party.name} are {terms_txt} effective "
                    f"{ev.event_time.date().isoformat()}.", [fact_t]))
        else:
            sender, rcpt = (contact, ours) if party.kind == "vendor" \
                else (ours, contact)
            self.compose(
                key, f"Trading terms - {party.name} / {w.self_party.name}",
                ev.event_time, sender, [rcpt],
                lambda b: b.statement(
                    f"This confirms payment terms of {terms_txt} between "
                    f"{w.self_party.name} and {party.name}, effective "
                    f"{ev.event_time.date().isoformat()}.", [fact_t]))

    def _ev_price_agreed(self, ev: Event) -> None:
        w = self.world
        party = w.party(ev.actor_party)
        item = ev.payload["item"]
        fact_t = {"fact": self.event_fact[ev.event_id]}
        self.compose(
            f"price:{party.party_id}:{ev.event_id}",
            f"Pricing - {item}", ev.event_time,
            self.them(party.party_id), [self.us("purchasing")],
            lambda b: b.statement(
                f"We can confirm a unit price of {money(ev.payload['value'])} "
                f"per unit for {item}, effective "
                f"{ev.event_time.date().isoformat()}.", [fact_t]))

    def _ev_lease_signed(self, ev: Event) -> None:
        w = self.world
        doc = self.docs_by_id[ev.refs["doc"]]
        fact_t = {"fact": self.event_fact[ev.event_id]}
        rent = ev.payload["monthly_rent_cents"]

        def body(b):
            b.statement(
                f"Please find attached the signed lease {doc.doc_id} for the "
                f"premises, with a term of {ev.payload['term_months']} months.",
                [{"doc_field": [doc.doc_id, "term_months"]}])
            b.statement(
                f"Monthly rent is {money(rent)}, effective "
                f"{ev.event_time.date().isoformat()}.",
                [fact_t, {"doc_field": [doc.doc_id, "monthly_rent_cents"]}])

        self.compose(f"lease:{doc.root_id}", f"Lease agreement {doc.root_id}",
                     ev.event_time, self.them(doc.party_id),
                     [self.us("operations")], body, attachments=[doc.doc_id])

    def _ev_lease_amended(self, ev: Event) -> None:
        doc = self.docs_by_id[ev.refs["doc"]]
        fact_t = {"fact": self.event_fact[ev.event_id]}
        rent = ev.payload["monthly_rent_cents"]

        def body(b):
            b.statement(
                f"As per our review clause, monthly rent under lease "
                f"{doc.root_id} is revised to {money(rent)} effective "
                f"{ev.event_time.date().isoformat()}.",
                [fact_t, {"doc_field": [doc.doc_id, "monthly_rent_cents"]}])
            b.statement(
                f"The amendment document {doc.doc_id} is attached.",
                [{"doc_field": [doc.doc_id, "lease_number"]}])

        self.compose(f"lease:{doc.root_id}", "", ev.event_time,
                     self.them(doc.party_id), [self.us("operations")], body,
                     attachments=[doc.doc_id])

    def _ev_po_issued(self, ev: Event) -> None:
        doc = self.docs_by_id[ev.refs["doc"]]
        f = doc.fields
        buyer, seller = self.us("purchasing"), self.them(doc.party_id)

        def body(b):
            b.statement(
                f"Please find attached purchase order {f['po_number']} for "
                f"{f['qty']} units of {f['item']} at "
                f"{money(f['unit_price_cents'])} per unit.",
                [{"doc_field": [doc.doc_id, "qty"]},
                 {"doc_field": [doc.doc_id, "unit_price_cents"]}])
            b.statement(
                f"The order total is {money(f['total_cents'])}.",
                [{"doc_field": [doc.doc_id, "total_cents"]}])

        self.compose(f"po:{doc.root_id}",
                     f"Purchase order {f['po_number']} - {f['item']}",
                     ev.event_time, buyer, [seller], body,
                     attachments=[doc.doc_id])
        self.compose(f"po:{doc.root_id}", "", self.reply_ts(ev.event_time),
                     seller, [buyer],
                     lambda b: b.statement(
                         f"Confirming receipt of {f['po_number']}; we will "
                         f"schedule this for delivery.", [{"event": ev.event_id}]))

    def _ev_po_amended(self, ev: Event) -> None:
        doc = self.docs_by_id[ev.refs["doc"]]
        f = doc.fields

        def body(b):
            b.statement(
                f"Please amend {doc.root_id}: quantity is now {f['qty']} units "
                f"of {f['item']}, revised order total {money(f['total_cents'])}.",
                [{"doc_field": [doc.doc_id, "qty"]},
                 {"doc_field": [doc.doc_id, "total_cents"]}])
            b.statement(
                f"The amended purchase order is attached as {doc.doc_id}.",
                [{"doc_field": [doc.doc_id, "po_number"]}])

        self.compose(f"po:{doc.root_id}", "", ev.event_time,
                     self.us("purchasing"), [self.them(doc.party_id)], body,
                     attachments=[doc.doc_id])

    def _ev_invoice_issued(self, ev: Event) -> None:
        w = self.world
        doc = self.docs_by_id[ev.refs["doc"]]
        f = doc.fields
        we_issue = ev.actor_party == w.self_party.party_id
        sender = self.us("accounts receivable") if we_issue \
            else self.them(doc.party_id)
        rcpt = self.them(doc.party_id) if we_issue \
            else self.us("accounts payable")

        def body(b):
            po_bit = f" against {f['po_ref']}" if "po_ref" in f else ""
            b.statement(
                f"Please find attached invoice {f['invoice_number']}{po_bit} "
                f"for {money(f['total_cents'])}.",
                [{"doc_field": [doc.doc_id, "total_cents"]}] +
                ([{"doc_field": [doc.doc_id, "po_ref"]}] if "po_ref" in f else []))
            b.statement(
                f"Payment is due by {f['due_date']} per our {f['terms']} terms.",
                [{"doc_field": [doc.doc_id, "due_date"]}])

        thread_key = f"po:{f['po_ref'].split('-A')[0]}" if "po_ref" in f \
            else f"inv:{doc.doc_id}"
        if "po_ref" in f:
            # invoice arrives on the existing PO thread
            self.compose(thread_key, "", ev.event_time, sender, [rcpt], body,
                         attachments=[doc.doc_id])
        else:
            self.compose(thread_key,
                         f"Invoice {f['invoice_number']} from "
                         f"{w.party(ev.actor_party).name}",
                         ev.event_time, sender, [rcpt], body,
                         attachments=[doc.doc_id])

    def _ev_credit_note_issued(self, ev: Event) -> None:
        doc = self.docs_by_id[ev.refs["doc"]]
        f = doc.fields
        we_issue = ev.actor_party == self.world.self_party.party_id
        sender = self.us("accounts receivable") if we_issue \
            else self.them(doc.party_id)
        rcpt = self.them(doc.party_id) if we_issue \
            else self.us("accounts payable")
        inv = self.docs_by_id[f["invoice_ref"]]
        thread_key = f"po:{inv.fields['po_ref'].split('-A')[0]}" \
            if "po_ref" in inv.fields else f"inv:{inv.doc_id}"

        def body(b):
            b.statement(
                f"We have issued credit note {f['credit_note_number']} for "
                f"{money(f['amount_cents'])} against invoice "
                f"{f['invoice_ref']} ({f['reason']}).",
                [{"doc_field": [doc.doc_id, "amount_cents"]},
                 {"doc_field": [doc.doc_id, "invoice_ref"]},
                 {"doc_field": [doc.doc_id, "reason"]}])

        self.compose(thread_key, f"Credit note {f['credit_note_number']}",
                     ev.event_time, sender, [rcpt], body,
                     attachments=[doc.doc_id])

    def _ev_payment_sent(self, ev: Event) -> None:
        self._payment(ev)

    def _ev_payment_received(self, ev: Event) -> None:
        self._payment(ev)

    def _payment(self, ev: Event) -> None:
        w = self.world
        inv = self.docs_by_id[ev.refs["invoice"]]
        we_pay = ev.actor_party == w.self_party.party_id
        sender = self.us("accounts payable") if we_pay \
            else self.them(inv.party_id)
        rcpt = self.them(inv.party_id) if we_pay \
            else self.us("accounts receivable")
        thread_key = f"po:{inv.fields['po_ref'].split('-A')[0]}" \
            if "po_ref" in inv.fields else f"inv:{inv.doc_id}"
        self.compose(
            thread_key, f"Payment - invoice {inv.doc_id}", ev.event_time,
            sender, [rcpt],
            lambda b: b.statement(
                f"Payment of {money(ev.payload['amount_cents'])} for invoice "
                f"{ev.payload['invoice_ref']} was sent today by "
                f"{ev.payload['method']}.", [{"event": ev.event_id}]))


def _target_key(t: dict) -> tuple:
    if "fact" in t:
        return ("fact", t["fact"])
    if "event" in t:
        return ("event", t["event"])
    return ("doc_field", t["doc_field"][0], t["doc_field"][1])


def render(sim: SimResult, event_fact: dict[str, str]) -> RenderResult:
    return _Renderer(sim, event_fact, sim.config.seed).render()


# -- attachment + EML rendering ------------------------------------------------

_DOC_TITLES = {"po": "PURCHASE ORDER", "invoice": "INVOICE",
               "credit_note": "CREDIT NOTE", "lease": "LEASE AGREEMENT"}
_MONEY_FIELDS = {"unit_price_cents", "total_cents", "amount_cents",
                 "monthly_rent_cents"}


def render_attachment(doc: Document, world: World) -> bytes:
    lines = [f"{_DOC_TITLES[doc.kind]} {doc.doc_id}",
             f"Date: {doc.issued_date.isoformat()}",
             f"Party: {world.party(doc.party_id).name}", ""]
    for k, v in doc.fields.items():
        label = k.removesuffix("_cents").replace("_", " ").capitalize()
        if isinstance(v, str) and v.startswith("PTY-"):
            v = world.party(v).name  # documents show names, ground truth keeps ids
        lines.append(f"{label}: {money(v) if k in _MONEY_FIELDS else v}")
    return ("\n".join(lines) + "\n").encode("ascii")


def render_eml(msg: Message, world: World, docs_by_id: dict[str, Document]
               ) -> bytes:
    from email.message import EmailMessage
    from email.policy import SMTP
    from email.utils import format_datetime

    domain = world.party(
        next(p for p in world.people
             if p.person_id == msg.from_person).party_id).domain
    m = EmailMessage(policy=SMTP)
    m["From"] = f"{msg.from_name} <{msg.from_address}>"
    m["To"] = ", ".join(f"{n} <{a}>" for n, a in msg.to)
    m["Subject"] = msg.subject
    m["Date"] = format_datetime(msg.ts)
    m["Message-ID"] = f"<{msg.message_id}@{domain}>"
    if msg.in_reply_to:
        m["In-Reply-To"] = msg.in_reply_to
    if msg.references:
        m["References"] = " ".join(msg.references)
    m.set_content(msg.body)
    for doc_id in msg.attachments:
        doc = docs_by_id[doc_id]
        m.add_attachment(render_attachment(doc, world).decode("ascii"),
                         filename=f"{doc_id}.txt")
    if msg.attachments:
        m.set_boundary(f"=-PTB-{msg.message_id}")
    return m.as_bytes()
