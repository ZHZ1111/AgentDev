"""E1/E2 controller: tool observations -> attributed failure -> explicit action.

Initial execution is implemented here. Automatic revision execution, detailed
historical memory remain E3 responsibilities.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from pydantic import Field

from .generation import (
    CandidateValidationError, GenerationClient, InitialCandidateArtifacts,
    generate_initial_candidate, validate_generated_tests,
)
from .llm_client import GenerationContext
from .failure_analysis import classify_failures, repeated_without_progress
from .models import (
    AgentAction, AgentState, CandidateRound, ContractModel, ExecutionKind,
    Issue, OracleMode, SourceInfo, StopReason, TaskInput, TaskStatus, Text,
)
from .prompts import build_feedback_context, build_generation_context
from .tools import analyze_source, run_tests_with_coverage
from .tools.coverage_mapper import build_coverage_source_hints
from .tools.coverage_runner import CoverageRunResult


class ActionDecision(ContractModel):
    action: AgentAction
    reason: Text
    stop_reason: StopReason | None = None
    feedback: dict[str, Any] = Field(default_factory=dict)
    issues: tuple[Issue, ...] = ()
    status: TaskStatus | None = None


@dataclass(frozen=True)
class AgentTools:
    """Replaceable host interfaces; model output cannot select shell commands."""

    analyze: Callable[[Path], SourceInfo] = analyze_source
    generate: Callable[..., InitialCandidateArtifacts] = generate_initial_candidate
    execute: Callable[..., CoverageRunResult] = run_tests_with_coverage


def _feedback(state: AgentState, candidate: CandidateRound) -> dict[str, Any]:
    source = state.source_info
    if source is None:
        raise ValueError("decisions require analyzed source")
    hints = (build_coverage_source_hints(source.source_code, candidate.coverage)
             if candidate.coverage is not None else None)
    affected = set()
    if hints is not None:
        affected.update(item["function"] for item in hints["missing_lines"])
        for arc in hints["missing_branches"]:
            affected.update((arc["start_location"]["function"], arc["end_location"]["function"]))
    affected.discard(None)
    chain = set(affected)
    while True:
        callers = {edge.caller for edge in source.direct_calls if edge.callee in chain}
        if callers.issubset(chain):
            break
        chain.update(callers)
    plan = candidate.generated.plan if candidate.generated is not None else None
    return {
        "coverage_source_hints": hints,
        "affected_functions": sorted(affected),
        "caller_chain_functions": sorted(chain),
        "direct_call_evidence": [edge.model_dump(mode="json") for edge in source.direct_calls
                                 if edge.caller in chain and edge.callee in chain],
        "prior_strategy": [item.model_dump(mode="json") for item in plan.strategy] if plan else [],
        "test_selection_instruction": (
            "结合缺失位置、真实调用链和已有策略，判断补充单元边界或入口协作行为，"
            "说明新增行为及预期依据；不要机械地为每条调用边添加测试。"
        ),
    }


def choose_action(state: AgentState) -> ActionDecision:
    """Deterministic gates around the LLM's validated relationship/test strategy."""
    if state.stop_reason is not None:
        status = (TaskStatus.NEEDS_REVIEW if state.next_action == AgentAction.REQUEST_REVIEW or any(issue.requires_review for issue in state.issues) else
                  TaskStatus.COMPLETED if state.stop_reason == StopReason.COVERAGE_TARGET_MET else
                  TaskStatus.PARTIAL if state.best_available_round is not None else TaskStatus.FAILED)
        return ActionDecision(action=state.next_action, reason="任务已停止。", stop_reason=state.stop_reason,
                              issues=state.issues, status=status)
    if state.source_info is None:
        return ActionDecision(action=AgentAction.ANALYZE_SOURCE, reason="先提取源码及调用证据。")
    if not state.history:
        return ActionDecision(action=AgentAction.GENERATE_TESTS, reason="依据源码事实自主规划关系和测试策略。")
    candidate = state.history[-1]
    feedback = _feedback(state, candidate)
    issues = list(classify_failures(state, candidate))

    def decision(action: AgentAction, reason: str, stop: StopReason | None = None) -> ActionDecision:
        status = (TaskStatus.NEEDS_REVIEW if action == AgentAction.REQUEST_REVIEW or any(issue.requires_review for issue in issues) else
                  TaskStatus.COMPLETED if stop == StopReason.COVERAGE_TARGET_MET else
                  (TaskStatus.PARTIAL if any(item.available for item in state.history) else TaskStatus.FAILED)
                  if stop is not None else None)
        return ActionDecision(action=action, reason=reason, stop_reason=stop, feedback=feedback,
                              issues=tuple(issues), status=status)

    def revise(action: AgentAction, reason: str) -> ActionDecision:
        if repeated_without_progress(state):
            return decision(AgentAction.FINISH, reason + " 相同候选及结果重复，没有进展。", StopReason.NO_PROGRESS)
        if state.current_round >= state.request.max_rounds:
            return decision(AgentAction.FINISH, reason + " 候选轮次预算已耗尽。", StopReason.ROUND_LIMIT_REACHED)
        return decision(action, reason)

    generated = candidate.generated
    if generated is None:
        return decision(AgentAction.FINISH, "未取得结构化候选。", StopReason.UNRECOVERABLE_ERROR)
    if generated.questions:
        feedback["questions"] = list(generated.questions)
        issues.append(Issue(kind="ambiguous_specification", summary="候选包含需确认的规格疑问。",
                            evidence=generated.questions, round_number=candidate.number))
        return decision(AgentAction.REQUEST_REVIEW, "候选包含需确认的预期或规格疑问。", StopReason.AMBIGUOUS_SPECIFICATION)
    if candidate.validation_error:
        feedback["validation_error"] = candidate.validation_error
        if candidate.validation_error.startswith("external_dependency"):
            issues.append(Issue(kind="environment_error", summary="生成测试依赖初版不支持的外部模块，不自动安装。",
                                evidence=(candidate.validation_error,), round_number=candidate.number))
            return decision(AgentAction.FINISH, "候选包含不支持的外部依赖。", StopReason.UNRECOVERABLE_ERROR)
        issues.append(Issue(kind="generation_error", summary="生成测试未通过宿主校验。",
                            evidence=(candidate.validation_error,), round_number=candidate.number))
        return revise(AgentAction.REPAIR_GENERATED_TEST, "候选校验失败，修复生成测试后才能执行。")
    if generated.code is None or candidate.test_path is None:
        return decision(AgentAction.FINISH, "没有可执行测试文件。", StopReason.UNRECOVERABLE_ERROR)
    try:
        validate_generated_tests(generated, state.source_info)
    except CandidateValidationError as error:
        feedback["validation_error"] = error.summary
        return revise(AgentAction.REPAIR_GENERATED_TEST, "场景映射或有效断言未通过宿主校验。")
    if candidate.execution is None:
        return decision(AgentAction.RUN_TESTS, "执行已校验候选以取得真实结果。")
    execution = candidate.execution
    if execution.kind == ExecutionKind.TIMEOUT:
        return decision(AgentAction.FINISH, "测试执行超时，停止自动生成。", StopReason.EXECUTION_TIMEOUT)
    if any(issue.kind == "environment_error" for issue in issues):
        return decision(AgentAction.FINISH, "环境缺少依赖，报告不支持或环境问题；不安装模型提出的依赖。", StopReason.UNRECOVERABLE_ERROR)
    if any(issue.kind == "suspected_source_defect" for issue in issues):
        return decision(AgentAction.REQUEST_REVIEW, "失败断言有明确规格表格支持，报告疑似源码缺陷并保留用例。", StopReason.SUSPECTED_SOURCE_DEFECT)
    if any(issue.requires_review for issue in issues):
        return decision(AgentAction.REQUEST_REVIEW, "真实失败的预期或责任依据不足，保留测试并请求人工确认。", StopReason.AMBIGUOUS_SPECIFICATION)
    if repeated_without_progress(state) and not (execution.all_passed and candidate.coverage is not None and candidate.coverage.meets_target):
        return decision(AgentAction.FINISH, "相同候选及实测结果重复，没有进展。", StopReason.NO_PROGRESS)
    if issues and all(issue.kind == "generation_error" for issue in issues):
        return revise(AgentAction.REPAIR_GENERATED_TEST, "结构化失败位置指向生成测试的名称、语法或导入错误。")
    if execution.kind == ExecutionKind.COLLECTION_ERROR:
        issues.append(Issue(kind="ambiguous_specification", summary="收集失败但缺少可归因的结构化异常，不能直接假定生成测试有误。",
                            round_number=candidate.number))
        return decision(AgentAction.REQUEST_REVIEW, "收集失败的责任无法确认，需要人工检查。", StopReason.AMBIGUOUS_SPECIFICATION)
    if execution.kind == ExecutionKind.NO_TESTS:
        return revise(AgentAction.REPAIR_GENERATED_TEST, "未收集到测试，需要检查生成测试。")
    if not execution.all_passed:
        return decision(AgentAction.FINISH, "执行异常或存在未通过/跳过项，不能宣称完成。", StopReason.UNRECOVERABLE_ERROR)
    required = {item.relationship_id for item in generated.plan.strategy
                if item.subject_kind == "relationship" and item.decision == "collaboration_test"}
    verified = {relation for scenario in generated.plan.scenarios
                if scenario.test_kind == "collaboration" for relation in scenario.relationship_ids}
    missing = required - verified
    if missing:
        feedback["unverified_relationship_ids"] = sorted(missing)
        return revise(AgentAction.ADD_MISSING_CASES, "关键协作策略缺少已映射并断言验证的场景，覆盖率达标也不能完成。")
    if candidate.coverage is None or candidate.coverage.status != "available":
        return decision(AgentAction.FINISH, "覆盖结果不可用，测试通过但覆盖目标未验收。", StopReason.UNRECOVERABLE_ERROR)
    if not candidate.coverage.meets_target:
        return revise(AgentAction.ADD_MISSING_CASES, "测试通过但覆盖目标未达到；结合缺失函数与调用链选择补充场景。")
    return decision(AgentAction.FINISH, "真实测试全通过、覆盖目标达到，已选协作场景通过宿主断言校验。", StopReason.COVERAGE_TARGET_MET)


