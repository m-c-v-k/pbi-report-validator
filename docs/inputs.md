# Supported inputs

`pbi-validate diff OLD NEW` takes two inputs. This page lists every input it
accepts, what it reads from each, and what to do with inputs it cannot read
yet. It describes the behaviour in v0.7.0.

## At a glance

| Input | Supported | Report read from | Model read from |
|---|---|---|---|
| PBIP project, PBIR report format | Yes | `<Name>.Report/definition/` | `<Name>.SemanticModel/` (TMDL or `model.bim`) |
| PBIP project, legacy report format | Yes | `<Name>.Report/report.json` | `<Name>.SemanticModel/` (TMDL or `model.bim`) |
| Power BI template (`.pbit`) | Yes | `Report/Layout` in the archive | `DataModelSchema` in the archive |
| Power BI file (`.pbix`) | Not yet (planned for v0.9.0) | – | – |
| Semantic model on its own | Not yet (planned for v0.10.0) | – | – |

Any supported input can be compared with any other: a `.pbit` with a PBIP
project, or a legacy-format project with a PBIR one. The report format doesn't
change the findings. The same report saved in both formats gives the same
findings, only their source locations differ.

## Ways to point at a PBIP project

Each argument can be:

- the project folder that contains one `<Name>.Report` folder
- the `<Name>.Report` folder itself
- the project's `<Name>.pbip` file (its first report artifact is used; the
  path it lists must stay inside the project folder)
- a `.pbit` file

File extensions are matched without regard to case, so `Sales.PBIT` works too.

## PBIP project, PBIR report format

The format Power BI Desktop writes when *Store reports using enhanced metadata
format (PBIR)* is on. Read from the `<Name>.Report` folder:

- `definition/report.json`: report settings and report-level filters
- `definition/pages/pages.json`: page order
- `definition/pages/<page>/page.json`: page settings and page-level filters
- `definition/pages/<page>/visuals/<visual>/visual.json`: type, position,
  fields, visual-level filters and slicer selections
- `definition.pbir`: which semantic model the report uses

Source locations in the JSON and HTML reports name the file and a JSON
pointer to the exact object.

## PBIP project, legacy report format

The format Power BI Desktop writes when PBIR is off: one
`<Name>.Report/report.json` for the whole report, in which settings and
filters are stored as JSON-encoded strings. Pages, visuals, fields, filters
and slicer selections are all read from it.

Source locations point to the page, the visual, or the encoded `config` or
`filters` string in `report.json`. They can't point to a position inside an
encoded string.

## The semantic model of a PBIP project

The model is found through `definition.pbir`:

- `byPath`: the folder it points to, which must be inside the project folder;
  a path outside it is an error
- `byConnection` (a report connected to a published model): the
  `<Name>.SemanticModel` folder next to the report, if there is one
- no `definition.pbir`: the `<Name>.SemanticModel` folder next to the report

From the model folder, the `.tmdl` files under `definition/` are read, or
`model.bim` for a model saved without the TMDL format. Tables, columns and
measures are compared. When there is no model to read, the run still compares
the report and adds a warning that measures were not compared, and why.

## Power BI template (`.pbit`)

A `.pbit` is a zip archive. Only two entries are read, both UTF-16LE JSON:

- `Report/Layout`: the report, in the legacy report format (see above)
- `DataModelSchema`: the model schema (TMSL), with tables, columns and
  measures but no data

Every other entry is ignored. A template holds no data values, so none can be
read from it.

The archive is treated as untrusted input. It is read in memory and nothing
is unpacked to disk. It is refused with an error (exit code 1) when:

- it is not a valid zip archive, is truncated or is encrypted
- an entry name is absolute or climbs out of the archive with `..`
- `Report/Layout` or `DataModelSchema` appears more than once
- it holds more than 10,000 entries
- `Report/Layout` or `DataModelSchema` is larger than 256 MiB, or the two
  together are larger than 512 MiB once decompressed

A `.pbit` without `DataModelSchema` is still compared; the run adds a warning
that measures were not compared. A `.pbit` without `Report/Layout` is an
error. A template saved with the PBIR report format may store its report
differently, and isn't supported yet: save that report as a PBIP project
instead.

## Inputs that are not supported yet

`diff` names the input, says why it can't read it and exits with code 2.

| Input | What to do |
|---|---|
| `.pbix` | Open it in Power BI Desktop and save it as a PBIP project (*File → Save as → Power BI project (.pbip)*), or export a template (*File → Export → Power BI template*) |
| A `.SemanticModel` folder, or a folder with a model and no report | Pass the PBIP project folder, its `.Report` folder or its `.pbip` file |
| Anything else | Pass a PBIP project folder, a `.Report` folder, a `.pbip` file or a `.pbit` file |

Planned for later versions (see the [roadmap](PROJECT.md#next-phase-m6m10)):

- `.pbix` (v0.9.0): the report part read locally. Model metadata from the
  `DataModel` entry is read only with the opt-in `--read-pbix-model` flag;
  data values are never read, stored, logged or written to any output.
  Files last saved before Power BI Desktop's enhanced metadata format
  (about 2020) will need to be opened and saved in a current Power BI
  Desktop, or exported as a `.pbit`.
- Semantic models on their own (v0.10.0): two `.SemanticModel` folders,
  `model.bim` files or `.pbit` files compared without a report.

The tool never uploads, converts or creates items in a Power BI workspace to
read a file.

## Errors and exit codes

| Situation | Exit code |
|---|---|
| An input format that isn't supported yet (`.pbix`, a model on its own, an unknown file) | `2` |
| A path that doesn't exist, or a folder without exactly one `.Report` folder | `1` |
| A report with neither a PBIR definition nor a legacy `report.json`, or a `.pbit` without `Report/Layout` | `1` |
| An unreadable or refused `.pbit` archive, or a report file that isn't valid JSON | `1` |
| A `definition.pbir` or `.pbip` file that points outside the project folder | `1` |

A single page, visual, filter or model file that can't be parsed doesn't stop
the run: it becomes a `parse_issue` finding and the rest is compared.
