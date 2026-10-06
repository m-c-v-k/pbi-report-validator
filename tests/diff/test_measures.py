from pbi_report_validator.diff.measures import diff_measures
from pbi_report_validator.domain.models import ChangeKind, Measure, SemanticModel, Table


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
    assert result.renames == {"Sales[Margin %]": "Sales[Gross Margin %]"}


def test_added_removed_and_modified() -> None:
    old = model(m("Keep", "1"), m("Gone", "2"))
    new = model(m("Keep", "10"), m("Fresh", "3"))

    result = diff_measures(old, new)

    assert sorted((f.path, f.change) for f in result.findings) == [
        ("model/Sales/Fresh", ChangeKind.ADDED),
        ("model/Sales/Gone", ChangeKind.REMOVED),
        ("model/Sales/Keep", ChangeKind.MODIFIED),
    ]
    assert result.renames == {}


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


def test_missing_model_compares_nothing() -> None:
    assert diff_measures(None, model(m("A", "1"))).findings == ()
    assert diff_measures(model(m("A", "1")), None).findings == ()
