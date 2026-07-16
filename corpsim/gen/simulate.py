"""The 24-month simulation engine.

Produces, into the world dict:
  pos, vendor_invoices, customer_invoices, timesheets, payroll_runs,
  bank_txns, emails, anomalies
Everything downstream (render, truth DB, questions) reads these.
"""
import datetime as dt
from .core import (COMPANY, SIM_START, N_MONTHS, months, month_start, month_end,
                   first_bday, last_bday, next_bday, add_bdays, mondays_in,
                   workdays_of_week_in_month, fmt_money, ymd, month_key,
                   OPENING_CAPITAL, BANK_FEE, TAX_WITHHOLD, EMPLOYER_TAX,
                   CORP_TAX_QUARTERLY)

SIM_END = month_end(*months()[-1])


def clamp(d):
    return min(d, SIM_END)


# ---------------------------------------------------------------- emails
def make_email(world, rng, date, sender, to, subject, body, thread_id, seq,
               cc=None):
    t = dt.time(hour=rng.randrange(8, 18), minute=rng.randrange(0, 60))
    msg = {
        "msg_id": f"<{thread_id}.{seq}@{COMPANY['domain']}>",
        "in_reply_to": f"<{thread_id}.{seq-1}@{COMPANY['domain']}>" if seq > 1 else None,
        "thread_id": thread_id, "seq": seq,
        "dt": dt.datetime.combine(clamp(date), t),
        "from": sender, "to": to, "cc": cc or "",
        "subject": ("Re: " + subject) if seq > 1 else subject,
        "body": body,
    }
    world["emails"].append(msg)
    return msg


def sig(name, org):
    return f"\nBest regards,\n{name}\n{org}\n"


