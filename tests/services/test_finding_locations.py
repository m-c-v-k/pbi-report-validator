from pbi_report_validator.diff.structural import diff_pages_and_visuals
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    Finding,
    MatchMethod,
    PageMatch,
    ReportMatch,
    SourceLocation,
    VisualMatch,
)
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES, page, visual
from tests.parsers.test_source_locations import resolve

LOCATED = {
    Category.PAGE,
    Category.VISUAL,
    Category.FIELD,
    Category.FILTER,
    Category.SLICER,
    Category.MEASURE,
}


def findings() -> list[Finding]:
    result = validate(FIXTURES / "sales_v1", FIXTURES / "sales_v3")
    return list(result.findings)


def test_every_located_category_is_covered_by_the_fixtures() -> None:
    assert {f.category for f in findings()} >= LOCATED


def test_locations_exist_exactly_on_the_sides_that_have_the_object() -> None:
    for finding in findings():
        if finding.category not in LOCATED:
            assert (finding.old_location, finding.new_location) == (None, None)
            continue
        has_old = finding.change is not ChangeKind.ADDED
        has_new = finding.change is not ChangeKind.REMOVED
        assert (finding.old_location is not None) == has_old, finding.path
        assert (finding.new_location is not None) == has_new, finding.path


def test_json_locations_point_at_the_changed_object() -> None:
    for finding in findings():
        sides = [
            (FIXTURES / "sales_v1", finding.old_location),
            (FIXTURES / "sales_v3", finding.new_location),
        ]
        for project, location in sides:
            if location is None or finding.category is Category.MEASURE:
                continue
            target = resolve(project, location)
            if finding.category is Category.FIELD:
                assert "field" in target
            elif finding.category is Category.SLICER:
                assert "filter" in target
            else:
                assert target["name"] == finding.path.rsplit("/", 1)[-1]


def test_renamed_measure_has_its_old_and_new_name() -> None:
    renamed = next(f for f in findings() if f.change is ChangeKind.RENAMED)

    assert renamed.old_location is not None and renamed.new_location is not None
    assert renamed.old_location.pointer == "table Sales / measure 'Margin %'"
    assert renamed.new_location.pointer == "table Sales / measure 'Gross Margin %'"


def test_visual_with_a_new_id_points_at_its_new_folder() -> None:
    old_at = SourceLocation(file="p/visuals/old_id/visual.json", pointer="")
    new_at = SourceLocation(file="p/visuals/new_id/visual.json", pointer="")
    old = visual("old_id").model_copy(update={"location": old_at})
    new = visual("new_id").model_copy(update={"location": new_at})
    match = ReportMatch(
        pages=(
            PageMatch(
                old=page("p", old),
                new=page("p", new),
                method=MatchMethod.ID,
                visuals=(
                    VisualMatch(
                        old=old, new=new, method=MatchMethod.SIMILARITY, score=0.9
                    ),
                ),
            ),
        )
    )

    (finding,) = diff_pages_and_visuals(match)

    assert finding.change is ChangeKind.RENAMED
    assert (finding.old_location, finding.new_location) == (old_at, new_at)
