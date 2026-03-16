"""
ui/screens/export_screen.py — Экран экспорта в DOCX

Интегрирует ExportWorker для генерации документов.
"""

import logging
from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QMessageBox
from PySide6.QtCore import Signal, Slot

from config import AppConfig, VALID_SPLIT_MODES
from core.database import DBManager
from features.export.ui import ExportWorker, ExportParams
from ui_shared.widgets import ModernCard, PrimaryButton, SectionLabel

logger = logging.getLogger(__name__)

class ExportScreen(QWidget):
    export_complete = Signal(list)  # List[str] — пути к файлам
    log_message = Signal(str)
    character_state = Signal(str)

    def __init__(self, cfg: AppConfig, db: DBManager, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.db = db
        self._parse_result = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        
        layout.addWidget(SectionLabel("📄 Экспорт в DOCX"))
        
        card = ModernCard("🎨 Режим разбивки", "📑")
        self.split_combo = QComboBox()
        for mode in VALID_SPLIT_MODES:
            self.split_combo.addItem(mode)
        card.add_widget(self.split_combo)
        layout.addWidget(card)
        
        self.export_btn = PrimaryButton("Экспортировать")
        self.export_btn.clicked.connect(self._start_export)
        layout.addWidget(self.export_btn)
        layout.addStretch()

    def set_parse_result(self, result):
        self._parse_result = result

    @Slot()
    def _start_export(self):
        if not self._parse_result:
            return
        self.log_message.emit("📝 Начинаем экспорт DOCX...")
        self.character_state.emit("working")
        self.export_btn.setEnabled(False)
        
        params = ExportParams(
            chat_id=self._parse_result.chat_id,
            chat_title=self._parse_result.chat_title,
            split_mode=self.split_combo.currentText(),
            period_label=self._parse_result.period_label
        )
        
        self._worker = ExportWorker(params, parent=self)
        self._worker.log_message.connect(self.log_message.emit)
        self._worker.export_complete.connect(self._on_export_complete)
        self._worker.error.connect(self._on_export_error)
        self._worker.character_state.connect(self.character_state.emit)
        self._worker.start()

    @Slot(list)
    def _on_export_complete(self, file_paths):
        self.log_message.emit(f"✅ Экспорт завершён: {len(file_paths)} файлов")
        self.character_state.emit("success")
        self.export_btn.setEnabled(True)
        self.export_complete.emit(file_paths)

    @Slot(str)
    def _on_export_error(self, error_msg):
        self.log_message.emit(f"❌ Ошибка экспорта: {error_msg}")
        self.character_state.emit("error")
        self.export_btn.setEnabled(True)
        QMessageBox.critical(self, "Ошибка", error_msg)