# ---------------------------------------------------------------- procurement
def plan_pos(world, rng):
    """Plan every PO (blanket terms + adhoc purchases), then number by date."""
    plans = []
    vmap = {v["id"]: v for v in world["vendors"]}

    for v in world["vendors"]:
        if v["mode"] == "blanket":
            for term in (0, 1):
                tstart = dt.date(SIM_START.year + term, SIM_START.month, 1)
                tend = dt.date(tstart.year + 1, tstart.month, 1) - dt.timedelta(days=1)
                every = v["params"].get("every", 1)
                periods = 12 // every
                base = v["params"]["monthly"] * every
                list_monthly = base if term == 0 else int(base * (1 + rng.uniform(0.03, 0.09)))
                issue = tstart - dt.timedelta(days=rng.randrange(18, 32))
                if term == 0:
                    issue = tstart - dt.timedelta(days=rng.randrange(5, 12))
                plans.append({
                    "vendor_id": v["id"], "kind": "blanket", "issue_date": next_bday(issue),
                    "term_start": tstart, "term_end": tend, "every": every,
                    "list_amount": list_monthly * periods, "list_period": list_monthly,
                    "description": f"{v['category']} services, annual agreement "
                                   f"{ymd(tstart)} to {ymd(tend)}",
                    "negotiate": True,
                })
        elif v["id"] == "V09":  # hardware: per hire + quarterly refresh
            for e in world["employees"]:
                if e["hire_date"] > SIM_START:
                    d = e["hire_date"] - dt.timedelta(days=rng.randrange(10, 18))
                    plans.append(_adhoc(v, d, rng.randrange(2_400_00, 3_800_00, 100),
                                        f"Workstation package for new hire ({e['id']})", rng))
            for q in range(8):
                d = SIM_START + dt.timedelta(days=q * 91 + rng.randrange(5, 40))
                plans.append(_adhoc(v, d, rng.randrange(4_000_00, 14_000_00, 500),
                                    "Quarterly IT hardware refresh", rng))
        elif v["id"] == "V10":  # recruiting: fee per hire
            for e in world["employees"]:
                if e["hire_date"] > SIM_START:
                    d = e["hire_date"] - dt.timedelta(days=rng.randrange(25, 40))
                    fee = int(e["salary"] * 0.18)
                    plans.append(_adhoc(v, d, fee,
                                        f"Placement fee, {e['title']} role (18% of base)", rng))
        elif v["id"] == "V11":  # legal
            for _ in range(7):
                d = SIM_START + dt.timedelta(days=rng.randrange(0, N_MONTHS * 30 - 40))
                plans.append(_adhoc(v, d, rng.randrange(3_000_00, 18_000_00, 500),
                                    rng.choice(["MSA review and negotiation support",
                                                "Employment matter advisory",
                                                "IP assignment and licensing review",
                                                "Contract dispute advisory"]), rng))
        elif v["id"] == "V12":  # marketing
            d = SIM_START + dt.timedelta(days=rng.randrange(10, 30))
            while d < SIM_END - dt.timedelta(days=45):
                plans.append(_adhoc(v, d, rng.randrange(5_000_00, 25_000_00, 500),
                                    rng.choice(["Demand-gen campaign", "Website refresh sprint",
                                                "Conference booth design", "Content marketing package",
                                                "Brand asset production"]), rng))
                d += dt.timedelta(days=rng.randrange(35, 70))
        elif v["id"] == "V13":  # travel, most months
            for (y, m) in months():
                if rng.random() < 0.8:
                    d = month_start(y, m) + dt.timedelta(days=rng.randrange(2, 18))
                    plans.append(_adhoc(v, d, rng.randrange(800_00, 9_000_00, 100),
                                        f"Client travel bookings, {month_key(y, m)}", rng))
        elif v["id"] == "V14":  # catering
            for (y, m) in months():
                if rng.random() < 0.7:
                    d = month_start(y, m) + dt.timedelta(days=rng.randrange(2, 24))
                    amt = rng.randrange(600_00, 3_500_00, 50)
                    desc = "Team lunch & event catering"
                    if m in (1, 8) and rng.random() < 0.8:
                        amt = rng.randrange(6_000_00, 9_500_00, 100)
                        desc = "Company offsite catering"
                    plans.append(_adhoc(v, d, amt, desc, rng))
        elif v["id"] == "V15":  # training
            for q in range(8):
                d = SIM_START + dt.timedelta(days=q * 91 + rng.randrange(10, 60))
                plans.append(_adhoc(v, d, rng.randrange(2_000_00, 8_000_00, 250),
                                    rng.choice(["Cloud architecture certification cohort",
                                                "Leadership training workshop",
                                                "Security awareness program",
                                                "Advanced data engineering course"]), rng))

    # annual audit as adhoc engagement from the accounting vendor
    for yr in (2024, 2025):
        d = dt.date(yr, 9, rng.randrange(3, 12))
        plans.append(_adhoc(vmap["V08"], d, 24_000_00, f"Annual financial audit FY{yr}", rng))

    plans = [p for p in plans if SIM_START <= p["issue_date"] <= SIM_END - dt.timedelta(days=7)
             or p["kind"] == "blanket"]
    plans.sort(key=lambda p: (p["issue_date"], p["vendor_id"]))
    seq_by_year = {}
    for p in plans:
        yr = max(p["issue_date"].year, SIM_START.year)
        seq_by_year[yr] = seq_by_year.get(yr, 0) + 1
        p["po_number"] = f"PO-{yr}-{seq_by_year[yr]:04d}"
    return plans


def _adhoc(v, d, amount, desc, rng):
    return {"vendor_id": v["id"], "kind": "adhoc", "issue_date": next_bday(max(d, SIM_START)),
            "term_start": None, "term_end": None, "every": 1,
            "list_amount": amount, "list_period": amount,
            "description": desc, "negotiate": amount >= 5_000_00}


NEGO_ASKS = [
    "Given the committed volume here, we'd like to see some movement on the number.",
    "This is above the budget line we planned. Can you sharpen the pricing?",
    "We have a competing quote that comes in lower. Is there room to close the gap?",
    "For a multi-month commitment we'd expect a partnership discount.",
]
NEGO_COUNTERS = [
    "We can move a little, but the quoted rate already reflects preferred pricing.",
    "Let me check with our commercial team — we value the relationship.",
    "We could restructure the payment schedule, or shave the rate slightly.",
]


