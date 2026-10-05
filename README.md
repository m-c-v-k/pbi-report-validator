# pbi-report-validator

> Compare two versions of a Power BI report and find out what changed — visuals,
> filters, slicers and the numbers themselves.

**Status:** early development. See the [roadmap](docs/PROJECT.md#milestones-6-weeks-part-time).

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

## Planned usage

```bash
# Save both reports as Power BI Projects (File → Save as → .pbip), then:
pbi-validate diff ./old/Sales.Report ./new/Sales.Report --html report.html
```

It will also be available as a Docker image and a GitHub Action that comments on
pull requests that change a report.

## Data handling

- Runs locally or in your own CI; nothing is sent anywhere by default.
- The optional AI layer only receives metadata (field names, filter
  definitions), never row-level data, unless you explicitly opt in.

## Development

Built with Python, uv, Typer and Pydantic. See [CLAUDE.md](CLAUDE.md) for
architecture and contribution rules, and [docs/PROJECT.md](docs/PROJECT.md) for
scope and milestones.

## License

MIT — see [LICENSE](LICENSE).

This is an independent project and is not affiliated with or endorsed by
Microsoft. Power BI is a trademark of Microsoft Corporation.
