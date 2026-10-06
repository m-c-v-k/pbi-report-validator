# CLAUDE.md

Guidance for Claude Code and other agents working in this repository. Read it in
full before changing anything. Scope and milestones live in `docs/PROJECT.md`;
this file holds the rules.

## Project

CLI tool that compares two versions of a Power BI report (old vs new) and reports
what changed: visuals, fields, filters, slicer selections and — optionally — the
data each visual returns. Output is JSON for CI, Markdown for pull request
comments and a self-contained HTML report with page wireframes coloured by status.

**Problem it solves:** report migrations and refactors are validated by hand today
— two reports open side by side, clicking through every page and slicer and
comparing numbers by eye. That is slow, error-prone and repeated after every
change. Existing tools diff semantic models (ALM Toolkit, Tabular Editor) or lint
report definitions (PBI Inspector), but none compares visual-level output under
its filter context between two report versions. Built for BI developers,
testers and teams that keep Power BI reports in git.

## Tech stack

| Area | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Strong data tooling; the Power BI/Fabric ecosystem is Python-first |
| Packaging | uv + `pyproject.toml` (hatchling) | Fast, reproducible, installable with `pipx`/`uvx` |
| CLI | Typer | Typed commands with little boilerplate |
| Domain models | Pydantic v2 | Validated, serialisable models of reports and diffs |
| Data comparison | pandas | Tabular diffs with tolerances; familiar to BI people |
| HTML report | Jinja2, one self-contained file | No server needed; works as CI artifact and on GitHub Pages |
| Power BI access | httpx + msal (REST `executeQueries`) | Runs in CI with a service principal; no Windows-only drivers |
| AI layer (optional) | anthropic SDK | Match renamed objects, explain diffs; tool works without it |
| Tests / quality | pytest, ruff, mypy | Fast feedback for humans and agents |
| Distribution | Package, Docker image (GHCR), GitHub Action, GitHub Pages demo | Something anyone can run |

## Code conventions

- Format and lint with ruff (`ruff format` is Black-compatible; default settings
  plus the rules in `pyproject.toml`).
- Type hints on all functions; `mypy --strict` must pass. No bare `Any` past the
  parser boundary.
- Google-style docstrings on modules and public functions.
- Naming: `snake_case` for functions and variables, `PascalCase` for classes,
  `UPPER_SNAKE_CASE` for constants.
- Domain data is Pydantic models, never loose dicts outside `parsers/`.
- Logging via `logging.getLogger(__name__)`; logging is configured only in `cli/`.
  No `print()` outside `cli/`.

## Architecture

Layered; dependencies point inwards only (outer layers may import inner ones,
never the reverse).

```
cli/          Typer commands: parse args, call services, print. No logic.
services/     Orchestration: parse → match → diff → query → report.
parsers/      PBIP/PBIR + TMDL contents → domain models.
matching/     Pair old and new pages/visuals/fields (deterministic first, AI fallback).
diff/         Pure functions: domain models → diff models.
dax/          Pure functions: visual + filter context → DAX query string.
reporting/    Diff models → JSON / Markdown / HTML.
domain/       Pydantic models only. No I/O, no imports from other layers.
integrations/ ALL I/O: filesystem, Power BI REST API, Anthropic API, env config.
```

- All I/O lives in `integrations/`. Parsers, matching, diff, dax and reporting
  never touch the filesystem or network directly.
- Deterministic core, AI at the edges: everything must work and be tested with
  the AI layer switched off. AI output is always labelled as AI-generated.
- Functions do one thing. If a function needs a comment to explain what it does,
  split it.
- No global variables or global state. Pass configuration as arguments.
- All external calls have explicit error handling with typed exceptions. Never
  swallow exceptions. A visual that cannot be parsed or queried becomes a
  finding in the report, not a crash of the whole run.
- Output is deterministic (stable ordering) and the JSON has a `schema_version`.
- Tests are written alongside implementation, not after. Every diff category has
  an old/new fixture pair in `tests/fixtures/` that demonstrates it.

### Power BI formats (domain notes)

- Primary input is **PBIP with the PBIR report format**:
  - `<Name>.Report/definition/report.json`: report settings and filters
  - `<Name>.Report/definition/pages/pages.json`: page order
  - `<Name>.Report/definition/pages/<page>/page.json`: page settings and filters
  - `<Name>.Report/definition/pages/<page>/visuals/<visual>/visual.json`: type,
    position, query fields, visual filters, slicer state
  - `<Name>.SemanticModel/definition/**/*.tmdl`: tables, columns, measures