def negotiate_po(world, rng, po, vendor):
    """Email thread; returns final amount."""
    buyer = world["office"] if vendor["category"] in ("Facilities", "Catering & Events",
                                                       "Travel", "IT Hardware") else world["finance"]
    tid = "po-" + po["po_number"].lower()
    d = po["issue_date"]
    amt = po["list_amount"]
    subj = f"{po['po_number']}: {vendor['category']} — {COMPANY['short']}"
    if not po["negotiate"]:
        make_email(world, rng, d, buyer["email"], vendor["email"], subj,
                   f"Hi {vendor['contact'].split()[0]},\n\nPlease find our purchase order "
                   f"{po['po_number']} for: {po['description']}.\nTotal: {fmt_money(amt)}. "
                   f"Kindly confirm and countersign.\n" + sig(buyer["name"], COMPANY["name"]),
                   tid, 1)
        d2 = add_bdays(d, rng.randrange(1, 3))
        make_email(world, rng, d2, vendor["email"], buyer["email"], subj,
                   f"Confirmed and signed, thank you. We will proceed as scheduled.\n"
                   + sig(vendor["contact"], vendor["name"]), tid, 2)
        return amt, d2, 0.0

    disc = rng.choice([0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12])
    final = int(round(amt * (1 - disc), -2))
    ask_disc = min(disc * rng.uniform(1.3, 1.9), 0.20)
    ask = int(round(amt * (1 - ask_disc), -2))
    make_email(world, rng, d, buyer["email"], vendor["email"], subj,
               f"Hi {vendor['contact'].split()[0]},\n\nDraft PO {po['po_number']} attached for: "
               f"{po['description']}.\nYour quote stands at {fmt_money(amt)}. "
               f"{rng.choice(NEGO_ASKS)} We were thinking closer to {fmt_money(ask)}.\n"
               + sig(buyer["name"], COMPANY["name"]), tid, 1)
    d2 = add_bdays(d, rng.randrange(1, 4))
    make_email(world, rng, d2, vendor["email"], buyer["email"], subj,
               f"Thanks for the note. {rng.choice(NEGO_COUNTERS)} "
               f"The best we can do on this scope is {fmt_money(final)}.\n"
               + sig(vendor["contact"], vendor["name"]), tid, 2)
    d3 = add_bdays(d2, rng.randrange(1, 3))
    make_email(world, rng, d3, buyer["email"], vendor["email"], subj,
               f"{fmt_money(final)} works. I've updated PO {po['po_number']} to that amount "
               f"({disc*100:.0f}% off the original quote) — please countersign.\n"
               + sig(buyer["name"], COMPANY["name"]), tid, 3)
    d4 = add_bdays(d3, rng.randrange(1, 3))
    make_email(world, rng, d4, vendor["email"], buyer["email"], subj,
               f"Countersigned. Thanks for the partnership.\n"
               + sig(vendor["contact"], vendor["name"]), tid, 4)
    return final, d4, disc


def vendor_invoice_number(vendor, date):
    vendor["inv_seq"] += 1
    return vendor["numbering"].format(n=vendor["inv_seq"], y=date.year, m=date.month)


