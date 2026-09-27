"""Reproducible B3 check: one real generation using the formal prompt builder."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
from uuid import uuid4

from .config import ConfigError, load_config
from .llm_client import DeepSeekClient, LLMError
from .models import OracleMode, validate_plan_against_source
from .prompts import (
    PROMPT_VERSION, TASK_DATA_END, TASK_DATA_START, build_generation_context,
)
from .tools import analyze_source


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)) and not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="B3：使用正式生成 Prompt 验证一次真实 DeepSeek 输出。")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, default=Path("outputs/b3"))
    args = parser.parse_args(argv)

    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    workspace = (args.output / run_id).resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    record: dict[str, object] = {
        "stage": "B3",
        "run_id": run_id,
        "tested_at_utc": started.isoformat(),
        "python": platform.python_version(),
        "prompt_version": PROMPT_VERSION,
    }

    try:
        project_root = Path(__file__).resolve().parents[2]
        source_path = project_root / "examples/relationships.py"
        specification = (project_root / "examples/relationships.md").read_text(encoding="utf-8")
        source = analyze_source(source_path).updated(
            source_path=Path("examples/relationships.py"),
        )
        context = build_generation_context(source, specification, OracleMode.SPECIFICATION)
        config = load_config(env_file=args.env_file)
        client = DeepSeekClient(config, max_tokens=4096)
        result = client.generate_tests(context)
        generated = result.generated
        validate_plan_against_source(generated.plan, source)
        code = generated.code or ""
        try:
            ast.parse(code)
            syntax_valid = bool(code)
        except SyntaxError:
            syntax_valid = False

        categories = {scenario.category for scenario in generated.plan.scenarios}
        forbidden_fragments = (
            "pytest.skip", "pytest.xfail", "@pytest.mark.skip", "@pytest.mark.xfail",
            "assert True", "except Exception", "except BaseException",
        )
        checks = {
            "schema_validated": True,
            "prompt_data_delimited": (
                context.user_prompt.startswith(TASK_DATA_START + "\n")
                and context.user_prompt.endswith("\n" + TASK_DATA_END)
            ),
            "requested_oracle_mode_preserved": generated.plan.oracle_mode == OracleMode.SPECIFICATION,
            "relationship_schema_11_used": generated.plan.schema_version == "1.1",
            "target_functions_preserved": set(generated.plan.target_functions) == {"calculate_total", "checkout"},
            "workflow_entry_selected": "checkout" in generated.plan.entry_functions,
            "confirmed_direct_relationship_preserved": any(
                relationship.kind == "direct_call"
                and relationship.confidence == "confirmed"
                and set(relationship.involved_functions) == {"checkout", "calculate_total"}
                for relationship in generated.plan.relationships
            ),
            "strategy_complete": len(generated.plan.strategy) == 3,
            "unit_and_collaboration_scenarios_present": (
                {scenario.test_kind for scenario in generated.plan.scenarios}
                == {"unit", "collaboration"}
            ),
            "normal_and_boundary_scenarios_present": {"normal", "boundary"}.issubset(categories),
            "all_scenarios_have_supported_basis": all(
                scenario.expected_basis.kind in {"specification", "docstring"}
                for scenario in generated.plan.scenarios
            ),
            "import_convention_followed": "from subject import" in code,
            "generated_code_is_python": syntax_valid,
            "no_forbidden_test_bypass": not any(fragment in code for fragment in forbidden_fragments),
            "tool_metrics_absent_from_generation": not any(
                name in type(generated).model_fields
                for name in ("execution", "coverage", "passed", "line_percent")
            ),
        }
        passed = all(checks.values())
        record.update({
            "status": "passed" if passed else "failed",
            "adapter_config": client.safe_config,
            "prompt": context.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "checks": checks,
        })
        exit_code = 0 if passed else 1
    except ConfigError as error:
        record.update({"status": "failed", "error": {"code": "configuration", "message": str(error)}})
        exit_code = 1
    except LLMError as error:
        record.update({"status": "failed", "error": error.safe_details()})
        exit_code = 1
    except ValueError:
        record.update({
            "status": "failed",
            "error": {
                "code": "relationship_validation",
                "message": "生成计划未通过源码函数关系与策略交叉校验。",
            },
        })
        exit_code = 1

    artifact = workspace / "validation.json"
    artifact.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"实测产物：{artifact}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
