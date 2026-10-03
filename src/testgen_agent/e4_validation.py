"""Reproduce feedback and defect traces with offline responses and real tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from .agent import run_agent
from .llm_client import LLMCallRecord, LLMGenerationResult
from .models import (ExpectedBasis, GeneratedTests, ModelInfo, ScenarioInput, StrategyDecision,
                     TaskInput, TestCaseMapping, TestPlan, TestScenario, OracleMode)
from .tracing import TraceEvent


class OfflineSequence:
    """Hand-authored fixture responses; no network client or credentials."""

    def __init__(self, candidates):
        self.candidates = iter(candidates)
        self.requests = 0

    def generate_tests(self, context):
        self.requests += 1
        return LLMGenerationResult(generated=next(self.candidates), provider="deepseek",
            requested_model="offline-e4-fixture", response_model="offline-e4-fixture",
            attempts=1, format_repairs=0, latency_seconds=0,
            calls=(LLMCallRecord(purpose="generation", response_model="offline-e4-fixture"),))


def _candidate(function: str, cases: list[tuple[str, int, int]]) -> GeneratedTests:
    scenarios, mappings, tests = [], [], []
    for name, value, expected in cases:
        scenarios.append(TestScenario(scenario_id=name, target_function=function, category="boundary",
            inputs=ScenarioInput(args=(value,)), expected_behavior=f"returns {expected}",
            expected_basis=ExpectedBasis(kind="specification", detail="handwritten validation fixture specification"),
            involved_functions=(function,)))
        mappings.append(TestCaseMapping(test_function=f"test_{name}", scenario_ids=(name,)))
        tests.append(f"def test_{name}():\n    assert {function}({value}) == {expected}\n")
    return GeneratedTests(plan=TestPlan(schema_version="1.1", target_functions=(function,),
        oracle_mode="specification", entry_functions=(function,), scenarios=tuple(scenarios),
        strategy=(StrategyDecision(subject_kind="function", function_name=function,
                                   decision="unit_test", reason="independent pure function boundary"),)),
        code=f"from subject import {function}\n\n" + "\n".join(tests), mappings=tuple(mappings))


def validate(output: Path) -> dict:
    project = Path(__file__).resolve().parents[2]
    root = output / uuid4().hex
    positive, zero, negative = ("positive", 1, 1), ("zero", 0, 0), ("negative", -1, -1)
    cases = [
        ("feedback", project / "validation/e4/source.py", "Positive -> 1; zero -> 0; negative -> -1.",
         [_candidate("choose", rows) for rows in ([positive], [positive, zero], [positive, zero, negative])],
         "coverage_target_met", 3),
        ("defect", project / "examples/discount.py", (project / "examples/discount.md").read_text(encoding="utf-8"),
         [_candidate("calculate_discount", [("discount_boundary", 100, 90)])], "suspected_source_defect", 1),
    ]
    records = []
    for name, source, spec, candidates, expected_stop, rounds in cases:
        before = source.read_bytes()
        client = OfflineSequence(candidates)
        request = TaskInput(source_path=source, output_dir=root / name,
                           model=ModelInfo(model="offline-e4-fixture", base_url="https://example.invalid"))
        result = run_agent(request, client=client, oracle_mode=OracleMode.SPECIFICATION, behavior_specification=spec)
        events = [TraceEvent.model_validate_json(line) for line in result.trace_file.read_text(encoding="utf-8").splitlines()]
        actions = [event.action for event in events if event.phase == "decision"]
        checks = {
            "expected_stop": result.state.stop_reason == expected_stop,
            "expected_rounds": result.state.current_round == client.requests == rounds,
            "source_unchanged": source.read_bytes() == before,
            "terminal_event": events[-1].phase == "run_finished" and events[-1].result_summary["stop_reason"] == expected_stop,
            "consecutive_events": [item.sequence for item in events] == list(range(1, len(events) + 1)),
            "feedback_action": "add_missing_cases" in actions if name == "feedback" else "request_review" in actions,
            "raw_artifacts": all((request.output_dir / "rounds" / f"{item.number:02d}" / "test_subject.py").is_file()
                and bool(list((request.output_dir / "rounds" / f"{item.number:02d}" / "executions").glob("run-*/coverage.json")))
                for item in result.state.history),
        }
        records.append({"case": name, "run_id": result.state.run_id, "checks": checks,
                        "status": result.decision.status, "stop_reason": result.state.stop_reason,
                        "trace": str(result.trace_file.resolve()), "metadata": str(result.metadata_file.resolve()),
                        "summary": str(result.summary_file.resolve()), "events": len(events),
                        "offline_adapter_requests": client.requests, "real_network_requests": 0})
    report = {"schema_version": 1, "provenance": "handwritten offline responses with real local pytest/coverage",
              "e4_passed": all(all(case["checks"].values()) for case in records), "cases": records}
    (root / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/e4"))
    args = parser.parse_args(argv)
    report = validate(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["e4_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
