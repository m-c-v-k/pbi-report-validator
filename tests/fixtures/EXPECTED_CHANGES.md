# Expected changes: `sales_v1` → `sales_v2`

`sales_v2` is `sales_v1` with exactly the changes below and nothing else.
The diff engine must report every one of them, and tests assert against
this list. Paths are relative to `Sales.Report/definition/` or
`Sales.SemanticModel/definition/`.

| # | Category | Object | Old (`sales_v1`) | New (`sales_v2`) | File(s) |
|---|---|---|---|---|---|
| 1 | Visual filter removed | `details` / `table_product_sales`, filter `visual_filter_category` | `Product[Category]` in Bikes, Clothing | *(none)* | `pages/details/visuals/table_product_sales/visual.json` |
| 2 | Slicer selection changed | `overview` / `slicer_year` | `Date[Year]` = 2025 | `Date[Year]` = 2024 | `pages/overview/visuals/slicer_year/visual.json` |
| 3 | Measure renamed | `Sales[Margin %]` | `Margin %` | `Gross Margin %` (same expression) | `tables/Sales.tmdl`; references in `card_margin`, `table_product_sales` |
| 4 | Visual moved | `details` / `chart_sales_by_region` | x 840, y 40 | x 840, y 360 | `pages/details/visuals/chart_sales_by_region/visual.json` |
| 5 | Visual type changed | `overview` / `chart_sales_by_month` | `clusteredColumnChart` | `lineChart` | `pages/overview/visuals/chart_sales_by_month/visual.json` |
| 6 | Page added | `trends` (Trends) with `chart_margin_by_month` (line chart, `Gross Margin %` by `Date[Month]`) | *(none)* | added, last in page order | `pages/pages.json`, `pages/trends/**` |
| 7 | Measure expression changed | `Sales[Total Sales]` | `SUM(Sales[Amount])` | `CALCULATE(SUM(Sales[Amount]), Sales[Amount] > 0)` | `tables/Sales.tmdl` |

Notes for the diff engine:

- #3 must be reported once as a rename. The changed field references in
  `card_margin` and `table_product_sales` follow from the rename and must not
  appear as unrelated field removals and additions.
- #6: the new page's visual is reported as part of the added page.
- Unchanged on purpose: report filter, page filter, `card_total_sales`, size
  of `chart_sales_by_region`, all titles.
