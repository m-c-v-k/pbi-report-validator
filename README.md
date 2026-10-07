# pbi-report-validator

[![CI](https://github.com/m-c-v-k/pbi-report-validator/actions/workflows/ci.yml/badge.svg)](https://github.com/m-c-v-k/pbi-report-validator/actions/workflows/ci.yml)
[![Demo](https://img.shields.io/badge/demo-live%20report-2457c5)](https://m-c-v-k.github.io/pbi-report-validator/)
[![Coverage](https://img.shields.io/endpoint?url=https://m-c-v-k.github.io/pbi-report-validator/coverage-badge.json)](https://m-c-v-k.github.io/pbi-report-validator/coverage/)

> Compare two versions of a Power BI report and find out what changed — visuals,
> filters, slicers and the numbers themselves.

**Status:** v0.1.0 – structural diff with JSON, Markdown and HTML reports. See the [live demo report](https://m-c-v-k.github.io/pbi-report-validator/) and the [roadmap](docs/PROJECT.md#milestones-6-weeks-part-time).

## Why

Validating a migrated or refactored Power BI report usually means opening the
old and new versions side by side and clicking through every page and slicer.
`pbi-report-validator` automates that:

- **Structure** – visuals added, removed, moved or changed; fields and measures used
- **Filter context** – report, page and visual filters, plus slicer selections
- **Data** – each visual re-run as a DAX query against both models and compared
- **Report** – JSON for CI, Markdown for pull requests, and an HTML report with
  page wireframes coloured by status
- **Explanations (optional)** – AI-written summaries of why numbers differ

## Install

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you).
Install the latest release as a command-line tool:

```bash
uv tool install git+https://github.com/m-c-v-k/pbi-report-validator@v0.1.0
```

Or run it once without installing:

```bash
uvx --from git+https://github.com/m-c-v-k/pbi-report-validator@v0.1.0 pbi-validate --help
```

Each [GitHub release](https://github.com/m-c-v-k/pbi-report-validator/releases)
also has the wheel attached, which `pip install` or `uv tool install` accept
directly.

### Docker

Each release is also published as an image on GitHub Container Registry.
Mount the folder that holds both reports at `/work`:

```bash
docker run --rm -v "$PWD:/work" ghcr.io/m-c-v-k/pbi-report-validator diff old new
```

To write `--json`, `--markdown` or `--html` files into the mounted folder on Linux,
add `--user "$(id -u):$(id -g)"` so the files are owned by you.

## Quick start

1. Save both report versions as Power BI Projects (*File → Save as → Power BI
   project (.pbip)*) in the **PBIR** report format. If your Power BI Desktop
   version does not use PBIR by default, enable it under *Options → Preview
   features* first.
2. Compare them:

```bash
pbi-validate diff ./old ./new --html report.html
```

Each argument is a PBIP project folder (containing one `<Name>.Report` folder)
or the `.Report` folder itself. The terminal always shows a summary; add any of:

| Option | Output |
|---|---|
| `--html PATH` | Self-contained HTML report: summary, page wireframes coloured by status, a drill-down per visual. Works offline. [Example](https://m-c-v-k.github.io/pbi-report-validator/report.html) |
| `--markdown PATH` | Summary for a pull request comment, kept under GitHub's size limit |
| `--json PATH` | Every finding with old and new values, plus every page and visual with its status, and counts per severity (`schema_version` 1.3) |

Running it on the sample reports in this repository gives:

```text
Compared tests/fixtures/sales_v1 -> tests/fixtures/sales_v2
7 findings (3 critical, 2 warning, 2 info):
  page         1
  visual       2
  filter       1
  slicer       1
  measure      2

  info     [moved] details/chart_sales_by_region: clusteredBarChart 'Sales by region' (chart_sales_by_region) moved
  critical [removed] details/table_product_sales/filters/visual_filter_category: Filter visual_filter_category removed
  warning  [renamed] model/Sales/Margin %: Measure Sales[Margin %] renamed to Sales[Gross Margin %]
  critical [modified] model/Sales/Total Sales: Expression of measure Sales[Total Sales] changed
  warning  [retyped] overview/chart_sales_by_month: clusteredColumnChart 'Sales by month' (chart_sales_by_month) changed type to lineChart
  critical [modified] overview/slicer_year: Slicer selection changed
  info     [added] trends: Page 'Trends' added with 1 visual
```

Exit codes: `0` when the comparison ran (whether or not there are
differences), `1` when a project cannot be loaded or an output file cannot be
written. No credentials or environment variables are needed.

### What it compares

- Pages: added, removed, renamed, reordered
- Visuals: added, removed, moved/resized, type changed, title changed
- Fields per visual, including role and aggregation
- Filters at report, page and visual level; slicer selections
- Measures in the semantic model (TMDL): added, removed, expression changed,
  renamed (detected by identical expression)
- Files that cannot be parsed are reported as findings instead of stopping
  the run

Every finding has a severity:

| Severity | Findings |
|---|---|
| `critical` | Data differences, removed pages and visuals, added/removed/changed filters and slicer selections, changed measure expressions |
| `warning` | Changed visual type, changed fields, renamed or removed measures, parse issues, visuals whose data could not be validated |
| `info` | Added pages, visuals and measures, moved or reordered pages and visuals, renamed pages, changed titles |

### Limitations

- Only the PBIR report format; the legacy `report.json` and `.pbix` files are
  not supported (save as `.pbip` with PBIR enabled)
- Data validation (`--data`) is new and not yet verified against a live
  workspace; see its own limitations below
- A visual moved to a different page shows as removed on one page and added
  on the other

### Data validation (optional, `--data`)

The structural diff tells you what changed in the report definition. With
`--data` the tool also checks whether the **numbers** are the same: each
visual is turned into a DAX query (with its report, page and visual filters
and the slicer selections on its page), run against the old and the new
**published** semantic model, and the results are compared row by row.

```bash
pbi-validate diff ./old ./new --data \
  --old-dataset <dataset id> --new-dataset <dataset id> --html report.html
```

- Numbers are equal when they differ by at most `--abs-tol` (default 0) or
  `--rel-tol` times the larger value (default 1e-9); text must match exactly.
- Findings show rows that exist in only one version and values that differ,
  with old, new and the difference. The HTML drill-down shows a per-visual
  summary; the JSON has a `data` summary per visual (schema 1.2).
- Visuals whose query cannot be built faithfully (custom visuals, hierarchy
  levels, filters on measures, ...) or fails are reported as
  "not validated" with the reason. Slicers are skipped: they only filter.

**Setup (one time).** Data validation signs in as a Microsoft Entra
service principal and uses the Power BI REST API `executeQueries` endpoint,
so it runs in CI without Windows-only drivers:

1. Register an app in Microsoft Entra ID and create a client secret.
2. In the Power BI admin portal, enable *Allow service principals to use
   Power BI APIs* and *Dataset Execute Queries REST API* (for the app or a
   security group that contains it).
3. Add the app to the workspace(s) that hold both semantic models, with at
   least Contributor rights (it needs read and build permission).
4. Provide the credentials as environment variables (`.env.example` lists
   them; never commit them):

   ```bash
   export PBI_TENANT_ID=...  PBI_CLIENT_ID=...  PBI_CLIENT_SECRET=...
   ```

The dataset id is the GUID in the semantic model's URL in the Power BI
service (`.../datasets/<id>/...`).

If sign-in fails or a dataset id is wrong, the run stops with exit code 1
and no output files are written; fix the setup and run it again.

Limitations: models with row-level security can't be queried by a service
principal; slicer interactions edited in Power BI and slicers synced from
other pages are not taken into account; the API allows about 120 queries a
minute (40 on Pro/PPU), and each visual needs two.

Coming next: a GitHub Action that comments on pull requests that change a
report.

## Data handling

- Runs locally or in your own CI; nothing is sent anywhere by default.
- With `--data`, queries go only to the Power BI API of your own tenant.
  Query results stay in memory and in the output files you ask for; they
  are never logged or sent anywhere else.
- The optional AI layer only receives metadata (field names, filter
  definitions), never row-level data, unless you explicitly opt in.

## Development

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you).

```bash
uv sync                        # install runtime and dev dependencies
uv run pbi-validate --version  # run the CLI
uv run pytest                  # tests
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

Every CI run shows the test results and a coverage table in its summary
and attaches the HTML coverage report. The coverage report of the latest
release is on the [demo site](https://m-c-v-k.github.io/pbi-report-validator/coverage/);
CI fails if coverage drops below 95%.

Built with Python, uv, Typer, Pydantic and Jinja2. See [CLAUDE.md](CLAUDE.md) for
architecture and contribution rules, and [docs/PROJECT.md](docs/PROJECT.md) for
scope and milestones.

## Branching

- `develop` is the default branch where work is integrated.
- Feature branches (`feat/<issue>-slug`, `fix/<issue>-slug`) start from
  `develop`, and pull requests target `develop`.
- `main` holds released versions only. It is updated by a release PR from
  `develop`, followed by a version tag.
- Both branches are protected: changes go through pull requests and need
  green CI.

## Working with Claude

Issues and pull requests can be handed to [Claude Code](https://github.com/anthropics/claude-code-action):

- Mention `@claude` in an issue or PR comment to have it implement or change
  something. It follows [CLAUDE.md](CLAUDE.md) (feature branch, one issue per PR).
- New non-draft PRs get one automated review.

Only the repository owner can trigger these runs. They authenticate with the
owner's Claude subscription (`CLAUDE_CODE_OAUTH_TOKEN`), not an API key, so
they cost nothing extra.

## License

MIT — see [LICENSE](LICENSE).

This is an independent project and is not affiliated with or endorsed by
Microsoft. Power BI is a trademark of Microsoft Corporation.
