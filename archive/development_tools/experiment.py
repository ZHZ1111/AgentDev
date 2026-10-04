"""F3/F4 paired generation and small known-defect experiment, with offline rebuild."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
from uuid import uuid4

from .agent import run_agent
from .benchmark import BenchmarkDataset, CaseAnnotations, DatasetManifest
from .config import load_config
from .f2_validation import changed_functions
from .llm_client import DeepSeekClient, LLMError, LLMGenerationResult, RetryPolicy
from .models import AgentState, ExecutionResult, ModelInfo, OracleMode, TaskInput
from .prompts import PROMPT_VERSION, build_generation_context
from .tools import run_tests_with_coverage


MODES = ("baseline", "feedback")


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def usage_sum(values):
    if not values or any(value is None for value in values):
        return None
    return {key: sum(value[key] for value in values) if all(value.get(key) is not None for value in values) else None
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")}


class SharedSeedClient:
    """Replay exactly one real first response; only subsequent calls reach the adapter."""
    def __init__(self, client, seed, expected_context):
        self.client, self.seed, self.expected_context = client, seed, expected_context
        self.replayed = False
        self.additional_calls = []

    def generate_tests(self, context):
        if not self.replayed:
            self.replayed = True
            if context.canonical_json() != self.expected_context.canonical_json():
                raise ValueError("initial prompt differs from the frozen shared prompt")
            if isinstance(self.seed, LLMError):
                raise self.seed
            return self.seed
        started = perf_counter()
        try:
            result = self.client.generate_tests(context)
        except LLMError as error:
            self.additional_calls.append({"attempts": error.attempts, "usage": None,
                                          "seconds": perf_counter() - started, "error": error.safe_details()})
            raise
        self.additional_calls.append({"attempts": result.attempts,
            "usage": result.total_usage.model_dump(mode="json") if result.total_usage else None,
            "seconds": perf_counter() - started, "response_model": result.response_model})
        return result


def attributed_failures(execution: ExecutionResult, generated, source, variant, mutant_code: str) -> list[dict]:
    """Counterfactual attribution: passing reference, one changed function, mapped call failure.

    The caller separately checks the passing reference and unchanged test bytes.
    Dynamic/unmapped evidence and import/environment failures do not count as detections.
    """
    if generated is None:
        return []
    graph = {item.name: set() for item in source.functions}
    for edge in source.direct_calls:
        graph[edge.caller].add(edge.callee)
    def reaches(name):
        pending, seen = [name], set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(graph.get(current, ()))
        return variant.affected_function in seen
    scenarios = {item.scenario_id: item for item in generated.plan.scenarios}
    mappings = {item.test_function: item for item in generated.mappings}
    changed = next(node for node in ast.parse(mutant_code).body
                   if isinstance(node, ast.FunctionDef) and node.name == variant.affected_function)
    observations = []
    for failure in execution.failures:
        name = failure.nodeid.split("::")[-1].split("[")[0]
        mapping = mappings.get(name)
        origin = Path(failure.path).name if failure.path else None
        if (failure.phase != "call" or failure.exception_type not in variant.failure_types or not mapping
                or not any(reaches(scenarios[item].target_function) for item in mapping.scenario_ids)):
            continue
        if origin == "subject.py":
            if failure.line is None or not changed.lineno <= failure.line <= changed.end_lineno:
                continue
        elif origin != "test_subject.py":
            # pytest.raises reports its own outcomes.py as the deepest frame.
            # Require an actual raises context calling the affected mapped path,
            # rather than treating arbitrary framework failures as assertions.
            test_node = next((node for node in ast.parse(generated.code).body
                              if isinstance(node, ast.FunctionDef) and node.name == name), None)
            raises_target = test_node is not None and any(
                isinstance(node, ast.With) and any(
                    isinstance(item.context_expr, ast.Call)
                    and isinstance(item.context_expr.func, ast.Attribute)
                    and isinstance(item.context_expr.func.value, ast.Name)
                    and item.context_expr.func.value.id == "pytest"
                    and item.context_expr.func.attr == "raises" for item in node.items)
                and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                        and reaches(call.func.id) for statement in node.body for call in ast.walk(statement))
                for node in ast.walk(test_node))
            if not (failure.exception_type == "Failed" and origin == "outcomes.py"
                    and "_pytest" in Path(failure.path).parts and raises_target):
                continue
        elif failure.exception_type not in {"AssertionError", "Failed"}:
            continue
        observations.append({"nodeid": failure.nodeid, "exception_type": failure.exception_type,
            "path": failure.path, "line": failure.line, "scenario_ids": list(mapping.scenario_ids),
            "affected_function": variant.affected_function,
            "basis": "same tests pass paired reference; only this function differs; confirmed mapped call path"})
    return observations


def _selected(state):
    return state.history[state.best_available_round - 1] if state.best_available_round else None


def relation_metrics(candidate, state, annotation):
    if candidate is None or candidate.generated is None:
        return {"assessment": "unavailable"}
    plan = candidate.generated.plan
    expected = {(edge.caller, edge.callee) for edge in annotation.confirmed_edges}
    confirmed = {tuple(item.involved_functions) for item in plan.relationships
                 if item.kind == "direct_call" and item.confidence == "confirmed"}
    collaborations = [item for item in plan.scenarios if item.test_kind == "collaboration"]
    return {"assessment": "automatic_structure_only; see manual relation review for behavior assertions",
        "annotated_edges": sorted(expected), "reported_confirmed_edges": sorted(confirmed),
        "missing_confirmed_edges": sorted(expected - confirmed), "unsupported_confirmed_edges": sorted(confirmed - expected),
        "reasonable_entries_selected": set(annotation.reasonable_entries).issubset(plan.entry_functions),
        "collaboration_scenarios": len(collaborations),
        "collaboration_entry_targets": sorted({item.target_function for item in collaborations}),
        "independent_control_respected": not annotation.independent_control or not collaborations,
        "unresolved_source_calls": len(state.source_info.unresolved_calls),
        "planned_scenarios": len(plan.scenarios)}


def mode_metrics(state, summary, cost, annotation):
    selected = _selected(state)
    execution = selected.execution if selected else None
    coverage = selected.coverage if selected else None
    known = coverage is not None and coverage.status == "available"
    return {"status": summary["status"], "stop_reason": state.stop_reason,
        "selected_round": state.best_available_round, "candidate_rounds": len(state.history),
        "executed_rounds": sum(item.execution is not None for item in state.history),
        "runnable": bool(execution and execution.runnable), "all_passed": bool(execution and execution.all_passed),
        "collected": execution.collected if execution else None, "passed": execution.passed if execution else None,
        "execution_kind": execution.kind if execution else None,
        "coverage_status": coverage.status if coverage else "unavailable",
        "line_percent": coverage.line_percent if known else None, "branch_percent": coverage.branch_percent if known else None,
        "branch_not_applicable": bool(known and coverage.total_branches == 0),
        "credited_http_attempts": state.api_calls, "token_usage": state.token_usage.model_dump(mode="json") if state.token_usage else None,
        "seconds_including_shared_generation": cost["shared_generation_seconds"] + cost["controller_seconds"],
        "new_actual_http_attempts": sum(item["attempts"] for item in cost["additional_calls"]),
        "relations": relation_metrics(selected, state, annotation)}


def rebuild(root: Path) -> dict:
    """Rebuild every metric from saved state/tool observations; no client or dataset reads."""
    root = root.resolve()
    frozen = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
    manifest = DatasetManifest.model_validate_json((root / "dataset_manifest.json").read_text(encoding="utf-8"))
    results = []
    physical_calls, unknown_usage_attempts, physical_usage = 0, 0, []
    for case_id in frozen["case_ids"]:
        case = next(item for item in manifest.cases if item.case_id == case_id)
        directory = root / "cases" / case_id
        seed = json.loads((directory / "seed/cost.json").read_text(encoding="utf-8"))
        physical_calls += seed["attempts"]
        physical_usage.append(seed["usage"])
        if seed["usage"] is None:
            unknown_usage_attempts += seed["attempts"]
        annotation = CaseAnnotations.model_validate_json((directory / "evaluation/annotations.json").read_text(encoding="utf-8"))
        if digest((directory / "evaluation/annotations.json").read_bytes()) != manifest.sha256[case.annotations]:
            raise ValueError("saved evaluator annotation does not match frozen dataset")
        item = {"case_id": case_id, "split": case.split, "modes": {}, "variants": {}}
        hashes = []
        for mode in MODES:
            path = directory / mode
            state = AgentState.model_validate_json((path / "state.json").read_text(encoding="utf-8"))
            summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
            cost = json.loads((path / "cost.json").read_text(encoding="utf-8"))
            if (summary["selected_round"] != state.best_available_round or summary["api_calls"] != state.api_calls
                    or summary["stop_reason"] != state.stop_reason
                    or state.api_calls != seed["attempts"] + sum(call["attempts"] for call in cost["additional_calls"])):
                raise ValueError("state, summary and cost evidence disagree")
            selected = _selected(state)
            if selected and (path / "test_subject.py").read_text(encoding="utf-8") != selected.generated.code:
                raise ValueError("exported tests differ from selected candidate")
            physical_calls += sum(call["attempts"] for call in cost["additional_calls"])
            physical_usage.extend(call["usage"] for call in cost["additional_calls"])
            unknown_usage_attempts += sum(call["attempts"] for call in cost["additional_calls"] if call["usage"] is None)
            item["modes"][mode] = mode_metrics(state, summary, cost, annotation)
            first = path / "rounds/01/llm_result.json"
            hashes.append(digest(first.read_bytes()) if first.exists() else None)
            seed_result = directory / "seed/llm_result.json"
            if seed_result.exists() and (not first.exists() or json.loads(first.read_text(encoding="utf-8"))
                                          != json.loads(seed_result.read_text(encoding="utf-8"))):
                raise ValueError("first candidate does not match the frozen seed")
            # Source/spec hashes belong to the frozen F2 manifest, not caller claims.
            for relative, saved in ((case.source, "input/subject.py"), (case.specification, "input/behavior.md")):
                if digest((directory / saved).read_bytes()) != manifest.sha256[relative]:
                    raise ValueError("saved public input does not match frozen dataset")
            item["variants"][mode] = []
            for variant in manifest.variants:
                if variant.case_id != case_id:
                    continue
                variant_root = directory / "variants" / mode / variant.variant_id
                meta = json.loads((variant_root / "evaluation.json").read_text(encoding="utf-8"))
                outcome = {"variant_id": variant.variant_id, "affected_function": variant.affected_function,
                           "status": "not_evaluable", "reason": meta.get("reason"), "attributed_failures": []}
                if meta.get("evaluated"):
                    paired = ExecutionResult.model_validate_json((directory / mode / "paired_reference/execution.json").read_text(encoding="utf-8"))
                    observed = ExecutionResult.model_validate_json((variant_root / "execution.json").read_text(encoding="utf-8"))
                    code = (variant_root / "rounds/01/test_subject.py").read_bytes()
                    selected = _selected(state)
                    reference_code = (directory / "input/subject.py").read_text(encoding="utf-8")
                    mutant_code = (variant_root / "subject.py").read_text(encoding="utf-8")
                    unchanged = (code == (path / "test_subject.py").read_bytes()
                                 == (path / "paired_reference/rounds/01/test_subject.py").read_bytes())
                    input_matches = ((path / "paired_reference/subject.py").read_bytes()
                                     == (directory / "input/subject.py").read_bytes()
                                     and digest((variant_root / "subject.py").read_bytes()) == manifest.sha256[variant.source])
                    eligible = (selected is not None and selected.execution.all_passed and paired.all_passed and unchanged
                        and input_matches
                        and changed_functions(reference_code, mutant_code) == (variant.affected_function,)
                        and observed.kind in {"passed", "assertion_failed", "execution_error"}
                        and observed.collected == paired.collected and observed.executed == paired.executed
                        and observed.skipped == observed.xfailed == observed.xpassed == 0
                        and all(failure.phase == "call" and failure.exception_type not in {"ImportError", "ModuleNotFoundError", "SyntaxError"}
                                for failure in observed.failures))
                    outcome.update(test_sha256=digest(code), execution_kind=observed.kind,
                        collected=observed.collected, failed=observed.failed, errors=observed.errors,
                        unchanged_tests=unchanged, paired_reference_all_passed=paired.all_passed)
                    if eligible:
                        matched = attributed_failures(observed, selected.generated, state.source_info, variant, mutant_code)
                        outcome.update(status="detected" if matched else "not_detected" if observed.all_passed else "unattributed_failure",
                                       reason=None, attributed_failures=matched)
                    else:
                        outcome["reason"] = "paired reference, unchanged bytes, or framework/collection gate failed"
                item["variants"][mode].append(outcome)
        item["shared_first_candidate_identical"] = hashes[0] == hashes[1]
        b, f = (item["modes"][mode] for mode in MODES)
        deltas = {key: f[key] - b[key] if f[key] is not None and b[key] is not None else None
                  for key in ("line_percent", "branch_percent", "collected", "passed")}
        item["change"] = {**deltas, "status_before": b["status"], "status_after": f["status"],
            "description": "improved" if any((deltas[key] or 0) > 0 for key in ("line_percent", "branch_percent"))
                else "declined" if any((deltas[key] or 0) < 0 for key in ("line_percent", "branch_percent")) else "no_coverage_change"}
        results.append(item)
    comparable = []
    for item in results:
        feedback = {variant["variant_id"]: variant for variant in item["variants"]["feedback"]}
        for baseline in item["variants"]["baseline"]:
            other = feedback[baseline["variant_id"]]
            if baseline["status"] != "not_evaluable" and other["status"] != "not_evaluable":
                comparable.append({"variant_id": baseline["variant_id"], "baseline_status": baseline["status"],
                                   "feedback_status": other["status"]})
    summary = {"stage": "F3/F4", "provenance": frozen["provenance"], "frozen_config": frozen,
        "cases": results, "aggregate": aggregate(results),
        "aggregate_by_split": {split: aggregate([item for item in results if item["split"] == split])
                               for split in ("development", "holdout")},
        "physical_cost": {"http_attempts": physical_calls,
                          "actual_network_http_attempts": physical_calls if frozen["provenance"] == "live" else 0,
                          "token_usage": usage_sum(physical_usage),
                          "known_token_subtotal": usage_sum([usage for usage in physical_usage if usage is not None]),
                          "http_attempts_with_unknown_usage": unknown_usage_attempts},
        "paired_comparable_variants": {"evaluable_variants": len(comparable),
             "baseline_detected": sum(item["baseline_status"] == "detected" for item in comparable),
             "feedback_detected": sum(item["feedback_status"] == "detected" for item in comparable),
             "variants": comparable},
        "fairness_all_shared_first_candidates_identical": all(item["shared_first_candidate_identical"] for item in results),
        "limitations": "Eight small tasks; one stochastic sample each. Coverage is not correctness. Credited mode costs share one physical seed. This is a small known-defect experiment, not a complete mutation system."}
    write_json(root / "summary.json", summary)
    _write_tables(root, summary)
    return summary


def aggregate(cases):
    result = {}
    for mode in MODES:
        metrics = [item["modes"][mode] for item in cases]
        variants = [variant for item in cases for variant in item["variants"][mode]]
        result[mode] = {"tasks": len(metrics), "runnable_tasks": sum(item["runnable"] for item in metrics),
            "all_passed_tasks": sum(item["all_passed"] for item in metrics),
            "completed_tasks": sum(item["status"] == "completed" for item in metrics),
            "credited_http_attempts": sum(item["credited_http_attempts"] for item in metrics),
            "token_usage": usage_sum([item["token_usage"] for item in metrics]),
            "seconds": sum(item["seconds_including_shared_generation"] for item in metrics),
            "known_variants": len(variants), "evaluable_variants": sum(item["status"] != "not_evaluable" for item in variants),
            "detected_variants": sum(item["status"] == "detected" for item in variants),
            "unattributed_failures": sum(item["status"] == "unattributed_failure" for item in variants)}
        for key in ("line_percent", "branch_percent"):
            known = [item[key] for item in metrics if item[key] is not None]
            result[mode][f"mean_{key}"] = sum(known) / len(known) if known else None
            result[mode][f"{key}_available_tasks"] = len(known)
        result[mode]["coverage_unavailable_tasks"] = sum(item["coverage_status"] != "available" for item in metrics)
        result[mode]["branch_not_applicable_tasks"] = sum(item["branch_not_applicable"] for item in metrics)
        for count, denominator, name in (("runnable_tasks", "tasks", "runnable_rate"),
                                         ("all_passed_tasks", "tasks", "all_passed_rate"),
                                         ("detected_variants", "evaluable_variants", "detection_rate")):
            result[mode][name] = result[mode][count] / result[mode][denominator] if result[mode][denominator] else None
    return result


def _write_tables(root, summary):
    import csv
    columns = ["case_id", "split", "mode", "status", "stop_reason", "candidate_rounds", "selected_round", "collected",
               "passed", "line_percent", "branch_percent", "credited_http_attempts", "new_actual_http_attempts", "seconds_including_shared_generation",
               "prompt_tokens", "completion_tokens", "total_tokens"]
    with (root / "cases.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for item in summary["cases"]:
            for mode in MODES:
                values = {**item["modes"][mode], "case_id": item["case_id"], "split": item["split"], "mode": mode}
                values.update({key: (values["token_usage"] or {}).get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")})
                writer.writerow({name: values[name] for name in columns})
    lines = ["# F3/F4 experiment", "", summary["limitations"], "", "| Mode | Passing tasks | Mean line | Mean branch | Coverage unavailable | Branch N/A | Defects detected/evaluable | Credited HTTP |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for mode, item in summary["aggregate"].items():
        lines.append(f"| {mode} | {item['all_passed_tasks']}/{item['tasks']} | {item['mean_line_percent']} | {item['mean_branch_percent']} | {item['coverage_unavailable_tasks']} | {item['branch_not_applicable_tasks']} | {item['detected_variants']}/{item['evaluable_variants']} | {item['credited_http_attempts']} |")
    lines.extend(["", "| Mode | Credited prompt/completion/total tokens | Seconds including shared seed |", "|---|---|---:|"])
    for mode, item in summary["aggregate"].items():
        usage = item["token_usage"] or {}
        lines.append(f"| {mode} | {usage.get('prompt_tokens')}/{usage.get('completion_tokens')}/{usage.get('total_tokens')} | {item['seconds']:.3f} |")
    lines.extend(["", f"Physical cost (shared seed counted once): {json.dumps(summary['physical_cost'], ensure_ascii=False)}", "",
                  "Known token subtotal is not the complete cost; missing measurements are null/None, never zero. Branch N/A is excluded from the branch mean. Split aggregates are in summary.json.", "",
                  f"Common evaluable variants: {json.dumps(summary['paired_comparable_variants'], ensure_ascii=False)}", "",
                  "Unequal F4 denominators can reflect framework failures and must not be interpreted as feedback improvement."])
    lines.extend(["", "| Case | Split | Baseline status/line/branch | Feedback status/line/branch | Change |", "|---|---|---|---|---|"])
    for item in summary["cases"]:
        def label(mode):
            v = item["modes"][mode]
            return f"{v['status']} / {v['line_percent']} / {v['branch_percent']}"
        lines.append(f"| {item['case_id']} | {item['split']} | {label('baseline')} | {label('feedback')} | {item['change']['description']} |")
    lines.extend(["", "| Variant | Mode | Outcome | Attributed failing test |", "|---|---|---|---|"])
    for item in summary["cases"]:
        for mode in MODES:
            for variant in item["variants"][mode]:
                names = ", ".join(failure["nodeid"].split("::")[-1] for failure in variant["attributed_failures"])
                lines.append(f"| {variant['variant_id']} | {mode} | {variant['status']} | {names} |")
    (root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_experiment(output: Path, *, config, client=None, dataset_root=None, split="all", provenance="live", case_ids=None) -> Path:
    if split not in {"all", "development", "holdout"}:
        raise ValueError("unknown split")
    if provenance not in {"live", "offline_fixture"}:
        raise ValueError("unknown provenance")
    dataset = BenchmarkDataset() if dataset_root is None else BenchmarkDataset(dataset_root)
    client = client or DeepSeekClient(config, retry_policy=RetryPolicy(max_transient_retries=1, max_format_repairs=1), max_tokens=6144)
    cases = [case for case in dataset.manifest.cases if split == "all" or case.split == split]
    if case_ids is not None:
        requested = set(case_ids)
        if not requested or requested - {case.case_id for case in cases}:
            raise ValueError("case_ids must select nonempty known cases in the chosen split")
        cases = [case for case in cases if case.case_id in requested]
    root = (output / uuid4().hex).resolve()
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / "dataset_manifest.json", dataset.manifest.model_dump(mode="json"))
    frozen = {"schema_version": 1, "dataset_id": dataset.manifest.dataset_id, "case_ids": [case.case_id for case in cases],
        "split": split, "provenance": provenance, "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "prompt_version": PROMPT_VERSION,
        "software_sha256": {name: digest((Path(__file__).parent / name).read_bytes())
                            for name in ("prompts.py", "agent.py", "generation.py", "llm_client.py", "models.py", "experiment.py", "benchmark.py")},
        "adapter_config": client.safe_config if isinstance(client, DeepSeekClient) else {"adapter_type": type(client).__name__, "model": config.model},
        "budgets": {"baseline_rounds": 1, "feedback_rounds": 3, "execution_timeout_seconds": 30},
        "cost_policy": "One physical initial generation; both arms credit its attempts/usage/time for comparison. Feedback replay is not a new HTTP request.",
        "generation_inputs": "Only frozen reference source/specification and formal host observations; no private annotations, oracles or variants.",
    }
    write_json(root / "experiment.json", frozen)
    print(f"Experiment workspace: {root}", flush=True)
    for case in cases:
        directory = root / "cases" / case.case_id
        for name in ("input", "seed", "evaluation"):
            (directory / name).mkdir(parents=True, exist_ok=False)
        public = dataset.public_input(case.case_id)
        source_path, spec_path = directory / "input/subject.py", directory / "input/behavior.md"
        source_path.write_bytes(dataset.path(case.source).read_bytes())
        spec_path.write_bytes(dataset.path(case.specification).read_bytes())
        source = public.source.updated(source_path=source_path)
        context = build_generation_context(source, public.behavior_specification, OracleMode.SPECIFICATION)
        write_json(directory / "seed/context.json", context.model_dump(mode="json"))
        # Private evaluator data is written separately and never supplied to run_agent.
        (directory / "evaluation/annotations.json").write_bytes(dataset.path(case.annotations).read_bytes())
        print(f"{case.case_id}: generate shared first candidate", flush=True)
        started = perf_counter()
        try:
            seed = client.generate_tests(context)
        except LLMError as error:
            seed = error
            write_json(directory / "seed/error.json", error.safe_details())
            seed_cost = {"attempts": error.attempts, "usage": None, "seconds": perf_counter() - started}
        else:
            write_json(directory / "seed/llm_result.json", seed.model_dump(mode="json"))
            seed_cost = {"attempts": seed.attempts, "usage": seed.total_usage.model_dump(mode="json") if seed.total_usage else None,
                         "seconds": perf_counter() - started}
        write_json(directory / "seed/cost.json", seed_cost)
        for mode in MODES:
            wrapper = SharedSeedClient(client, seed, context)
            request = TaskInput(source_path=source_path, spec_path=spec_path, output_dir=directory / mode,
                                model=ModelInfo.from_config(config), max_rounds=1 if mode == "baseline" else 3,
                                execution_timeout_seconds=30)
            started = perf_counter()
            result = run_agent(request, client=wrapper, oracle_mode=OracleMode.SPECIFICATION)
            write_json(directory / mode / "cost.json", {"initial_candidate_is_replay": True,
                "shared_generation_seconds": seed_cost["seconds"], "controller_seconds": perf_counter() - started,
                "additional_calls": wrapper.additional_calls})
            print(f"{case.case_id}: {mode} {result.decision.status}, {result.state.current_round} rounds", flush=True)
            selected = _selected(result.state)
            valid = selected is not None and selected.execution.all_passed and result.final_test_file is not None
            paired = None
            if valid:
                paired_root = directory / mode / "paired_reference"
                (paired_root / "rounds/01").mkdir(parents=True, exist_ok=False)
                (paired_root / "subject.py").write_bytes(source_path.read_bytes())
                (paired_root / "rounds/01/test_subject.py").write_bytes(result.final_test_file.read_bytes())
                paired = run_tests_with_coverage(paired_root, timeout=30)
                write_json(paired_root / "execution.json", paired.execution.model_dump(mode="json", exclude_computed_fields=True))
            for variant in dataset.manifest.variants:
                if variant.case_id != case.case_id:
                    continue
                variant_root = directory / "variants" / mode / variant.variant_id
                variant_root.mkdir(parents=True, exist_ok=False)
                if not valid or not paired.execution.all_passed:
                    write_json(variant_root / "evaluation.json", {"evaluated": False, "reason": "generated tests did not pass the correct paired reference"})
                    continue
                (variant_root / "rounds/01").mkdir(parents=True)
                (variant_root / "subject.py").write_bytes(dataset.path(variant.source).read_bytes())
                (variant_root / "rounds/01/test_subject.py").write_bytes(result.final_test_file.read_bytes())
                observed = run_tests_with_coverage(variant_root, timeout=30)
                write_json(variant_root / "execution.json", observed.execution.model_dump(mode="json", exclude_computed_fields=True))
                write_json(variant_root / "evaluation.json", {"evaluated": True, "test_sha256": digest(result.final_test_file.read_bytes())})
        rebuild_partial = {"last_completed_case": case.case_id, "case_count_completed": cases.index(case) + 1}
        write_json(root / "progress.json", rebuild_partial)
    BenchmarkDataset(dataset.root)
    rebuild(root)
    return root


def archive(root: Path, destination: Path) -> dict:
    """Copy reviewable evidence without caches/databases; refuse overwrites."""
    import shutil
    root, destination = root.resolve(), destination.resolve()
    if root == destination or root in destination.parents:
        raise ValueError("archive destination must be outside the source run")
    if destination.exists():
        raise ValueError("archive destination already exists")
    rebuild(root)
    allowed = {".json", ".jsonl", ".py", ".md", ".csv", ".txt", ".xml", ".log", ".ini", ".cfg", ".toml"}
    records = {}
    destination.mkdir(parents=True)
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if (not path.is_file() or path.is_symlink() or path.suffix not in allowed
                or any(part in {"__pycache__", ".pytest_cache"} for part in relative.parts)):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        records[relative.as_posix()] = {"sha256": digest(target.read_bytes()), "bytes": target.stat().st_size}
    # Rebuild must work with copied files and without following original workspace paths.
    rebuild(destination)
    index = {"stage": "F3/F4", "files": records, "file_count": len(records),
             "total_bytes": sum(item["bytes"] for item in records.values()),
             "excluded": "credentials, caches, compiled Python and coverage databases; original paths in raw observations are retained as evidence"}
    write_json(destination / "artifact_index.json", index)
    return index


def recheck_framework_errors(root: Path) -> dict:
    """One local retry of framework errors only; retain the original execution.

    No generation/client call, no source/test changes, no retry of behavior failures.
    A paired correct reference must pass again before each mutant retry.
    """
    root = root.resolve()
    before = rebuild(root)
    observations = []
    for case in before["cases"]:
        for mode in MODES:
            directory = root / "cases" / case["case_id"]
            for variant in case["variants"][mode]:
                path = directory / "variants" / mode / variant["variant_id"]
                execution_file = path / "execution.json"
                if not execution_file.exists() or (path / "framework_recheck.json").exists():
                    continue
                initial = ExecutionResult.model_validate_json(execution_file.read_text(encoding="utf-8"))
                if initial.kind not in {"internal_error", "launch_error", "result_error", "timeout"}:
                    continue
                paired_root = directory / mode / "paired_reference"
                original_tests = (path / "rounds/01/test_subject.py").read_bytes()
                original_source = (path / "subject.py").read_bytes()
                if original_tests != (paired_root / "rounds/01/test_subject.py").read_bytes():
                    raise ValueError("recheck requires the same paired reference tests")
                reference = run_tests_with_coverage(paired_root, timeout=30)
                record = {"case_id": case["case_id"], "mode": mode, "variant_id": variant["variant_id"],
                          "initial_kind": initial.kind, "reference_recheck_kind": reference.execution.kind}
                if reference.execution.all_passed:
                    observed = run_tests_with_coverage(path, timeout=30)
                    if ((path / "subject.py").read_bytes() != original_source
                            or (path / "rounds/01/test_subject.py").read_bytes() != original_tests):
                        raise ValueError("recheck changed source or tests")
                    (path / "initial_execution.json").write_bytes(execution_file.read_bytes())
                    write_json(execution_file, observed.execution.model_dump(mode="json", exclude_computed_fields=True))
                    record["rechecked_kind"] = observed.execution.kind
                write_json(path / "framework_recheck.json", record)
                observations.append(record)
    write_json(root / "framework_rechecks.json", {"network_calls": 0, "max_retries_per_framework_error": 1,
               "policy": "Only framework errors; same frozen source/tests, paired correct reference rechecked first; original observations retained",
               "observations": observations})
    return rebuild(root)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)) and not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="F3/F4 paired model experiment and offline summary rebuild")
    sub = parser.add_subparsers(dest="command", required=True)
    live = sub.add_parser("run")
    live.add_argument("--live", action="store_true", required=True, help="send frozen F2 reference source/specs to configured provider; incurs API usage")
    live.add_argument("--output", type=Path, default=Path("outputs/f3_f4"))
    live.add_argument("--split", choices=("all", "development", "holdout"), default="all")
    saved = sub.add_parser("rebuild")
    saved.add_argument("--run-dir", type=Path, required=True)
    copied = sub.add_parser("archive")
    copied.add_argument("--run-dir", type=Path, required=True)
    copied.add_argument("--output", type=Path, required=True)
    checked = sub.add_parser("recheck-framework")
    checked.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        root = run_experiment(args.output, config=load_config(), split=args.split)
        print(f"Saved summary: {root / 'summary.md'}")
    elif args.command == "rebuild":
        summary = rebuild(args.run_dir)
        print(json.dumps(summary["aggregate"], ensure_ascii=False, indent=2))
    elif args.command == "archive":
        index = archive(args.run_dir, args.output)
        print(f"Archived {index['file_count']} evidence files ({index['total_bytes']} bytes)")
    else:
        summary = recheck_framework_errors(args.run_dir)
        print(json.dumps(summary["aggregate"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
