"""Renders the document mountain under out/docs/."""
import os
import csv
from .core import COMPANY, fmt_money, ymd, months, month_key
from .simulate import SIM_END

HR = "=" * 72


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def render_emails(world, docs):
    for e in world["emails"]:
        folder = e["dt"].strftime("%Y-%m")
        slug = e["thread_id"].replace("/", "-")
        name = f"{e['dt'].strftime('%Y%m%d-%H%M%S')}__{slug}__{e['seq']:02d}.eml"
        irt = f"In-Reply-To: {e['in_reply_to']}\n" if e["in_reply_to"] else ""
        cc = f"Cc: {e['cc']}\n" if e["cc"] else ""
        _w(os.path.join(docs, "emails", folder, name),
           f"Message-ID: {e['msg_id']}\n{irt}From: {e['from']}\nTo: {e['to']}\n{cc}"
           f"Date: {e['dt'].strftime('%a, %d %b %Y %H:%M:%S -0600')}\n"
           f"Subject: {e['subject']}\n\n{e['body']}")


def render_pos(world, docs):
    vmap = {v["id"]: v for v in world["vendors"]}
    for po in world["pos"]:
        v = vmap[po["vendor_id"]]
        term = ""
        if po["kind"] == "blanket":
            term = (f"Agreement term   : {ymd(po['term_start'])} to {ymd(po['term_end'])}\n"
                    f"Billing cadence  : every {po['every']} month(s), "
                    f"{fmt_money(po['final_amount'] // (12 // po['every']))} per period\n")
        disc = (f"Negotiated       : {po['discount_pct']}% off quoted "
                f"{fmt_money(po['list_amount'])}\n") if po["discount_pct"] else ""
        _w(os.path.join(docs, "purchase_orders", po["po_number"] + ".txt"), f"""{HR}
                    PURCHASE ORDER   {po['po_number']}
{HR}
Buyer            : {COMPANY['name']}
                   {COMPANY['address']}
Vendor           : {v['name']} ({v['id']})
Vendor contact   : {v['contact']} <{v['email']}>
Category         : {v['category']}
Issue date       : {ymd(po['issue_date'])}
Signed date      : {ymd(po['signed_date'])}
{term}{disc}Payment terms    : net {v['terms_days']}
Description      : {po['description']}
{HR}
TOTAL COMMITTED  : {fmt_money(po['final_amount'])}
{HR}
Authorized by    : {world['cfo']['name']}, CFO
""")


def render_vendor_invoices(world, docs):
    vmap = {v["id"]: v for v in world["vendors"]}
    for inv in world["vendor_invoices"]:
        v = vmap[inv["vendor_id"]]
        po_line = inv["po_number"] or "(none supplied)"
        suffix = "__resubmitted" if inv["anomaly"] == "duplicate" else ""
        fn = inv["inv_number"].replace("/", "-") + suffix + ".txt"
        _w(os.path.join(docs, "vendor_invoices", fn), f"""{HR}
  {v['name'].upper()}
  {v['category']}  |  billing@{v['domain']}
{HR}
INVOICE          : {inv['inv_number']}
Invoice date     : {ymd(inv['date'])}
Bill to          : {COMPANY['name']}, {COMPANY['address']}
PO reference     : {po_line}
Description      : {inv['description']}
Payment terms    : net {v['terms_days']}  (due {ymd(inv['due_date'])})
{HR}
AMOUNT DUE       : {fmt_money(inv['amount'])}
{HR}
Remit to: {v['name']}, via ACH on file.
""")


def render_customer_invoices(world, docs):
    cmap = {c["id"]: c for c in world["customers"]}
    for inv in world["customer_invoices"]:
        c = cmap[inv["customer_id"]]
        lines = "\n".join(f"  {l['desc']:<64} {fmt_money(l['amount']):>14}"
                          for l in inv["lines"])
        _w(os.path.join(docs, "customer_invoices", inv["inv_number"] + ".txt"), f"""{HR}
  {COMPANY['name'].upper()}
  {COMPANY['address']}  |  Tax ID {COMPANY['tax_id']}
{HR}
INVOICE          : {inv['inv_number']}
Service period   : {inv['period']}
Issue date       : {ymd(inv['issue_date'])}
Bill to          : {c['name']}
Attn             : {c['contact']} <{c['email']}>
Payment terms    : net {c['terms_days']}  (due {ymd(inv['due_date'])})
{HR}
{lines}
{HR}
TOTAL DUE        : {fmt_money(inv['amount'])}
{HR}
Please remit by wire to {COMPANY['bank']}.
""")


def render_timesheets(world, docs):
    emap = world["emap"]
    for ts in world["timesheets"]:
        e = emap[ts["employee_id"]]
        mgr = emap[ts["approver_id"]]
        path = os.path.join(docs, "timesheets", ts["month"],
                            f"{e['id']}_{ts['month']}.csv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["employee_id", "employee", "month", "week_start",
                        "project_code", "hours"])
            for wk in ts["weeks"]:
                for code, hrs in sorted(wk["alloc"].items()):
                    w.writerow([e["id"], e["name"], ts["month"],
                                ymd(wk["week_start"]), code, hrs])
            w.writerow([])
            w.writerow(["status", "APPROVED", "approver", mgr["name"],
                        "approved_on", ymd(ts["approved_date"])])
            if ts["rejected"]:
                w.writerow(["note", f"resubmitted {ymd(ts['resubmitted_date'])} "
                                    f"after rejection: {ts['rejection_reason']}"])


