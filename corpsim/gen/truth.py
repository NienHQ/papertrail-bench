"""Held-out source of truth: SQLite DB + benchmark questions with answer key."""
import os
import sqlite3
import datetime as dt
from .core import ymd, month_key, months, month_end, fmt_money
from .simulate import SIM_END


def build_db(world, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    c = db.cursor()
    c.executescript("""
    CREATE TABLE employees(id TEXT PRIMARY KEY, name TEXT, dept TEXT, title TEXT,
        email TEXT, salary_cents INT, billable INT, bill_rate_cents INT,
        hire_date TEXT, exit_date TEXT, manager_id TEXT);
    CREATE TABLE vendors(id TEXT PRIMARY KEY, name TEXT, category TEXT, mode TEXT,
        terms_days INT, contact TEXT, email TEXT);
    CREATE TABLE customers(id TEXT PRIMARY KEY, name TEXT, model TEXT, behavior TEXT,
        terms_days INT, retainer_cents INT, contact TEXT, email TEXT, team_ids TEXT);
    CREATE TABLE purchase_orders(po_number TEXT PRIMARY KEY, vendor_id TEXT,
        kind TEXT, issue_date TEXT, signed_date TEXT, term_start TEXT, term_end TEXT,
        list_amount_cents INT, final_amount_cents INT, discount_pct REAL,
        description TEXT);
    CREATE TABLE vendor_invoices(rowid_ INTEGER PRIMARY KEY AUTOINCREMENT,
        inv_number TEXT, vendor_id TEXT, po_number TEXT, true_po_number TEXT,
        invoice_date TEXT, due_date TEXT, amount_cents INT, correct_amount_cents INT,
        anomaly TEXT, description TEXT, period TEXT, status TEXT,
        paid_amount_cents INT, paid_date TEXT);
    CREATE TABLE customer_invoices(inv_number TEXT PRIMARY KEY, customer_id TEXT,
        period TEXT, issue_date TEXT, due_date TEXT, amount_cents INT, status TEXT,
        dunning_count INT);
    CREATE TABLE receipts(inv_number TEXT, date TEXT, amount_cents INT);
    CREATE TABLE timesheet_lines(employee_id TEXT, month TEXT, week_start TEXT,
        project_code TEXT, hours INT);
    CREATE TABLE timesheets(employee_id TEXT, month TEXT, submitted_date TEXT,
        approved_date TEXT, approver_id TEXT, rejected INT, rejection_reason TEXT);
    CREATE TABLE payroll_slips(month TEXT, pay_date TEXT, employee_id TEXT,
        gross_cents INT, tax_cents INT, net_cents INT, prorated INT);
    CREATE TABLE bank_transactions(date TEXT, description TEXT, ref TEXT,
        category TEXT, counterparty TEXT, amount_cents INT, balance_cents INT);
    CREATE TABLE anomalies(kind TEXT, ref TEXT, vendor_id TEXT, date TEXT,
        delta_cents INT, note TEXT);
    CREATE TABLE emails(msg_id TEXT, thread_id TEXT, seq INT, dt TEXT,
        sender TEXT, recipient TEXT, subject TEXT);
    """)
    for e in world["employees"]:
        c.execute("INSERT INTO employees VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (e["id"], e["name"], e["dept"], e["title"], e["email"], e["salary"],
                   int(e["billable"]), e["bill_rate"], ymd(e["hire_date"]),
                   ymd(e["exit_date"]) if e["exit_date"] else None, e["manager_id"]))
    for v in world["vendors"]:
        c.execute("INSERT INTO vendors VALUES(?,?,?,?,?,?,?)",
                  (v["id"], v["name"], v["category"], v["mode"], v["terms_days"],
                   v["contact"], v["email"]))
    for cu in world["customers"]:
        c.execute("INSERT INTO customers VALUES(?,?,?,?,?,?,?,?,?)",
                  (cu["id"], cu["name"], cu["model"], cu["behavior"], cu["terms_days"],
                   cu["retainer"], cu["contact"], cu["email"], ",".join(cu["team_ids"])))
    for p in world["pos"]:
        c.execute("INSERT INTO purchase_orders VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (p["po_number"], p["vendor_id"], p["kind"], ymd(p["issue_date"]),
                   ymd(p["signed_date"]),
                   ymd(p["term_start"]) if p["term_start"] else None,
                   ymd(p["term_end"]) if p["term_end"] else None,
                   p["list_amount"], p["final_amount"], p["discount_pct"],
                   p["description"]))
    for i in world["vendor_invoices"]:
        c.execute("INSERT INTO vendor_invoices(inv_number, vendor_id, po_number, "
                  "true_po_number, invoice_date, due_date, amount_cents, "
                  "correct_amount_cents, anomaly, description, period, status, "
                  "paid_amount_cents, paid_date) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (i["inv_number"], i["vendor_id"], i["po_number"], i["true_po_number"],
                   ymd(i["date"]), ymd(i["due_date"]), i["amount"], i["correct_amount"],
                   i["anomaly"], i["description"], i["period"], i["status"],
                   i["paid_amount"], ymd(i["paid_date"]) if i["paid_date"] else None))
    for i in world["customer_invoices"]:
        c.execute("INSERT INTO customer_invoices VALUES(?,?,?,?,?,?,?,?)",
                  (i["inv_number"], i["customer_id"], i["period"], ymd(i["issue_date"]),
                   ymd(i["due_date"]), i["amount"], i["status"], i["dunning_count"]))
        for r in i["receipts"]:
            c.execute("INSERT INTO receipts VALUES(?,?,?)",
                      (i["inv_number"], ymd(r["date"]), r["amount"]))
    for ts in world["timesheets"]:
        c.execute("INSERT INTO timesheets VALUES(?,?,?,?,?,?,?)",
                  (ts["employee_id"], ts["month"], ymd(ts["submitted_date"]),
                   ymd(ts["approved_date"]), ts["approver_id"], int(ts["rejected"]),
                   ts["rejection_reason"]))
        for w in ts["weeks"]:
            for code, hrs in w["alloc"].items():
                c.execute("INSERT INTO timesheet_lines VALUES(?,?,?,?,?)",
                          (ts["employee_id"], ts["month"], ymd(w["week_start"]),
                           code, hrs))
    for run in world["payroll_runs"]:
        for s in run["slips"]:
            c.execute("INSERT INTO payroll_slips VALUES(?,?,?,?,?,?,?)",
                      (run["month"], ymd(run["pay_date"]), s["employee_id"],
                       s["gross"], s["tax"], s["net"], int(s["prorated"])))
    for t in world["bank_txns"]:
        c.execute("INSERT INTO bank_transactions VALUES(?,?,?,?,?,?,?)",
                  (ymd(t["date"]), t["description"], t["ref"], t["category"],
                   t["counterparty"], t["amount"], t["balance"]))
    for a in world["anomalies"]:
        c.execute("INSERT INTO anomalies VALUES(?,?,?,?,?,?)",
                  (a["kind"], a["ref"], a["vendor_id"], ymd(a["date"]), a["delta"],
                   a["note"]))
    for e in world["emails"]:
        c.execute("INSERT INTO emails VALUES(?,?,?,?,?,?,?)",
                  (e["msg_id"], e["thread_id"], e["seq"], e["dt"].isoformat(),
                   e["from"], e["to"], e["subject"]))
    db.commit()
    db.close()


