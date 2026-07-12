from __future__ import annotations


class KnowledgeCenterError(RuntimeError):
    pass


class FeatureDisabledError(KnowledgeCenterError):
    pass


class KnowledgePermissionError(KnowledgeCenterError):
    pass


class KnowledgeNotFoundError(KnowledgeCenterError):
    pass


class KnowledgeConflictError(KnowledgeCenterError):
    pass


class KnowledgeValidationError(KnowledgeCenterError):
    pass
