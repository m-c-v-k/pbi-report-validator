from pbi_report_validator.domain.models import Column, Measure
from pbi_report_validator.domain.raw import RawSemanticModel, RawTextFile
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.parsers.tmdl import parse_semantic_model, parse_tmdl
from tests.factories import FIXTURES


def test_parses_sales_v1_model() -> None:
    raw = load_project(FIXTURES / "sales_v1").semantic_model
    assert raw is not None

    model = parse_semantic_model(raw)

    assert model.issues == ()
    assert [t.name for t in model.tables] == ["Date", "Product", "Sales"]
    sales = model.tables[2]
    assert [c.name for c in sales.columns] == [
        "ProductKey",
        "DateKey",
        "Region",
        "Amount",
        "Cost",
    ]
    assert sales.columns[3] == Column(name="Amount", data_type="decimal")
    assert sales.measures[0] == Measure(
        name="Total Sales", expression="SUM(Sales[Amount])"
    )
    assert sales.measures[1] == Measure(
        name="Margin %",
        expression=(
            "DIVIDE(\n"
            "    SUM(Sales[Amount]) - SUM(Sales[Cost]),\n"
            "    SUM(Sales[Amount])\n"
            ")"
        ),
    )


def test_parses_sales_v2_measure_changes() -> None:
    raw = load_project(FIXTURES / "sales_v2").semantic_model
    assert raw is not None

    sales = parse_semantic_model(raw).tables[2]

    assert [m.name for m in sales.measures] == ["Total Sales", "Gross Margin %"]
    assert sales.measures[0].expression == (
        "CALCULATE(SUM(Sales[Amount]), Sales[Amount] > 0)"
    )


def test_quoted_names_are_unquoted() -> None:
    text = (
        "table 'Sales Order''s'\n"
        "\tmeasure 'Net ''Value''' = 1\n"
        "\tcolumn 'Order Date'\n"
        "\t\tdataType: dateTime\n"
    )

    tables, _ = parse_tmdl(text, "t.tmdl")

    assert tables[0].name == "Sales Order's"
    assert tables[0].measures[0].name == "Net 'Value'"
    assert tables[0].columns[0] == Column(name="Order Date", data_type="dateTime")


def test_skips_unsupported_objects() -> None:
    text = (
        "table Sales\n"
        "\tmeasure X = 1\n"
        "\tpartition Sales = m\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\t\tlet\n"
        "\t\t\t\t    column = 1\n"
        "\t\t\t\tin column\n"
        "\thierarchy H\n"
        "\t\tlevel Year\n"
        "\tannotation PBI_Id = abc\n"
        "\n"
        "relationship r1\n"
        "\tfromColumn: Sales.Key\n"
    )

    tables, issues = parse_tmdl(text, "t.tmdl")

    assert issues == []
    assert len(tables) == 1
    assert tables[0].measures == (Measure(name="X", expression="1"),)
    assert tables[0].columns == ()


def test_fenced_expression_is_unwrapped() -> None:
    text = "table T\n\tmeasure M = ```\n\t\t\tSUM(T[A])\n\t\t\t```\n"

    tables, _ = parse_tmdl(text, "t.tmdl")

    assert tables[0].measures[0].expression == "SUM(T[A])"


def test_description_comments_are_ignored() -> None:
    text = "table T\n\t/// The total\n\tmeasure M = 1\n"

    tables, _ = parse_tmdl(text, "t.tmdl")

    assert tables[0].measures[0] == Measure(name="M", expression="1")


def test_measure_without_expression_is_an_issue() -> None:
    text = "table T\n\tmeasure Broken\n\t\tformatString: 0\n\tmeasure Ok = 2\n"

    tables, issues = parse_tmdl(text, "t.tmdl")

    assert [m.name for m in tables[0].measures] == ["Ok"]
    assert len(issues) == 1
    assert issues[0].path == "t.tmdl:2"
    assert "T[Broken]" in issues[0].message


def test_space_indentation_is_supported() -> None:
    text = "table T\n    measure M =\n            1 +\n                2\n"

    tables, _ = parse_tmdl(text, "t.tmdl")

    assert tables[0].measures[0].expression == "1 +\n    2"


def test_measure_with_empty_expression_is_an_issue() -> None:
    text = "table T\n\tmeasure Empty =\n\t\tformatString: 0\n"

    tables, issues = parse_tmdl(text, "t.tmdl")

    assert tables[0].measures == ()
    assert issues[0].path == "t.tmdl:2"
    assert "T[Empty]" in issues[0].message


def test_calculated_column_is_read_without_expression() -> None:
    text = "table T\n\tcolumn Double = T[A] * 2\n\t\tdataType: int64\n"

    tables, _ = parse_tmdl(text, "t.tmdl")

    assert tables[0].columns == (Column(name="Double", data_type="int64"),)


def test_triple_slash_inside_expression_is_kept() -> None:
    text = "table T\n\tmeasure M =\n\t\t\t1\n\t\t\t/// not a description\n"

    tables, _ = parse_tmdl(text, "t.tmdl")

    assert tables[0].measures[0].expression == "1\n/// not a description"


def test_fence_keeps_relative_indentation() -> None:
    text = (
        "table T\n"
        "\tmeasure M = ```\n"
        "\t\t\tIF(\n"
        "\t\t\t\tTRUE,\n"
        "\t\t\t\t1\n"
        "\t\t\t)\n"
        "\t\t\t```\n"
    )

    tables, _ = parse_tmdl(text, "t.tmdl")

    assert tables[0].measures[0].expression == "IF(\n\tTRUE,\n\t1\n)"


def test_ref_table_lines_are_not_tables() -> None:
    text = "model Model\n\tculture: en-US\n\nref table Sales\nref table Date\n"

    tables, issues = parse_tmdl(text, "model.tmdl")

    assert tables == []
    assert issues == []


def test_semantic_model_combines_files_in_order() -> None:
    raw = RawSemanticModel(
        path="M.SemanticModel",
        files=(
            RawTextFile(path="a.tmdl", text="table A\n\tmeasure Bad\n"),
            RawTextFile(path="b.tmdl", text="table B\n\tmeasure Ok = 1\n"),
            RawTextFile(path="c.tmdl", text="table C\n\tmeasure Bad =\n"),
        ),
    )

    model = parse_semantic_model(raw)

    assert [t.name for t in model.tables] == ["A", "B", "C"]
    assert [i.path for i in model.issues] == ["a.tmdl:2", "c.tmdl:2"]
