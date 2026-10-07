import subprocess
import sys

import pytest

from pbi_report_validator.domain import base, data, diff, models, report, semantic


def test_models_reexports_every_class_of_the_split_modules() -> None:
    split = (base, data, diff, report, semantic)
    defined = {
        name
        for module in split
        for name, obj in vars(module).items()
        if isinstance(obj, type) and obj.__module__ == module.__name__
    }

    assert defined <= set(models.__all__)
    assert all(hasattr(models, name) for name in models.__all__)
    assert len(models.__all__) == 44


@pytest.mark.parametrize("module", ["report", "semantic", "data", "diff"])
def test_each_module_works_when_imported_on_its_own(module: str) -> None:
    code = (
        f"from pbi_report_validator.domain import {module} as m\n"
        "for name in dir(m):\n"
        "    obj = getattr(m, name)\n"
        "    if hasattr(obj, 'model_json_schema'):\n"
        "        obj.model_json_schema()\n"
    )

    subprocess.run([sys.executable, "-c", code], check=True)