def render_payroll(world, docs):
    emap = world["emap"]
    for run in world["payroll_runs"]:
        for s in run["slips"]:
            e = emap[s["employee_id"]]
            pro = "  (prorated for partial month)" if s["prorated"] else ""
            _w(os.path.join(docs, "payroll", run["month"],
                            f"payslip_{e['id']}.txt"), f"""{HR}
  {COMPANY['name'].upper()}  —  PAYSLIP  {run['month']}
{HR}
Employee         : {e['name']}  ({e['id']})
Title            : {e['title']}, {e['dept']}
Pay date         : {ymd(run['pay_date'])}
Gross salary     : {fmt_money(s['gross'])}{pro}
Tax withheld     : {fmt_money(s['tax'])}  (24%)
NET PAID         : {fmt_money(s['net'])}
Paid via ACH to account on file.
{HR}
""")
        summary = "\n".join(
            f"  {emap[s['employee_id']]['id']}  {emap[s['employee_id']]['name']:<28} "
            f"gross {fmt_money(s['gross']):>12}  net {fmt_money(s['net']):>12}"
            for s in run["slips"])
        _w(os.path.join(docs, "payroll", run["month"], "_register.txt"),
           f"PAYROLL REGISTER {run['month']}  (pay date {ymd(run['pay_date'])})\n{HR}\n"
           f"{summary}\n{HR}\n"
           f"TOTAL GROSS {fmt_money(run['total_gross'])}   "
           f"TOTAL WITHHELD {fmt_money(run['total_tax'])}   "
           f"TOTAL NET {fmt_money(run['total_net'])}\n"
           f"Employer payroll tax accrued: {fmt_money(run['employer_tax'])}\n")


def render_bank(world, docs):
    by_month = {}
    for t in world["bank_txns"]:
        by_month.setdefault(month_key(t["date"].year, t["date"].month), []).append(t)
    opening = 0
    for mk in sorted(by_month):
        txns = by_month[mk]
        path = os.path.join(docs, "bank_statements", f"statement_{mk}.csv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([f"# {COMPANY['bank']} — {COMPANY['name']}"])
            w.writerow([f"# Statement period {mk} | opening balance",
                        f"{opening / 100:.2f}"])
            w.writerow(["date", "description", "ref", "debit", "credit", "balance"])
            for t in txns:
                debit = f"{-t['amount'] / 100:.2f}" if t["amount"] < 0 else ""
                credit = f"{t['amount'] / 100:.2f}" if t["amount"] > 0 else ""
                w.writerow([ymd(t["date"]), t["description"], t["ref"],
                            debit, credit, f"{t['balance'] / 100:.2f}"])
        closing = txns[-1]["balance"]
        credits = sum(t["amount"] for t in txns if t["amount"] > 0)
        debits = sum(-t["amount"] for t in txns if t["amount"] < 0)
        _w(os.path.join(docs, "bank_statements", f"statement_{mk}.txt"),
           f"{COMPANY['bank']}\nStatement {mk} — {COMPANY['name']}\n{HR}\n"
           f"Opening balance : {fmt_money(opening)}\n"
           f"Total credits   : {fmt_money(credits)}\n"
           f"Total debits    : {fmt_money(debits)}\n"
           f"Closing balance : {fmt_money(closing)}\n"
           f"Transactions    : {len(txns)}  (see statement_{mk}.csv)\n")
        opening = closing


def render_directory(world, docs):
    lines = [f"{COMPANY['name']} — EMPLOYEE DIRECTORY (point-in-time roster with "
             f"hire/exit dates)", HR]
    for e in world["employees"]:
        ex = f"  exited {ymd(e['exit_date'])}" if e["exit_date"] else ""
        lines.append(f"{e['id']}  {e['name']:<26} {e['title']:<28} {e['dept']:<12} "
                     f"hired {ymd(e['hire_date'])}{ex}")
    _w(os.path.join(docs, "company", "employee_directory.txt"), "\n".join(lines) + "\n")
    lines = [f"{COMPANY['name']} — APPROVED VENDOR LIST", HR]
    for v in world["vendors"]:
        lines.append(f"{v['id']}  {v['name']:<36} {v['category']:<20} net {v['terms_days']}")
    _w(os.path.join(docs, "company", "vendor_list.txt"), "\n".join(lines) + "\n")
    lines = [f"{COMPANY['name']} — CLIENT LIST", HR]
    for c in world["customers"]:
        model = "retainer" if c["model"] == "retainer" else "time & materials"
        lines.append(f"{c['id']}  {c['name']:<36} {model:<18} net {c['terms_days']}")
    _w(os.path.join(docs, "company", "client_list.txt"), "\n".join(lines) + "\n")


def render_all(world, docs):
    render_emails(world, docs)
    render_pos(world, docs)
    render_vendor_invoices(world, docs)
    render_customer_invoices(world, docs)
    render_timesheets(world, docs)
    render_payroll(world, docs)
    render_bank(world, docs)
    render_directory(world, docs)