def submit_vendor_invoice(world, rng, vendor, po, inv_date, correct_amount, desc,
                          period=None):
    """Vendor emails an invoice; may carry an injected anomaly. Handles AP flow,
    resolution thread, payment scheduling. Returns the invoice record."""
    inv_date = clamp(next_bday(inv_date))
    number = vendor_invoice_number(vendor, inv_date)
    roll = rng.random()
    anomaly = None
    amount = correct_amount
    if roll < 0.05:
        anomaly = "overbilling"
        amount = int(round(correct_amount * rng.uniform(1.02, 1.10), -2))
    elif roll < 0.09:
        anomaly = "missing_po_ref"
    dup = roll >= 0.09 and roll < 0.11

    due = inv_date + dt.timedelta(days=vendor["terms_days"])
    inv = {
        "inv_number": number, "vendor_id": vendor["id"],
        "po_number": None if anomaly == "missing_po_ref" else po["po_number"],
        "true_po_number": po["po_number"], "date": inv_date, "due_date": due,
        "amount": amount, "correct_amount": correct_amount,
        "anomaly": anomaly, "duplicate_of": None, "description": desc,
        "period": period, "status": "open", "paid_amount": 0, "paid_date": None,
    }
    world["vendor_invoices"].append(inv)
    ap = world["ap"]
    tid = "inv-" + number.lower().replace("/", "-").replace(" ", "")
    subj = f"Invoice {number} — {vendor['name']}"
    po_line = f"PO reference: {inv['po_number']}\n" if inv["po_number"] else ""
    make_email(world, rng, inv_date, vendor["email"], "ap@" + COMPANY["domain"], subj,
               f"Dear Accounts Payable,\n\nPlease find attached invoice {number} for "
               f"{fmt_money(amount)} — {desc}.\n{po_line}"
               f"Payment terms: net {vendor['terms_days']}, due {ymd(due)}.\n"
               + sig(vendor["contact"], vendor["name"]), tid, 1)

    resolved = inv_date
    if anomaly == "overbilling":
        d2 = add_bdays(inv_date, rng.randrange(2, 6))
        make_email(world, rng, d2, ap["email"], vendor["email"], subj,
                   f"Hi {vendor['contact'].split()[0]},\n\nInvoice {number} bills "
                   f"{fmt_money(amount)}, but PO {po['po_number']} authorizes "
                   f"{fmt_money(correct_amount)} for this period. Could you review? "
                   f"We'll hold payment until this is reconciled.\n"
                   + sig(ap["name"], COMPANY["name"]), tid, 2)
        d3 = add_bdays(d2, rng.randrange(1, 4))
        make_email(world, rng, d3, vendor["email"], ap["email"], subj,
                   f"Apologies — a rate table error on our side. Please treat invoice "
                   f"{number} as amended to {fmt_money(correct_amount)}; a corrected copy "
                   f"is attached.\n" + sig(vendor["contact"], vendor["name"]), tid, 3)
        resolved = d3
        world["anomalies"].append({
            "kind": "overbilling", "ref": number, "vendor_id": vendor["id"],
            "date": inv_date, "delta": amount - correct_amount,
            "note": f"Invoice {number} overbilled by {fmt_money(amount - correct_amount)} "
                    f"vs PO {po['po_number']}; amended after AP challenge."})
    elif anomaly == "missing_po_ref":
        d2 = add_bdays(inv_date, rng.randrange(2, 6))
        make_email(world, rng, d2, ap["email"], vendor["email"], subj,
                   f"Hi {vendor['contact'].split()[0]},\n\nInvoice {number} arrived without "
                   f"a PO reference; our policy requires one before payment. Could you "
                   f"confirm the purchase order this bills against?\n"
                   + sig(ap["name"], COMPANY["name"]), tid, 2)
        d3 = add_bdays(d2, rng.randrange(1, 4))
        make_email(world, rng, d3, vendor["email"], ap["email"], subj,
                   f"Of course — invoice {number} bills against PO {po['po_number']}. "
                   f"Sorry for the omission.\n" + sig(vendor["contact"], vendor["name"]),
                   tid, 3)
        resolved = d3
        world["anomalies"].append({
            "kind": "missing_po_ref", "ref": number, "vendor_id": vendor["id"],
            "date": inv_date, "delta": 0,
            "note": f"Invoice {number} submitted without PO reference; "
                    f"resolved to {po['po_number']} by email."})

    pay_date = next_bday(max(due, add_bdays(resolved, 3)) +
                         dt.timedelta(days=rng.randrange(0, 3)))
    if pay_date <= SIM_END:
        inv["status"] = "paid"
        inv["paid_amount"] = correct_amount
        inv["paid_date"] = pay_date
        world["bank_txns"].append({
            "date": pay_date, "amount": -correct_amount,
            "description": f"ACH OUT {vendor['name'].upper()} {number}",
            "ref": number, "category": "vendor_payment",
            "counterparty": vendor["name"]})
        make_email(world, rng, pay_date, ap["email"], vendor["email"], subj,
                   f"Remittance advice: {fmt_money(correct_amount)} was paid today against "
                   f"invoice {number} (PO {po['po_number']}).\n"
                   + sig(ap["name"], COMPANY["name"]),
                   tid, 4 if anomaly else 2)

    if dup:
        d_dup = add_bdays(inv_date, rng.randrange(6, 20))
        if d_dup <= SIM_END:
            dup_inv = dict(inv)
            dup_inv.update({"anomaly": "duplicate", "duplicate_of": number,
                            "date": d_dup, "status": "rejected", "paid_amount": 0,
                            "paid_date": None, "amount": amount})
            world["vendor_invoices"].append(dup_inv)
            tid2 = tid + "-dup"
            make_email(world, rng, d_dup, vendor["email"], "ap@" + COMPANY["domain"], subj,
                       f"Dear Accounts Payable,\n\nResending invoice {number} for "
                       f"{fmt_money(amount)} — {desc} — as we do not show it settled "
                       f"in our system yet.\n" + sig(vendor["contact"], vendor["name"]),
                       tid2, 1)
            d_rej = add_bdays(d_dup, rng.randrange(1, 4))
            make_email(world, rng, d_rej, ap["email"], vendor["email"], subj,
                       f"Hi {vendor['contact'].split()[0]},\n\nThis is a duplicate of "
                       f"invoice {number}, which is already in our payment run. Please "
                       f"disregard the resubmission — no second payment will be made.\n"
                       + sig(ap["name"], COMPANY["name"]), tid2, 2)
            world["anomalies"].append({
                "kind": "duplicate", "ref": number, "vendor_id": vendor["id"],
                "date": d_dup, "delta": amount,
                "note": f"Invoice {number} resubmitted on {ymd(d_dup)}; rejected as duplicate."})
    return inv


