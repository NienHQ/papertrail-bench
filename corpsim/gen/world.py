"""Builds the static world: company roster, vendors, customers, contracts."""
import datetime as dt
from .core import (FIRST_NAMES, LAST_NAMES, SIM_START, N_MONTHS, months,
                   month_start, COMPANY)


def _email(name, domain):
    return name.lower().replace(" ", ".").replace("'", "") + "@" + domain


def build_employees(rng):
    """~50 employees: Delivery(30 billable), Engineering(8), Sales(5), G&A(9).
    47 present on day 1, 5 hires during sim, 2 exits."""
    names = []
    used = set()
    while len(names) < 52:
        n = rng.choice(FIRST_NAMES) + " " + rng.choice(LAST_NAMES)
        if n not in used:
            used.add(n)
            names.append(n)

    roles = []
    # (dept, title, salary_band_lo, hi, billable, bill_rate_lo, hi)
    roles.append(("G&A", "Chief Executive Officer", 240000, 240000, False, 0, 0))
    roles.append(("G&A", "Chief Financial Officer", 210000, 210000, False, 0, 0))
    roles.append(("Delivery", "VP Delivery", 195000, 195000, False, 0, 0))
    roles.append(("Engineering", "VP Engineering", 195000, 195000, False, 0, 0))
    roles.append(("Sales", "Head of Sales", 175000, 175000, False, 0, 0))
    roles.append(("G&A", "Head of People", 145000, 145000, False, 0, 0))
    for _ in range(6):
        roles.append(("Delivery", "Engagement Manager", 140000, 160000, True, 210, 230))
    for _ in range(10):
        roles.append(("Delivery", "Senior Consultant", 115000, 135000, True, 180, 200))
    for _ in range(14):
        roles.append(("Delivery", "Consultant", 85000, 105000, True, 150, 170))
    for _ in range(3):
        roles.append(("Engineering", "Staff Engineer", 150000, 170000, False, 0, 0))
    for _ in range(4):
        roles.append(("Engineering", "Software Engineer", 100000, 130000, False, 0, 0))
    for _ in range(4):
        roles.append(("Sales", "Account Executive", 90000, 110000, False, 0, 0))
    roles.append(("G&A", "Finance Manager", 115000, 115000, False, 0, 0))
    roles.append(("G&A", "Staff Accountant", 78000, 78000, False, 0, 0))
    roles.append(("G&A", "Accounts Payable Specialist", 68000, 68000, False, 0, 0))
    roles.append(("G&A", "Office Manager", 62000, 62000, False, 0, 0))
    roles.append(("G&A", "IT Administrator", 88000, 88000, False, 0, 0))
    assert len(roles) == 52, len(roles)

    emps = []
    for i, (dept, title, lo, hi, billable, rlo, rhi) in enumerate(roles):
        sal = rng.randrange(lo, hi + 1, 1000) if hi > lo else lo
        rate = rng.randrange(rlo, rhi + 1, 5) if billable else 0
        emps.append({
            "id": f"E{i+1:03d}", "name": names[i], "dept": dept, "title": title,
            "email": _email(names[i], COMPANY["domain"]),
            "salary": sal * 100, "billable": billable, "bill_rate": rate * 100,
            "hire_date": SIM_START, "exit_date": None, "manager_id": None,
        })

    # managers: dept heads approve; delivery consultants report to engagement managers
    by_title = lambda t: [e for e in emps if e["title"] == t]
    ceo = by_title("Chief Executive Officer")[0]
    vpd = by_title("VP Delivery")[0]
    vpe = by_title("VP Engineering")[0]
    hos = by_title("Head of Sales")[0]
    cfo = by_title("Chief Financial Officer")[0]
    ems = by_title("Engagement Manager")
    for e in emps:
        if e is ceo:
            continue
        if e["title"] in ("Chief Financial Officer", "VP Delivery", "VP Engineering",
                          "Head of Sales", "Head of People"):
            e["manager_id"] = ceo["id"]
        elif e["dept"] == "Delivery" and e["title"] != "VP Delivery":
            e["manager_id"] = vpd["id"] if e["title"] == "Engagement Manager" \
                else rng.choice(ems)["id"]
        elif e["dept"] == "Engineering":
            e["manager_id"] = vpe["id"]
        elif e["dept"] == "Sales":
            e["manager_id"] = hos["id"]
        else:
            e["manager_id"] = cfo["id"]

    # 5 hires during sim (months 3..18), 2 exits (months 10..20); never officers
    rank_and_file = [e for e in emps if e["title"] in
                     ("Consultant", "Software Engineer", "Account Executive",
                      "Senior Consultant")]
    hires = rng.sample(rank_and_file, 5)
    ms = months()
    for e in hires:
        y, m = ms[rng.randrange(2, 18)]
        e["hire_date"] = month_start(y, m) + dt.timedelta(days=rng.randrange(0, 12))
    exits = rng.sample([e for e in rank_and_file if e not in hires], 2)
    for e in exits:
        y, m = ms[rng.randrange(9, 20)]
        e["exit_date"] = month_start(y, m) + dt.timedelta(days=14)
    return emps


