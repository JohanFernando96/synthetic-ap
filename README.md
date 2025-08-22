# Synthetic AP

This project generates synthetic accounts payable invoices for testing and demos.

## AI line item descriptions

To have invoice lines use realistic descriptions rather than the raw catalog item
names, enable the feature in `data/config/runtime_config.yaml`:


```yaml
ai:
  line_item_description_enabled: true
  line_item_description_prompt: "Write a short description for invoice line item '{item_name}'."
```

Defaults live in `data/config/service_defaults.yaml` and can be overridden at
runtime. When enabled the generator will call OpenAI to craft a natural
description for each line item while keeping it consistent with the catalog's
item name.

## Invoice insertion and payment reports

Run `synthap generate` to stage invoices and `synthap insert` to post them to
Xero. After insertion the application writes several JSON reports to the run
directory (`runs/<run_id>`):

- `insertion_report.json` – summary counts of inserted invoices and payments
  made.
- `invoice_report.json` – raw invoice records returned by the Xero Invoices
  API, including the assigned `InvoiceID` values.
- `payment_report.json` – raw payment records returned by the Xero Payments
  API.

The generator can understand phrases like "pay for 4 bills" or "pay for all"
in the NLP query and will automatically create and submit corresponding payment
payloads. The Xero account used for payments is configured via the
`XERO_PAYMENT_ACCOUNT_CODE` setting.