def run_procurement(world, rng):
    vmap = {v["id"]: v for v in world["vendors"]}
    for plan in plan_pos(world, rng):
        v = vmap[plan["vendor_id"]]
        final, signed, disc = negotiate_po(world, rng, plan, v)
        po = {**plan, "final_amount": final, "signed_date": signed,
              "discount_pct": round(disc * 100, 1)}
        world["pos"].append(po)
        if po["kind"] == "adhoc":
            # delivery then invoice 3-15 days after signing
            inv_d = signed + dt.timedelta(days=rng.randrange(3, 15))
            if inv_d <= SIM_END:
                submit_vendor_invoice(world, rng, v, po, inv_d, final,
                                      po["description"])
        else:
            every = po["every"]
            periods = 12 // every
            per_amount = final // periods
            var = v["params"].get("var", 0.0)
            y, m = po["term_start"].year, po["term_start"].month
            for k in range(periods):
                py, pm = y, m
                for _ in range(k * every):
                    pm += 1
                    if pm == 13:
                        py, pm = py + 1, 1
                inv_d = month_start(py, pm) + dt.timedelta(days=rng.randrange(1, 6))
                if inv_d > SIM_END:
                    continue
                amt = per_amount if var == 0 else \
                    int(round(per_amount * (1 + rng.uniform(-var, var)), -2))
                label = month_key(py, pm) if every == 1 else \
                    f"{month_key(py, pm)} quarter"
                submit_vendor_invoice(world, rng, v, po, inv_d, amt,
                                      f"{v['category']} — {label}", period=label)


# ---------------------------------------------------------------- payroll & timesheets
def active_in_month(e, y, m):
    if e["hire_date"] > month_end(y, m):
        return False
    if e["exit_date"] and e["exit_date"] < month_start(y, m):
        return False
    return True


