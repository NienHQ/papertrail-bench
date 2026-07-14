"""Core ground-truth data structures. Mirrors docs/ground-truth-schema.md."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


@dataclass
class AddressPeriod:
    address: str
    from_date: date
    to_date: date | None = None


@dataclass
class Party:
    party_id: str
    kind: str  # self | vendor | customer | landlord | bank | payroll
    name: str
    domain: str
    is_self: bool = False


@dataclass
class Person:
    person_id: str
    name: str
    party_id: str
    role: str
    addresses: list[AddressPeriod]

    def address_on(self, d: date) -> str:
        for p in self.addresses:
            if p.from_date <= d and (p.to_date is None or d < p.to_date):
                return p.address
        raise ValueError(f"{self.person_id} has no address on {d}")

    @property
    def first(self) -> str:
        return self.name.split()[0]


@dataclass
class Event:
    event_id: str
    event_time: datetime
    type: str
    actor_party: str
    counterparty: str | None
    payload: dict
    refs: dict = field(default_factory=dict)


@dataclass
class Document:
    doc_id: str
    kind: str  # po | invoice | credit_note | lease
    root_id: str
    version: int
    supersedes: str | None
    party_id: str  # counterparty the document is with
    issued_date: date
    fields: dict
    created_event: str


@dataclass
class Fact:
    fact_id: str
    entity: str  # party_id
    relation: str
    value: str | int
    valid_from: date
    valid_to: date | None
    source_event: str


@dataclass
class StatementOccurrence:
    statement_id: str
    message_id: str
    span: tuple[int, int]  # char offsets into decoded text/plain body
    occurrence: str  # canonical | quoted
    targets: list[dict]  # {"fact": id} | {"event": id} | {"doc_field": [doc_id, field]}
    text: str


@dataclass
class Message:
    message_id: str
    thread_id: str
    ts: datetime
    from_person: str
    from_address: str
    from_name: str
    to: list[tuple[str, str]]  # (name, address)
    subject: str
    in_reply_to: str | None
    references: list[str]
    attachments: list[str]  # doc_ids
    body: str
    statements: list[StatementOccurrence]


@dataclass
class Thread:
    thread_id: str
    subject: str
    participants: list[str]  # person_ids


@dataclass
class Question:
    question_id: str
    category: int
    template: str
    text: str
    answer: dict  # {"type": ..., "value": ...}
    evidence: list[dict]  # {"message_id", "statement_id"} | {"doc_id", "field"}
    params: dict


def to_row(obj) -> dict:
    """Dataclass -> JSON-safe dict (ISO dates, lists for tuples)."""

    def enc(v):
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, tuple):
            return [enc(x) for x in v]
        if isinstance(v, list):
            return [enc(x) for x in v]
        if isinstance(v, dict):
            return {k: enc(x) for k, x in v.items()}
        return v

    return {k: enc(v) for k, v in dataclasses.asdict(obj).items()}
