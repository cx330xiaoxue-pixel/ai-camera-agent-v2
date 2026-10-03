"""Small integration-only SDK boundary; no credential discovery in Agent core."""

from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_system.errors import AgentError

def load_local_config(path=None):
    """Integration-only, three known settings; no expansion, eval or global mutation."""
    path = Path(path) if path is not None else Path(__file__).resolve().parents[1] / ".env"
    names = {"OPENAI_API_KEY", "OPENAI_BASE_URL", "AGENT_OPENAI_MODEL"}
    config = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key in names:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                config[key] = value
    for key in names:
        if os.getenv(key):
            config[key] = os.getenv(key)
    return config


class RecordingClient:
    """Record only validation metadata, never headers, credentials or input text."""

    def __init__(self, client):
        self.requests = []
        def create(**kwargs):
            self.requests.append(deepcopy({key: value for key, value in kwargs.items()
                                           if key in {"model", "tools", "text", "store"}}))
            return client.responses.create(**kwargs)
        self.responses = SimpleNamespace(create=create)


@contextmanager
def real_client(legacy_opt_in):
    if os.getenv("RUN_AGENT_REAL_LLM_VALIDATION") != "1" and os.getenv(legacy_opt_in) != "1":
        pytest.skip("BLOCKED_EXTERNAL: explicit integration opt-in required")
    config = load_local_config()
    model = config.get("AGENT_OPENAI_MODEL")
    key = config.get("OPENAI_API_KEY")
    if not model or not key:
        pytest.skip("BLOCKED_EXTERNAL: explicit model and API key required")
    openai = pytest.importorskip("openai", reason="BLOCKED_EXTERNAL: provider SDK is not installed")
    with openai.OpenAI(api_key=key, base_url=config.get("OPENAI_BASE_URL"), max_retries=0, timeout=30.0) as client:
        error_code = None
        try:
            yield RecordingClient(client), model
        except AgentError as error:
            error_code = error.code
        if error_code is not None:
            # Outside the exception handler: pytest must not render a raw SDK cause
            # that could echo credentials. Preserve the stable classification code.
            raise pytest.fail.Exception(
                f"Real validation failure: {error_code}; raw provider details omitted", pytrace=False,
            ) from None
