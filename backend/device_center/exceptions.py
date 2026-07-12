class DeviceCenterError(RuntimeError):
    pass


class DeviceNotFoundError(DeviceCenterError):
    pass


class DevicePermissionError(DeviceCenterError):
    pass


class DeviceAuthenticationError(DeviceCenterError):
    pass


class DeviceReplayError(DeviceAuthenticationError):
    pass


class DeviceObservationError(DeviceCenterError):
    pass

