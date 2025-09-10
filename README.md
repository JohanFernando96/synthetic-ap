# Synthetic Data Generation App

Synthetic Data Generation App generates realistic accounts payable invoices and can insert them
into a Xero sandbox for demos or testing.  The generator uses catalog data and
optionally an OpenAI model to plan invoice mixes and craft line item
descriptions.  Run artifacts and reports make it easy to audit the process or
build further analytics.

## Installation

1. **Install Python 3.11**.
2. **Install dependencies** using either Poetry or pip:

   ```bash
   # using Poetry (recommended)
   poetry install

   # or using pip
   pip install -e .
   ```

3. (Optional) install development dependencies with
   `poetry install --with dev`.

## Running the Streamlit frontend

Launch the user interface with:

```bash
poetry run streamlit run app.py
```

This opens a multi-page dashboard. The main page presents overview metrics and
connection statuses. A dedicated catalog page under `streamlit/` lists vendors,
items and vendor‑item assignments in tabbed tables. A configuration page exposes
form-based runtime settings with options to save or revert to defaults, while
other pages handle run browsing and data generation.


## Environment variables

Configuration values are read from environment variables or a `.env` file.  The
most important settings are shown below:

| Variable                                                                   | Purpose                                                   |
|----------------------------------------------------------------------------|-----------------------------------------------------------|
| `OPENAI_API_KEY`                                                           | API key for OpenAI when LLM features are enabled.         |
| `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_REDIRECT_URI`, `XERO_SCOPES` | OAuth details for Xero.                                   |
| `XERO_TENANT_ID`                                                           | Xero tenant identifier (resolved after auth if omitted).  |
| `XERO_PAYMENT_ACCOUNT_CODE`                                                | Account code used when posting payments (default `101`).  |
| `PAY_ON_DUE_DATE`                                                          | If `true`, date payments exactly on the invoice due date. |
| `TIMEZONE`, `DEFAULT_SEED`, `FISCAL_YEAR_START_MONTH`                      | Optional service settings.                                |
| `DATA_DIR`                                                                 | Base directory for catalogs and configuration files.      |
| `RUNS_DIR`                                                                 | Directory where run artifacts are written.                |
| `XERO_TOKEN_FILE`                                                          | Location of the OAuth token store.                        |

All variables can be placed in a `.env` file in the project root.  See
`src/synthap/config/settings.py` for the complete list of supported values.

## Configuration files

Runtime configuration lives under `data/config/` and is composed of two files:

* `service_defaults.yaml` – repository defaults
* `runtime_config.yaml` – local overrides applied at runtime

The files are deep‑merged with runtime values taking precedence.  The structure
supports the following sections:

```yaml
ai:
  enabled: true              # use the LLM for planning and descriptions
  model: gpt-4o-mini         # OpenAI model name
  temperature: 0.15
  top_p: 1.0
  max_output_tokens: 1200
  max_vendors: 6
  line_item_description_enabled: false
  line_item_description_prompt: "Write a short description for invoice line item '{item_name}'."

generator:
  allow_price_variation: false
  price_variation_pct: 0.10  # ±10% when variation enabled
  currency: AUD
  status: AUTHORISED
  business_days_only: true   # only choose business days for invoice dates

artifacts:
  include_meta_json: true    # also save xero_invoices_with_meta.json

force_no_tax: false

payments:
  pay_on_due_date: false     # pay exactly on due date if true
  allow_overdue: false       # if true and not paying on due date, allow payment after due
  pay_when_unspecified: false # allow random payments when no directive in prompt
```

Edit `data/config/runtime_config.yaml` to customise behaviour.

## Workflow

### 1. Authenticate with Xero

```bash
poetry run python -m synthap.cli auth-init
```

This launches a local server and prints an authorization URL.  After completing
the OAuth consent flow the resulting token is saved (default: `.xero_token.json`).
Verify the token and resolved tenant identifier with:

```bash
poetry run python -m synthap.cli xero-status
```

### 2. Generate invoices

```bash
poetry run python -m synthap.cli generate -q "Generate 6 bills for the Q1 2023 pay for only 2"
```
Where the prompt can include directives for the number of invoices, date ranges, vendors to use, and how many to pay.

Examples are as follows:
* "Generate 20 bills for yesterday"
* "Generate 10000 bills for the financial year 2023"
* "Generate 50 bills for 20-05-2025 for vendor ABC"
* "Generate 10 bills for last month and pay all"
* "Generate 15 bills for last week and pay only 5"

Useful options:

* `--seed` – make runs deterministic
* `--allow-price-variation/--no-price-variation` – override price variation
* `--price-variance-pct` – set the variation percentage (e.g. `0.05` for ±5 %)

Each invocation creates `runs/<run_id>/` containing:

* `invoices.parquet`, `invoice_lines.parquet`
* `plan.json` – LLM planning result
* `xero_invoices.json` – Xero invoice payloads
* `xero_invoices_with_meta.json` – payloads with extra metadata when enabled
* `to_pay.json` – invoice references selected for payment
* `generation_report.json` – summary report of the generation step

### 3. Insert and optionally pay invoices

```bash
poetry run python -m synthap.cli insert --run-id <run_id>

# limit the subset to insert
poetry run python -m synthap.cli insert --run-id <run_id> --reference REF123 --limit 5
```

The command posts staged invoices to Xero and issues payments for references in
`to_pay.json`.  Additional artifacts are written into the run directory:

* `invoice_report.json` – responses from the Invoices API with invoice IDs
* `payment_report.json` – responses from the Payments API
* `xero_log.json` – chronological request/response log
* `insertion_report.json` – counts of inserted invoices and payments

## Inspecting results

Run artifacts live under `runs/<run_id>/`.  They contain the generated invoice
data, the exact payloads sent to Xero, receipts for invoices and payments, and a
detailed log of API interactions.  Inspect the JSON or parquet files directly or
load them into analytics tools for further analysis.

## Testing

Execute the test suite with:

```bash
pytest -q
```

Running the tests ensures that configuration parsing, invoice generation and
Xero integration helpers work as expected.

