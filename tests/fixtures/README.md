# Test fixtures

Synthetic Power BI Projects (PBIP, PBIR report format + TMDL semantic model)
used by the tests and the demo. All names and values are made up; no real
report, tenant, workspace or customer data may be added here.

## `sales_v1/` – the "old" report

Semantic model `Sales.SemanticModel` (inline `#table` data, so no data source):

| Table | Columns | Measures |
|---|---|---|
| `Sales` | ProductKey, DateKey, Region, Amount, Cost | `Total Sales`, `Margin %` (multi-line) |
| `Product` | ProductKey, Product, Category | – |
| `Date` | DateKey, Year, Month | – |

Report `Sales.Report`:

- **Report filter** `report_filter_year`: `Date[Year]` in 2024, 2025
- **Page `overview`** (Overview), page filter `page_filter_category`:
  `Product[Category]` not in Accessories
  - `card_total_sales` – card, `Total Sales`
  - `card_margin` – card, `Margin %`
  - `slicer_year` – slicer on `Date[Year]`, selection 2025
  - `chart_sales_by_month` – clustered column chart, `Total Sales` by `Date[Month]`
- **Page `details`** (Details)
  - `table_product_sales` – table, Category, Product, `Total Sales`, `Margin %`;
    visual filter `visual_filter_category`: `Product[Category]` in Bikes, Clothing
  - `chart_sales_by_region` – clustered bar chart, `Total Sales` by `Sales[Region]`

Page and visual folder names are readable on purpose, so tests and
expected-change lists can refer to them directly.

## `sales_v2/` – the "new" report

A copy of `sales_v1` with seven deliberate changes, listed with old and new
values in [`EXPECTED_CHANGES.md`](EXPECTED_CHANGES.md). Keep that file in sync
whenever either fixture changes.

## `sales_v3/` – field and parse issue

A copy of `sales_v2` with two deliberate changes, so the `field` and
`parse_issue` categories also have a fixture pair (`sales_v2` → `sales_v3`):
`Sales[Region]` is added to `table_product_sales`, and
`overview/card_total_sales/visual.json` is invalid JSON on purpose. Details in
[`EXPECTED_CHANGES.md`](EXPECTED_CHANGES.md).
