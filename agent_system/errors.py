"""Small, inspectable Agent boundary errors."""


class AgentError(ValueError):
    def __init__(self, code: str, reason: str, context: dict | None = None):
        self.code = code
        self.reason = reason
        self.context = context or {}
        super().__init__(f"{code}: {reason}")
