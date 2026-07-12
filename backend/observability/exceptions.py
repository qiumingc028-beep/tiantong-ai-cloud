from __future__ import annotations


class ObservabilityError(RuntimeError):
    pass


class ObservabilityPermissionError(ObservabilityError):
    pass


class ObservabilityNotFoundError(ObservabilityError):
    pass

