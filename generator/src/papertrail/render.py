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

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

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

    def __init__(self, message_id: str, format_drift: bool = False):
        self.message_id = message_id
        self.format_drift = format_drift
        self.parts: list[str] = []
        self.pos = 0
        self.statements: list[StatementOccurrence] = []
        self._sid = 0

    def raw(self, text: str) -> None:
        self.parts.append(text)
        self.pos += len(text)

    def money(self, cents: int) -> str:
        """Money as statement prose. With the format_drift screw on, the
        form is picked deterministically from a hash of (message id, index
        of the statement about to be written): no rng draws either way, so
        the screw never shifts the generator's random sequence. All three
        forms are within what the harness money scorer normalizes."""
        if not self.format_drift or cents < 0:
            return money(cents)
        digest = hashlib.sha256(
            f"{self.message_id}:{self._sid + 1}".encode("ascii")).digest()
        form = digest[0] % 3
        if form == 0:
            return money(cents)
        if form == 1:
            return (f"{cents // 100} USD" if cents % 100 == 0
                    else f"{cents // 100}.{cents % 100:02d} USD")
        return f"USD {cents // 100:,}.{cents % 100:02d}"

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
        self.cfg = sim.config
        self.world: World = sim.world
        self.event_fact = event_fact
        self.rng = random.Random(seed ^ 0x5AFE)
        self.threads: list[Thread] = []
        self.messages: list[Message] = []
        self.evidence_index: dict[tuple, list[tuple[str, str]]] = {}
        self._tid = 0
        self._mid = 0
        # per-thread message count, for the truncate_references screw's
        # deterministic every-5th-reply header drop (no rng involved)
        self.thread_msg_no: dict[str, int] = {}
        self.docs_by_id = {d.doc_id: d for d in sim.documents}
        self.people_by_id = {p.person_id: p for p in sim.world.people}
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
        # Per-thread monotone clock: a reply is never dated before the
        # message it answers. Year-end clamps can put the next event on the
        # same calendar day as its predecessor while the predecessor's ack
        # drew a many-hour reply delay; without this bump the reply would
        # sort before the message its References point at. No-op (and so
        # byte-identical) for corpora where the inversion never occurs.
        if prev is not None and ts < prev.ts:
            ts = prev.ts + timedelta(minutes=1)
        self._mid += 1
        mid = f"MSG-{self._mid:06d}"
        d = ts.date()
        # Message-ID domain follows the sending address at send time, so a
        # mover's pre-move mail carries the old employer's domain.
        self.header_mid[mid] = \
            f"<{mid}@{sender.address_on(d).split('@', 1)[1]}>"
        b = _BodyBuilder(mid, self.cfg.format_drift)
        recipient = to[0]
        b.raw(self.rng.choice(GREETINGS).format(first=recipient.first) + "\n\n")
        write_body(b)
        b.raw(f"\n{self.rng.choice(CLOSINGS)},\n{sender.first}\n"
              f"{self.world.party(sender.party_id).name}\n")
        body = b.build()
        statements = list(b.statements)
        if self.cfg.quoted_replies and prev is not None:
            body, statements = self._append_quote(mid, body, statements, prev)

        in_reply_to = self.header_mid[prev.message_id] if prev else None
        references = (prev.references + [self.header_mid[prev.message_id]]) \
            if prev else []
        if self.cfg.truncate_references and prev is not None:
            # reply index within the thread (root = message 0); every 5th
            # reply continues by subject only, per the schema doc screw
            reply_no = self.thread_msg_no.get(thread.thread_id, 1)
            if reply_no % 5 == 0:
                in_reply_to, references = None, []
            else:
                references = references[-2:]

        msg = Message(
            message_id=mid, thread_id=thread.thread_id, ts=ts,
            from_person=sender.person_id, from_address=sender.address_on(d),
            from_name=sender.name,
            to=[(p.name, p.address_on(d)) for p in to],
            subject=(f"Re: {thread.subject}" if is_reply else subject),
            in_reply_to=in_reply_to,
            references=references,
            attachments=list(attachments or []),
            body=body, statements=statements)
        self.messages.append(msg)
        self.last_msg_in_thread[thread.thread_id] = msg
        self.thread_msg_no[thread.thread_id] = \
            self.thread_msg_no.get(thread.thread_id, 0) + 1
        for p in [sender] + to:
            if p.person_id not in thread.participants:
                thread.participants.append(p.person_id)
        # Only canonical statements enter the evidence index: question
        # evidence sets never point at quoted copies (schema doc 6.1).
        for s in b.statements:
            for t in s.targets:
                self.evidence_index.setdefault(_target_key(t), []).append(
                    (mid, s.statement_id))
        return msg

    def _append_quote(self, mid: str, body: str,
                      statements: list[StatementOccurrence],
                      prev: Message) -> tuple[str, list[StatementOccurrence]]:
        """quoted_replies screw: append the previous message's body with
        every line prefixed "> ", and re-emit each of its statements as an
        occurrence: quoted row of THIS message. Statement texts never
        contain newlines (asserted), so each quoted statement stays
        contiguous in the prefixed block and the span invariant
        body[start:end] == text keeps holding."""
        header = f"\n\nOn {prev.ts.date().isoformat()}, " \
                 f"{prev.from_name} wrote:\n"
        prefixed = "\n".join("> " + line for line in prev.body.split("\n"))
        block_start = len(body) + len(header)
        # bodies must end with a newline: MIME serialization appends one
        # to unterminated text and would break the roundtrip invariant
        new_body = body + header + prefixed + "\n"
        out = list(statements)
        for qn, s in enumerate(prev.statements, start=1):
            assert "\n" not in s.text, s.statement_id
            start = s.span[0]
            # one "> " prefix for every line up to and including the
            # statement's own line
            offset = block_start + start + 2 * (prev.body.count("\n", 0, start) + 1)
            occ = StatementOccurrence(
                statement_id=f"{mid}-Q{qn}", message_id=mid,
                span=(offset, offset + len(s.text)), occurrence="quoted",
                targets=[dict(t) for t in s.targets], text=s.text)
            assert new_body[occ.span[0]:occ.span[1]] == s.text
            out.append(occ)
        return new_body, out

    def us(self, role: str) -> Person:
        return self.world.contact_for(self.world.self_party.party_id, role)

    def them(self, party_id: str, on: date | None = None) -> Person:
        """The counterparty contact, date-aware where the caller knows the
        message date, so pre-move mail comes from the mover and post-move
        mail from the replacement (old party) or the mover (new party)."""
        return self.world.contact_for(party_id, on=on)

    def reply_ts(self, ts: datetime) -> datetime:
        return ts + timedelta(hours=self.rng.randint(2, 30))

    def invoice_thread_key(self, inv: Document) -> str:
        return f"po:{inv.fields['po_ref'].split('-A')[0]}" \
            if "po_ref" in inv.fields else f"inv:{inv.doc_id}"

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
        ours = self.us("accounts payable" if party.kind == "vendor"
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
            req_ts = ev.event_time - timedelta(days=2)
            # contacts resolved per message date: sender and recipient stay
            # correct across a CONTACT_CHANGED or PERSON_MOVED boundary
            contact_req = self.them(entity, req_ts.date())
            contact_conf = self.them(entity, ev.event_time.date())
            requester, req_to = (contact_req, ours) \
                if party.kind == "vendor" else (ours, contact_req)
            approver, conf_to = (ours, contact_conf) \
                if party.kind == "vendor" else (contact_conf, ours)
            self.compose(
                key, subj, req_ts, requester, [req_to],
                lambda b: b.statement(
                    f"Given our trading volume this year, we would like to "
                    f"revise payment terms from {prev.removeprefix('NET')} to "
                    f"{value.removeprefix('NET')} days going forward.", []))
            self.compose(
                key, subj, ev.event_time, approver, [conf_to],
                lambda b: b.statement(
                    f"Confirmed - payment terms between {w.self_party.name} and "
                    f"{party.name} are {terms_txt} effective "
                    f"{ev.event_time.date().isoformat()}.", [fact_t]))
        else:
            contact = self.them(entity, ev.event_time.date())
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
            self.them(party.party_id, ev.event_time.date()),
            [self.us("purchasing")],
            lambda b: b.statement(
                f"We can confirm a unit price of {b.money(ev.payload['value'])} "
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
                f"Monthly rent is {b.money(rent)}, effective "
                f"{ev.event_time.date().isoformat()}.",
                [fact_t, {"doc_field": [doc.doc_id, "monthly_rent_cents"]}])

        self.compose(f"lease:{doc.root_id}", f"Lease agreement {doc.root_id}",
                     ev.event_time,
                     self.them(doc.party_id, ev.event_time.date()),
                     [self.us("operations")], body, attachments=[doc.doc_id])

    def _ev_lease_amended(self, ev: Event) -> None:
        doc = self.docs_by_id[ev.refs["doc"]]
        fact_t = {"fact": self.event_fact[ev.event_id]}
        rent = ev.payload["monthly_rent_cents"]

        def body(b):
            b.statement(
                f"As per our review clause, monthly rent under lease "
                f"{doc.root_id} is revised to {b.money(rent)} effective "
                f"{ev.event_time.date().isoformat()}.",
                [fact_t, {"doc_field": [doc.doc_id, "monthly_rent_cents"]}])
            b.statement(
                f"The amendment document {doc.doc_id} is attached.",
                [{"doc_field": [doc.doc_id, "lease_number"]}])

        self.compose(f"lease:{doc.root_id}", "", ev.event_time,
                     self.them(doc.party_id, ev.event_time.date()),
                     [self.us("operations")], body,
                     attachments=[doc.doc_id])

    def _ev_po_issued(self, ev: Event) -> None:
        doc = self.docs_by_id[ev.refs["doc"]]
        f = doc.fields
        buyer = self.us("purchasing")
        seller = self.them(doc.party_id, ev.event_time.date())

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
        # the ack sender is resolved at the ack's own date, so an ack that
        # lands after a PERSON_MOVED comes from the replacement
        ack_ts = self.reply_ts(ev.event_time)
        self.compose(f"po:{doc.root_id}", "", ack_ts,
                     self.them(doc.party_id, ack_ts.date()), [buyer],
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
                     self.us("purchasing"),
                     [self.them(doc.party_id, ev.event_time.date())], body,
                     attachments=[doc.doc_id])

    def _ev_invoice_issued(self, ev: Event) -> None:
        w = self.world
        doc = self.docs_by_id[ev.refs["doc"]]
        f = doc.fields
        we_issue = ev.actor_party == w.self_party.party_id
        contact = self.them(doc.party_id, ev.event_time.date())
        sender = self.us("accounts receivable") if we_issue else contact
        rcpt = contact if we_issue else self.us("accounts payable")

        def body(b):
            po_bit = f" against {f['po_ref']}" if "po_ref" in f else ""
            b.statement(
                f"Please find attached invoice {f['invoice_number']}{po_bit} "
                f"for {b.money(f['total_cents'])}.",
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
        contact = self.them(doc.party_id, ev.event_time.date())
        sender = self.us("accounts receivable") if we_issue else contact
        rcpt = contact if we_issue else self.us("accounts payable")
        inv = self.docs_by_id[f["invoice_ref"]]
        thread_key = self.invoice_thread_key(inv)

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

    def _ev_invoice_disputed(self, ev: Event) -> None:
        inv = self.docs_by_id[ev.refs["invoice"]]
        self.compose(
            self.invoice_thread_key(inv), f"Dispute - invoice {inv.doc_id}",
            ev.event_time, self.us("accounts payable"),
            [self.them(inv.party_id, ev.event_time.date())],
            lambda b: b.statement(
                f"We dispute {b.money(ev.payload['disputed_cents'])} on invoice "
                f"{ev.payload['invoice_ref']}: {ev.payload['reason']}.",
                [{"event": ev.event_id}]))

    def _ev_invoice_corrected(self, ev: Event) -> None:
        """near_dup_invoices screw: the vendor voids the duplicate on the
        same thread the day after re-sending it."""
        dup = self.docs_by_id[ev.refs["invoice"]]
        self.compose(
            self.invoice_thread_key(dup),
            f"Correction - invoice {dup.doc_id}", ev.event_time,
            self.them(dup.party_id, ev.event_time.date()),
            [self.us("accounts payable")],
            lambda b: b.statement(
                f"Please disregard invoice {ev.payload['duplicate_ref']}; "
                f"it duplicates {ev.payload['original_ref']}.",
                [{"event": ev.event_id}]))

    def _ev_dispute_resolved(self, ev: Event) -> None:
        inv = self.docs_by_id[ev.refs["invoice"]]
        thread_key = self.invoice_thread_key(inv)
        ours = self.us("accounts payable")
        vendor = self.them(inv.party_id, ev.event_time.date())
        if ev.payload["resolution"] == "credit_note":
            cn = self.docs_by_id[ev.payload["credit_note_ref"]]
            self.compose(
                thread_key, f"Dispute resolution - invoice {inv.doc_id}",
                ev.event_time, vendor, [ours],
                lambda b: b.statement(
                    f"We accept the dispute on {ev.payload['invoice_ref']}; "
                    f"credit note {cn.doc_id} for "
                    f"{money(cn.fields['amount_cents'])} follows.",
                    [{"event": ev.event_id}]))
        else:
            self.compose(
                thread_key, f"Dispute resolution - invoice {inv.doc_id}",
                ev.event_time, ours, [vendor],
                lambda b: b.statement(
                    f"After review we are withdrawing our dispute on invoice "
                    f"{ev.payload['invoice_ref']}.",
                    [{"event": ev.event_id}]))

    def _ev_contact_changed(self, ev: Event) -> None:
        """One message from the NEW address on a fresh thread. Every later
        message from this person picks the new address via address_on."""
        person = self.people_by_id[ev.payload["person_id"]]
        kind = self.world.party(person.party_id).kind
        ours = self.us("accounts payable" if kind == "vendor"
                       else "accounts receivable")
        self.compose(
            f"contact:{ev.event_id}",
            f"New contact address - {person.name}", ev.event_time,
            person, [ours],
            lambda b: b.statement(
                f"Please note my new address {ev.payload['new_address']} "
                f"going forward; the old one stops working this week.",
                [{"event": ev.event_id}]))

    def _ev_person_moved(self, ev: Event) -> None:
        """ONE farewell/handover message, sent the day before the switch so
        it leaves from the OLD address. No announcement from the new side:
        the new domain just starts appearing (the mover is the destination's
        acting contact from the move date, per World.contact_for)."""
        mover = self.people_by_id[ev.payload["person_id"]]
        old_party = self.world.party(ev.payload["from_party"])
        new_party = self.world.party(ev.payload["to_party"])
        replacement = self.people_by_id[ev.payload["replacement_person_id"]]
        self.compose(
            f"move:{ev.event_id}", f"Handover - {old_party.name} account",
            ev.event_time - timedelta(days=1), mover, [self.us("purchasing")],
            lambda b: b.statement(
                f"I am leaving {old_party.name}; {replacement.name} takes "
                f"over our account. You can reach me at {new_party.name} "
                f"going forward.", [{"event": ev.event_id}]))

    def _ev_payment_sent(self, ev: Event) -> None:
        self._payment(ev)

    def _ev_payment_received(self, ev: Event) -> None:
        self._payment(ev)

    def _payment(self, ev: Event) -> None:
        w = self.world
        inv = self.docs_by_id[ev.refs["invoice"]]
        we_pay = ev.actor_party == w.self_party.party_id
        contact = self.them(inv.party_id, ev.event_time.date())
        sender = self.us("accounts payable") if we_pay else contact
        rcpt = contact if we_pay else self.us("accounts receivable")
        thread_key = self.invoice_thread_key(inv)
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
# Ground-truth bookkeeping on near-duplicate invoices; a real re-sent
# invoice would not announce itself, so these never render.
_HIDDEN_FIELDS = {"duplicate_of", "voided_by_correction"}


def render_attachment(doc: Document, world: World) -> bytes:
    lines = [f"{_DOC_TITLES[doc.kind]} {doc.doc_id}",
             f"Date: {doc.issued_date.isoformat()}",
             f"Party: {world.party(doc.party_id).name}", ""]
    for k, v in doc.fields.items():
        if k in _HIDDEN_FIELDS:
            continue
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

    # Message-ID domain follows the sending address (matches the renderer's
    # header_mid rule), not the sender's current employer.
    domain = msg.from_address.split("@", 1)[1]
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
