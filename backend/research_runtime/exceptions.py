class ResearchError(RuntimeError):
    pass


class ResearchConfigurationError(ResearchError):
    pass


class ResearchLimitExceeded(ResearchError):
    pass


class SearchProviderUnavailable(ResearchError):
    pass


class ResearchCancelled(ResearchError):
    pass
