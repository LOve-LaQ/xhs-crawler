from __future__ import annotations

from PySide6.QtWidgets import QDialog

from .settings_dialog import SettingsDialog


class SettingsMixin:
    """工作区设置与 Bridge 连接状态。"""

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.analysis_service = self._make_analysis_service()
            self.api_status_label.setText(self._api_status_text())
            self.show_status("设置已保存")

    def refresh_connection_status(self) -> None:
        self._run_worker(
            self.adapter.bridge_status,
            on_result=self._on_connection_status,
            on_error=lambda message: self._on_connection_status(
                {"server": False, "extension": False}
            ),
        )

    def _on_connection_status(self, status: dict[str, bool]) -> None:
        bridge = "在线" if status.get("server") else "未启动"
        extension = "扩展已连接" if status.get("extension") else "扩展未连接"
        self.bridge_status_label.setText(f"Chrome / Bridge   {bridge} · {extension}")
        self.api_status_label.setText(self._api_status_text())