# ---------------------------------------------------------------- questions
def usd(cents):
    return round(cents / 100, 2)


def build_questions(world, rng):
    """Returns [{id, category, question, answer_type, answer, tolerance_pct}].
    Everything is computed from the simulated world, so the key is exact."""
    Q = []
    vmap = {v["id"]: v for v in world["vendors"]}
    cmap = {c["id"]: c for c in world["customers"]}
    emap = world["emap"]

    def add(cat, question, ans, atype="number", tol=0.1):
        Q.append({"id": f"Q{len(Q)+1:03d}", "category": cat, "question": question,
                  "answer_type": atype, "answer": ans, "tolerance_pct": tol})

    window = "between 2024-07-01 and 2026-06-30 inclusive"

    # -- AP / vendor spend
    paid_by_vendor = {}
    for i in world["vendor_invoices"]:
        paid_by_vendor[i["vendor_id"]] = paid_by_vendor.get(i["vendor_id"], 0) \
            + i["paid_amount"]
    for vid in rng.sample(sorted(paid_by_vendor), 5):
        add("vendor_spend",
            f"What total amount (USD) was actually paid from the bank account to "
            f"{vmap[vid]['name']} {window}?", usd(paid_by_vendor[vid]))
    top3 = sorted(paid_by_vendor, key=lambda v: -paid_by_vendor[v])[:3]
    add("vendor_spend",
        f"Which three vendors received the highest total payments {window}? "
        f"Answer with vendor names.", [vmap[v]["name"] for v in top3], "list")
    add("vendor_spend",
        f"How many distinct vendor invoices (excluding duplicate resubmissions) did "
        f"the company receive {window}?",
        sum(1 for i in world["vendor_invoices"] if i["anomaly"] != "duplicate"),
        tol=0)

    # -- anomalies / controls
    over = [a for a in world["anomalies"] if a["kind"] == "overbilling"]
    dups = [a for a in world["anomalies"] if a["kind"] == "duplicate"]
    nopo = [a for a in world["anomalies"] if a["kind"] == "missing_po_ref"]
    add("anomalies", "List the invoice numbers of every vendor invoice that was "
        "submitted with an amount higher than its purchase order authorized "
        "(overbilling caught by AP).", [a["ref"] for a in over], "list")
    add("anomalies", "What is the total USD amount of overbilling that AP caught and "
        "avoided paying (sum of submitted-minus-authorized across all overbilled "
        "invoices)?", usd(sum(a["delta"] for a in over)))
    add("anomalies", "List the invoice numbers that vendors submitted twice "
        "(duplicate resubmissions rejected by AP).", [a["ref"] for a in dups], "list")
    add("anomalies", "How many vendor invoices arrived without a PO reference and had "
        "to be resolved by email?", len(nopo), tol=0)

    # -- procurement
    savings = sum(p["list_amount"] - p["final_amount"] for p in world["pos"])
    add("procurement", f"Across all purchase orders signed {window}, what total USD "
        f"amount was saved through negotiation (sum of quoted price minus signed "
        f"price)?", usd(savings))
    negotiated = [p for p in world["pos"] if p["discount_pct"] > 0]
    big = max(negotiated, key=lambda p: p["list_amount"] - p["final_amount"])
    add("procurement", f"Which single purchase order achieved the largest absolute "
        f"negotiated saving, and to which vendor was it issued? Answer with the PO "
        f"number.", big["po_number"], "string")
    add("procurement", f"How many purchase orders were signed in calendar year 2025?",
        sum(1 for p in world["pos"] if p["signed_date"].year == 2025), tol=0)

    # -- AR / revenue
    rev_by_cust = {}
    for i in world["customer_invoices"]:
        rev_by_cust[i["customer_id"]] = rev_by_cust.get(i["customer_id"], 0) + i["amount"]
    for cid in rng.sample(sorted(rev_by_cust), 4):
        add("revenue", f"What total USD amount did the company invoice to "
            f"{cmap[cid]['name']} across all invoices issued {window}?",
            usd(rev_by_cust[cid]))
    fy = [i for i in world["customer_invoices"]
          if dt.date(2025, 1, 1) <= i["issue_date"] <= dt.date(2025, 12, 31)]
    add("revenue", "What was the total USD amount invoiced to all customers on "
        "invoices issued in calendar year 2025?", usd(sum(i["amount"] for i in fy)))
    open_ar = [i for i in world["customer_invoices"] if i["status"] != "paid"]
    add("revenue", "As of 2026-06-30, which customer invoices were not yet fully "
        "paid? Answer with invoice numbers.", [i["inv_number"] for i in open_ar], "list")
    partials = [i for i in world["customer_invoices"]
                if len(i["receipts"]) > 1]
    add("revenue", "Which customer invoices were settled in more than one payment "
        "(partial payments)? Answer with invoice numbers.",
        [i["inv_number"] for i in partials], "list")

    # days late / dunning
    lateness = {}
    for i in world["customer_invoices"]:
        paid = sum(r["amount"] for r in i["receipts"])
        if paid >= i["amount"] and i["receipts"]:
            last = max(r["date"] for r in i["receipts"])
            lateness.setdefault(i["customer_id"], []).append(
                max(0, (last - i["due_date"]).days))
    worst = max(lateness, key=lambda c: sum(lateness[c]) / len(lateness[c]))
    add("collections", "Which customer had the highest average days-late to fully "
        "settle its invoices (considering only invoices fully paid by 2026-06-30, "
        "days late = max(0, final payment date minus due date))? Answer with the "
        "customer name.", cmap[worst]["name"], "string")
    add("collections", f"What was that highest average days-late value, for "
        f"{cmap[worst]['name']}? Answer in days.",
        round(sum(lateness[worst]) / len(lateness[worst]), 1), tol=2.0)
    dun_total = sum(i["dunning_count"] for i in world["customer_invoices"])
    add("collections", f"How many payment-reminder (dunning) emails did the company "
        f"send to customers {window}?", dun_total, tol=0)

    # -- payroll & timesheets
    for year in (2025,):
        net = sum(s["net"] for r in world["payroll_runs"] for s in r["slips"]
                  if r["month"].startswith(str(year)))
        gross = sum(s["gross"] for r in world["payroll_runs"] for s in r["slips"]
                    if r["month"].startswith(str(year)))
        add("payroll", f"What was the total NET payroll paid to employees in calendar "
            f"year {year} (sum of all payslip net amounts)?", usd(net))
        add("payroll", f"What was the total GROSS payroll for calendar year {year}?",
            usd(gross))
    rej = [t for t in world["timesheets"] if t["rejected"]]
    add("timesheets", f"How many timesheets were rejected by a manager and "
        f"resubmitted {window}?", len(rej), tol=0)
    # hours by a sampled billable employee for their customer in one quarter
    tm_cust = [c for c in world["customers"] if c["model"] == "tm"]
    cpick = rng.choice(tm_cust)
    epick = emap[cpick["team_ids"][0]]
    qmonths = ["2025-01", "2025-02", "2025-03"]
    hrs = sum(w["alloc"].get(cpick["id"], 0)
              for t in world["timesheets"]
              if t["employee_id"] == epick["id"] and t["month"] in qmonths
              for w in t["weeks"])
    add("timesheets", f"How many hours did {epick['name']} ({epick['id']}) log to the "
        f"{cpick['name']} engagement across January–March 2025 (per approved "
        f"timesheets)?", hrs, tol=0)
    hc = sum(1 for e in world["employees"]
             if e["hire_date"] <= dt.date(2025, 12, 31)
             and (not e["exit_date"] or e["exit_date"] >= dt.date(2025, 12, 31)))
    add("timesheets", "How many employees were on the payroll as of 2025-12-31?",
        hc, tol=0)

    # -- bank / reconciliation
    by_month_close = {}
    for t in world["bank_txns"]:
        by_month_close[month_key(t["date"].year, t["date"].month)] = t["balance"]
    for mk in rng.sample(sorted(by_month_close), 6):
        add("bank", f"What was the closing bank balance at the end of {mk} "
            f"(USD, per the bank statement)?", usd(by_month_close[mk]), tol=0.01)
    biggest = min((t for t in world["bank_txns"] if t["amount"] < 0),
                  key=lambda t: t["amount"])
    add("bank", "What was the largest single outgoing bank payment of the entire "
        "24 months, in USD (absolute amount)?", usd(-biggest["amount"]), tol=0.01)
    q_in = sum(t["amount"] for t in world["bank_txns"]
               if t["category"] == "customer_receipt"
               and dt.date(2025, 10, 1) <= t["date"] <= dt.date(2025, 12, 31))
    add("bank", "What total USD amount of customer receipts landed in the bank "
        "account during Q4 2025 (2025-10-01 to 2025-12-31)?", usd(q_in))

    # -- 3-way match spot checks: pick clean invoices from fixed-price vendors
    clean = [i for i in world["vendor_invoices"]
             if i["anomaly"] is None and i["status"] == "paid"
             and vmap[i["vendor_id"]]["params"].get("var", 1) == 0]
    for i in rng.sample(clean, 3):
        add("three_way_match",
            f"Invoice {i['inv_number']} from {vmap[i['vendor_id']]['name']}: which "
            f"purchase order does it bill against? Answer with the PO number.",
            i["true_po_number"], "string")
        add("three_way_match",
            f"What amount (USD) was actually paid against invoice "
            f"{i['inv_number']} from {vmap[i['vendor_id']]['name']}?",
            usd(i["paid_amount"]), tol=0.01)
    return Q
