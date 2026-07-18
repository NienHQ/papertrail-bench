"""Layer 0: the simulated SME and its counterparties.

All name material is vendored (no faker) so output is byte-stable across
environments and library versions. ASCII only: keeps spans byte==char and
EML bodies 7bit.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date

from .model import AddressPeriod, EmploymentPeriod, Party, Person

FIRST_NAMES = [
    "Ava", "Ben", "Carla", "Dev", "Elena", "Farid", "Grace", "Hugo", "Iris",
    "Jonas", "Kira", "Liam", "Mona", "Nils", "Omar", "Priya", "Quinn", "Rosa",
    "Sam", "Tara", "Uma", "Victor", "Wendy", "Yusuf", "Zoe",
]
LAST_NAMES = [
    "Adler", "Brant", "Costa", "Drake", "Ellis", "Fontane", "Garvey", "Holt",
    "Iverson", "Joshi", "Keller", "Lund", "Marsh", "Novak", "Okafor", "Pratt",
    "Reyes", "Sato", "Tanaka", "Ueda", "Vance", "Whitfield", "Yates", "Zeller",
]
COMPANY_STEMS = [
    "Northgate", "Bluepine", "Cardinal", "Delta Ridge", "Eastport", "Fairhaven",
    "Granite", "Harborline", "Ironwood", "Junction", "Kestrel", "Lakeshore",
    "Meridian", "Nightingale", "Oakfield", "Pinnacle", "Quarry", "Redwood",
    "Silverton", "Truman", "Umber", "Vantage", "Westbrook", "Yellowstone",
]
# Overflow stems for worlds larger than COMPANY_STEMS can seat. Kept in a
# separate pool: rng.sample draws depend on the population size, so growing
# COMPANY_STEMS itself would shift every existing seed's world. Small worlds
# keep sampling from the original 24 and stay byte-identical.
EXTRA_COMPANY_STEMS = [
    "Alderbrook", "Baxter", "Coppermine", "Dunmore", "Elmcrest", "Foxglove",
    "Grayling", "Hollowell", "Ivybridge", "Juniper", "Kingsford", "Larkspur",
    "Millbrook", "Norwich", "Ottershaw", "Pembroke",
]


def company_stem_pool(n_parties: int) -> list[str]:
    """The stem population for a world with n_parties companies (self,
    vendors, customers, landlord). Question sampling (category 6 unused
    names) must use the same pool the world was built from."""
    if n_parties <= len(COMPANY_STEMS):
        return list(COMPANY_STEMS)
    return COMPANY_STEMS + EXTRA_COMPANY_STEMS
VENDOR_SUFFIXES = ["Supplies", "Industrial", "Components", "Materials", "Logistics", "Packaging"]
CUSTOMER_SUFFIXES = ["Retail", "Trading", "Distribution", "Outfitters", "Wholesale", "Stores"]
ITEMS = [
    "steel brackets", "shipping cartons", "hex bolts M8", "pallet wrap",
    "safety gloves", "aluminum sheet 2mm", "conveyor rollers", "label stock",
    "epoxy resin", "rubber gaskets", "LED panels", "copper wire 12AWG",
]
ROLES_SELF = ["purchasing", "accounts payable", "accounts receivable", "operations"]


@dataclass
class World:
    self_party: Party
    parties: list[Party]  # includes self
    people: list[Person]
    items: list[str]
    # unused person names, in draw order, for post-build hires (replacements)
    name_pool: list[str] = field(default_factory=list)

    def party(self, party_id: str) -> Party:
        return next(p for p in self.parties if p.party_id == party_id)

    def contact_for(self, party_id: str, role: str | None = None,
                    on: date | None = None) -> Person:
        """The acting contact for a party.

        Date-free: whoever is CURRENTLY employed there (used by the renderer
        for "who sends now" style lookups and by the simulator).
        Date-aware: whoever was employed there on that date; when several
        people qualify, the MOST RECENT joiner wins (ties broken by
        person_id). This is the deterministic sender rule after a
        PERSON_MOVED: the mover handles the destination party's mail from
        the move date on, while the destination's original contact remains
        employed there.
        """
        if on is None:
            cands = [p for p in self.people if p.party_id == party_id
                     and (role is None or p.role == role)]
            return cands[0]
        dated: list[tuple[date, str, Person]] = []
        for p in self.people:
            if role is not None and p.role != role:
                continue
            for e in p.employments:
                if (e.party_id == party_id and e.from_date <= on
                        and (e.to_date is None or on < e.to_date)):
                    dated.append((e.from_date, p.person_id, p))
        assert dated, f"no contact for {party_id} on {on}"
        dated.sort(key=lambda t: (t[0], t[1]))
        return dated[-1][2]

    def hire(self, party: Party, role: str, from_date: date) -> Person:
        """Add a replacement contact at a party mid-corpus."""
        name = self.name_pool.pop(0)
        person = Person(
            person_id=f"PER-{len(self.people) + 1:04d}", name=name,
            party_id=party.party_id, role=role,
            addresses=[AddressPeriod(_addr(name, party.domain), from_date,
                                     None)],
            employments=[EmploymentPeriod(party.party_id, from_date, None)])
        self.people.append(person)
        return person

    def vendors(self) -> list[Party]:
        return [p for p in self.parties if p.kind == "vendor"]

    def customers(self) -> list[Party]:
        return [p for p in self.parties if p.kind == "customer"]

    def landlord(self) -> Party:
        return next(p for p in self.parties if p.kind == "landlord")


def _domain(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum()) + ".example"


def _addr(person_name: str, domain: str) -> str:
    parts = person_name.lower().split()
    return f"{parts[0]}.{parts[-1]}@{domain}"


def build_world(rng: random.Random, n_vendors: int, n_customers: int,
                year_start: date) -> World:
    ids = iter(range(1, 10_000))
    pids = iter(range(1, 10_000))
    n_parties = n_vendors + n_customers + 2
    stems = rng.sample(company_stem_pool(n_parties), n_parties)
    names = [f"{f} {l}" for f in FIRST_NAMES for l in LAST_NAMES]
    rng.shuffle(names)
    names_iter = iter(names)

    parties: list[Party] = []
    people: list[Person] = []

    def add_party(kind: str, name: str, is_self: bool = False) -> Party:
        p = Party(party_id=f"PTY-{next(ids):04d}", kind=kind, name=name,
                  domain=_domain(name), is_self=is_self)
        parties.append(p)
        return p

    def add_person(party: Party, role: str) -> Person:
        name = next(names_iter)
        person = Person(
            person_id=f"PER-{next(pids):04d}", name=name, party_id=party.party_id,
            role=role,
            addresses=[AddressPeriod(_addr(name, party.domain), year_start, None)],
            employments=[EmploymentPeriod(party.party_id, year_start, None)])
        people.append(person)
        return person

    self_party = add_party("self", f"{stems[0]} Fabrication", is_self=True)
    for role in ROLES_SELF:
        add_person(self_party, role)

    for i in range(n_vendors):
        v = add_party("vendor", f"{stems[1 + i]} {rng.choice(VENDOR_SUFFIXES)}")
        add_person(v, "sales")
    for i in range(n_customers):
        c = add_party("customer",
                      f"{stems[1 + n_vendors + i]} {rng.choice(CUSTOMER_SUFFIXES)}")
        add_person(c, "purchasing")

    landlord = add_party("landlord", f"{stems[1 + n_vendors + n_customers]} Properties")
    add_person(landlord, "property manager")

    items = rng.sample(ITEMS, min(len(ITEMS), max(4, n_vendors)))
    return World(self_party=self_party, parties=parties, people=people,
                 items=items, name_pool=list(names_iter))
