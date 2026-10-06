# pbi-report-validator

[![CI](https://github.com/m-c-v-k/pbi-report-validator/actions/workflows/ci.yml/badge.svg)](https://github.com/m-c-v-k/pbi-report-validator/actions/workflows/ci.yml)

> Compare two versions of a Power BI report and find out what changed — visuals,
> filters, slicers and the numbers themselves.

**Status:** early development. Structural diff works; see the [roadmap](docs/PROJECT.md#milestones-6-weeks-part-time) for what comes next.

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

## Quick start

Save both report versions as Power BI Projects (*File → Save as → Power BI
project (.pbip)*) with the PBIR report format enabled. Then, from a clone of
this repository (requires [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
uv run pbi-validate diff tests/fixtures/sales_v1 tests/fixtures/sales_v2 --json out/diff.json
```

```text
Compared tests/fixtures/sales_v1 -> tests/fixtures/sales_v2
7 findings:
  page         1
  visual       2
  filter       1
  slicer       1
  measure      2

  [moved] details/chart_sales_by_region: clusteredBarChart 'Sales by region' (chart_sales_by_region) moved
  [removed] details/table_product_sales/filters/visual_filter_category: Filter visual_filter_category removed
  [renamed] model/Sales/Margin %: Measure Sales[Margin %] renamed to Sales[Gross Margin %]
  ...
```

Each argument is a PBIP project folder (containing one `<Name>.Report` folder)
or the `.Report` folder itself. `--json` writes every finding with old and new
values; the JSON has a `schema_version`. The command exits with `1` if a
project cannot be loaded. No credentials or environment variables are needed.

Coming next: Markdown and HTML reports, data validation against published
semantic models, a Docker image and a GitHub Action that comments on pull
requests that change a report.

## Data handling

- Runs locally or in your own CI; nothing is sent anywhere by default.
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

Built with Python, uv, Typer and Pydantic. See [CLAUDE.md](CLAUDE.md) for
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
