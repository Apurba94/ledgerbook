"""The offline web app."""
from datetime import date

from . import core
from .core import money
from .fieldkit import App, Fail, Raw, card, form, h, link, redirect, stats, table

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (code TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY, day TEXT NOT NULL, memo TEXT NOT NULL, reverses INTEGER UNIQUE REFERENCES entries(id));
CREATE TABLE IF NOT EXISTS lines (entry INTEGER NOT NULL REFERENCES entries(id), account TEXT NOT NULL REFERENCES accounts(code), debit INTEGER NOT NULL DEFAULT 0, credit INTEGER NOT NULL DEFAULT 0);
CREATE TRIGGER IF NOT EXISTS no_edit_lines BEFORE UPDATE ON lines BEGIN SELECT RAISE(ABORT, 'posted lines cannot be changed'); END;
CREATE TRIGGER IF NOT EXISTS no_drop_lines BEFORE DELETE ON lines BEGIN SELECT RAISE(ABORT, 'posted lines cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS no_edit_entries BEFORE UPDATE ON entries BEGIN SELECT RAISE(ABORT, 'posted entries cannot be changed'); END;
CREATE TRIGGER IF NOT EXISTS no_drop_entries BEFORE DELETE ON entries BEGIN SELECT RAISE(ABORT, 'posted entries cannot be deleted'); END;
"""


def create_app(db="ledger.db", today=date.today):
    a = App("LedgerBook", db, SCHEMA, [("Overview", "/"), ("New entry", "/entry"), ("Accounts", "/accounts"), ("Trial balance", "/trial"), ("Statements", "/statements")])
    if not a.one("SELECT COUNT(*) FROM accounts"):
        for row in core.STARTER:
            a.run("INSERT INTO accounts (code, name, kind) VALUES (?, ?, ?)", *row)

    def accounts():
        return {r["code"]: core.Account(r["code"], r["name"], r["kind"]) for r in a.rows("SELECT * FROM accounts")}

    def entries():
        rows = {}
        for e in a.rows("SELECT * FROM entries ORDER BY id"):
            rows[e["id"]] = core.Entry(e["id"], e["day"], e["memo"], [], e["reverses"])
        for l in a.rows("SELECT * FROM lines"):
            rows[l["entry"]].lines.append(core.Line(l["account"], l["debit"], l["credit"]))
        return list(rows.values())

    def post(day, memo, lines, reverses=None):
        cur = a.run("INSERT INTO entries (day, memo, reverses) VALUES (?, ?, ?)", day, memo, reverses)
        for l in lines:
            a.run("INSERT INTO lines (entry, account, debit, credit) VALUES (?, ?, ?, ?)", cur.lastrowid, l.account, l.debit, l.credit)
        a.log("post", f"{cur.lastrowid} {memo}")
        return cur.lastrowid

    @a.route("/")
    def home(req):
        acc = accounts()
        es = entries()
        y = today().year
        s = core.income_statement(es, acc, f"{y}-01-01", f"{y}-12-31")
        sheet = core.balance_sheet(es, acc, today().isoformat())
        cash = sum(v for ac, v in sheet["assets"] if ac.code.startswith("10"))
        rows = list(reversed(es))[:20]
        body = stats([("Cash and bank", money(cash)), (f"Income {y}", money(s["total_income"])), (f"Spent {y}", money(s["total_expenses"])), ("Surplus", money(s["surplus"]))])
        body += card("Latest entries", table(rows, [("No.", lambda e: e.id), ("Date", lambda e: e.day), ("Memo", lambda e: e.memo), ("Amount", lambda e: money(sum(l.debit for l in e.lines))), ("", lambda e: Raw(f'<form method="post" action="/reverse/{e.id}" style="display:inline">{a.form_token()}<button>Reverse</button></form>'))], "No entries yet."))
        return a.page("Overview", body)

    @a.route("/accounts", ("GET", "POST"))
    def account_page(req):
        if req.method == "POST":
            try:
                core.Account(req.text("code"), req.text("name"), req.text("kind"))
            except core.LedgerError as exc:
                raise Fail(str(exc)) from None
            a.run("INSERT INTO accounts (code, name, kind) VALUES (?, ?, ?)", req.text("code"), req.text("name"), req.text("kind"))
            return redirect("/accounts")
        b = core.balances(entries(), accounts())
        return a.page("Accounts", card("Add an account", form(a, "/accounts", [("code", "Code"), ("name", "Name"), ("kind", "Type", "select", [(t, t) for t in core.TYPES])], "Add")) + card("Chart of accounts", table(sorted(accounts().values(), key=lambda x: x.code), [("Code", lambda x: link(f"/ledger/{x.code}", x.code)), ("Name", lambda x: x.name), ("Type", lambda x: x.kind), ("Balance", lambda x: money(b[x.code] if x.kind in core.DEBIT_NORMAL else -b[x.code]))])))

    @a.route("/ledger/<code>")
    def ledger_page(req, code):
        acc = accounts().get(code)
        if acc is None:
            raise Fail("No such account", 404)
        return a.page(f"{code} {acc.name}", card("Ledger", table(core.ledger(entries(), code, acc.kind in core.DEBIT_NORMAL), [("Date", lambda r: r[0]), ("Entry", lambda r: r[1]), ("Memo", lambda r: r[2]), ("Debit", lambda r: money(r[3]) if r[3] else ""), ("Credit", lambda r: money(r[4]) if r[4] else ""), ("Balance", lambda r: money(r[5]))], "No entries for this account.")))

    @a.route("/entry", ("GET", "POST"))
    def entry(req):
        acc = accounts()
        if req.method == "POST":
            lines = []
            try:
                for i in range(6):
                    code = req.get(f"account{i}")
                    d, c = str(req.get(f"debit{i}")).strip(), str(req.get(f"credit{i}")).strip()
                    if code and (d or c):
                        lines.append(core.Line(code, core.to_paisa(d or 0), core.to_paisa(c or 0)))
                core.check_entry(lines, acc)
            except core.LedgerError as exc:
                raise Fail(str(exc)) from None
            post(req.date("day"), req.text("memo"), lines)
            return redirect("/")
        opts = [("", "")] + [(k, f"{k} {v.name}") for k, v in sorted(acc.items())]
        fields = [("day", "Date", "date", today().isoformat()), ("memo", "What happened")]
        for i in range(6):
            fields += [(f"account{i}", f"Line {i + 1}: account", "select", opts), (f"debit{i}", "Debit", "text"), (f"credit{i}", "Credit", "text")]
        return a.page("New entry", card("Debits must equal credits", form(a, "/entry", fields, "Post")))

    @a.route("/reverse/<id>", ("POST",))
    def reverse(req, id):
        e = next((x for x in entries() if x.id == int(id)), None) if id.isdigit() else None
        if e is None:
            raise Fail("No such entry", 404)
        r = core.reversal(e, 0, today().isoformat())
        post(r.day, r.memo, r.lines, e.id)
        return redirect("/")

    @a.route("/trial")
    def trial(req):
        rows, d, c = core.trial_balance(entries(), accounts())
        body = table(rows, [("Code", lambda r: r[0]), ("Account", lambda r: r[1]), ("Debit", lambda r: money(r[2]) if r[2] else ""), ("Credit", lambda r: money(r[3]) if r[3] else "")], "No entries yet.")
        return a.page("Trial balance", card("Trial balance", body + f"<p><b>Total {money(d)} / {money(c)}</b></p>"))

    @a.route("/statements")
    def statements(req):
        y = today().year
        start, end = req.get("start") or f"{y}-01-01", req.get("end") or today().isoformat()
        s = core.income_statement(entries(), accounts(), start, end)
        b = core.balance_sheet(entries(), accounts(), end)
        rows = lambda items: table(items, [("Account", lambda r: r[0].name), ("Amount", lambda r: money(r[1]))], "None.")
        check = '<p class="good">Assets equal claims.</p>' if b["balanced"] else '<p class="bad">The balance sheet does not balance.</p>'
        return a.page("Statements", card(f"Income and expenditure, {h(start)} to {h(end)}", "<h3>Income</h3>" + rows(s["income"]) + "<h3>Expenditure</h3>" + rows(s["expenses"]) + f"<p><b>Surplus {money(s['surplus'])}</b></p>") + card(f"Balance sheet at {h(end)}", "<h3>Assets</h3>" + rows(b["assets"]) + f"<p><b>Total assets {money(b['total_assets'])}</b></p><h3>Liabilities</h3>" + rows(b["liabilities"]) + "<h3>Funds</h3>" + rows(b["equity"]) + f"<p>Surplus so far {money(b['surplus'])}</p><p><b>Total {money(b['total_claims'])}</b></p>" + check))

    return a
