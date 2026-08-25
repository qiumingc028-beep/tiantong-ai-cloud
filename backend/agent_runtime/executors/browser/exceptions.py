from __future__ import annotations


class BrowserExecutorError(RuntimeError):
    def __init__(self, message: str, code: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class BrowserPolicyError(BrowserExecutorError):
    pass


class BrowserFetchError(BrowserExecutorError):
    def __init__(self, message: str, code: str, *, http_status: int | None = None, retryable: bool = False):
        super().__init__(message, code, retryable=retryable)
        self.http_status = http_status


class BrowserExtractionError(BrowserExecutorError):
    pass