def run_timesheets_and_payroll(world, rng):
    emap = world["emap"]
    team_of = {}
    for c in world["customers"]:
        for eid in c["team_ids"]:
            team_of[eid] = c["id"]

    for (y, m) in months():
        mk = month_key(y, m)
        # ---- timesheets
        reject_pool = []
        for e in world["employees"]:
            if not active_in_month(e, y, m):
                continue
            weeks = []
            for monday in mondays_in(y, m):
                days = workdays_of_week_in_month(monday, y, m)
                # trim for mid-month hire/exit
                dd = 0
                for i in range(5):
                    d = monday + dt.timedelta(days=i)
                    if d.month != m or d.year != y:
                        continue
                    if d < e["hire_date"]:
                        continue
                    if e["exit_date"] and d > e["exit_date"]:
                        continue
                    dd += 1
                if dd == 0:
                    continue
                cap = dd * 8
                pto = 8 * rng.randrange(0, dd + 1) if rng.random() < 0.10 else 0
                pto = min(pto, cap)
                work = cap - pto
                alloc = {}
                if e["billable"] and work > 0:
                    cust = team_of.get(e["id"])
                    ch = int(work * rng.uniform(0.85, 0.96))
                    alloc[cust] = ch
                    if work - ch:
                        alloc["INT"] = work - ch
                elif work > 0:
                    alloc["INT"] = work
                if pto:
                    alloc["PTO"] = pto
                weeks.append({"week_start": monday, "alloc": alloc, "total": cap})
            if not weeks:
                continue
            submitted = clamp(last_bday(y, m))
            ts = {"employee_id": e["id"], "month": mk, "weeks": weeks,
                  "submitted_date": submitted, "approver_id": e["manager_id"] or e["id"],
                  "approved_date": clamp(add_bdays(submitted, rng.randrange(0, 3))),
                  "rejected": False, "rejection_reason": None,
                  "resubmitted_date": None}
            world["timesheets"].append(ts)
            if e["manager_id"]:
                reject_pool.append(ts)
        # ~2 rejections/month: manager bounces it, employee resubmits
        for ts in rng.sample(reject_pool, min(2, len(reject_pool))):
            e = emap[ts["employee_id"]]
            mgr = emap[ts["approver_id"]]
            ts["rejected"] = True
            ts["rejection_reason"] = rng.choice(
                ["Hours logged against the wrong project code",
                 "Week total exceeds recorded PTO balance",
                 "Missing allocation for the final week"])
            rej_d = clamp(add_bdays(ts["submitted_date"], 1))
            ts["resubmitted_date"] = clamp(add_bdays(rej_d, rng.randrange(1, 3)))
            ts["approved_date"] = clamp(add_bdays(ts["resubmitted_date"], 1))
            tid = f"ts-{e['id'].lower()}-{mk}"
            subj = f"Timesheet {mk} — {e['name']}"
            make_email(world, rng, rej_d, mgr["email"], e["email"], subj,
                       f"Hi {e['name'].split()[0]},\n\nI've sent back your {mk} timesheet: "
                       f"{ts['rejection_reason'].lower()}. Please correct and resubmit.\n"
                       + sig(mgr["name"], COMPANY["name"]), tid, 1)
            make_email(world, rng, ts["resubmitted_date"], e["email"], mgr["email"], subj,
                       f"Fixed and resubmitted — thanks for catching it.\n"
                       + sig(e["name"], COMPANY["name"]), tid, 2)
            make_email(world, rng, ts["approved_date"], mgr["email"], e["email"], subj,
                       f"Approved. Thanks.\n" + sig(mgr["name"], COMPANY["name"]), tid, 3)

        # ---- payroll run
        pay_date = last_bday(y, m)
        slips = []
        for e in world["employees"]:
            if not active_in_month(e, y, m):
                continue
            # prorate by active workdays
            total_wd = act_wd = 0
            d = month_start(y, m)
            while d <= month_end(y, m):
                if d.weekday() < 5:
                    total_wd += 1
                    if d >= e["hire_date"] and (not e["exit_date"] or d <= e["exit_date"]):
                        act_wd += 1
                d += dt.timedelta(days=1)
            if act_wd == 0:
                continue
            gross = round(e["salary"] / 12 * act_wd / total_wd)
            tax = round(gross * TAX_WITHHOLD)
            net = gross - tax
            slips.append({"employee_id": e["id"], "gross": gross, "tax": tax,
                          "net": net, "prorated": act_wd != total_wd})
            world["bank_txns"].append({
                "date": pay_date, "amount": -net,
                "description": f"PAYROLL {e['id']} {e['name'].upper()}",
                "ref": f"PR-{mk}-{e['id']}", "category": "payroll",
                "counterparty": e["name"]})
        run = {"month": mk, "pay_date": pay_date, "slips": slips,
               "total_gross": sum(s["gross"] for s in slips),
               "total_tax": sum(s["tax"] for s in slips),
               "total_net": sum(s["net"] for s in slips)}
        run["employer_tax"] = round(run["total_gross"] * EMPLOYER_TAX)
        world["payroll_runs"].append(run)
        remit_d = next_bday(month_end(y, m) + dt.timedelta(days=7))
        if remit_d <= SIM_END:
            world["bank_txns"].append({
                "date": remit_d, "amount": -(run["total_tax"] + run["employer_tax"]),
                "description": f"TAX AUTHORITY PAYROLL TAX {mk}",
                "ref": f"PTX-{mk}", "category": "payroll_tax",
                "counterparty": "Federal Tax Authority"})


