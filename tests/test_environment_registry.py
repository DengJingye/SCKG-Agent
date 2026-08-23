from copy import deepcopy

import pytest
from pydantic import ValidationError

from core.execution_models import EnvironmentRecord
from execution.environment_registry import EnvironmentRegistry


def test_scrnaseq_environment_is_integration_qualified_for_restricted_policy():
    environment = EnvironmentRegistry().get("scRNAseq")

    assert environment.qualification_status == "integration_passed"
    assert environment.import_smoke_passed is True
    assert environment.integration_test_passed is True
    assert environment.enabled_for_execution is True
    assert environment.package_versions["scrublet"] == "0.2.3"


def test_environment_registry_loads_all_records():
    records = EnvironmentRegistry().load_all()

    assert [record.environment_id for record in records] == [
        "annotation-python",
        "annotation-r",
        "scDblFinder-R",
        "scRNAseq",
        "sckg-batch-cpu",
    ]


def test_scdblfinder_environment_is_integration_qualified_for_restricted_policy():
    environment = EnvironmentRegistry().get("scDblFinder-R")
    assert environment.qualification_status == "integration_passed"
    assert environment.import_smoke_passed is True
    assert environment.integration_test_passed is True
    assert environment.package_versions["rscript"] == "4.5.3"
    assert environment.package_versions["scdblfinder"] == "1.24.0"
    assert environment.enabled_for_execution is True


def test_environment_cannot_be_enabled_without_integration():
    environment = EnvironmentRegistry().get("scRNAseq")
    payload = deepcopy(environment.model_dump())
    payload["qualification_status"] = "import_qualified"
    payload["integration_test_passed"] = False
    payload["enabled_for_execution"] = True

    with pytest.raises(ValidationError, match="execution-enabled"):
        EnvironmentRecord.model_validate(payload)
