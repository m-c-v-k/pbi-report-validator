from pbi_report_validator.diff.measures import diff_measures
from pbi_report_validator.domain.models import (
    ChangeKind,
    Measure,
    MeasureRename,
    ParseIssue,
    SemanticModel,
    Table,
)


def new_keys(renames: dict[str, MeasureRename]) -> dict[str, str]:
    return {old: rename.new_key for old, rename in renames.items()}


def model(*measures: Measure, table: str = "Sales") -> SemanticModel:
    return SemanticModel(tables=(Table(name=table, measures=measures),))


def m(name: str, expression: str) -> Measure:
    return Measure(name=name, expression=expression)


def test_rename_with_same_expression_is_one_finding() -> None:
    result = diff_measures(
        model(m("Margin %", "DIVIDE(1, 2)")), model(m("Gross Margin %", "DIVIDE(1, 2)"))
    )

    assert [(f.path, f.change, f.old, f.new) for f in result.findings] == [
        ("model/Sales/Margin %", ChangeKind.RENAMED, "Margin %", "Gross Margin %")
    ]
    assert new_keys(result.renames) == {"Sales[Margin %]": "Sales[Gross Margin %]"}


def test_added_removed_and_modified() -> None:
    old = model(m("Keep", "1"), m("Gone", "2"))
    new = model(m("Keep", "10"), m("Fresh", "3"))

    result = diff_measures(old, new)

    assert sorted((f.path, f.change) for f in result.findings) == [
        ("model/Sales/Fresh", ChangeKind.ADDED),
        ("model/Sales/Gone", ChangeKind.REMOVED),
        ("model/Sales/Keep", ChangeKind.MODIFIED),
    ]
    assert new_keys(result.renames) == {}


def test_ambiguous_expressions_are_not_renames() -> None:
    old = model(m("A", "1"), m("B", "1"))
    new = model(m("C", "1"))

    result = diff_measures(old, new)

    assert sorted(f.change for f in result.findings) == [
        ChangeKind.ADDED,
        ChangeKind.REMOVED,
        ChangeKind.REMOVED,
    ]


def test_same_name_in_another_table_is_not_a_rename() -> None:
    old = model(m("X", "1"), table="A")
    new = model(m("Y", "1"), table="B")

    result = diff_measures(old, new)

    assert sorted((f.path, f.change) for f in result.findings) == [
        ("model/A/X", ChangeKind.REMOVED),
        ("model/B/Y", ChangeKind.ADDED),
    ]


def test_table_declared_in_several_files_is_compared_as_one() -> None:
    def split(extra: str) -> SemanticModel:
        return SemanticModel(
            tables=(
                Table(name="Sales", measures=(m("Total", "1"),)),
                Table(name="Sales", measures=(m("Extra", extra),)),
            )
        )

    result = diff_measures(split("SUM(Amount)"), split("SUM(Cost)"))

    assert [(f.change, f.path) for f in result.findings] == [
        (ChangeKind.MODIFIED, "model/Sales/Extra")
    ]


def test_measure_that_failed_to_parse_is_not_reported_removed() -> None:
    old = model(m("Total", "1"), m("Margin", "2"))
    issue = ParseIssue(path="t.tmdl:3", message="m", measure="Sales[Margin]")
    new = model(m("Total", "1")).model_copy(update={"issues": (issue,)})

    assert diff_measures(old, new).findings == ()


def test_missing_model_compares_nothing() -> None:
    assert diff_measures(None, model(m("A", "1"))).findings == ()
    assert diff_measures(model(m("A", "1")), None).findings == ()


def test_whole_table_added_and_removed() -> None:
    old = model(m("X", "1"), table="Gone")
    new = model(m("Y", "2"), m("Z", "3"), table="Fresh")

    result = diff_measures(old, new)

    assert sorted((f.path, f.change) for f in result.findings) == [
        ("model/Fresh/Y", ChangeKind.ADDED),
        ("model/Fresh/Z", ChangeKind.ADDED),
        ("model/Gone/X", ChangeKind.REMOVED),
    ]


def test_two_renames_in_one_table() -> None:
    old = model(m("A", "1"), m("B", "2"))
    new = model(m("A2", "1"), m("B2", "2"))

    result = diff_measures(old, new)

    assert [(f.old, f.new) for f in result.findings] == [("A", "A2"), ("B", "B2")]
    assert new_keys(result.renames) == {
        "Sales[A]": "Sales[A2]",
        "Sales[B]": "Sales[B2]",
    }


def test_rename_with_expression_edit_is_removed_plus_added() -> None:
    result = diff_measures(model(m("Old", "1")), model(m("New", "2")))

    assert sorted(f.change for f in result.findings) == [
        ChangeKind.ADDED,
        ChangeKind.REMOVED,
    ]
    assert new_keys(result.renames) == {}


def tables(**measures: tuple[Measure, ...]) -> SemanticModel:
    return SemanticModel(
        tables=tuple(Table(name=name, measures=ms) for name, ms in measures.items())
    )


def test_measure_moved_to_another_table_is_one_finding() -> None:
    old = tables(Sales=(m("Margin %", "DIVIDE(1, 2)"),), Measures=())
    new = tables(Sales=(), Measures=(m("Margin %", "DIVIDE(1, 2)"),))

    result = diff_measures(old, new)

    assert [(f.path, f.change, f.old, f.new, f.message) for f in result.findings] == [
        (
            "model/Sales/Margin %",
            ChangeKind.MOVED,
            "Sales",
            "Measures",
            "Measure Sales[Margin %] moved to Measures[Margin %]",
        )
    ]
    assert new_keys(result.renames) == {"Sales[Margin %]": "Measures[Margin %]"}


def test_moved_measure_with_an_edited_expression_is_removed_plus_added() -> None:
    old = tables(Sales=(m("X", "1"),), Measures=())
    new = tables(Sales=(), Measures=(m("X", "2"),))

    result = diff_measures(old, new)

    assert sorted((f.path, f.change) for f in result.findings) == [
        ("model/Measures/X", ChangeKind.ADDED),
        ("model/Sales/X", ChangeKind.REMOVED),
    ]
    assert new_keys(result.renames) == {}


def test_ambiguous_moves_are_not_paired() -> None:
    old = tables(A=(m("X", "1"),), B=(m("X", "1"),), C=())
    new = tables(A=(), B=(), C=(m("X", "1"),))

    result = diff_measures(old, new)

    assert sorted((f.path, f.change) for f in result.findings) == [
        ("model/A/X", ChangeKind.REMOVED),
        ("model/B/X", ChangeKind.REMOVED),
        ("model/C/X", ChangeKind.ADDED),
    ]


def test_rename_within_a_table_is_paired_before_moves() -> None:
    old = tables(Sales=(m("Old", "1"),), Measures=())
    new = tables(Sales=(m("New", "1"),), Measures=(m("Old", "1"),))

    result = diff_measures(old, new)

    assert [(f.path, f.change) for f in result.findings] == [
        ("model/Sales/Old", ChangeKind.RENAMED),
        ("model/Measures/Old", ChangeKind.ADDED),
    ]
