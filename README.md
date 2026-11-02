# LedgerBook

Proper double-entry accounting for a small organisation, school or shop, offline and in one file.

```
python -m ledgerbook
```

Then open http://127.0.0.1:8043. A starter chart of accounts is included. It needs Python 3.10 or newer.

## What it does

- **Journal entries** where debits must equal credits, or nothing is saved
- **Ledgers** with running balances, and a **trial balance**
- **Income statement and balance sheet** for any dates, with a check that the books balance
- **Bank reconciliation logic** in `core.py`, matching statement lines to the cash book by amount and nearest date

## Built to be trusted

- **Exact money.** Amounts are whole paisa, never floats, so 0.10 + 0.20 is exactly 0.30. An amount with too many decimals is refused, not rounded.
- **Nothing is edited.** Database triggers refuse any change to a posted entry, even from outside the app. A mistake is corrected by a reversing entry, so the history stays honest.
- **An audit log** records each posting.

## How it is tested

A random test posts 500 entries and checks after each one that assets equal liabilities plus funds and surplus. Tests confirm that a direct SQL edit of a posted record fails, that a mistake can be reversed only once, and that an unbalanced entry saves nothing. Bank matching is tested by hand, and a worked reconciliation must end at zero.

## Limits

It is not certified for statutory reporting, and it knows nothing of tax or VAT. Use a qualified accountant for audited accounts. The screens cover posting and reports; bank matching has no screen yet. It handles one currency and one organisation, with no user logins. Keep a copy of the file, because it is the only copy.

## Tests

```
python -m unittest discover -s tests
```

MIT licence.
