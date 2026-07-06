import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QBoxLayout,
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from version import APP_NAME, APP_VERSION


BREAKPOINT_WIDTH = 1100
PAGE_MARGIN_X = 24
PAGE_MARGIN_Y = 20
CARD_PADDING = 16
SPACING = 12
BUTTON_HEIGHT = 36


class MainWindow(QMainWindow):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self._layout_mode = ""
        self._rebuilding_layout = False
        self._welcome_prompt_pending = False
        self._status_hint_token = 0

        self.path_label = QLabel()
        self.status_badge = QLabel()
        self.status_hint = QLabel()
        self.rules_list = QListWidget()
        self.activity_list = QListWidget()
        self.activity_empty_widget = QWidget()
        self.activity_empty_label = QLabel("还没有整理记录")
        self.activity_empty_hint = QLabel("点击“立即扫描”，CleanDesk 会在这里显示整理结果。")
        self.detailed_log_lines: list[str] = []
        self.log_view = QTextEdit()
        self.start_button = QPushButton("开始")
        self.stop_button = QPushButton("停止")
        self.scan_button = QPushButton("立即扫描")
        self.undo_button = QPushButton("撤销上一次整理")
        self.suggestion_button = QPushButton("智能整理建议")

        self._build_window()
        self._bind_service()
        self._refresh_from_service()
        QTimer.singleShot(0, self.update_responsive_layout)

    def _build_window(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 800)
        self.setMinimumSize(820, 640)
        self._build_menu_bar()

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("scrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setCentralWidget(self.scroll_area)

        self.page_widget = QWidget()
        self.page_widget.setObjectName("root")
        self.page_widget.setMinimumWidth(0)
        self.page_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.scroll_area.setWidget(self.page_widget)

        self.root_layout = QVBoxLayout(self.page_widget)
        self.root_layout.setContentsMargins(PAGE_MARGIN_X, PAGE_MARGIN_Y, PAGE_MARGIN_X, PAGE_MARGIN_Y)
        self.root_layout.setSpacing(SPACING)

        self.header_widget = self._header_widget()
        self.content_container = QWidget()
        self.content_container.setMinimumWidth(0)
        self.content_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.content_layout = QBoxLayout(QBoxLayout.LeftToRight, self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(SPACING)

        self.left_column = QWidget()
        self.left_column.setMinimumWidth(0)
        self.left_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.left_layout = QVBoxLayout(self.left_column)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(SPACING)

        self.right_column = QWidget()
        self.right_column.setMinimumWidth(0)
        self.right_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.right_layout = QVBoxLayout(self.right_column)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(SPACING)

        self.folder_card = self._folder_card()
        self.rules_card = self._rules_card()
        self.status_card = self._status_card()
        self.actions_card = self._actions_card()
        self.log_card = self._logs_card()

        self.root_layout.addWidget(self.header_widget, 0)
        self.root_layout.addWidget(self.content_container, 0)
        self.root_layout.addWidget(self.log_card, 1)

        self._apply_style()
        self.update_responsive_layout(force=True)

    def _header_widget(self) -> QWidget:
        header = QWidget()
        header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(4)

        title = QLabel("CleanDesk")
        title.setObjectName("appTitle")

        subtitle = self._label("自动整理文件，让工作区保持清爽。", "caption", wrap=True)
        subtitle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        layout.addLayout(title_box, 1)
        return header

    def update_responsive_layout(self, force: bool = False) -> None:
        if self._rebuilding_layout:
            return

        width = self.width()
        mode = "desktop" if width >= BREAKPOINT_WIDTH else "single"
        if not force and mode == self._layout_mode:
            self._refresh_rule_item_sizes()
            return

        self._rebuilding_layout = True
        try:
            for widget in (
                self.left_column,
                self.right_column,
                self.folder_card,
                self.status_card,
                self.rules_card,
                self.actions_card,
                self.log_card,
            ):
                self._remove_widget_from_responsive_layouts(widget)

            if mode == "desktop":
                self.content_layout.setDirection(QBoxLayout.LeftToRight)
                self.root_layout.addWidget(self.log_card, 1)
                self.content_layout.addWidget(self.left_column)
                self.content_layout.addWidget(self.right_column)
                self.content_layout.setStretch(0, 1)
                self.content_layout.setStretch(1, 1)

                self.left_layout.addWidget(self.folder_card, 0)
                self.left_layout.addWidget(self.rules_card, 1)
                self.left_layout.setStretch(0, 0)
                self.left_layout.setStretch(1, 1)

                self.right_layout.addWidget(self.status_card, 0)
                self.right_layout.addWidget(self.actions_card, 1)
                self.right_layout.setStretch(0, 0)
                self.right_layout.setStretch(1, 1)

                self.rules_card.setMinimumHeight(0)
                self.actions_card.setMinimumHeight(0)
            else:
                self.content_layout.setDirection(QBoxLayout.TopToBottom)
                self.content_layout.addWidget(self.folder_card)
                self.content_layout.addWidget(self.status_card)
                self.content_layout.addWidget(self.rules_card)
                self.content_layout.addWidget(self.actions_card)
                self.content_layout.addWidget(self.log_card)
                for index in range(5):
                    self.content_layout.setStretch(index, 0)

                self.rules_card.setMinimumHeight(260)
                self.actions_card.setMinimumHeight(0)

            self._layout_mode = mode
            self._refresh_rule_item_sizes()
        finally:
            self._rebuilding_layout = False

    def rebuild_responsive_layout(self, force: bool = False) -> None:
        self.update_responsive_layout(force=force)

    def _remove_widget_from_responsive_layouts(self, widget: QWidget) -> None:
        for layout in (self.root_layout, self.content_layout, self.left_layout, self.right_layout):
            layout.removeWidget(widget)
        widget.setParent(None)

    def _folder_card(self) -> QFrame:
        card = self._card(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = self._card_layout(card)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(SPACING)

        self.path_label.setObjectName("pathLabel")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path_label.setFixedHeight(BUTTON_HEIGHT)
        self.path_label.setMinimumWidth(0)
        self.path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        change_button = self._button("更改", "secondaryButton")
        change_button.setFixedWidth(80)
        change_button.clicked.connect(self._choose_folder)

        path_row.addWidget(self.path_label, 1)
        path_row.addWidget(change_button, 0)

        layout.addWidget(self._label("监控文件夹", "cardTitle"))
        layout.addWidget(self._label("CleanDesk 会监听此位置的新文件。", "caption", wrap=True))
        layout.addLayout(path_row)
        return card

    def _rules_card(self) -> QFrame:
        card = self._card(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = self._card_layout(card)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(SPACING)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(4)
        title_box.addWidget(self._label("自动整理规则", "cardTitle"))
        title_box.addWidget(self._label("符合条件的文件会自动移动到对应文件夹。", "caption", wrap=True))
        title_box.addWidget(self._label("上方规则会优先匹配。", "caption", wrap=True))

        self._prepare_button(self.suggestion_button, "secondaryButton")
        self.suggestion_button.setFixedWidth(116)
        self.suggestion_button.clicked.connect(self._show_smart_suggestions)

        add_button = self._button("+ 新建整理规则", "secondaryButton")
        add_button.setFixedWidth(132)
        add_button.clicked.connect(self._add_rule)

        top.addLayout(title_box, 1)
        top.addWidget(self.suggestion_button, 0, Qt.AlignRight | Qt.AlignTop)
        top.addWidget(add_button, 0, Qt.AlignRight | Qt.AlignTop)

        self.rules_list.setObjectName("rulesList")
        self.rules_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.rules_list.setFocusPolicy(Qt.NoFocus)
        self.rules_list.setUniformItemSizes(False)
        self.rules_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rules_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.rules_list.setResizeMode(QListWidget.Adjust)
        self.rules_list.setWordWrap(True)
        self.rules_list.setMinimumHeight(180)
        self.rules_list.setMinimumWidth(0)
        self.rules_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout.addLayout(top)
        layout.addWidget(self.rules_list, 1)
        return card

    def _status_card(self) -> QFrame:
        card = self._card(QSizePolicy.Expanding, QSizePolicy.Preferred)
        card.setMinimumHeight(190)
        layout = self._card_layout(card)
        layout.setSpacing(10)

        self.status_badge.setObjectName("statusBadge")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setMinimumHeight(58)
        self.status_badge.setMinimumWidth(0)
        self.status_badge.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.status_hint.setObjectName("statusHint")
        self.status_hint.setAlignment(Qt.AlignCenter)
        self.status_hint.setWordWrap(True)
        self.status_hint.setMinimumHeight(24)
        self.status_hint.setMinimumWidth(0)
        self.status_hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        status_text_box = QVBoxLayout()
        status_text_box.setContentsMargins(0, 0, 0, 0)
        status_text_box.setSpacing(10)
        status_text_box.addWidget(self.status_badge)
        status_text_box.addWidget(self.status_hint)

        layout.addWidget(self._label("运行状态", "cardTitle"))
        layout.addWidget(self._label("当前监听服务状态", "caption", wrap=True))
        layout.addLayout(status_text_box)
        return card

    def _actions_card(self) -> QFrame:
        card = self._card(QSizePolicy.Expanding, QSizePolicy.Preferred)
        card.setMinimumHeight(210)
        layout = self._card_layout(card)
        layout.setSpacing(12)

        self._prepare_button(self.start_button, "primaryButton")
        self._prepare_button(self.stop_button, "dangerButton")
        self._prepare_button(self.scan_button, "secondaryButton")

        self.start_button.clicked.connect(self.service.start)
        self.stop_button.clicked.connect(self.service.stop)
        self.scan_button.clicked.connect(self.service.scan_now)

        button_box = QVBoxLayout()
        button_box.setContentsMargins(0, 0, 0, 0)
        button_box.setSpacing(10)
        button_box.addWidget(self.start_button)
        button_box.addWidget(self.stop_button)
        button_box.addWidget(self.scan_button)

        layout.addWidget(self._label("操作", "cardTitle"))
        layout.addWidget(self._label("启动监听、停止监听或手动扫描一次。", "caption", wrap=True))
        layout.addLayout(button_box)
        layout.addStretch(1)
        return card

    def _logs_card(self) -> QFrame:
        card = self._card(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card.setMinimumHeight(220)
        layout = self._card_layout(card)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(SPACING)
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(4)
        title_box.addWidget(self._label("最近活动", "cardTitle"))
        title_box.addWidget(self._label("这里会显示最近的整理结果。", "caption", wrap=True))

        details_button = self._button("查看详细日志", "secondaryButton")
        details_button.setFixedWidth(116)
        details_button.clicked.connect(self._show_detailed_log)

        self._prepare_button(self.undo_button, "secondaryButton")
        self.undo_button.setFixedWidth(132)
        self.undo_button.setEnabled(False)
        self.undo_button.setToolTip("暂无可撤销的整理记录。")
        self.undo_button.clicked.connect(self._confirm_undo_last_batch)

        top.addLayout(title_box, 1)
        top.addWidget(self.undo_button, 0, Qt.AlignRight | Qt.AlignTop)
        top.addWidget(details_button, 0, Qt.AlignRight | Qt.AlignTop)

        self.activity_list.setObjectName("activityList")
        self.activity_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.activity_list.setFocusPolicy(Qt.NoFocus)
        self.activity_list.setUniformItemSizes(False)
        self.activity_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.activity_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.activity_list.setMinimumHeight(150)
        self.activity_list.setMinimumWidth(0)
        self.activity_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.activity_empty_widget.setObjectName("emptyStateBox")
        self.activity_empty_widget.setMinimumHeight(84)
        self.activity_empty_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        empty_layout = QVBoxLayout(self.activity_empty_widget)
        empty_layout.setContentsMargins(12, 18, 12, 18)
        empty_layout.setSpacing(6)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.activity_empty_label)
        empty_layout.addWidget(self.activity_empty_hint)
        empty_layout.addStretch(1)

        self.activity_empty_label.setObjectName("emptyStateTitle")
        self.activity_empty_label.setAlignment(Qt.AlignCenter)
        self.activity_empty_label.setWordWrap(True)
        self.activity_empty_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.activity_empty_hint.setObjectName("emptyStateHint")
        self.activity_empty_hint.setAlignment(Qt.AlignCenter)
        self.activity_empty_hint.setWordWrap(True)
        self.activity_empty_hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        activity_area = QWidget()
        activity_area.setMinimumWidth(0)
        activity_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        activity_layout = QVBoxLayout(activity_area)
        activity_layout.setContentsMargins(0, 0, 0, 0)
        activity_layout.setSpacing(0)
        activity_layout.addWidget(self.activity_empty_widget, 0)
        activity_layout.addWidget(self.activity_list, 1)
        self._refresh_activity_empty_state()

        layout.addLayout(top)
        layout.addWidget(activity_area, 1)
        return card

    def _bind_service(self) -> None:
        self.service.folder_changed.connect(self._set_folder)
        self.service.status_changed.connect(self._set_status)
        self.service.rules_changed.connect(self._set_rules)
        self.service.log_emitted.connect(self._append_log)
        if hasattr(self.service, "activity_emitted"):
            self.service.activity_emitted.connect(self._add_activity)
        if hasattr(self.service, "undo_state_changed"):
            self.service.undo_state_changed.connect(self._set_undo_available)
        if hasattr(self.service, "undo_completed"):
            self.service.undo_completed.connect(self._show_undo_completed_hint)
        if hasattr(self.service, "conflict_requested"):
            self.service.conflict_requested.connect(self._handle_name_conflict_request)
        if hasattr(self.service, "conflict_hint_requested"):
            self.service.conflict_hint_requested.connect(self._show_temporary_status_hint)
        if hasattr(self.service, "conflict_choice_handler"):
            self.service.conflict_choice_handler = self._choose_name_conflict_action
        self.service.error_occurred.connect(self._show_error)

    def _build_menu_bar(self) -> None:
        help_menu = self.menuBar().addMenu("帮助")
        about_action = help_menu.addAction(f"关于 {APP_NAME}")
        about_action.triggered.connect(self._show_about)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"关于 {APP_NAME}",
            f"{APP_NAME}\n\n"
            f"Version {APP_VERSION}\n\n"
            "本地文件自动整理工具\n\n"
            "开发者：Zmx\n\n"
            "当前版本为 Beta，建议先使用测试文件夹。",
        )

    def _refresh_from_service(self) -> None:
        self._set_folder(self.service.monitored_folder)
        self._set_status(self.service.is_running)
        self._set_rules(self.service.rules)
        self._set_undo_available(bool(getattr(self.service, "undo_stack", [])))
        for line in self.service.recent_logs:
            self._append_log(line)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择监控文件夹", self.service.monitored_folder)
        if folder:
            self.service.set_monitored_folder(folder)

    def _add_rule(self) -> None:
        dialog = RuleDialog(self, existing_rules=self.service.rules, monitored_folder=self.service.monitored_folder)
        if dialog.exec() == QDialog.Accepted:
            self.service.add_rule(dialog.rule_data())

    def _edit_rule(self, rule: dict) -> None:
        dialog = RuleDialog(self, rule, existing_rules=self.service.rules, monitored_folder=self.service.monitored_folder)
        if dialog.exec() == QDialog.Accepted:
            self.service.update_rule(rule.get("id", ""), dialog.rule_data())

    def _show_smart_suggestions(self) -> None:
        summary = self.service.analyze_smart_suggestions()
        dialog = SmartSuggestionDialog(
            self,
            summary,
            monitored_folder=self.service.monitored_folder,
            existing_rules=self.service.rules,
        )
        result = dialog.exec()
        if result == SmartSuggestionDialog.ADD_RULES:
            self._apply_smart_suggestions(dialog.selected_suggestions(), scan_after=False)
        elif result == SmartSuggestionDialog.ADD_AND_SCAN:
            selected = dialog.selected_suggestions()
            if not selected:
                return
            box = QMessageBox(self)
            box.setWindowTitle("确认应用建议")
            box.setText(f"将新增 {len(selected)} 条整理规则，并整理当前文件夹中符合这些规则的文件。\n文件会被移动到对应文件夹。是否继续？")
            confirm_button = box.addButton("确认整理", QMessageBox.AcceptRole)
            return_button = box.addButton("返回修改", QMessageBox.ActionRole)
            cancel_button = box.addButton("取消", QMessageBox.RejectRole)
            box.setDefaultButton(confirm_button)
            box.exec()
            if box.clickedButton() == confirm_button:
                self._apply_smart_suggestions(selected, scan_after=True)
            elif box.clickedButton() == return_button:
                self._show_smart_suggestions()

    def _apply_smart_suggestions(self, suggestions: list[dict], scan_after: bool) -> None:
        created = self.service.add_suggested_rules(suggestions)
        skipped_count = len(suggestions) - len(created)
        if skipped_count:
            self._add_activity(
                {
                    "time": "刚刚",
                    "status": "skipped",
                    "title": "部分智能建议已跳过",
                    "detail": f"{skipped_count} 条建议的文件类型已被现有规则覆盖。",
                }
            )
        if scan_after and created:
            self._add_activity(
                {
                    "time": "刚刚",
                    "status": "started",
                    "title": "已应用智能建议",
                    "detail": f"已新增 {len(created)} 条规则，并开始整理当前文件夹",
                }
            )
            self.service.scan_now()

    def _move_rule_up(self, rule: dict) -> None:
        self.service.move_rule(rule.get("id", ""), -1)

    def _move_rule_down(self, rule: dict) -> None:
        self.service.move_rule(rule.get("id", ""), 1)

    def _delete_rule(self, rule: dict) -> None:
        rule_name = rule.get("name", "未命名规则")
        result = QMessageBox.question(
            self,
            "删除整理规则",
            f"确定要删除“{rule_name}”吗？\n\n删除后，这条规则不会再用于自动整理。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result == QMessageBox.Yes:
            self.service.delete_rule(rule.get("id", ""))

    def _set_undo_available(self, available: bool) -> None:
        self.undo_button.setEnabled(available)
        self.undo_button.setCursor(Qt.PointingHandCursor if available else Qt.ArrowCursor)
        self.undo_button.setToolTip("" if available else "暂无可撤销的整理记录。")

    def _confirm_undo_last_batch(self) -> None:
        undo_stack = getattr(self.service, "undo_stack", [])
        if not undo_stack:
            self._set_undo_available(False)
            QMessageBox.information(self, "CleanDesk", "暂无可撤销的整理记录。")
            return

        count = len(undo_stack[-1].get("items", []))
        box = QMessageBox(self)
        box.setWindowTitle("确认撤销")
        box.setText(f"将把上一次整理的 {count} 个文件移回原位置。是否继续？")
        undo_button = box.addButton("撤销", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(undo_button)
        box.exec()
        if box.clickedButton() == undo_button:
            self.service.undo_last_batch()

    def _handle_name_conflict_request(self, conflict: dict) -> None:
        action = self._choose_name_conflict_action(conflict)
        self.service.resolve_name_conflict(str(conflict.get("request_id", "")), action)

    def _choose_name_conflict_action(self, conflict: dict) -> str:
        filename = str(conflict.get("filename") or "文件")
        box = QMessageBox(self)
        box.setWindowTitle("发现同名文件")
        box.setText(f"目标位置已存在“{filename}”。\n你希望如何处理？")
        keep_button = box.addButton("保留两个", QMessageBox.AcceptRole)
        replace_button = box.addButton("替换已有文件", QMessageBox.DestructiveRole)
        skip_button = box.addButton("跳过此文件", QMessageBox.RejectRole)
        cancel_button = box.addButton("取消本次操作", QMessageBox.RejectRole)
        box.setDefaultButton(keep_button)
        box.exec()

        clicked = box.clickedButton()
        if clicked == replace_button:
            confirm = QMessageBox.warning(
                self,
                "确认替换",
                f"已有文件“{filename}”会被替换，此操作不可恢复。\n\n确定要替换吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return "replace" if confirm == QMessageBox.Yes else "keep"
        if clicked == skip_button:
            return "skip"
        if clicked == cancel_button:
            return "cancel"
        return "keep"

    def _set_folder(self, folder: str) -> None:
        display = folder or "尚未选择文件夹"
        self.path_label.setText(display)
        self.path_label.setToolTip(display)
        self.suggestion_button.setEnabled(bool(folder) and Path(folder).expanduser().exists())

    def _set_status(self, running: bool) -> None:
        self._status_hint_token += 1
        if running:
            self.status_badge.setText("运行中")
            self.status_badge.setProperty("state", "running")
            self.status_hint.setText("正在监听新文件")
        else:
            self.status_badge.setText("已停止")
            self.status_badge.setProperty("state", "stopped")
            self.status_hint.setText("点击开始后自动整理新文件")

        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def _show_undo_completed_hint(self, result: dict) -> None:
        was_running = bool(result.get("was_running", False))
        if was_running:
            message = "已撤销，上一次整理的文件已移回。自动整理仍在运行。"
        else:
            message = "已撤销，上一次整理的文件已移回。"

        self._show_temporary_status_hint(message)

    def _show_temporary_status_hint(self, message: str) -> None:
        self._status_hint_token += 1
        token = self._status_hint_token
        self.status_hint.setText(message)
        QTimer.singleShot(4000, lambda: self._restore_status_hint(token))

    def _restore_status_hint(self, token: int) -> None:
        if token != self._status_hint_token:
            return
        if self.service.is_running:
            self.status_hint.setText("正在监听新文件")
        else:
            self.status_hint.setText("点击开始后自动整理新文件")

    def _set_rules(self, rules: list[dict]) -> None:
        self.rules_list.clear()
        total = len(rules)
        for index, rule in enumerate(rules):
            item = QListWidgetItem()
            row = RuleListItem(
                rule,
                self._edit_rule,
                self._delete_rule,
                self._move_rule_up,
                self._move_rule_down,
                index,
                total,
            )
            item.setSizeHint(row.sizeHint())
            self.rules_list.addItem(item)
            self.rules_list.setItemWidget(item, row)
        self._refresh_rule_item_sizes()

    def _refresh_rule_item_sizes(self) -> None:
        viewport_width = self.rules_list.viewport().width()
        if viewport_width <= 0:
            return
        item_width = max(240, viewport_width - 14)
        for index in range(self.rules_list.count()):
            item = self.rules_list.item(index)
            widget = self.rules_list.itemWidget(item)
            if widget:
                widget.setFixedWidth(item_width)
                widget.adjustSize()
                item.setSizeHint(widget.sizeHint().expandedTo(widget.minimumSizeHint()))

    def _append_log(self, line: str) -> None:
        self.detailed_log_lines.append(line)
        self.detailed_log_lines = self.detailed_log_lines[-500:]
        if not self._is_user_visible_log(line):
            return
        activity = self._activity_from_log(line)
        if not activity:
            return
        self._add_activity(activity)

    def _add_activity(self, activity: dict) -> None:
        item = QListWidgetItem()
        row = ActivityListItem(activity, self._open_activity_location)
        item.setSizeHint(row.sizeHint())
        self.activity_list.insertItem(0, item)
        self.activity_list.setItemWidget(item, row)
        while self.activity_list.count() > 50:
            self.activity_list.takeItem(self.activity_list.count() - 1)
        scrollbar = self.activity_list.verticalScrollBar()
        scrollbar.setValue(scrollbar.minimum())
        self._refresh_activity_empty_state()

    def _refresh_activity_empty_state(self) -> None:
        has_activity = self.activity_list.count() > 0
        self.activity_empty_widget.setVisible(not has_activity)
        self.activity_list.setVisible(has_activity)

    def _activity_from_log(self, line: str) -> dict | None:
        message = self._log_message(line)
        time_text = self._log_time(line)
        if not message:
            return None
        if message.startswith("Moved ") and " -> " in message:
            return None
        if message.startswith("No rule matched: "):
            file_name = message[len("No rule matched: "):]
            return {
                "time": time_text,
                "status": "skipped",
                "title": f"未整理：{file_name}",
                "detail": "没有匹配的整理规则",
            }
        if "已开始监听" in message or "Monitoring started" in message:
            return {"time": time_text, "status": "started", "title": "已开始：自动整理", "detail": "正在监听新文件"}
        if "已停止监听" in message or "Monitoring stopped" in message:
            return {"time": time_text, "status": "stopped", "title": "已停止：自动整理", "detail": "不会继续监听新文件"}
        if "正在启动监听" in message:
            return {"time": time_text, "status": "started", "title": "已开始：自动整理", "detail": "准备扫描已有文件并监听新文件"}
        if message == "Manual scan started":
            return {"time": time_text, "status": "skipped", "title": "开始整理当前文件夹", "detail": ""}
        if message.startswith("Manual scan queued"):
            count = self._extract_first_number(message)
            if count == "0":
                return {"time": time_text, "status": "skipped", "title": "准备整理：未发现待处理文件", "detail": ""}
            return {"time": time_text, "status": "skipped", "title": f"准备整理：发现 {count} 个文件", "detail": ""}
        if message.startswith("启动前扫描：发现"):
            count = self._extract_first_number(message)
            return {"time": time_text, "status": "skipped", "title": f"准备整理：发现 {count} 个文件", "detail": ""}
        if message.startswith("启动前扫描：未发现"):
            return {"time": time_text, "status": "skipped", "title": "准备整理：未发现待处理文件", "detail": ""}
        if "Manual scan" in message:
            return None
        if "Failed" in message or "failed" in message or "ERROR" in line:
            return {"time": time_text, "status": "error", "title": "整理失败", "detail": message}
        return None

    def _extract_first_number(self, text: str) -> str:
        digits = []
        for character in text:
            if character.isdigit():
                digits.append(character)
            elif digits:
                break
        return "".join(digits) if digits else "0"

    def _open_activity_location(self, activity: dict) -> None:
        target_path_text = str(activity.get("target_path", "")).strip()
        target_folder_text = str(activity.get("target_folder", "")).strip()
        if not target_path_text and not target_folder_text:
            QMessageBox.information(self, "CleanDesk", "无法打开位置，文件夹可能已被移动或删除。")
            return

        target_path = Path(target_path_text).expanduser() if target_path_text else None
        if target_path and not target_path.is_absolute():
            target_path = target_path.resolve()
        target_folder = Path(target_folder_text).expanduser() if target_folder_text else None
        if target_folder and not target_folder.is_absolute():
            target_folder = target_folder.resolve()
        if not target_folder and target_path:
            target_folder = target_path.parent

        try:
            if target_path and target_path.exists():
                subprocess.run(["explorer", f"/select,{str(target_path)}"], check=False)
                return
            if target_folder and target_folder.exists():
                os.startfile(str(target_folder))
                QMessageBox.information(self, "CleanDesk", "文件可能已被移动或删除，已打开目标文件夹。")
                return
            QMessageBox.information(self, "CleanDesk", "无法打开位置，文件夹可能已被移动或删除。")
        except Exception as exc:
            QMessageBox.information(self, "CleanDesk", f"无法打开位置：{exc}")

    def _log_message(self, line: str) -> str:
        parts = line.split(" | ", 2)
        if len(parts) == 3:
            return parts[2]
        return line

    def _log_time(self, line: str) -> str:
        if len(line) >= 16 and line[4:5] == "-" and line[13:14] == ":":
            return line[11:16]
        return "刚刚"

    def _show_detailed_log(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("详细日志")
        dialog.resize(760, 480)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(SPACING)

        detail_view = QTextEdit()
        detail_view.setObjectName("logView")
        detail_view.setReadOnly(True)
        detail_view.setLineWrapMode(QTextEdit.NoWrap)
        detail_view.setText("\n".join(self._load_detailed_logs()))
        layout.addWidget(detail_view, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _load_detailed_logs(self) -> list[str]:
        app_log = Path("logs") / "app.log"
        if app_log.exists():
            try:
                lines = app_log.read_text(encoding="utf-8").splitlines()
                return lines[-500:]
            except OSError:
                pass
        return self.detailed_log_lines

    def _is_user_visible_log(self, line: str) -> bool:
        hidden_fragments = (
            "CleanDesk ready",
            "Duplicate file event ignored",
            "Queued file skipped because it is temporary or hidden",
            "File still unavailable, retrying",
            "Folder watcher active:",
            "Folder watcher stopped",
        )
        return not any(fragment in line for fragment in hidden_fragments)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "CleanDesk", message)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_responsive_layout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._show_welcome_if_needed)

    def _show_welcome_if_needed(self) -> None:
        if self._welcome_prompt_pending or self.service.config.get("welcome_shown", False):
            return
        self._welcome_prompt_pending = True
        QMessageBox.information(
            self,
            "欢迎使用 CleanDesk Beta",
            "建议先选择测试文件夹。\n\n"
            "CleanDesk 会移动匹配规则的文件。\n\n"
            "建议先使用“立即扫描”验证规则。\n\n"
            "确认无误后再启动自动监听。",
        )
        self.service.config["welcome_shown"] = True
        self.service.storage.save(self.service.config)
        self._welcome_prompt_pending = False

    def _card(self, horizontal: QSizePolicy.Policy, vertical: QSizePolicy.Policy) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.NoFrame)
        card.setMinimumWidth(0)
        card.setSizePolicy(horizontal, vertical)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(20, 24, 31, 14))
        card.setGraphicsEffect(shadow)
        return card

    def _card_layout(self, card: QFrame) -> QVBoxLayout:
        layout = QVBoxLayout(card)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(SPACING)
        return layout

    def _label(self, text: str, object_name: str, wrap: bool = False) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(wrap)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return label

    def _button(self, text: str, object_name: str) -> QPushButton:
        button = QPushButton(text)
        self._prepare_button(button, object_name)
        return button

    def _prepare_button(self, button: QPushButton, object_name: str) -> None:
        button.setObjectName(object_name)
        button.setFixedHeight(BUTTON_HEIGHT)
        button.setMinimumWidth(0)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setCursor(Qt.PointingHandCursor)

    def _apply_style(self) -> None:
        app_font = QFont(QApplication.font().family(), 10)
        self.setFont(app_font)
        self.setStyleSheet(
            """
            QScrollArea#scrollArea {
                background: #F6F7F9;
                border: none;
            }
            QWidget#root {
                background: #F6F7F9;
                color: #111827;
            }
            QLabel#appTitle {
                font-size: 28px;
                font-weight: 700;
                letter-spacing: 0px;
            }
            QLabel#cardTitle {
                color: #111827;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#caption {
                color: #6B7280;
                font-size: 13px;
            }
            QFrame#card {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
            }
            QLabel#pathLabel {
                background: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 10px;
                padding: 0 12px;
                color: #374151;
                font-size: 13px;
            }
            QLabel#statusBadge {
                border-radius: 12px;
                font-size: 24px;
                font-weight: 750;
            }
            QLabel#statusBadge[state="running"] {
                background: #E8F0FF;
                color: #2563EB;
            }
            QLabel#statusBadge[state="stopped"] {
                background: #F3F4F6;
                color: #6B7280;
            }
            QLabel#statusHint {
                color: #6B7280;
                font-size: 13px;
            }
            QPushButton {
                border: none;
                border-radius: 10px;
                padding: 0 14px;
                font-size: 14px;
                font-weight: 650;
            }
            QPushButton:disabled {
                background: #E5E7EB;
                color: #9CA3AF;
            }
            QPushButton#primaryButton {
                background: #2563EB;
                color: #FFFFFF;
            }
            QPushButton#primaryButton:hover {
                background: #1D4ED8;
            }
            QPushButton#dangerButton {
                background: #EF4444;
                color: #FFFFFF;
            }
            QPushButton#dangerButton:hover {
                background: #DC2626;
            }
            QPushButton#secondaryButton {
                background: #F3F4F6;
                color: #374151;
            }
            QPushButton#secondaryButton:hover {
                background: #E5E7EB;
            }
            QPushButton#secondaryButton:disabled,
            QPushButton#secondaryButton:disabled:hover {
                background: #F9FAFB;
                color: #CBD5E1;
                border: 1px solid #EEF2F7;
            }
            QPushButton#linkButton {
                background: transparent;
                color: #6B7280;
                padding: 0 4px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton#linkButton:hover {
                background: #F3F4F6;
                color: #374151;
            }
            QPushButton#ruleArrowButton {
                background: #F3F4F6;
                border: 1px solid #E5E7EB;
                border-radius: 7px;
                color: #6B7280;
                font-size: 12px;
                font-weight: 700;
                padding: 0;
            }
            QPushButton#ruleArrowButton:hover {
                background: #E5E7EB;
                color: #374151;
            }
            QPushButton#ruleArrowButton:disabled {
                background: transparent;
                border: 1px solid #EEF0F3;
                color: #D1D5DB;
            }
            QListWidget#rulesList {
                background: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 10px;
                padding: 6px;
                color: #374151;
                font-size: 13px;
                selection-background-color: transparent;
            }
            QListWidget#rulesList::item {
                border: none;
            }
            QListWidget#activityList {
                background: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 10px;
                padding: 6px;
                color: #374151;
                selection-background-color: transparent;
            }
            QListWidget#activityList::item {
                border: none;
            }
            QWidget#ruleItem {
                background: transparent;
                border-bottom: 1px solid #E5E7EB;
            }
            QWidget#activityItem {
                background: transparent;
                border-bottom: 1px solid #E5E7EB;
            }
            QLabel#ruleName {
                color: #111827;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#ruleMeta {
                color: #4B5563;
                font-size: 11px;
            }
            QLabel#ruleTarget {
                color: #6B7280;
                font-size: 11px;
            }
            QLabel#activityTitle {
                color: #111827;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#activityDetail {
                color: #4B5563;
                font-size: 12px;
            }
            QLabel#activityTime {
                color: #6B7280;
                font-size: 12px;
            }
            QPushButton#activityActionButton {
                background: #F3F4F6;
                color: #374151;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                padding: 0 10px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#activityActionButton:hover {
                background: #E5E7EB;
            }
            QWidget#emptyStateBox {
                background: transparent;
            }
            QLabel#emptyStateTitle {
                color: #6B7280;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#emptyStateHint {
                color: #9CA3AF;
                font-size: 12px;
                font-weight: 500;
            }
            QLabel#fieldHint {
                color: #6B7280;
                font-size: 12px;
            }
            QLabel#fieldError {
                color: #EF4444;
                font-size: 12px;
            }
            QLabel#fieldWarning {
                background: #FFFBEB;
                border: 1px solid #FDE68A;
                border-radius: 8px;
                color: #92400E;
                font-size: 12px;
                padding: 8px 10px;
            }
            QTextEdit#logView {
                background: #111827;
                border: 1px solid #1F2937;
                border-radius: 10px;
                padding: 10px;
                color: #E5E7EB;
                font-family: Consolas, Menlo, monospace;
                font-size: 12px;
                selection-background-color: #2563EB;
            }
            QLineEdit,
            QComboBox {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 10px;
                padding: 0 12px;
                min-height: 36px;
                color: #111827;
                font-size: 14px;
            }
            QLineEdit:focus,
            QComboBox:focus {
                border: 1px solid #2563EB;
            }
            QDialog {
                background: #F6F7F9;
                color: #111827;
            }
            QDialog QLabel {
                color: #374151;
                font-size: 13px;
                font-weight: 600;
            }
            QDialogButtonBox QPushButton {
                min-width: 80px;
                min-height: 36px;
            }
            """
        )



class RuleListItem(QWidget):
    def __init__(self, rule: dict, edit_callback, delete_callback, move_up_callback, move_down_callback, index: int, total: int):
        super().__init__()
        self.rule = dict(rule)
        self.edit_callback = edit_callback
        self.delete_callback = delete_callback
        self.move_up_callback = move_up_callback
        self.move_down_callback = move_down_callback
        self.setObjectName("ruleItem")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(0)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        arrow_box = QVBoxLayout()
        arrow_box.setContentsMargins(0, 0, 0, 0)
        arrow_box.setSpacing(3)

        up_button = QPushButton("↑")
        up_button.setObjectName("ruleArrowButton")
        up_button.setFixedSize(22, 20)
        up_button.setEnabled(index > 0)
        up_button.clicked.connect(lambda: self.move_up_callback(self.rule))

        down_button = QPushButton("↓")
        down_button.setObjectName("ruleArrowButton")
        down_button.setFixedSize(22, 20)
        down_button.setEnabled(index < total - 1)
        down_button.clicked.connect(lambda: self.move_down_callback(self.rule))

        arrow_box.addWidget(up_button)
        arrow_box.addWidget(down_button)

        content_box = QVBoxLayout()
        content_box.setContentsMargins(0, 0, 0, 0)
        content_box.setSpacing(2)
        content_box.addWidget(self._line(self._display_name(), "ruleName"))
        content_box.addWidget(self._line(self._condition_text(), "ruleMeta"))
        content_box.addWidget(self._line(f"→ 移动到：{self.rule.get('target', '未分类')}", "ruleTarget"))

        actions_box = QVBoxLayout()
        actions_box.setContentsMargins(0, 0, 0, 0)
        actions_box.setSpacing(2)

        edit_button = QPushButton("编辑")
        edit_button.setObjectName("linkButton")
        edit_button.setFixedHeight(22)
        edit_button.setFixedWidth(34)
        edit_button.clicked.connect(lambda: self.edit_callback(self.rule))

        delete_button = QPushButton("删除")
        delete_button.setObjectName("linkButton")
        delete_button.setFixedHeight(22)
        delete_button.setFixedWidth(34)
        delete_button.clicked.connect(lambda: self.delete_callback(self.rule))

        actions_box.addWidget(edit_button)
        actions_box.addWidget(delete_button)
        actions_box.addStretch(1)

        row.addLayout(arrow_box, 0)
        row.addLayout(content_box, 1)
        row.addLayout(actions_box, 0)
        layout.addLayout(row)

    def _line(self, text: str, object_name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return label

    def _display_name(self) -> str:
        name = str(self.rule.get("name", "")).strip()
        if name and name != "Untitled Rule":
            return natural_rule_name(self.rule)
        return natural_rule_name(self.rule)

    def _condition_text(self) -> str:
        return natural_rule_condition(self.rule)


class ActivityListItem(QWidget):
    def __init__(self, activity: dict, open_callback=None):
        super().__init__()
        self.activity = dict(activity)
        self.open_callback = open_callback
        self.setObjectName("activityItem")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        title = QLabel(activity.get("title", ""))
        title.setObjectName("activityTitle")
        title.setWordWrap(True)
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        time_label = QLabel(activity.get("time", "刚刚"))
        time_label.setObjectName("activityTime")
        time_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        time_label.setFixedWidth(54)

        top.addWidget(title, 1)
        top.addWidget(time_label, 0)
        layout.addLayout(top)

        detail = activity.get("detail", "")
        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("activityDetail")
            detail_label.setWordWrap(True)
            detail_label.setMinimumWidth(0)
            detail_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            layout.addWidget(detail_label)

        if activity.get("status") == "success" and activity.get("target_path") and open_callback:
            action_row = QHBoxLayout()
            action_row.setContentsMargins(0, 2, 0, 0)
            action_row.setSpacing(0)
            open_button = QPushButton("打开所在位置")
            open_button.setObjectName("activityActionButton")
            open_button.setFixedHeight(28)
            open_button.setMinimumWidth(104)
            open_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            open_button.clicked.connect(lambda: self.open_callback(self.activity))
            action_row.addStretch(1)
            action_row.addWidget(open_button, 0, Qt.AlignRight)
            layout.addLayout(action_row)


class SmartSuggestionDialog(QDialog):
    ADD_RULES = 101
    ADD_AND_SCAN = 102

    def __init__(
        self,
        parent=None,
        summary: dict | None = None,
        monitored_folder: str | Path = "",
        existing_rules: list[dict] | None = None,
    ):
        super().__init__(parent)
        self.summary = dict(summary or {})
        self.monitored_folder = Path(monitored_folder).expanduser() if monitored_folder else Path.home()
        self.existing_rules = [dict(rule) for rule in (existing_rules or [])]
        self.rows: list[dict] = []
        self.setWindowTitle("智能整理建议")
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(SPACING)

        title = QLabel("智能整理建议")
        title.setObjectName("cardTitle")
        description = QLabel("CleanDesk 会根据当前文件夹中数量较多、且还没有整理规则的文件类型，为你生成整理建议。\n只会分析文件名和扩展名，不会读取文件内容。")
        description.setObjectName("caption")
        description.setWordWrap(True)
        suggestion_count = len(self.summary.get("suggestions", []))
        summary_label = QLabel(
            f"已分析当前文件夹中的 {self.summary.get('total_files', 0)} 个文件。\n"
            f"其中 {self.summary.get('covered_files', 0)} 个文件已有整理规则，发现 {suggestion_count} 类文件值得新增规则。"
        )
        summary_label.setObjectName("fieldHint")
        summary_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(summary_label)

        suggestions = list(self.summary.get("suggestions", []))
        if suggestions:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(10)
            for suggestion in suggestions:
                content_layout.addWidget(self._suggestion_row(suggestion))
            content_layout.addStretch(1)
            scroll.setWidget(content)
            layout.addWidget(scroll, 1)
        else:
            empty = QLabel("没有发现需要新增规则的高频文件类型。\n你也可以使用“新建整理规则”手动创建规则。")
            empty.setObjectName("emptyStateHint")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setMinimumHeight(120)
            layout.addWidget(empty)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        add_button = QPushButton("仅添加规则")
        add_button.setObjectName("secondaryButton")
        apply_button = QPushButton("添加规则并整理")
        apply_button.setObjectName("secondaryButton")
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("secondaryButton")
        add_button.setEnabled(bool(suggestions))
        apply_button.setEnabled(bool(suggestions))
        add_button.clicked.connect(lambda: self.done(self.ADD_RULES))
        apply_button.clicked.connect(lambda: self.done(self.ADD_AND_SCAN))
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(add_button)
        button_row.addWidget(apply_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

    def _suggestion_row(self, suggestion: dict) -> QWidget:
        row = QFrame()
        row.setObjectName("suggestionItem")
        row.setMinimumWidth(0)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        checkbox = QCheckBox(str(suggestion.get("name", "整理建议")))
        checkbox.setChecked(True)
        checkbox.setObjectName("ruleTitle")
        extensions = [str(extension) for extension in suggestion.get("extensions", [])]
        detail = QLabel(f"发现 {suggestion.get('count', 0)} 个 {'、'.join(extensions)} 文件")
        detail.setObjectName("ruleMeta")
        detail.setWordWrap(True)

        target_label = QLabel("建议整理到：")
        target_label.setObjectName("ruleMeta")
        target_input = QLineEdit(str(suggestion.get("target", "")))
        choose_button = QPushButton("选择...")
        choose_button.setObjectName("secondaryButton")
        choose_button.setFixedWidth(80)
        target_row = QHBoxLayout()
        target_row.setContentsMargins(0, 0, 0, 0)
        target_row.setSpacing(8)
        target_row.addWidget(target_label, 0)
        target_row.addWidget(target_input, 1)
        target_row.addWidget(choose_button, 0)

        choose_button.clicked.connect(lambda: self._choose_target_folder(target_input))

        layout.addWidget(checkbox)
        layout.addWidget(detail)
        layout.addLayout(target_row)
        self.rows.append({"suggestion": dict(suggestion), "checkbox": checkbox, "target_input": target_input})
        return row

    def _choose_target_folder(self, target_input: QLineEdit) -> None:
        start_folder = self._target_dialog_start_folder(target_input.text().strip())
        folder = QFileDialog.getExistingDirectory(self, "选择目标文件夹", start_folder)
        if folder:
            target_input.setText(folder)

    def _target_dialog_start_folder(self, target_text: str) -> str:
        fallback = self.monitored_folder if self.monitored_folder.exists() else Path.home()
        if not target_text:
            return str(fallback)
        current_path = Path(target_text).expanduser()
        if current_path.is_absolute():
            return str(current_path if current_path.exists() else fallback)
        relative_target = self.monitored_folder / current_path
        return str(relative_target if relative_target.exists() else fallback)

    def selected_suggestions(self) -> list[dict]:
        selected = []
        for row in self.rows:
            if not row["checkbox"].isChecked():
                continue
            suggestion = dict(row["suggestion"])
            suggestion["target"] = row["target_input"].text().strip() or suggestion.get("target", "")
            selected.append(suggestion)
        return selected


def natural_rule_name(rule: dict) -> str:
    name = str(rule.get("name", "")).strip()
    known_names = {
        "Invoice files": "发票文件",
        "Course files": "课程资料",
        "Images": "图片",
        "PDF": "PDF 文档",
        "Audio": "音频",
        "Videos": "视频",
    }
    if name in known_names:
        return known_names[name]
    if name and name != "Untitled Rule":
        return name
    rule_type = rule.get("type")
    if rule_type == "extension":
        return auto_extension_rule_name(rule.get("extensions", []))
    if rule_type == "name_contains":
        keywords = rule.get("keywords", [])
        first = str(keywords[0]).strip() if keywords else "关键词"
        return f"{first}文件"
    return "自动整理规则"


def natural_rule_condition(rule: dict) -> str:
    if rule.get("type") == "extension":
        extensions = [str(value).strip().lstrip(".") for value in rule.get("extensions", []) if str(value).strip()]
        if not extensions:
            return "文件类型：未设置"
        if len(extensions) > 5:
            shown = "、".join(extensions[:5]) + " 等"
        else:
            shown = "、".join(extensions)
        return f"文件类型：{shown}"
    if rule.get("type") == "name_contains":
        keywords = [str(value).strip() for value in rule.get("keywords", []) if str(value).strip()]
        if not keywords:
            return "文件名包含：未设置"
        quoted = "、".join(f"“{keyword}”" for keyword in keywords)
        return f"文件名包含{quoted}"
    return "条件：未设置"


def auto_extension_rule_name(extensions: list[str]) -> str:
    normalized = {str(value).strip().lower().lstrip(".") for value in extensions}
    if normalized == {"pdf"}:
        return "PDF 文档"
    if normalized & {"zip", "rar", "7z", "tar", "gz"}:
        return "压缩文件"
    if normalized & {"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "heic", "svg"}:
        return "图片"
    if normalized & {"mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v"}:
        return "视频"
    if normalized & {"mp3", "wav", "aac", "flac", "m4a", "ogg", "wma"}:
        return "音频"
    if normalized:
        first = sorted(normalized)[0].upper()
        return f"{first} 文件"
    return "条件：未设置"


class RuleDialog(QDialog):
    def __init__(
        self,
        parent=None,
        rule: dict | None = None,
        existing_rules: list[dict] | None = None,
        monitored_folder: str | Path = "",
    ):
        super().__init__(parent)
        self.rule = dict(rule or {})
        self.existing_rules = [dict(existing_rule) for existing_rule in (existing_rules or [])]
        self.monitored_folder = Path(monitored_folder).expanduser() if monitored_folder else Path.home()
        self.setWindowTitle("编辑自动整理规则" if rule else "新建自动整理规则")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(SPACING)

        title = QLabel("编辑自动整理规则" if rule else "新建自动整理规则")
        title.setObjectName("cardTitle")
        hint = QLabel("用自然条件描述要整理的文件，保存后会立即加入规则列表。")
        hint.setObjectName("caption")
        hint.setWordWrap(True)

        self.type_input = QComboBox()
        self.type_input.addItem("按文件类型", "extension")
        self.type_input.addItem("按文件名关键词", "name_contains")
        self.type_input.currentIndexChanged.connect(self._sync_fields)

        self.value_label = QLabel()
        self.value_input = QLineEdit()
        self.value_input.textChanged.connect(self._update_conflict_hint)
        self.value_hint = QLabel()
        self.value_hint.setObjectName("fieldHint")
        self.value_error = QLabel()
        self.value_error.setObjectName("fieldError")
        self.value_error.setWordWrap(True)

        self.target_label = QLabel("移动到哪个文件夹？")
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("例如：发票 或 PDF文档")
        self.target_button = QPushButton("选择...")
        self.target_button.setObjectName("secondaryButton")
        self.target_button.setFixedWidth(80)
        self.target_button.clicked.connect(self._choose_target_folder)
        self.target_hint = QLabel("可以输入文件夹名称，也可以点击“选择...”选择位置。")
        self.target_hint.setObjectName("fieldHint")
        self.target_error = QLabel()
        self.target_error.setObjectName("fieldError")
        self.target_error.setWordWrap(True)

        self.name_label = QLabel("规则名称（可选）")
        self.name_input = QLineEdit()
        self.name_hint = QLabel()
        self.name_hint.setObjectName("fieldHint")
        self.conflict_hint = QLabel()
        self.conflict_hint.setObjectName("fieldWarning")
        self.conflict_hint.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(QLabel("你想按什么方式整理？"))
        layout.addWidget(self.type_input)
        layout.addWidget(self.value_label)
        layout.addWidget(self.value_input)
        layout.addWidget(self.value_hint)
        layout.addWidget(self.value_error)
        layout.addWidget(self.target_label)
        target_row = QHBoxLayout()
        target_row.setContentsMargins(0, 0, 0, 0)
        target_row.setSpacing(8)
        target_row.addWidget(self.target_input, 1)
        target_row.addWidget(self.target_button, 0)
        layout.addLayout(target_row)
        layout.addWidget(self.target_hint)
        layout.addWidget(self.target_error)
        layout.addWidget(self.name_label)
        layout.addWidget(self.name_input)
        layout.addWidget(self.name_hint)
        layout.addWidget(self.conflict_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("创建规则" if not rule else "保存规则")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_rule()
        self._sync_fields()
        self._update_conflict_hint()

    def _load_rule(self) -> None:
        rule_type = self.rule.get("type", "extension")
        index = self.type_input.findData(rule_type)
        self.type_input.setCurrentIndex(max(0, index))
        if rule_type == "name_contains":
            self.value_input.setText("，".join(self.rule.get("keywords", [])))
        else:
            self.value_input.setText("，".join(str(value).lstrip(".") for value in self.rule.get("extensions", [])))
        self.target_input.setText(self.rule.get("target", ""))
        existing_name = self.rule.get("name", "")
        self.name_input.setText("" if existing_name in {"Untitled Rule"} else existing_name)

    def _sync_fields(self) -> None:
        rule_type = self.type_input.currentData()
        self.value_error.clear()
        self.target_error.clear()
        self._update_conflict_hint()
        if rule_type == "extension":
            self.value_label.setText("整理哪些文件类型？")
            self.value_input.setPlaceholderText("例如：pdf，docx，zip")
            self.value_hint.setText("支持用逗号分隔多个扩展名。")
            self.name_input.setPlaceholderText("例如：PDF 文档")
            self.name_hint.setText("不填写时会根据文件类型自动生成名称，例如“PDF 文档”或“压缩文件”。")
        else:
            self.value_label.setText("文件名包含什么关键词？")
            self.value_input.setPlaceholderText("例如：发票，报销单，课程")
            self.value_hint.setText("支持用逗号分隔多个关键词。")
            self.name_input.setPlaceholderText("例如：发票文件")
            self.name_hint.setText("不填写时会根据第一个关键词自动生成名称，例如“发票文件”。")

    def _update_conflict_hint(self) -> None:
        rule_type = self.type_input.currentData()
        if rule_type == "name_contains":
            self.conflict_hint.setText("如果某个文件同时符合多条规则，将优先使用列表中更靠上的规则。")
            return

        values = {normalize_extension_text(value) for value in split_values(self.value_input.text())}
        current_id = self.rule.get("id", "")
        conflicts = []
        for existing_rule in self.existing_rules:
            if existing_rule.get("id") == current_id or existing_rule.get("type") != "extension":
                continue
            existing_extensions = {normalize_extension_text(value) for value in existing_rule.get("extensions", [])}
            if values & existing_extensions:
                conflicts.append(natural_rule_name(existing_rule))
        if conflicts:
            joined = "、".join(dict.fromkeys(conflicts))
            self.conflict_hint.setText(f"这个文件类型已经被“{joined}”规则使用。保存后，列表中更靠上的规则会优先生效。")
        else:
            self.conflict_hint.setText("如果某个文件同时符合多条规则，将优先使用列表中更靠上的规则。")

    def _choose_target_folder(self) -> None:
        start_folder = self._target_dialog_start_folder()
        folder = QFileDialog.getExistingDirectory(self, "选择目标文件夹", start_folder)
        if folder:
            self.target_input.setText(folder)

    def _target_dialog_start_folder(self) -> str:
        fallback = self.monitored_folder if self.monitored_folder.exists() else Path.home()
        current_text = self.target_input.text().strip()
        if not current_text:
            return str(fallback)

        current_path = Path(current_text).expanduser()
        if current_path.is_absolute():
            return str(current_path if current_path.exists() else fallback)

        relative_target = self.monitored_folder / current_path
        return str(relative_target if relative_target.exists() else fallback)

    def rule_data(self) -> dict:
        rule_type = self.type_input.currentData()
        values = split_values(self.value_input.text())
        name = self.name_input.text().strip()
        target = self.target_input.text().strip()
        rule = {
            "id": self.rule.get("id", ""),
            "name": name or auto_rule_name(rule_type, values),
            "type": rule_type,
            "target": target,
            "enabled": self.rule.get("enabled", True),
            "priority": int(self.rule.get("priority", 50)),
        }
        if rule_type == "extension":
            rule["extensions"] = [normalize_extension_text(value) for value in values]
        else:
            rule["keywords"] = values
        return rule

    def _accept_if_valid(self) -> None:
        self.value_error.clear()
        self.target_error.clear()
        valid = True
        if not split_values(self.value_input.text()):
            self.value_error.setText("请至少填写一个文件类型或关键词。")
            valid = False
        if not self.target_input.text().strip():
            self.target_error.setText("请填写要移动到的目标文件夹。")
            valid = False
        if valid:
            self.accept()


def split_values(text: str) -> list[str]:
    normalized = text.replace("，", ",").replace("、", ",").replace("；", ",").replace(";", ",")
    return [value.strip() for value in normalized.split(",") if value.strip()]


def normalize_extension_text(value: str) -> str:
    value = value.strip().lower()
    return value if value.startswith(".") else f".{value}"


def auto_rule_name(rule_type: str, values: list[str]) -> str:
    if rule_type == "extension":
        return auto_extension_rule_name([normalize_extension_text(value) for value in values])
    first = values[0] if values else "关键词"
    return f"{first}文件"