VENDOR_SPECS = [
    # (id, name, domain, category, mode, terms_days, numbering, params)
    ("V01", "Harborview Property Group", "harborview-properties.example", "Rent",
     "blanket", 5, "HPG-{n:04d}", {"monthly": 18_500_00, "var": 0.0}),
    ("V02", "Nimbus Cloud Infrastructure", "nimbuscloud.example", "Cloud Hosting",
     "blanket", 30, "NCI-{y}-{n:05d}", {"monthly": 21_800_00, "var": 0.16}),
    ("V03", "Brightdesk SaaS Suite", "brightdesk.example", "Software Licenses",
     "blanket", 30, "BD/{y}/{n:04d}", {"monthly": 4_150_00, "var": 0.04}),
    ("V04", "Linkfield Communications", "linkfield-comms.example", "Internet & Telecom",
     "blanket", 15, "LFC{n:06d}", {"monthly": 1_150_00, "var": 0.02}),
    ("V05", "Shieldrock Insurance Brokers", "shieldrock.example", "Insurance",
     "blanket", 30, "SRB-{n:05d}", {"monthly": 9_800_00, "var": 0.0, "every": 3}),
    ("V06", "Sparrow Facilities Services", "sparrowfacilities.example", "Facilities",
     "blanket", 15, "SFS-{y}{m:02d}-{n:03d}", {"monthly": 2_400_00, "var": 0.0}),
    ("V07", "Crestline Benefits Co", "crestlinebenefits.example", "Benefits Admin",
     "blanket", 30, "CB-{n:05d}", {"monthly": 6_900_00, "var": 0.03}),
    ("V08", "Ledgerstone Accounting & Audit", "ledgerstone.example", "Accounting",
     "blanket", 30, "LSA-{y}-{n:04d}", {"monthly": 2_800_00, "var": 0.0}),
    ("V09", "Ironvale Hardware Supply", "ironvale-supply.example", "IT Hardware",
     "adhoc", 30, "IHS-{n:05d}", {}),
    ("V10", "Talentbridge Recruiting Partners", "talentbridge.example", "Recruiting",
     "adhoc", 45, "TRP/{y}/{n:03d}", {}),
    ("V11", "Meridian Legal LLP", "meridianlegal.example", "Legal",
     "adhoc", 30, "ML-{n:04d}", {}),
    ("V12", "Bluearc Marketing Studio", "bluearc.example", "Marketing",
     "adhoc", 30, "BAM-{y}-{n:03d}", {}),
    ("V13", "Northgate Travel Desk", "northgatetravel.example", "Travel",
     "adhoc", 15, "NTD-{n:06d}", {}),
    ("V14", "Cedarline Catering", "cedarline-catering.example", "Catering & Events",
     "adhoc", 15, "CC-{n:04d}", {}),
    ("V15", "Skillforge Training Institute", "skillforge.example", "Training",
     "adhoc", 30, "SFT-{n:04d}", {}),
]


def build_vendors(rng):
    vendors = []
    for vid, name, domain, cat, mode, terms, numbering, params in VENDOR_SPECS:
        contact = rng.choice(FIRST_NAMES) + " " + rng.choice(LAST_NAMES)
        vendors.append({
            "id": vid, "name": name, "domain": domain, "category": cat,
            "mode": mode, "terms_days": terms, "numbering": numbering,
            "params": params, "contact": contact,
            "email": _email(contact, domain), "inv_seq": 0,
        })
    return vendors


CUSTOMER_SPECS = [
    # (id, name, domain, model, behavior, terms, team_size, retainer)
    ("C01", "Vantorre Logistics Group", "vantorre-logistics.example", "tm", "prompt", 30, 5, 0),
    ("C02", "Helixware Biotech Systems", "helixware.example", "tm", "prompt", 30, 4, 0),
    ("C03", "Quarrystone Financial", "quarrystone-fin.example", "tm", "late", 45, 4, 0),
    ("C04", "Orbital Freight Exchange", "orbitalfreight.example", "tm", "prompt", 30, 3, 0),
    ("C05", "Pinemont Retail Holdings", "pinemont.example", "tm", "very_late", 30, 3, 0),
    ("C06", "Auricfield Energy Analytics", "auricfield.example", "tm", "late", 30, 3, 0),
    ("C07", "Bramblewick Media Network", "bramblewick.example", "retainer", "prompt", 30, 2, 38_000_00),
    ("C08", "Sableport Maritime Services", "sableport.example", "retainer", "late", 30, 2, 30_000_00),
    ("C09", "Copperline Health Platforms", "copperline-health.example", "retainer", "prompt", 15, 2, 44_000_00),
    ("C10", "Thornfield Civic Software", "thornfield-civic.example", "retainer", "very_late", 30, 2, 26_500_00),
]


def build_customers(rng, employees):
    """Assign delivery teams (all 30 billable staff spread across 10 customers)."""
    billable = [e for e in employees if e["billable"]]
    rng.shuffle(billable)
    customers, idx = [], 0
    for cid, name, domain, model, behavior, terms, tsize, retainer in CUSTOMER_SPECS:
        team = billable[idx:idx + tsize]
        idx += tsize
        contact = rng.choice(FIRST_NAMES) + " " + rng.choice(LAST_NAMES)
        customers.append({
            "id": cid, "name": name, "domain": domain, "model": model,
            "behavior": behavior, "terms_days": terms, "retainer": retainer,
            "team_ids": [e["id"] for e in team],
            "contact": contact, "email": _email(contact, domain),
        })
    assert idx == len(billable), (idx, len(billable))
    return customers


def build_world(rng):
    employees = build_employees(rng)
    vendors = build_vendors(rng)
    customers = build_customers(rng, employees)
    emap = {e["id"]: e for e in employees}
    ap_clerk = next(e for e in employees if e["title"] == "Accounts Payable Specialist")
    fin_mgr = next(e for e in employees if e["title"] == "Finance Manager")
    cfo = next(e for e in employees if e["title"] == "Chief Financial Officer")
    office_mgr = next(e for e in employees if e["title"] == "Office Manager")
    return {
        "employees": employees, "vendors": vendors, "customers": customers,
        "emap": emap, "ap": ap_clerk, "finance": fin_mgr, "cfo": cfo,
        "office": office_mgr,
    }
