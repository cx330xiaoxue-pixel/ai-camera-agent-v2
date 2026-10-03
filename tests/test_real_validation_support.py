"""Local tests of real-test isolation; these never import the SDK or use keys."""

from types import SimpleNamespace

import pytest


def test_recording_boundary_preserves_response_without_storing_secrets():
    from real_llm_support import RecordingClient
    response = object()
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return response
    recording = RecordingClient(SimpleNamespace(responses=SimpleNamespace(create=create)))
    result = recording.responses.create(model="test-model", tools=[{"name": "hold"}],
                                        api_key="test-secret", extra_headers={"Authorization": "test-secret"},
                                        input="not recorded", store=False)
    assert result is response and len(calls) == 1
    assert recording.requests == [{"model": "test-model", "tools": [{"name": "hold"}], "store": False}]
    assert "test-secret" not in repr(recording.requests)


def test_missing_configuration_skips_before_sdk_or_network(monkeypatch):
    import real_llm_support
    from real_llm_support import real_client
    # Isolate this unit test even when the user later supplies a real local .env.
    monkeypatch.setattr(real_llm_support, "load_local_config", lambda: {})
    monkeypatch.setenv("RUN_AGENT_REAL_LLM_VALIDATION", "1")
    monkeypatch.delenv("AGENT_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(pytest.skip.Exception, match="model and API key"):
        with real_client("RUN_AGENT_DIRECTOR_SMOKE"):
            pytest.fail("Unconfigured client must not be constructed")


def test_default_tests_cannot_opt_into_provider_implicitly(monkeypatch):
    from real_llm_support import real_client
    monkeypatch.delenv("RUN_AGENT_REAL_LLM_VALIDATION", raising=False)
    monkeypatch.delenv("RUN_AGENT_OPENAI_SMOKE", raising=False)
    with pytest.raises(pytest.skip.Exception, match="opt-in"):
        with real_client("RUN_AGENT_OPENAI_SMOKE"):
            pytest.fail("An explicit integration opt-in is required")


def test_local_config_is_explicit_and_does_not_mutate_process(monkeypatch, tmp_path):
    from real_llm_support import load_local_config
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "AGENT_OPENAI_MODEL"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".env"
    path.write_text('OPENAI_API_KEY="fixture-only-value"\nOPENAI_BASE_URL=https://api.deepseek.com\nAGENT_OPENAI_MODEL=deepseek-flash\nUNRELATED=ignored\n', encoding="utf-8")
    config = load_local_config(path)
    assert config["AGENT_OPENAI_MODEL"] == "deepseek-flash"
    assert config["OPENAI_API_KEY"] == "fixture-only-value" and "UNRELATED" not in config
    import os
    assert "OPENAI_API_KEY" not in os.environ


def test_process_configuration_takes_precedence_over_file(monkeypatch, tmp_path):
    from real_llm_support import load_local_config
    path = tmp_path / ".env"
    path.write_text("AGENT_OPENAI_MODEL=file-model\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_OPENAI_MODEL", "process-model")
    assert load_local_config(path)["AGENT_OPENAI_MODEL"] == "process-model"


def test_integration_failure_does_not_expose_provider_exception_chain(monkeypatch):
    import sys
    import real_llm_support
    from agent_system.errors import AgentError

    class ClientStub:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setenv("RUN_AGENT_REAL_LLM_VALIDATION", "1")
    monkeypatch.setattr(real_llm_support, "load_local_config", lambda: {
        "OPENAI_API_KEY": "fixture-only", "AGENT_OPENAI_MODEL": "fixture-model"})
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kwargs: ClientStub()))
    with pytest.raises(pytest.fail.Exception) as caught:
        with real_llm_support.real_client("RUN_AGENT_DIRECTOR_SMOKE"):
            raise AgentError("LLM_ERROR", "Normalized provider failure") from RuntimeError("fixture-secret-echo")
    assert "LLM_ERROR" in str(caught.value)
    assert "fixture-secret-echo" not in str(caught.value)
    # Generator context managers may retain the thrown exception internally;
    # suppressing that chain is what prevents pytest from displaying it.
    assert caught.value.__suppress_context__ is True and caught.value.__cause__ is None
