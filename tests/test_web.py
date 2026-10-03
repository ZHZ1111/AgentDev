from __future__ import annotations

from pathlib import Path

import pytest

from testgen_agent.web import STATIC_ROOT, build_bootstrap, validate_run_payload


def test_web_assets_are_packaged() -> None:
    assert (STATIC_ROOT / "index.html").is_file()
    assert (STATIC_ROOT / "styles.css").is_file()
    assert (STATIC_ROOT / "app.js").is_file()


def test_bootstrap_reports_configuration_without_ui_scenarios(tmp_path: Path) -> None:
    result = build_bootstrap(tmp_path)

    assert result == {"config": {"ready": False, "model": None}}


def test_validate_run_payload_accepts_only_user_inputs() -> None:
    result = validate_run_payload({
        "source": "def answer():\n    return 42\n",
        "spec": "answer 返回 42",
    })

    assert result == {
        "source": "def answer():\n    return 42\n",
        "spec": "answer 返回 42",
    }


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"source": "", "spec": "x"}, "Python 源码"),
        ({"source": "x", "spec": ""}, "行为规格"),
    ],
)
def test_validate_run_payload_rejects_invalid_values(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_run_payload(payload)
