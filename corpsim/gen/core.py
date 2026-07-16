"""Core helpers: config, money, dates, name pools."""
import datetime as dt

SEED = 20260716
SIM_START = dt.date(2024, 7, 1)   # first day of month 1
N_MONTHS = 24                     # 2024-07 .. 2026-06
OPENING_CAPITAL = 2_500_000_00    # cents
COMPANY = {
    "name": "Cobalt Peak Software Ltd.",
    "short": "Cobalt Peak",
    "code": "CPS",
    "domain": "cobaltpeak.example",
    "address": "410 Summit Trade Center, Suite 900, Denver, CO 80202",
    "bank": "First Meridian Bank, acct ****4471",
    "tax_id": "84-2216690",
}
BANK_FEE = 45_00
TAX_WITHHOLD = 0.24
EMPLOYER_TAX = 0.085          # employer-side payroll tax remitted monthly
CORP_TAX_QUARTERLY = 60_000_00


def months():
    """[(year, month)] for the whole simulation."""
    out, y, m = [], SIM_START.year, SIM_START.month
    for _ in range(N_MONTHS):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def month_start(y, m):
    return dt.date(y, m, 1)


def month_end(y, m):
    if m == 12:
        return dt.date(y, 12, 31)
    return dt.date(y, m + 1, 1) - dt.timedelta(days=1)


def is_bday(d):
    return d.weekday() < 5


def next_bday(d):
    while not is_bday(d):
        d += dt.timedelta(days=1)
    return d


def prev_bday(d):
    while not is_bday(d):
        d -= dt.timedelta(days=1)
    return d


def first_bday(y, m):
    return next_bday(month_start(y, m))


def last_bday(y, m):
    return prev_bday(month_end(y, m))


def add_bdays(d, n):
    while n > 0:
        d += dt.timedelta(days=1)
        if is_bday(d):
            n -= 1
    return d


def mondays_in(y, m):
    """Mondays whose week (Mon-Fri) overlaps this month; used as timesheet week rows."""
    d = month_start(y, m)
    d -= dt.timedelta(days=d.weekday())  # back to Monday
    out = []
    while d <= month_end(y, m):
        if d + dt.timedelta(days=4) >= month_start(y, m):  # week touches month
            out.append(d)
        d += dt.timedelta(days=7)
    return out


def workdays_of_week_in_month(monday, y, m):
    """How many of Mon..Fri of this week fall inside month (y,m)."""
    n = 0
    for i in range(5):
        d = monday + dt.timedelta(days=i)
        if d.month == m and d.year == y:
            n += 1
    return n


def fmt_money(cents, sym="$"):
    neg = cents < 0
    cents = abs(cents)
    s = f"{sym}{cents // 100:,}.{cents % 100:02d}"
    return "-" + s if neg else s


def ymd(d):
    return d.strftime("%Y-%m-%d")


def month_key(y, m):
    return f"{y:04d}-{m:02d}"


def quarter_of(y, m):
    return f"{y}-Q{(m - 1) // 3 + 1}"


FIRST_NAMES = [
    "Ava", "Liam", "Maya", "Noah", "Zoe", "Ethan", "Isla", "Mason", "Chloe", "Lucas",
    "Priya", "Arjun", "Nia", "Kofi", "Amara", "Diego", "Lucia", "Mateo", "Sofia", "Andrei",
    "Ingrid", "Hana", "Kenji", "Yuki", "Wei", "Mei", "Omar", "Layla", "Tariq", "Fatima",
    "Elena", "Viktor", "Sasha", "Petra", "Nils", "Freya", "Ciaran", "Aoife", "Ewan", "Skye",
    "Jordan", "Taylor", "Casey", "Riley", "Morgan", "Avery", "Quinn", "Rowan", "Sage", "Emerson",
    "Dante", "Leila", "Marcus", "Simone", "Felix", "Clara", "Hugo", "Alma", "Ivan", "Rosa",
]
LAST_NAMES = [
    "Calloway", "Mercer", "Ashford", "Vance", "Holloway", "Kincaid", "Draper", "Whitfield",
    "Sablewood", "Fenwick", "Okafor", "Ramanathan", "Kowalczyk", "Ferreira", "Novak",
    "Takahashi", "Lindqvist", "Moreau", "Castellanos", "Petrov", "Nakamura", "Osei",
    "Delgado", "Hartmann", "Bergstrom", "Iwu", "Chandrasekar", "Alvarez", "Kobayashi",
    "Marchetti", "Sorensen", "Vasquez", "Adeyemi", "Rahman", "Kaplan", "Duarte",
    "Silvestri", "Brandt", "Oyelaran", "Mikkelsen", "Reyes", "Tanaka", "Weiss",
    "Abernathy", "Colfax", "Dunmore", "Ellsworth", "Farrow", "Gable", "Huxley",
    "Ives", "Joyner", "Kerrigan", "Lockhart",
]
