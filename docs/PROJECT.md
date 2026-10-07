# Project: pbi-report-validator

This document is the source the planning agent uses to create GitHub issues.
Keep it current: when scope changes, change it here first.

## Vision

Anyone who changes a Power BI report can, with one command or one pull request,
get a trustworthy answer to: *"Does the new version show the same thing as the
old one — and if not, where and why?"*

## Users

- **BI developers** refactoring or migrating reports (new semantic model, new
  data source, redesign).
- **Testers / validators** who today compare reports by hand.
- **Teams using git for Power BI** (PBIP + Fabric Git integration) who want a
  check on every pull request.

## Core use cases

1. `pbi-validate diff old/ new/` locally → terminal summary + HTML report.
2. Same command in CI (GitHub Action / Azure DevOps) on every PR that touches a
   report → PR comment with summary, HTML report as build artifact, optional
   failing check on critical findings.
3. With credentials configured: data validation of each visual against the
   published semantic models (e.g. dev vs prod workspace).

## Scope

### MVP (must have)

- Parse PBIP/PBIR reports into a normalised model: pages, visuals (type,
  position, title), fields/measures per visual, filters at report/page/visual
  level, slicer selections.
- Parse the semantic model (TMDL) for tables, columns and measures (name +
  expression).
- Match old ↔ new pages and visuals (by ID, then title/type/position/field
  similarity).
- Structural diff: added/removed/moved/retyped visuals, changed fields, changed
  filters and slicer state, changed measure expressions.
- Output: JSON (versioned schema), Markdown summary, self-contained HTML report
  with page wireframes coloured by status and drill-down per visual.
- Packaged CLI, Docker image, GitHub Action, demo report on GitHub Pages.

### Should have

- Data validation: generate a DAX query per visual including its full filter
  context, run it via the Power BI REST `executeQueries` API against old and new
  model, compare results with configurable tolerances.
- Severity levels (info / warning / critical) and `--fail-on` for CI.
- Optional AI layer: suggest matches for renamed visuals/measures; write a
  plain-language explanation per finding (metadata only by default).

### Could have

- Legacy report format (`report.json` with stringified config / `.pbix` Layout).
- Simple web UI (upload two zipped PBIPs → report).
- Azure DevOps pipeline template.
- Attribute data differences to the report or the semantic model: run the new
  report's queries against the old model as well (read-only; reports are never
  rebound or changed).

### Out of scope

- Parsing `.pbix` binaries / the compressed data model directly.
- Editing or auto-fixing reports.
- Pixel/screenshot comparison.
- Supporting Power BI Report Server or paginated reports.

## Milestones (≈6 weeks, part-time)

### M0 – Foundation (week 1)
- Repo, `CLAUDE.md`, this document, README, license.
- Python package skeleton (`uv`, `src/` layout, Typer entry point `pbi-validate`).
- CI workflow: pytest, ruff, mypy, secret scan (gitleaks).
- Fixtures: a public sample report saved as PBIP (`sales_v1`) and a modified copy
  (`sales_v2`) with deliberate changes: removed visual filter, changed slicer
  selection, renamed measure, moved visual, changed visual type, added page.
- Claude Code GitHub Action set up for issue → PR and automated PR review.

### M1 – Structural diff (week 2)
- Domain models (Pydantic) for report, page, visual, field, filter, slicer,
  semantic model.
- PBIR parser + TMDL parser (tables, columns, measures).
- Deterministic matcher.
- Diff engine for all structural categories.
- CLI `diff` command: terminal summary + JSON output.

### M2 – Report & first release (week 3)
- Markdown summary renderer.
- HTML report: overview, per-page wireframe from visual positions, per-visual
  detail with field/filter/slicer diff.
- Release v0.1.0: package build, Docker image to GHCR, GitHub Pages demo
  generated from the fixtures in CI.

### M3 – Data validation (week 4)
- Visual → DAX query generator (SUMMARIZECOLUMNS + filters + slicer state) for
  common visual types (card, table/matrix, bar/column/line, slicer).
- `integrations` client for `executeQueries` with service principal auth (MSAL).
- Result comparison with tolerances; data findings in all outputs.
- Mocked API tests; manual test against a personal/trial workspace.

### M4 – CI integration & AI layer (week 5)
- GitHub Action (`action.yml`) wrapping the Docker image; PR comment; `--fail-on`.
- Optional AI matching suggestions and explanations, metadata only by default.

### M5 – Hardening & polish (week 6)
- Edge cases from real-world-shaped fixtures (field parameters, calculation
  groups, bookmarks noted as unsupported).
- Optional `--attribute` for data findings: report change, model change or both.
- Docs: quick start, CI guide, security/data-handling page, architecture.
- Release v1.0.0, demo GIF, CV-ready README.

## Definition of done (per issue)

- Acceptance criteria in the issue are met.
- Tests added/updated; `pytest`, `ruff`, `mypy` pass in CI.
- No real data or secrets added; CLAUDE.md rules respected.
- README/docs updated when user-facing behaviour changes.

## Success criteria for the project

- A stranger can install the CLI and run it on the demo fixtures in under five
  minutes using only the README.
- The GitHub Pages demo shows a complete validation report.
- The GitHub Action runs on this repo's own PRs against the fixtures.
- Every MVP diff category is detected on the fixture pair.
