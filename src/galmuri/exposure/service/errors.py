"""Public errors never disclose implementation exception details."""


class ExposureError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def failure(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}