def apply_decision(state: AgentState, decision: ActionDecision) -> AgentState:
    data = state.model_dump(round_trip=True)
    data.update(next_action=decision.action, stop_reason=decision.stop_reason)
    data["issues"] = (*state.issues, *(issue for issue in decision.issues if issue not in state.issues))
    return AgentState.model_validate(data)


def build_action_context(state: AgentState) -> GenerationContext:
    """Prepare one generation action, without calling the model."""
    decision = choose_action(state)
    if decision.action not in {AgentAction.GENERATE_TESTS, AgentAction.REPAIR_GENERATED_TEST, AgentAction.ADD_MISSING_CASES}:
        raise ValueError("current decision does not permit model generation")
    if not state.history or state.history[-1].execution is None:
        context = build_generation_context(state.source_info, state.behavior_specification, state.oracle_mode)
        previous = state.history[-1].generated if state.history else None
        extra = {"previous_generated_tests": previous.model_dump(mode="json") if previous else None}
    else:
        context = build_feedback_context(
            state.source_info, state.behavior_specification, state.history[-1],
            requested_round=state.current_round + 1, max_rounds=state.request.max_rounds,
        )
        extra = {}
    payload = {"controller_decision": decision.model_dump(mode="json"), **extra}
    return GenerationContext(
        system_instruction=context.system_instruction,
        user_prompt=context.user_prompt + "\n<CONTROLLER_FEEDBACK_DATA>\n"
        + json.dumps(payload, ensure_ascii=False) + "\n</CONTROLLER_FEEDBACK_DATA>",
    )


