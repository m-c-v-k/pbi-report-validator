## Power BI report diff

`tests/fixtures/sales_v1` → `tests/fixtures/sales_v2` · 7 findings

Severity: 3 critical, 2 warning, 2 info

| Category | Findings |
|---|---:|
| Pages | 1 |
| Visuals | 2 |
| Filters | 1 |
| Slicers | 1 |
| Measures | 2 |

### Pages

- info · **added** `trends`: Page 'Trends' added with 1 visual (_(none)_ → `Trends`)

### Visuals

- info · **moved** `details/chart_sales_by_region`: clusteredBarChart 'Sales by region' (chart\_sales\_by\_region) moved (`x=840, y=40, width=400, height=320` → `x=840, y=360, width=400, height=320`)
- warning · **retyped** `overview/chart_sales_by_month`: clusteredColumnChart 'Sales by month' (chart\_sales\_by\_month) changed type to lineChart (`clusteredColumnChart` → `lineChart`)

### Filters

- critical · **removed** `details/table_product_sales/filters/visual_filter_category`: Filter visual\_filter\_category removed (`Product[Category] in ('Bikes', 'Clothing')` → _(none)_)

### Slicers

- critical · **modified** `overview/slicer_year`: Slicer selection changed (`Date[Year] in (2025)` → `Date[Year] in (2024)`)

### Measures

- warning · **renamed** `model/Sales/Margin %`: Measure Sales\[Margin %\] renamed to Sales\[Gross Margin %\] (`Margin %` → `Gross Margin %`)
- critical · **modified** `model/Sales/Total Sales`: Expression of measure Sales\[Total Sales\] changed (`SUM(Sales[Amount])` → `CALCULATE(SUM(Sales[Amount]), Sales[Amount] > 0)`)