# ---------------------------------------------------------------- revenue
DUN_1 = ("Our records show invoice {inv} for {amt}, due {due}, remains unpaid. "
         "Could you confirm the payment status at your end?")
DUN_2 = ("Second reminder: invoice {inv} for {amt} is now well past its {due} due date. "
         "Please arrange settlement this week or share a payment date; we may have to "
         "pause new work on the account otherwise.")


def run_revenue(world, rng):
    emap = world["emap"]
    fin = world["finance"]
    seq_by_year = {}
    all_months = months()
    for idx, (y, m) in enumerate(all_months):
        # bill month (y,m) in arrears on 1st bday of following month
        ny, nm = (y, m + 1) if m < 12 else (y + 1, 1)
        issue = first_bday(ny, nm)
        if issue > SIM_END:
            continue
        mk = month_key(y, m)
        for c in world["customers"]:
            lines, total = [], 0
            if c["model"] == "retainer":
                lines.append({"desc": f"Monthly service retainer — {mk}",
                              "qty": 1, "rate": c["retainer"], "amount": c["retainer"]})
                total = c["retainer"]
            else:
                for eid in c["team_ids"]:
                    e = emap[eid]
                    hrs = 0
                    for ts in world["timesheets"]:
                        if ts["employee_id"] == eid and ts["month"] == mk:
                            hrs = sum(w["alloc"].get(c["id"], 0) for w in ts["weeks"])
                    if hrs:
                        amt = hrs * e["bill_rate"]
                        lines.append({"desc": f"{e['name']} ({e['title']}), {hrs} hrs "
                                              f"@ {fmt_money(e['bill_rate'])}/hr — {mk}",
                                      "qty": hrs, "rate": e["bill_rate"], "amount": amt})
                        total += amt
            if total == 0:
                continue
            seq_by_year[issue.year] = seq_by_year.get(issue.year, 0) + 1
            number = f"CPS-INV-{issue.year}-{seq_by_year[issue.year]:04d}"
            due = issue + dt.timedelta(days=c["terms_days"])
            inv = {"inv_number": number, "customer_id": c["id"], "period": mk,
                   "issue_date": issue, "due_date": due, "amount": total,
                   "lines": lines, "receipts": [], "status": "open",
                   "dunning_count": 0}
            world["customer_invoices"].append(inv)
            tid = "ar-" + number.lower()
            subj = f"{COMPANY['name']} invoice {number} ({mk})"
            make_email(world, rng, issue, fin["email"], c["email"], subj,
                       f"Dear {c['contact'].split()[0]},\n\nPlease find attached invoice "
                       f"{number} for services in {mk}: {fmt_money(total)}, due {ymd(due)} "
                       f"(net {c['terms_days']}).\n" + sig(fin["name"], COMPANY["name"]),
                       tid, 1)
            # payment behavior
            if c["behavior"] == "prompt":
                pay = add_bdays(due, rng.randrange(-3, 3))
                parts = [(pay, total)]
            elif c["behavior"] == "late":
                pay = due + dt.timedelta(days=rng.randrange(4, 21))
                parts = [(next_bday(pay), total)]
            else:
                pay = due + dt.timedelta(days=rng.randrange(18, 46))
                if rng.random() < 0.3:
                    p1 = int(total * 0.6)
                    parts = [(next_bday(pay), p1),
                             (next_bday(pay + dt.timedelta(days=rng.randrange(8, 16))),
                              total - p1)]
                else:
                    parts = [(next_bday(pay), total)]
            seqn = 2
            last_pay = max(p[0] for p in parts)
            for trigger, tmpl in ((7, DUN_1), (21, DUN_2)):
                dun_d = next_bday(due + dt.timedelta(days=trigger))
                if last_pay > dun_d and dun_d <= SIM_END:
                    make_email(world, rng, dun_d, fin["email"], c["email"], subj,
                               f"Dear {c['contact'].split()[0]},\n\n"
                               + tmpl.format(inv=number, amt=fmt_money(total), due=ymd(due))
                               + "\n" + sig(fin["name"], COMPANY["name"]), tid, seqn)
                    seqn += 1
                    inv["dunning_count"] += 1
            for pd, amt in parts:
                if pd <= SIM_END:
                    inv["receipts"].append({"date": pd, "amount": amt})
                    world["bank_txns"].append({
                        "date": pd, "amount": amt,
                        "description": f"WIRE IN {c['name'].upper()} {number}",
                        "ref": number, "category": "customer_receipt",
                        "counterparty": c["name"]})
            paid = sum(r["amount"] for r in inv["receipts"])
            inv["status"] = "paid" if paid >= total else \
                ("partial" if paid > 0 else "open")


