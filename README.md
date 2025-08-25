# Synthetic AP

Synthetic AP generates realistic accounts payable invoices and optional payment
records that can be inserted into Xero for demos or testing.

## Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt  # or rely on the provided Poetry setup
   ```
2. **Environment variables** – create a `.env` file or export the following:
   - `XERO_CLIENT_ID`
   - `XERO_CLIENT_SECRET`
   - `XERO_REDIRECT_URI`
   - `XERO_SCOPES`
   - `XERO_PAYMENT_ACCOUNT_CODE` (defaults to `101`)
   - `PAY_ON_DUE_DATE` (optional, default `false`)

## Configuration

Configuration lives under `data/config/`:

- **service_defaults.yaml** – baseline values committed to the repo
- **runtime_config.yaml** – overrides applied on each run

Both files support these sections:

```yaml
ai:
  model: gpt-4o-mini
  line_item_description_enabled: true

generator:
  allow_price_variation: false
  price_variation_pct: 0.10
  business_days_only: true

payments:
  pay_on_due_date: false   # pay exactly on the due date
  allow_overdue: false     # if true and not paying on due date, pick a date after due
  pay_when_unspecified: false  # if true, randomly pay some invoices even when the query has no pay directive
```

## Workflow

1. **Generate invoices**
   ```bash
   poetry run python -m synthap.cli generate -q "Generate 6 bills for the Q1 2023 pay for only 2"
   ```
   Options:
   - `--seed` to make runs deterministic
   - `--allow-price-variation/--no-price-variation`
   - `--price-variance-pct` to override the percentage

   The command stages data under `runs/<run_id>/` including `to_pay.json` which
   lists which invoices should be paid after insertion.

2. **Insert into Xero and pay**
   ```bash
   poetry run python -m synthap.cli insert --run-id <run_id>
   ```
   By default all staged invoices are inserted; use `--reference` or `--limit`
   to filter. The command:
   - posts invoices to the Xero Invoices API
   - reloads `invoice_report.json` to capture `InvoiceID`s
   - builds payment payloads for invoices listed in `to_pay.json`
   - posts payments via the Xero Payments endpoint

3. **Inspect run artifacts** – each run directory contains:
   - `invoice_report.json` – Xero invoice responses with IDs
   - `payment_report.json` – Xero payment responses
   - `xero_log.json` – chronological request/response log
   - `insertion_report.json` – counts of invoices inserted and payments made

## Additional Commands

- `poetry run python -m synthap.cli auth-init` – start a local server to obtain
  OAuth tokens for Xero
- `poetry run python -m synthap.cli xero-status` – verify token and tenant ID

## Testing

Run the test suite with:
```bash
pytest -q
```

## Notes

Payment generation obeys NLP directives such as "pay for 4" or "pay for all".
By default, no payments are made unless the NLP query includes a directive
(`pay for 2`, `pay for all`, etc.). Set `payments.pay_when_unspecified: true`
to allow random payments when no directive is provided. Payment dates are
chosen within the invoice term unless `payments.allow_overdue` or
`payments.pay_on_due_date` is set.
