from __future__ import annotations


class AlphaWorkflowError(Exception):
    pass


class AlphaWorkflowNotFoundError(AlphaWorkflowError):
    pass


class AlphaWorkflowValidationError(AlphaWorkflowError):
    pass


class AlphaWorkflowDependencyError(AlphaWorkflowError):
    pass
