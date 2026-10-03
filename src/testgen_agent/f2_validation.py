"""Validate F2 human-authored references/known errors locally, without a model."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
from uuid import uuid4

from .benchmark import DEFAULT_DATASET, BenchmarkDataset, handwritten_tests
from .tools import run_tests_with_coverage


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def changed_functions(reference: str, variant: str) -> tuple[str, ...]:
    before, after = ast.parse(reference), ast.parse(variant)
    def functions(tree):
        return {node.name: ast.dump(node, include_attributes=False) for node in tree.body if isinstance(node, ast.FunctionDef)}
    a, b = functions(before), functions(after)
    if set(a) != set(b):
        raise ValueError("variant changes the public function set")
    outlines = [tuple(ast.dump(node, include_attributes=False) for node in tree.body if not isinstance(node, ast.FunctionDef))
                for tree in (before, after)]
    if outlines[0] != outlines[1]:
        raise ValueError("variant changes module imports or statements")
    return tuple(name for name in a if a[name] != b[name])


def validate(output: Path, *, dataset_root: Path = DEFAULT_DATASET, split: str = "all") -> dict:
    if split not in {"all", "development", "holdout"}:
        raise ValueError("unknown split")
    dataset = BenchmarkDataset(dataset_root)
    selected = [case for case in dataset.manifest.cases if split == "all" or case.split == split]
    root = (output / uuid4().hex).resolve()
    root.mkdir(parents=True, exist_ok=False)
    _write(root / "manifest.json", dataset.manifest.model_dump(mode="json"))
    record = {
        "stage": "F2", "dataset_id": dataset.manifest.dataset_id, "split": split,
        "tested_at_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
        "workspace": str(root), "network_requests": 0,
        "provenance": "Handwritten fixture/oracle validation with real pytest/coverage; not LLM-generated test evaluation.",
        "references": [], "variants": [],
    }
    test_codes = {}

    def execute(source: Path, code: str, label: str):
        directory = root / label
        (directory / "rounds/01").mkdir(parents=True, exist_ok=False)
        (directory / "subject.py").write_bytes(source.read_bytes())
        (directory / "rounds/01/test_subject.py").write_text(code, encoding="utf-8")
        result = run_tests_with_coverage(directory, timeout=30)
        return {"workspace": str(directory), "artifacts": str(result.artifacts),
                "test_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
                "execution": result.execution.model_dump(mode="json"),
                "coverage": result.coverage.model_dump(mode="json")}, result

    for case in selected:
        public = dataset.public_input(case.case_id)
        oracles, annotation = dataset.oracles(case.case_id), dataset.annotations(case.case_id)
        sites = {item.call_id: item for item in public.source.call_sites}
        actual_edges = {(edge.caller, edge.callee, sites[edge.call_site_id].line, sites[edge.call_site_id].expression)
                        for edge in public.source.direct_calls}
        expected_edges = {(edge.caller, edge.callee, edge.line, edge.expression) for edge in annotation.confirmed_edges}
        scenario_ids = {item.scenario_id for item in oracles.scenarios}
        collaboration_ids = {item.scenario_id for item in oracles.scenarios if item.test_kind == "collaboration"}
        checks = {
            "functions_match_annotation": {item.name for item in public.source.functions} == set(case.functions),
            "confirmed_edges_and_locations_match": actual_edges == expected_edges,
            "entries_belong_to_source": set(annotation.reasonable_entries).issubset(case.functions),
            "combined_behavior_references_valid": all(set(item.scenario_ids).issubset(collaboration_ids)
                                                       for item in annotation.combined_behaviors),
            "collaboration_targets_are_entries": all(item.function in annotation.reasonable_entries
                                                       for item in oracles.scenarios if item.test_kind == "collaboration"),
            "independent_control_has_no_edges_or_workflow": not annotation.independent_control or (
                len(case.functions) >= 2 and not actual_edges and not annotation.combined_behaviors and not collaboration_ids),
            "variants_reference_real_oracles": all(set(item.witnesses).issubset(scenario_ids)
                for item in dataset.manifest.variants if item.case_id == case.case_id),
        }
        test_codes[case.case_id] = handwritten_tests(oracles)
        evidence, result = execute(dataset.path(case.source), test_codes[case.case_id], f"references/{case.case_id}")
        checks.update(reference_all_passed=result.execution.all_passed,
                      every_oracle_collected=result.execution.collected == len(oracles.scenarios),
                      target_coverage_available=result.coverage.status == "available")
        record["references"].append({"case_id": case.case_id, "split": case.split,
            "function_count": len(case.functions), "oracle_count": len(oracles.scenarios),
            "checks": checks, "passed": all(checks.values()), **evidence})
        _write(root / f"references/{case.case_id}/source_analysis.json", public.source.model_dump(mode="json"))

    reference_results = {item["case_id"]: item for item in record["references"]}
    for variant in dataset.manifest.variants:
        if variant.case_id not in reference_results:
            continue
        case = dataset.case(variant.case_id)
        reference = dataset.path(case.source).read_text(encoding="utf-8")
        faulty = dataset.path(variant.source).read_text(encoding="utf-8")
        evidence, result = execute(dataset.path(variant.source), test_codes[case.case_id], f"variants/{variant.variant_id}")
        failures = {item.nodeid.split("::")[-1]: item for item in result.execution.failures if item.phase == "call"}
        units = {f"test_{item.scenario_id}" for item in dataset.oracles(case.case_id).scenarios if item.test_kind == "unit"}
        checks = {
            "baseline_valid": reference_results[case.case_id]["passed"],
            "only_declared_function_changed": changed_functions(reference, faulty) == (variant.affected_function,),
            "same_handwritten_tests": evidence["test_sha256"] == reference_results[case.case_id]["test_sha256"],
            "same_collection_count": result.execution.collected == reference_results[case.case_id]["execution"]["collected"],
            "every_declared_witness_failed_for_known_behavior": all(
                f"test_{name}" in failures and failures[f"test_{name}"].exception_type in variant.failure_types
                for name in variant.witnesses),
            "not_import_or_environment_failure": result.execution.kind in {"assertion_failed", "execution_error"}
                and all(item.exception_type not in {"ImportError", "ModuleNotFoundError", "SyntaxError"}
                        for item in result.execution.failures),
        }
        if variant.variant_id == "order_quantity_increment":
            checks["component_units_pass_while_collaboration_fails"] = not (units & failures.keys())
        record["variants"].append({"variant_id": variant.variant_id, "case_id": case.case_id,
            "affected_function": variant.affected_function, "kind": variant.kind, "description": variant.description,
            "witnesses": list(variant.witnesses), "checks": checks, "passed": all(checks.values()), **evidence})

    # Re-open and fingerprint after execution; specimen mutation cannot pass unnoticed.
    BenchmarkDataset(dataset_root)
    record["fixtures_unchanged"] = True
    record["status"] = "passed" if all(item["passed"] for item in (*record["references"], *record["variants"])) else "failed"
    record["counts"] = {"tasks": len(selected), "functions": sum(len(case.functions) for case in selected),
                         "handwritten_oracles": sum(item["oracle_count"] for item in record["references"]),
                         "known_variants": len(record["variants"])}
    _write(root / "validation.json", record)
    return record


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)) and not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="F2：验证手写评测集、人工关系标注和已知错误变体，不调用模型。")
    parser.add_argument("--output", type=Path, default=Path("outputs/f2"))
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--split", choices=("all", "development", "holdout"), default="all")
    args = parser.parse_args(argv)
    result = validate(args.output, dataset_root=args.dataset, split=args.split)
    print(json.dumps({"status": result["status"], "counts": result["counts"], "workspace": result["workspace"],
                      "failed_checks": [{"case": item.get("case_id"), "variant": item.get("variant_id"),
                         "checks": [key for key, value in item["checks"].items() if not value]}
                         for item in (*result["references"], *result["variants"]) if not item["passed"]],
                      "network_requests": 0}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
