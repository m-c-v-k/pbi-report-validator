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
4. In a repository with many reports: `pbi-validate diff --base <ref>` finds
   every report and semantic model changed since a git ref and validates each,
   with one combined result.
5. Migrations from `.pbix`/`.pbit` to PBIP, or between file formats: compare
   any supported input with any other.
6. Semantic model changes without a report: compare two models on their own,
   structurally and, with credentials, by the numbers each measure returns.

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

### Next phase (M6–M10)

- Input formats:
  - Legacy report format (`report.json` with stringified config and filters),
    in PBIP projects saved without PBIR and as `Report/Layout` in `.pbit` and
    `.pbix`.
  - `.pbit`: report part plus the model schema (`DataModelSchema`, TMSL
    without data).
  - `.pbix`: report part read locally. The model comes from, in this order:
    an explicit model path (TMDL folder, `model.bim` or `.pbit`), the
    published model of a thin report (Fabric `getDefinition`), or, only with
    an explicit opt-in flag and optional extra, model metadata read from
    `DataModel`. Otherwise the model is reported as unavailable.
  - Published reports and models fetched read-only through the Fabric API.
  - Any supported input can be compared with any other.
- Semantic model validation: model-only diff, relationships, calculation
  groups, roles, hierarchies, column properties and Power Query expressions;
  model-level data checks of every measure.
- CI: git-aware discovery of changed reports and models, multiple projects per
  run with one combined comment, SARIF and JUnit output, Azure DevOps pipeline
  template, accepted (baselined) findings, link to the HTML report in the PR
  comment.
- CLI: `inspect` (dump the parsed model), `doctor` (check credentials and
  access), output filters, opening the HTML report, progress for data runs.

### Known limitations

- `.pbix` models last saved before the enhanced metadata format (Power BI
  Desktop, ~2020) are not read. The run reports this as a finding that asks
  the user to open and save the file in a current Power BI Desktop, or to
  export a `.pbit`; the report part is still compared.

### Could have

- Simple web UI (upload two zipped PBIPs → report).

### Out of scope

- Data values in `.pbix` files: `DataModel` is read only with the explicit
  opt-in, and only for model metadata. Data values are never parsed, stored or
  output.
- Uploading, converting or creating items in a workspace to read a file (no
  service round-trip to convert `.pbix`).
- Editing or auto-fixing reports, including rebinding a report to another
  semantic model. The validator only reads; a separate companion project may
  use its JSON output to propose and apply changes.
- Pixel/screenshot comparison.
- Supporting Power BI Report Server or paginated reports.

## Milestones

M0–M5 (≈6 weeks, part-time) are done and released as v0.1.0–v0.6.0, and M6
as v0.7.0.
M7–M10 follow in the order listed.

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
- Source locations (file and JSON pointer) on findings.
- Docs: quick start, CI guide, security/data-handling page, architecture.
- Release v1.0.0, demo GIF, CV-ready README. (v1.0.0 moved to M10.)

### M6 – Legacy report format and PBIT (v0.7.0)
- Parser for the legacy report format (`report.json` / `Report/Layout` with
  stringified config and filters) into the same domain models as PBIR.
- Input detection with clear errors: PBIP with PBIR, PBIP with the legacy
  format, `.pbit`, `.pbix`, or unsupported.
- `.pbit` reader: zip archive read safely in `integrations/` (allowlist of
  entries, size limits, no escaping paths), `Report/Layout` and
  `DataModelSchema` through the existing TMSL parser.
- Fixtures: a legacy-format copy of the sales fixtures and `.pbit` archives
  built from synthetic content.
- Docs: supported inputs and their limitations.

### M7 – CI-native (v0.8.0)
- Git-aware runs: `--base <ref>` finds changed reports and models between two
  refs and validates each; the Action defaults to the pull request base.
- Multiple projects per run with one combined result, PR comment and job
  summary.
- SARIF output for code scanning annotations on the changed definition files;
  JUnit output for Azure DevOps test results.
- Azure DevOps pipeline template.
- Stable finding keys and accepted (baselined) findings, so `--fail-on` only
  fails on new findings.
- Link to the HTML report artifact in the PR comment.

### M8 – PBIX and published sources (v0.9.0)
- `.pbix` report part: `Report/Layout` or the PBIR folder inside the archive.
- `--old-model` / `--new-model`: compare a report against an explicit model
  (TMDL folder, `model.bim` or `.pbit`).
- Thin reports: resolve the published model from `Connections` and fetch it
  read-only through Fabric `getDefinition`.
- Fetch published reports and models into a local PBIP folder (Fabric API).
- Spike, then opt-in `--read-pbix-model` (optional extra): model metadata from
  `DataModel`, no data values; pre-2020 metadata format becomes a finding with
  the documented limitation.

### M9 – Semantic model validation (v0.10.0)
- Model-only diff: two `.SemanticModel` folders, `model.bim` files or `.pbit`
  files without comparing a report.
- Richer model domain and diff: relationships, calculation groups, roles
  (RLS), hierarchies, column properties (data type, format string, sort by,
  hidden), Power Query / partition expressions.
- Model-level data checks: every measure in total and by chosen dimensions,
  run against old and new model with `executeQueries`.

### M10 – CLI ergonomics and v1.0.0
- `inspect <path>`: print the parsed model of one input.
- `doctor`: check credentials, workspace access and API scopes before a data
  run.
- Output filters by page and category, `--open` for the HTML report, progress
  for data runs.
- Docs review and release v1.0.0.

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