- The legacy single-file `report.json` (also `Report/Layout` inside `.pbix`)
  stores config and filters as JSON-encoded strings. Support is a later
  milestone and gets its own parser module.
- `.pbix` binaries are not parsed. Users convert with "Save as Power BI Project".

## Rules

- **Never commit real report data or client material.** Only the synthetic or
  public sample reports in `tests/fixtures/`. No real tenant/workspace IDs,
  dataset names, customer names or query results.
- **Never commit secrets.** Configuration is done via environment variables only.
  Do not create config files beyond `.env.example`.
- **Never send row-level data to an LLM by default.** The AI layer gets metadata
  only (field names, filter definitions, aggregated diff summaries). Sending
  values requires the explicit `--allow-data-to-llm` flag.
- Do not add or swap dependencies without asking (comment on the issue with the
  package and the reason). Dev-only test/lint tools are fine.
- Do not change the stack: no other language, CLI framework, dataframe library
  or templating engine.
- Do not change the CLI interface (command names, flags, JSON schema) once
  released without a dedicated issue — it affects existing users and CI setups.
- Do not make the AI layer required. Every command must work without
  `ANTHROPIC_API_KEY`.
- Do not add Windows-only or Power BI Desktop-only dependencies (e.g. ADOMD.NET)
  to the core; such integrations may only be optional extras.
- Never commit directly to `main` or `develop`. Create feature branches from
  `develop` (`feat/<issue>-slug`, `fix/<issue>-slug`) and open PRs against
  `develop`; one issue per PR, PR description starts with `Closes #<issue>`.
  Keep PRs under ~300 changed source lines (`src/` plus build and CI config
  such as `pyproject.toml`, `Dockerfile`, `action.yml` and workflows; tests,
  fixtures, snapshots and docs do not count) and state the source line count
  in the PR description; propose a split if an issue grows beyond that.
- `main` holds released versions only. It changes solely through a release PR
  from `develop` to `main`, followed by a version tag. Do not open PRs against
  `main` unless the issue is a release. After tagging, open a PR from `main`
  to `develop` and merge it once CI is green, so `develop` contains the
  release merge commit and the next release PR is not behind `main`.
- Do not modify CI workflows or this file unless that is the subject of the issue.
- Do not weaken checks to make them pass (no blanket `# type: ignore`, `noqa`,
  skipped tests or lowered thresholds without justification in the PR).
- If this file or `docs/PROJECT.md` is unclear or seems wrong, ask in the issue
  instead of guessing.

## Project structure

```
/
├── CLAUDE.md
├── README.md
├── LICENSE
├── pyproject.toml
├── .env.example
├── docs/
│   └── PROJECT.md                  # Vision, scope, milestones (input for planning)
├── src/pbi_report_validator/
│   ├── cli/main.py                 # Entry point, Typer commands (`pbi-validate`)
│   ├── services/validate.py        # Orchestrates a full validation run
│   ├── domain/models.py            # Report, Page, Visual, Filter, Slicer, Diff models
│   ├── parsers/pbir.py             # PBIR report definition → domain
│   ├── parsers/tmdl.py             # Semantic model (TMDL) → domain
│   ├── matching/matcher.py         # Old ↔ new pairing
│   ├── diff/structural.py          # Structural and filter diffs
│   ├── diff/data.py                # Result-set comparison with tolerances
│   ├── dax/builder.py              # Visual → DAX query
│   ├── reporting/                  # json_out.py, markdown.py, html.py, templates/
│   └── integrations/               # files.py, powerbi.py, anthropic_client.py, config.py
├── tests/
│   ├── fixtures/                   # sales_v1/, sales_v2/ sample PBIP reports
│   └── ...                         # mirrors src/ structure
├── Dockerfile
├── action.yml                      # GitHub Action
└── .github/workflows/              # CI, Pages demo, Claude agent workflows
```

## Setup

```bash
uv sync                      # installs runtime + dev dependencies
cp .env.example .env         # only needed for data validation / AI layer
# Set PBI_TENANT_ID, PBI_CLIENT_ID, PBI_CLIENT_SECRET and optionally ANTHROPIC_API_KEY
```

## Run

```bash
# Structural diff (no credentials needed)
uv run pbi-validate diff tests/fixtures/sales_v1 tests/fixtures/sales_v2 --html out/report.html

# Including data validation against published semantic models
uv run pbi-validate diff old/ new/ --data --old-dataset <id> --new-dataset <id>
```

## Test

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

All four must pass before a task is done.
