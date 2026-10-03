"""F2 fixture integrity and local reference verification; no model requests."""

from collections import Counter
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType

import pytest
from pydantic import ValidationError

from testgen_agent.benchmark import (
    DEFAULT_DATASET, BenchmarkDataset, DatasetManifest, OracleExpectation, handwritten_tests,
)
from testgen_agent.f2_validation import changed_functions, validate
from testgen_agent.prompts import build_generation_context
from testgen_agent.models import OracleMode


def test_catalog_has_balanced_categories_disjoint_holdout_and_required_controls():
    dataset = BenchmarkDataset()
    manifest = dataset.manifest
    assert len(manifest.cases) == 8
    categories = Counter(category for case in manifest.cases for category in case.functions.values())
    assert categories == {"numeric_boundaries": 3, "strings": 3, "lists": 3, "exceptions_branches": 3}
    development = {name for case in manifest.cases if case.split == "development" for name in case.functions}
    holdout = {name for case in manifest.cases if case.split == "holdout" for name in case.functions}
    assert len(development) == 8 and len(holdout) == 4 and not development & holdout
    assert sum(bool(dataset.annotations(case.case_id).confirmed_edges) for case in manifest.cases) >= 2
    assert dataset.annotations("independent").independent_control
    assert len(manifest.variants) == len({item.affected_function for item in manifest.variants}) == 6
    assert any(item.case_id == "order" and item.kind == "data_flow" for item in manifest.variants)


@pytest.mark.parametrize("case_id", ["order", "labels", "independent"])
def test_public_prompt_contains_no_hidden_oracles_annotations_or_variant_hints(case_id):
    dataset = BenchmarkDataset()
    public = dataset.public_input(case_id)
    assert set(public.model_dump()) == {"source", "behavior_specification"}
    context = build_generation_context(public.source, public.behavior_specification, OracleMode.SPECIFICATION)
    for item in dataset.oracles(case_id).scenarios:
        assert item.scenario_id not in context.user_prompt
    for item in dataset.manifest.variants:
        assert item.variant_id not in context.user_prompt
    assert "independent_control" not in context.user_prompt
    assert "combined_behaviors" not in context.user_prompt


@pytest.mark.parametrize("relative", ["development/order.py", "oracles/order.json", "annotations/order.json", "mutants/order_quantity_increment.py"])
def test_fingerprints_detect_changes_to_sources_or_private_evidence(tmp_path, relative):
    root = tmp_path / "dataset"
    shutil.copytree(DEFAULT_DATASET, root)
    path = root / relative
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        BenchmarkDataset(root)


@pytest.mark.parametrize("relative", ["../outside.py", "C:/outside.py", "development\\order.py", "/tmp/outside.py"])
def test_dataset_paths_cannot_escape_root(relative):
    with pytest.raises(ValueError, match="path"):
        BenchmarkDataset().path(relative)


@pytest.mark.parametrize("change", ["duplicate_case", "bad_function_category", "unknown_variant_target", "wrong_holdout_size"])
def test_manifest_rejects_inconsistent_dataset_definition(change):
    data = BenchmarkDataset().manifest.model_dump(mode="json")
    if change == "duplicate_case":
        data["cases"][1]["case_id"] = data["cases"][0]["case_id"]
    elif change == "bad_function_category":
        data["cases"][0]["functions"]["subtotal"] = "lists"
    elif change == "unknown_variant_target":
        data["variants"][0]["affected_function"] = "missing"
    else:
        data["cases"][-1]["split"] = "development"
    with pytest.raises(ValidationError):
        DatasetManifest.model_validate(data)


def test_variants_change_only_the_declared_function_and_preserve_test_oracles():
    dataset = BenchmarkDataset()
    for variant in dataset.manifest.variants:
        case = dataset.case(variant.case_id)
        assert changed_functions(dataset.path(case.source).read_text(encoding="utf-8"),
                                 dataset.path(variant.source).read_text(encoding="utf-8")) == (variant.affected_function,)
        ids = {item.scenario_id for item in dataset.oracles(case.case_id).scenarios}
        assert set(variant.witnesses).issubset(ids)
    with pytest.raises(ValueError, match="module imports"):
        changed_functions("def f():\n    return 1\n", "import math\ndef f():\n    return 2\n")


@pytest.mark.parametrize("values", [
    {"kind": "raises", "value": 1, "exception": "ValueError"},
    {"kind": "returns", "value": 1, "exception": "ValueError", "python_type": "int"},
    {"kind": "returns", "value": 1},
])
def test_oracles_reject_ambiguous_return_and_exception_definitions(values):
    with pytest.raises(ValidationError):
        OracleExpectation.model_validate(values)


def test_unknown_case_and_unknown_validation_split_are_explicit(tmp_path):
    with pytest.raises(KeyError):
        BenchmarkDataset().case("unknown")
    with pytest.raises(ValueError, match="split"):
        validate(tmp_path, split="unknown")


def test_holdout_references_and_known_errors_execute_locally_without_model(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("F2 must not invoke an LLM")
    monkeypatch.setattr("testgen_agent.llm_client.DeepSeekClient.generate_tests", forbidden)
    result = validate(tmp_path, split="holdout")
    assert result["status"] == "passed"
    assert result["network_requests"] == 0
    assert result["counts"] == {"tasks": 4, "functions": 4, "handwritten_oracles": 33, "known_variants": 2}
    assert result["fixtures_unchanged"]
    assert all(item["execution"]["passed"] == item["oracle_count"] for item in result["references"])
    by_case = {item["case_id"]: item for item in result["references"]}
    for item in result["variants"]:
        assert item["passed"]
        assert item["test_sha256"] == by_case[item["case_id"]]["test_sha256"]
        assert item["checks"]["every_declared_witness_failed_for_known_behavior"]
    saved = json.loads((Path(result["workspace"]) / "validation.json").read_text(encoding="utf-8"))
    assert saved == result
    assert "Handwritten" in saved["provenance"]


def test_materialized_oracles_reject_wrong_type_aliasing_and_input_mutation(monkeypatch):
    dataset = BenchmarkDataset()
    def mutating_rotate(values, steps):
        result = values[steps:] + values[:steps]
        values.append(99)
        return result
    for case_id, function, implementation, scenario in (
        ("mean", "safe_mean", lambda values: 0, "mean_empty"),
        ("rotation", "rotate_left", lambda values, steps: values, "rotate_empty"),
        ("rotation", "rotate_left", mutating_rotate, "rotate_one"),
    ):
        module = ModuleType("subject")
        setattr(module, function, implementation)
        monkeypatch.setitem(sys.modules, "subject", module)
        namespace = {}
        exec(compile(handwritten_tests(dataset.oracles(case_id)), "handwritten.py", "exec"), namespace)
        with pytest.raises(AssertionError):
            namespace[f"test_{scenario}"]()
