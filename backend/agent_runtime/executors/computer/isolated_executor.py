from __future__ import annotations

from .mock_executor import MockComputerExecutor


class IsolatedComputerExecutor(MockComputerExecutor):
    def get_metadata(self):
        metadata = super().get_metadata()
        metadata["name"] = "IsolatedComputerExecutor"
        metadata["provider"] = "isolated-test"
        return metadata
