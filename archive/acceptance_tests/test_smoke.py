"""Offline checks for A3: never spend API tokens in the normal test suite."""

import json

import httpx
import pytest

from testgen_agent.config import load_config
from testgen_agent.smoke import _test_environment, verify_llm


def probe_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return load_config(environ={"LLM_MODEL": "probe-model", "DEEPSEEK_API_KEY": "probe-secret"})


def test_minimal_llm_request_and_actual_usage(tmp_path, monkeypatch):
    config = probe_config(tmp_path, monkeypatch)
    requests = []

    def handle(request):
        requests.append(request)
        body = json.loads(request.content)
        assert body["model"] == "probe-model" and body["max_tokens"] == 16
        assert body["thinking"] == {"type": "disabled"}
        return httpx.Response(200, json={
            "model": "probe-model", "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9},
        })

    result = verify_llm(config, transport=httpx.MockTransport(handle))
    assert result["status"] == "passed"
    assert result["usage"]["total_tokens"] == 9
    assert len(requests) == result["attempts"] == 1


@pytest.mark.parametrize("status,body", [
    (401, {"error": "probe-secret"}), (402, {"error": "probe-secret"}),
    (429, {"error": "probe-secret"}), (200, {"choices": []}),
    (200, {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}),
    (200, {"choices": [{"message": {"content": "probe-secret"}, "finish_reason": "stop"}]}),
    (200, {"choices": [{"message": {"content": "OK"}, "finish_reason": "length"}]}),
])
def test_invalid_response_never_passes_or_discloses_body(tmp_path, monkeypatch, status, body):
    config = probe_config(tmp_path, monkeypatch)
    result = verify_llm(config, transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body)))
    assert result["status"] == "failed"
    assert "probe-secret" not in json.dumps(result)


def test_test_subprocess_environment_excludes_credentials(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "probe-secret")
    monkeypatch.setenv("CUSTOM_KEY", "probe-secret")
    monkeypatch.setenv("LLM_MODEL", "probe-model")
    environment = _test_environment()
    assert all(key not in environment for key in ("DEEPSEEK_API_KEY", "CUSTOM_KEY", "LLM_MODEL"))
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
