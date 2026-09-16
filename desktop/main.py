from __future__ import annotations

import sys

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton

from .ai_service import AnalysisService, DeepSeekClient, DeepSeekConfig
from .config import AppSettings
from .models import AnalysisReport, FeedNote
from .storage import LocalStore
from .ui.analysis import AnalysisMixin
from .ui.builder import UiBuilderMixin
from .ui.collection import CollectionMixin
from .ui.comments import CommentsMixin
from .ui.interaction import InteractionMixin
from .ui.qa import QaLibraryMixin
from .ui.settings_ops import SettingsMixin
from .ui.widgets import Worker
from .workspace import WorkspaceArchive
from .xhs_adapter import XhsCliAdapter


class MainWindow(
    UiBuilderMixin,
    InteractionMixin,
    CollectionMixin,
    CommentsMixin,
    QaLibraryMixin,
    AnalysisMixin,
    SettingsMixin,
    QMainWindow,
):
    """主窗口：仅负责状态装配与页面组合，具体职责由各 Mixin 承担。"""

    def __init__(
        self,
        *,
        store: LocalStore | None = None,
        settings: AppSettings | None = None,
        adapter: XhsCliAdapter | None = None,
        analysis_service: AnalysisService | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("XHS Insight")
        self.setMinimumSize(1180, 760)
        self.resize(1440, 900)
        self.store = store or LocalStore()
        self.settings = settings or AppSettings.load()
        self.workspace = WorkspaceArchive(self.settings.workspace_dir or None)
        if self.workspace.enabled:
            self.workspace.set_root(self.settings.workspace_dir)
        self.adapter = adapter or XhsCliAdapter(bridge_url=self.settings.bridge_url)
        self.analysis_service = analysis_service or self._make_analysis_service()
        self.thread_pool = QThreadPool.globalInstance()
        self.current_task_id: str | None = None
        self.current_notes: list[FeedNote] = []
        self.current_report: AnalysisReport | None = None
        self.creator_reference_note_ids: set[str] = set()
        self.active_workflow = "竞品分析"
        self._active_workers = 0
        self._worker_refs: set[Worker] = set()
        self.nav_buttons: dict[str, QPushButton] = {}
        self.page_indices: dict[str, int] = {}
        self._build_ui()
        self._load_tasks()
        self.refresh_qa_entries()
        QTimer.singleShot(100, self.refresh_connection_status)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._wait_for_workers)

    def _make_analysis_service(self) -> AnalysisService:
        return AnalysisService(
            DeepSeekClient(
                DeepSeekConfig(
                    base_url=self.settings.deepseek_base_url,
                    api_key=self.settings.deepseek_api_key,
                    model=self.settings.deepseek_model,
                )
            )
        )

    def _api_status_text(self) -> str:
        return f"DeepSeek API   {'已配置' if self.settings.deepseek_api_key else '未配置'}"


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("XHS Insight")
    app.setFont(QFont("Microsoft YaHei", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
