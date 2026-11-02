"""Double-entry accounting. Money is held as whole paisa, because binary floats cannot
represent 0.10 exactly and rounding errors must never reach a set of books."""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TYPES = ("asset", "liability", "equity", "income", "expense")
DEBIT_NORMAL = ("asset", "expense")


class LedgerError(Exception):
    pass


def to_paisa(text):
    """Parse money exactly. Refuses more than two decimal places rather than silently rounding."""
    try:
        d = Decimal(str(text).replace(",", "").strip())
    except InvalidOperation:
        raise LedgerError(f"not an amount: {text}") from None
    if not d.is_finite():
        raise LedgerError(f"not an amount: {text}")
    scaled = d * 100
    if scaled != scaled.to_integral_value():
        raise LedgerError(f"too many decimal places: {text}")
    return int(scaled)


def money(paisa):
    sign = "-" if paisa < 0 else ""
    p = abs(paisa)
    return f"{sign}{p // 100:,}.{p % 100:02d}"


@dataclass
class Account:
    code: str
    name: str
    kind: str

    def __post_init__(self):
        if self.kind not in TYPES:
            raise LedgerError(f"unknown account type {self.kind}")


@dataclass
class Line:
    account: str
    debit: int = 0
    credit: int = 0


@dataclass
class Entry:
    id: int
    day: str
    memo: str
    lines: list
    reverses: int = None


def check_entry(lines, accounts):
    """A journal entry must have at least two lines and debits equal to credits."""
    if len(lines) < 2:
        raise LedgerError("an entry needs at least two lines")
    for l in lines:
        if l.account not in accounts:
            raise LedgerError(f"unknown account {l.account}")
        if l.debit < 0 or l.credit < 0:
            raise LedgerError("amounts cannot be below zero; use the other side")
        if (l.debit > 0) == (l.credit > 0):
            raise LedgerError(f"a line for {l.account} needs a debit or a credit, not both")
    d, c = sum(l.debit for l in lines), sum(l.credit for l in lines)
    if d != c:
        raise LedgerError(f"debits {money(d)} do not equal credits {money(c)}")


def reversal(entry, new_id, day):
    """Correct a mistake with a new opposite entry. Posted entries are never edited."""
    return Entry(new_id, day, f"Reversal of entry {entry.id}: {entry.memo}", [Line(l.account, l.credit, l.debit) for l in entry.lines], entry.id)


def balances(entries, accounts, start=None, end=None):
    """{account code: debit minus credit}, within a date range."""
    out = {c: 0 for c in accounts}
    for e in entries:
        if (start and e.day < start) or (end and e.day > end):
            continue
        for l in e.lines:
            out[l.account] += l.debit - l.credit
    return out


def trial_balance(entries, accounts, end=None):
    b = balances(entries, accounts, end=end)
    rows = []
    for code, acc in sorted(accounts.items()):
        v = b[code]
        if v:
            rows.append((code, acc.name, max(v, 0), max(-v, 0)))
    return rows, sum(r[2] for r in rows), sum(r[3] for r in rows)


def income_statement(entries, accounts, start, end):
    b = balances(entries, accounts, start, end)
    income = [(a, -b[c]) for c, a in sorted(accounts.items()) if a.kind == "income" and b[c]]
    expense = [(a, b[c]) for c, a in sorted(accounts.items()) if a.kind == "expense" and b[c]]
    ti, te = sum(v for _, v in income), sum(v for _, v in expense)
    return {"income": income, "expenses": expense, "total_income": ti, "total_expenses": te, "surplus": ti - te}


def balance_sheet(entries, accounts, end):
    """Assets = liabilities + equity + all surplus so far. If this fails, the books are broken."""
    b = balances(entries, accounts, end=end)
    pick = lambda kind, sign: [(a, sign * b[c]) for c, a in sorted(accounts.items()) if a.kind == kind and b[c]]
    assets, liabilities, equity = pick("asset", 1), pick("liability", -1), pick("equity", -1)
    surplus = sum(-b[c] for c, a in accounts.items() if a.kind == "income") - sum(b[c] for c, a in accounts.items() if a.kind == "expense")
    ta = sum(v for _, v in assets)
    tl = sum(v for _, v in liabilities) + sum(v for _, v in equity) + surplus
    return {"assets": assets, "liabilities": liabilities, "equity": equity, "surplus": surplus, "total_assets": ta, "total_claims": tl, "balanced": ta == tl}


def ledger(entries, code, normal_debit=True):
    """Lines for one account, with a running balance."""
    rows, total = [], 0
    for e in sorted(entries, key=lambda e: (e.day, e.id)):
        for l in e.lines:
            if l.account == code:
                total += (l.debit - l.credit) * (1 if normal_debit else -1)
                rows.append((e.day, e.id, e.memo, l.debit, l.credit, total))
    return rows


def reconcile(book, bank):
    """Match bank statement lines with cash book lines. Both are (date, amount, text), where a
    deposit is positive. Same amount first, nearest date second, each line used once.
    Returns (matches, only in the book, only at the bank)."""
    left = list(range(len(book)))
    matches, bank_only = [], []
    for j, (day, amount, text) in enumerate(bank):
        hits = [i for i in left if book[i][1] == amount]
        if hits:
            def gap(i):
                from datetime import date
                return abs((date.fromisoformat(book[i][0]) - date.fromisoformat(day)).days)
            i = min(hits, key=gap)
            left.remove(i)
            matches.append((i, j))
        else:
            bank_only.append(j)
    return matches, left, bank_only


def reconciled_balance(book_balance, bank_balance, book, bank, book_only, bank_only):
    """Adjust each side for items the other has not seen. A correct reconciliation ends in zero."""
    adjusted_bank = bank_balance + sum(book[i][1] for i in book_only)
    adjusted_book = book_balance + sum(bank[j][1] for j in bank_only)
    return adjusted_book, adjusted_bank, adjusted_book - adjusted_bank


STARTER = [("1000", "Cash in hand", "asset"), ("1010", "Bank account", "asset"), ("1200", "Advances to staff", "asset"), ("2000", "Accounts payable", "liability"), ("2100", "Deferred grant income", "liability"), ("3000", "Accumulated fund", "equity"), ("4000", "Grant income", "income"), ("4100", "Donations", "income"), ("5000", "Salaries", "expense"), ("5100", "Rent", "expense"), ("5200", "Programme supplies", "expense"), ("5300", "Travel", "expense"), ("5400", "Office costs", "expense")]