@dataclass(frozen=True)
class ControllerResult:
    state: AgentState
    decision: ActionDecision
    steps: tuple[ActionDecision, ...]
    artifacts: InitialCandidateArtifacts


def run_initial_step(
    request: TaskInput, *, client: GenerationClient, oracle_mode: OracleMode,
    behavior_specification: str | None = None, tools: AgentTools | None = None,
) -> ControllerResult:
    """Analyze -> generate -> validate -> optionally execute -> choose action.

    output_dir must be a new workspace. Typed tool failures propagate; no retry
    loop or automatic revision is hidden here. E3 will consume this decision.
    """
    tools = tools or AgentTools()
    if behavior_specification is None and request.spec_path is not None:
        behavior_specification = request.spec_path.read_text(encoding="utf-8-sig")
    state = AgentState(schema_version="1.1", run_id=request.output_dir.name, request=request,
                       oracle_mode=oracle_mode, behavior_specification=behavior_specification)
    steps = [choose_action(state)]
    source = tools.analyze(request.source_path)
    data = state.model_dump(round_trip=True)
    data["source_info"] = source
    state = AgentState.model_validate(data)
    steps.append(choose_action(state))
    artifacts = tools.generate(source=source, behavior_specification=behavior_specification,
                               oracle_mode=oracle_mode, workspace=request.output_dir, client=client)
    data = state.model_dump(round_trip=True)
    data.update(current_round=1, history=(artifacts.candidate,), api_calls=artifacts.llm_result.attempts,
                token_usage=artifacts.llm_result.total_usage)
    state = AgentState.model_validate(data)
    decision = choose_action(state)
    if decision.action == AgentAction.RUN_TESTS:
        steps.append(decision)
        run = tools.execute(artifacts.workspace, timeout=request.execution_timeout_seconds)
        candidate_data = artifacts.candidate.model_dump(round_trip=True)
        candidate_data.update(execution=run.execution, coverage=run.coverage)
        candidate = CandidateRound.model_validate(candidate_data)
        data = state.model_dump(round_trip=True)
        data.update(history=(candidate,), best_available_round=1 if candidate.available else None)
        state = AgentState.model_validate(data)
        decision = choose_action(state)
    state = apply_decision(state, decision)
    return ControllerResult(state=state, decision=decision, steps=tuple((*steps, decision)), artifacts=artifacts)