# ---------------------------------------------------------------- bank
def run_bank(world, rng):
    world["bank_txns"].append({
        "date": SIM_START, "amount": OPENING_CAPITAL,
        "description": "CAPITAL CONTRIBUTION COBALT PEAK HOLDINGS",
        "ref": "CAP-001", "category": "capital", "counterparty": "Shareholders"})
    for (y, m) in months():
        world["bank_txns"].append({
            "date": last_bday(y, m), "amount": -BANK_FEE,
            "description": "ACCOUNT SERVICE FEE", "ref": f"FEE-{month_key(y, m)}",
            "category": "bank_fee", "counterparty": "First Meridian Bank"})
        if m in (1, 4, 7, 10) and (y, m) != (SIM_START.year, SIM_START.month):
            world["bank_txns"].append({
                "date": next_bday(dt.date(y, m, 15)), "amount": -CORP_TAX_QUARTERLY,
                "description": f"EST CORP INCOME TAX Q PAYMENT",
                "ref": f"CTX-{month_key(y, m)}", "category": "corp_tax",
                "counterparty": "Federal Tax Authority"})
    order = {"capital": 0, "customer_receipt": 1, "vendor_payment": 2,
             "payroll": 3, "payroll_tax": 4, "corp_tax": 5, "bank_fee": 6}
    world["bank_txns"].sort(key=lambda t: (t["date"], order[t["category"]], t["ref"]))
    bal = 0
    for t in world["bank_txns"]:
        bal += t["amount"]
        t["balance"] = bal
        assert bal >= 0, f"negative balance {bal} at {t['date']} {t['description']}"


def simulate(world, rng):
    for key in ("pos", "vendor_invoices", "customer_invoices", "timesheets",
                "payroll_runs", "bank_txns", "emails", "anomalies"):
        world[key] = []
    run_timesheets_and_payroll(world, rng)
    run_procurement(world, rng)
    run_revenue(world, rng)
    run_bank(world, rng)
    world["emails"].sort(key=lambda e: e["dt"])
    return world
