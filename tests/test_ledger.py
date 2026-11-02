import random
import sqlite3
import unittest
from datetime import date

from ledgerbook import core, create_app
from ledgerbook.core import Account, Entry, LedgerError, Line, balance_sheet, check_entry, income_statement, ledger, money, reconcile, reconciled_balance, reversal, to_paisa, trial_balance

ACC = {c: Account(c, n, k) for c, n, k in core.STARTER}


def e(i, day, *lines):
    return Entry(i, day, "x", [Line(c, d, cr) for c, d, cr in lines])


class TestMoney(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(to_paisa("0.10") + to_paisa("0.20"), to_paisa("0.30"))
        self.assertEqual(to_paisa("1,234.50"), 123450)

    def test_refuses_what_it_cannot_hold(self):
        for bad in ("1.005", "abc", "NaN", "Infinity"):
            with self.assertRaises(LedgerError):
                to_paisa(bad)

    def test_format(self):
        self.assertEqual(money(123456), "1,234.56")
        self.assertEqual(money(-5), "-0.05")
        self.assertEqual(money(0), "0.00")

    def test_many_small_amounts_add_up_exactly(self):
        self.assertEqual(sum(to_paisa("0.10") for _ in range(10000)), 100000)


class TestEntries(unittest.TestCase):
    def test_balanced(self):
        check_entry([Line("1000", 100, 0), Line("4100", 0, 100)], ACC)

    def test_refused(self):
        for lines in ([Line("1000", 100, 0)], [Line("1000", 100, 0), Line("4100", 0, 99)], [Line("zz", 1, 0), Line("4100", 0, 1)], [Line("1000", 1, 1), Line("4100", 0, 0)], [Line("1000", -1, 0), Line("4100", 0, -1)]):
            with self.assertRaises(LedgerError):
                check_entry(lines, ACC)

    def test_reversal_undoes_an_entry(self):
        a = e(1, "2026-01-01", ("1000", 500, 0), ("4100", 0, 500))
        r = reversal(a, 2, "2026-01-02")
        self.assertEqual(core.balances([a, r], ACC)["1000"], 0)
        self.assertEqual(r.reverses, 1)


class TestStatements(unittest.TestCase):
    def books(self):
        return [e(1, "2026-01-05", ("1010", 500000, 0), ("3000", 0, 500000)), e(2, "2026-02-01", ("1010", 200000, 0), ("4000", 0, 200000)), e(3, "2026-02-10", ("5100", 30000, 0), ("1010", 0, 30000)), e(4, "2026-03-01", ("5200", 50000, 0), ("2000", 0, 50000))]

    def test_trial_balance_balances(self):
        rows, d, c = trial_balance(self.books(), ACC)
        self.assertEqual(d, c)
        self.assertEqual(d, 750000)       # 670,000 bank + 30,000 rent + 50,000 supplies

    def test_income_statement(self):
        s = income_statement(self.books(), ACC, "2026-01-01", "2026-12-31")
        self.assertEqual((s["total_income"], s["total_expenses"], s["surplus"]), (200000, 80000, 120000))

    def test_date_ranges(self):
        self.assertEqual(income_statement(self.books(), ACC, "2026-03-01", "2026-03-31")["total_income"], 0)

    def test_balance_sheet_balances(self):
        b = balance_sheet(self.books(), ACC, "2026-12-31")
        self.assertTrue(b["balanced"])
        self.assertEqual(b["total_assets"], 670000)

    def test_the_accounting_equation_holds_for_any_valid_books(self):
        rng = random.Random(1)
        codes = list(ACC)
        entries = []
        for i in range(500):
            a, b = rng.sample(codes, 2)
            n = rng.randint(1, 10 ** 7)
            entries.append(e(i, f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}", (a, n, 0), (b, 0, n)))
            self.assertTrue(balance_sheet(entries, ACC, "2026-12-31")["balanced"])
        _, d, c = trial_balance(entries, ACC)
        self.assertEqual(d, c)

    def test_ledger_runs(self):
        rows = ledger(self.books(), "1010")
        self.assertEqual([r[5] for r in rows], [500000, 700000, 670000])


class TestBank(unittest.TestCase):
    def test_reconcile(self):
        book = [("2026-01-01", 100, "a"), ("2026-01-05", -50, "b"), ("2026-01-09", -30, "cheque not cashed")]
        bank = [("2026-01-02", 100, "dep"), ("2026-01-06", -50, "wd"), ("2026-01-31", -5, "bank fee")]
        m, bo, ba = reconcile(book, bank)
        self.assertEqual(m, [(0, 0), (1, 1)])
        self.assertEqual((bo, ba), ([2], [2]))
        book_bal, bank_bal = 20, 45
        self.assertEqual(reconciled_balance(book_bal, bank_bal, book, bank, bo, ba)[2], 0)

    def test_nearest_date_wins_when_amounts_repeat(self):
        book = [("2026-01-01", 10, ""), ("2026-01-20", 10, "")]
        self.assertEqual(reconcile(book, [("2026-01-19", 10, "")])[0], [(1, 0)])

    def test_each_line_is_used_once(self):
        m, _, ba = reconcile([("2026-01-01", 10, "")], [("2026-01-01", 10, ""), ("2026-01-01", 10, "")])
        self.assertEqual((len(m), ba), (1, [1]))


class TestApp(unittest.TestCase):
    def setUp(self):
        self.a = create_app(":memory:", lambda: date(2026, 6, 1))

    def post(self, memo="Rent", day="2026-05-01", a0="5100", d0="1,000.50", a1="1010", c1="1,000.50", **kw):
        return self.a.post("/entry", day=day, memo=memo, account0=a0, debit0=d0, credit0="", account1=a1, debit1="", credit1=c1, **kw)

    def text(self, url):
        return self.a.get(url).body.decode()

    def test_flow(self):
        self.assertEqual(self.post().status, 303)
        self.assertIn("1,000.50", self.text("/trial"))
        self.assertIn("Assets equal claims", self.text("/statements"))
        self.assertIn("Rent", self.text("/ledger/5100"))

    def test_unbalanced_entry_saves_nothing(self):
        self.assertEqual(self.post(c1="999").status, 400)
        self.assertEqual(self.a.one("SELECT COUNT(*) FROM entries"), 0)

    def test_posted_records_cannot_be_changed_even_directly(self):
        self.post()
        for sql in ("UPDATE lines SET debit = 1", "DELETE FROM lines", "UPDATE entries SET memo = 'x'", "DELETE FROM entries"):
            with self.assertRaises(sqlite3.Error):
                self.a.run(sql)

    def test_correction_by_reversal(self):
        self.post()
        self.assertEqual(self.a.post("/reverse/1").status, 303)
        self.assertNotIn("1,000.50", self.text("/trial"))
        self.assertEqual(self.a.one("SELECT COUNT(*) FROM entries"), 2)

    def test_reversing_twice_is_refused(self):
        self.post()
        self.a.post("/reverse/1")
        self.assertEqual(self.a.post("/reverse/1").status, 409)

    def test_custom_account(self):
        self.a.post("/accounts", code="5500", name="Internet", kind="expense")
        self.assertIn("Internet", self.text("/accounts"))
        self.assertEqual(self.a.post("/accounts", code="5501", name="x", kind="magic").status, 400)

    def test_missing(self):
        self.assertEqual(self.a.get("/ledger/9999").status, 404)
        self.assertEqual(self.a.post("/reverse/9").status, 404)


if __name__ == "__main__":
    unittest.main()
