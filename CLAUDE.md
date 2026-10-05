# CLAUDE.md

Guidance for Claude Code (and any other agent) working in this repository.
Read this file fully before making changes. `docs/PROJECT.md` holds the vision,
scope and milestones; this file holds the rules.

## What this project does

**pbi-report-validator** compares two versions of a Power BI report — "old" vs
"new" — and tells you exactly what changed and whether the numbers still match.

For every page and visual it reports:

- **Structure** – visuals added, removed, moved or retyped; fields, measures and
  columns used.
- **Filter context** – report-, page- and visual-level filters, and the current
  state of every slicer.
- **Data** – the result of each visual, re-run as a DAX query against both
  semantic models and compared with tolerances.
- **Explanation** – an optional AI-written summary that links a data difference
  to its likely cause ("the new version lacks the Region = EU filter").

Results are produced as JSON (for machines/CI), Markdown (for PR comments) and a
self-contained HTML report with page wireframes coloured by status.

## The problem it solves

Migrating or refactoring Power BI reports (new semantic model, new data source,
redesign) is validated by hand today: people open two reports side by side,
click through every slicer and compare numbers by eye. It is slow, error-prone
and has to be repeated after every change. Existing tools cover parts of this
(ALM Toolkit and Tabular Editor diff semantic models, PBI Inspector lints report
definitions) but none compares **visual-level output under its filter context**
between two report versions. This tool automates that and fits into a git/PR
workflow.

## Tech stack (and why)

| Area | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | Strong data tooling; the Power BI/Fabric ecosystem (semantic-link, notebooks) is Python-first |
| Packaging | `uv` + `pyproject.toml` (hatchling) | Fast, reproducible; installable with `pipx`/`uvx` |
| CLI | Typer | Typed, minimal boilerplate, good help output |
| Domain models | Pydantic v2 | Validated, serialisable models of reports, visuals and diffs |
| Data comparison | pandas | Tabular diffs with tolerances; familiar to BI people |
| HTML report | Jinja2, single self-contained file (inline CSS/JS) | No server needed; works as CI artifact and on GitHub Pages |
| Power BI access | `httpx` + `msal` (REST `executeQueries`) | Works from CI with a service principal; no Windows-only drivers |
| AI layer (optional) | `anthropic` SDK | Matching renamed objects and explaining diffs; tool must work without it |
| Quality | pytest, ruff (lint + format), mypy (strict) | Fast feedback for both humans and agents |
| Distribution | PyPI-style package, Docker image (GHCR), GitHub Action, GitHub Pages demo | "Something someone else can run" in every common form |

## Architecture

Layered, dependencies point **inwards only** (outer layers may import inner
ones, never the reverse):

```
cli/            Typer commands. Parses args, calls services, prints. No logic.
  │
services/       Orchestration: "validate old vs new" = parse → match → diff → query → report
  │
├─ parsers/     PBIP/PBIR files  → domain models   (reads files via io/ only)
├─ matching/    Pair old visuals/fields with new ones (deterministic first, AI fallback)
├─ diff/        Pure functions: domain models → Diff models
├─ dax/         Pure functions: visual + filter context → DAX query string
├─ reporting/   Diff models → JSON / Markdown / HTML
  │
domain/         Pydantic models only. No I/O, no imports from other layers.
  │
io/             ALL side effects: filesystem, Power BI REST, Anthropic API, env/config
```

Source lives in `src/pbi_report_validator/`, tests in `tests/` mirroring that
structure, test fixtures (sample reports) in `tests/fixtures/`.

### Principles

1. **All I/O happens in `io/`.** Parsers receive file contents or a filesystem
   abstraction; diff, dax and reporting are pure functions.
2. **Deterministic core, AI at the edges.** Parsing, diffing, querying and
   comparing must work and be testable with the AI layer switched off. AI only
   adds matching suggestions and explanations, and its output is always labelled
   as AI-generated.
