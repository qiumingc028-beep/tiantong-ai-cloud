class ComputerExecutorError(RuntimeError):
    pass


class ComputerPolicyError(ComputerExecutorError):
    pass


class ComputerSessionError(ComputerExecutorError):
    pass
