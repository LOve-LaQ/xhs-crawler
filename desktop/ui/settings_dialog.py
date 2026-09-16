from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import AppSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("工作区设置")
        self.setMinimumWidth(480)
        self.settings = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.base_url = QLineEdit(settings.deepseek_base_url)
        self.api_key = QLineEdit(settings.deepseek_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.model = QLineEdit(settings.deepseek_model)
        self.bridge_url = QLineEdit(settings.bridge_url)
        form.addRow("DeepSeek 地址", self.base_url)
        form.addRow("API Key", self.api_key)
        form.addRow("模型", self.model)
        form.addRow("Bridge 地址", self.bridge_url)
        layout.addLayout(form)
        hint = QLabel("API Key 仅保存在本机配置目录，不会写入分析内容。")
        hint.setObjectName("mutedLabel")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        self.settings.deepseek_base_url = self.base_url.text().strip()
        self.settings.deepseek_api_key = self.api_key.text().strip()
        self.settings.deepseek_model = self.model.text().strip() or "deepseek-chat"
        self.settings.bridge_url = self.bridge_url.text().strip() or "ws://localhost:9333"
        self.settings.save()
        super().accept()
