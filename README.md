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

