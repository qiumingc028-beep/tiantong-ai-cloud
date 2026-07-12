from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MacObserverPermissionPolicy:
    screen_recording: bool = True
    accessibility: bool = False
    automation: bool = False
    file_access: bool = False
    clipboard_access: bool = False
    keychain_access: bool = False

    def minimal_permissions(self) -> list[str]:
        allowed = []
        if self.screen_recording:
            allowed.append("屏幕录制")
        if self.accessibility:
            allowed.append("辅助功能")
        if self.automation:
            allowed.append("自动化")
        if self.file_access:
            allowed.append("文件访问")
        return allowed