3. **Functions do one thing.** Prefer small pure functions over classes with
   state. No global mutable state; configuration is passed in explicitly.
4. **Typed everywhere.** Full type hints, `mypy --strict` passes. Domain data is
   Pydantic models, never loose dicts past the parser boundary.
5. **Fail loudly, report gracefully.** Unknown PBIR structures raise a typed
   error inside the parser; the service layer records it as a finding
   ("visual X could not be parsed") instead of crashing the whole run.
6. **Stable output.** JSON output has a versioned schema (`schema_version`);
   ordering is deterministic so diffs of outputs are reviewable.
7. **Test with fixtures.** Every diff category has an old/new fixture pair that
   demonstrates it. New behaviour = new fixture + test.

## Domain notes (Power BI formats)

- Primary input is **PBIP with the PBIR report format**:
  - `<Name>.Report/definition/report.json` – report-level settings and filters
  - `<Name>.Report/definition/pages/pages.json` – page order
  - `<Name>.Report/definition/pages/<page>/page.json` – page settings and filters
  - `<Name>.Report/definition/pages/<page>/visuals/<visual>/visual.json` – visual
    type, position, query fields, visual filters, slicer state
  - `<Name>.SemanticModel/definition/**/*.tmdl` – tables, columns, measures
- Legacy single-file `report.json` (PBIR-Legacy, also inside `.pbix` as
  `Report/Layout`) stores config and filters as JSON-encoded **strings**; support
  is a later milestone and must go through its own parser module.
- `.pbix` binaries are **not** parsed directly in the MVP. Users convert with
  "Save as Power BI Project" in Power BI Desktop.

## Commands

```bash
uv sync                          # install deps incl. dev
uv run pytest                    # tests
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pbi-validate diff tests/fixtures/sales_v1 tests/fixtures/sales_v2 --html out/report.html
```

All four checks (pytest, ruff check, ruff format, mypy) must pass before a task
is considered done.

## Working agreement for agents

- Work from a GitHub issue. Branch name: `feat/<issue-number>-short-slug` or
  `fix/<issue-number>-short-slug`. PR description starts with `Closes #<n>`.
- Keep PRs small: one issue, one concern. If an issue turns out to be larger
  than ~300 changed lines, stop and propose a split in the issue instead.
- Update or add tests in the same PR. Update `README.md` when CLI behaviour
  changes.
- If something in this file or `docs/PROJECT.md` is unclear or seems wrong,
  ask (comment on the issue) rather than guessing.

## Things you must NOT do

- **Never commit real report data or client material.** Only the synthetic or
  public sample reports in `tests/fixtures/`. No real tenant IDs, workspace IDs,
  dataset names, customer names or query results from real environments.
- **Never commit secrets.** Credentials only via environment variables
  (`PBI_TENANT_ID`, `PBI_CLIENT_ID`, `PBI_CLIENT_SECRET`, `ANTHROPIC_API_KEY`).
  No `.env` files in git.
- **Never send row-level data to an LLM by default.** The AI layer receives
  metadata (field names, filter definitions, aggregated diff summaries). Sending
  values requires an explicit `--allow-data-to-llm` flag.
- **Don't add runtime dependencies without asking** (comment on the issue with
  the package and the reason). Dev dependencies for testing/linting are fine.
- **Don't change the stack**: no switching to another language, CLI framework,
  dataframe library or templating engine.
- **Don't put logic in `cli/`** or I/O outside `io/`.
- **Don't make the AI layer required.** Every command must work without
  `ANTHROPIC_API_KEY`.
- **Don't add Windows-only or Power BI Desktop-only dependencies** to the core
  (e.g. ADOMD.NET). Such integrations may only be optional extras.
- **Don't push to `main`**, force-push shared branches, or modify CI workflows
  and this file without it being the explicit subject of the issue.
- **Don't weaken checks** to make them pass (no blanket `# type: ignore`,
  `noqa`, skipped tests or lowered coverage thresholds without justification in
  the PR).
