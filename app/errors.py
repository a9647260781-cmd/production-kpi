from typing import Any


class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors or []

