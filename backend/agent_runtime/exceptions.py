from __future__ import annotations


class AgentRuntimeError(RuntimeError):
    """Base runtime error."""


class CapabilityNotFoundError(AgentRuntimeError):
    """Capability not found."""


class ExecutionNotFoundError(AgentRuntimeError):
    """Execution not found."""


class PermissionDeniedError(AgentRuntimeError):
    """Permission denied."""


class ApprovalRequiredError(AgentRuntimeError):
    """Execution requires approval."""


class ExecutorUnavailableError(AgentRuntimeError):
    """Executor unavailable."""


class InputValidationError(AgentRuntimeError):
    """Input validation failed."""

