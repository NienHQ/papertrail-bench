"""Layer 2: fact ledger derivation.

Deterministic view over the event log. Structural keying on (entity, relation):
a new value closes the previous fact and opens a new one: superseded, never
deleted. Returns the ledger plus an event_id -> fact_id map so the renderer can
anchor statements to the facts they assert.
"""
from __future__ import annotations

from datetime import date

from .model import Event, Fact

# event type -> (entity source, relation extractor, value extractor)
_FACT_EVENTS = {"TERMS_AGREED", "PRICE_AGREED", "LEASE_SIGNED", "LEASE_AMENDED"}


def _fact_parts(ev: Event) -> tuple[str, str, str | int] | None:
    if ev.type in ("TERMS_AGREED", "PRICE_AGREED"):
        return ev.actor_party, ev.payload["relation"], ev.payload["value"]
    if ev.type in ("LEASE_SIGNED", "LEASE_AMENDED"):
        return ev.actor_party, "monthly_rent", ev.payload["monthly_rent_cents"]
    return None


def derive_facts(events: list[Event], self_party: str
                 ) -> tuple[list[Fact], dict[str, str]]:
    facts: list[Fact] = []
    open_facts: dict[tuple[str, str], Fact] = {}
    event_fact: dict[str, str] = {}
    n = 0
    for ev in events:
        if ev.type not in _FACT_EVENTS:
            continue
        parts = _fact_parts(ev)
        assert parts is not None
        entity, relation, value = parts
        # Facts always attach to the counterparty (never "us"): for sales-side
        # terms the actor is us and the entity is the customer.
        if entity == self_party:
            assert ev.counterparty is not None
            entity = ev.counterparty
        d = ev.event_time.date()
        key = (entity, relation)
        prev = open_facts.get(key)
        if prev is not None:
            prev.valid_to = d
        n += 1
        fact = Fact(fact_id=f"FCT-{n:06d}", entity=entity, relation=relation,
                    value=value, valid_from=d, valid_to=None,
                    source_event=ev.event_id)
        facts.append(fact)
        open_facts[key] = fact
        event_fact[ev.event_id] = fact.fact_id
    return facts, event_fact


def fact_as_of(facts: list[Fact], entity: str, relation: str,
               as_of: date) -> Fact | None:
    for f in facts:
        if (f.entity == entity and f.relation == relation
                and f.valid_from <= as_of
                and (f.valid_to is None or as_of < f.valid_to)):
            return f
    return None
