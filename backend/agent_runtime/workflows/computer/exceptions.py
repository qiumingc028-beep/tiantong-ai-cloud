from __future__ import annotations


class WorkflowError(RuntimeError):
    pass


class WorkflowValidationError(WorkflowError):
    pass


class WorkflowApprovalError(WorkflowError):
    pass
