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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from version import APP_NAME, APP_VERSION
from notifications import (
    NOTIFICATION_DISABLED,
    NOTIFICATION_FAILED,
    NOTIFICATION_SHOWN,
    NOTIFICATION_TRAY_UNAVAILABLE,
    NOTIFICATION_UNSUPPORTED,
    NotificationManager,
)
from startup import StartupError, has_launch_at_login_entry, is_launch_at_login_enabled, set_launch_at_login_enabled


BREAKPOINT_WIDTH = 1100
PAGE_MARGIN_X = 24
PAGE_MARGIN_Y = 20
CARD_PADDING = 16
SPACING = 12
BUTTON_HEIGHT = 36


def about_information_text() -> str:
    return (
        f"{APP_NAME}\n\n"
        f"{APP_VERSION}\n\n"
        "本地自动化文件管家\n\n"
        "开发者：Zmx\n\n"
        "所有整理都在本机完成，不会上传文件。\n\n"
        "当前版本仍处于 Beta 阶段，建议先使用测试文件夹。"
    )


class MainWindow(QMainWindow):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self._layout_mode = ""
        self._rebuilding_layout = False
        self._welcome_prompt_pending = False
        self._auto_start_scheduled = False
        self._auto_start_attempted = False
        self._status_hint_token = 0
        self._updating_rules = False
        self._tray_hint_shown = False
        self._application_exit_requested = False
        self._startup_mode = False
        self._auto_start_success_notified = False
        self._auto_start_failure_notified = False

        self.path_label = QLabel()
        self.folder_title_label = QLabel()
        self.folder_caption_label = QLabel()
        self.folder_list = QListWidget()
        self.folder_empty_widget = QWidget()
        self.folder_add_button = QPushButton("+ 添加文件夹")
        self.folder_remove_button = QPushButton("移除当前文件夹")
        self.status_badge = QLabel()
        self.status_hint = QLabel()
        self.rules_list = QListWidget()
        self.activity_list = QListWidget()
        self.activity_empty_widget = QWidget()
        self.activity_empty_label = QLabel("还没有整理记录")
        self.activity_empty_hint = QLabel("点击“立即扫描”，CleanDesk 会在这里显示整理结果。")
        self.detailed_log_lines: list[str] = []
        self.log_view = QTextEdit()
        self.start_button = QPushButton("开始自动整理")
        self.stop_button = QPushButton("停止自动整理")
        self.scan_button = QPushButton("整理当前文件夹")
        self.undo_button = QPushButton("撤销上一次整理")
        self.ignore_rules_button = QPushButton("忽略规则")
        self.suggestion_button = QPushButton("智能整理建议")

        self._build_window()
        self._build_system_tray()
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
        self.control_card = self._control_center_card()
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
                self.control_card,
                self.rules_card,
                self.log_card,
            ):
                self._remove_widget_from_responsive_layouts(widget)

            if mode == "desktop":
                self.content_layout.setDirection(QBoxLayout.LeftToRight)
                self.root_layout.addWidget(self.log_card, 1)
                self.content_layout.addWidget(self.left_column)
                self.content_layout.addWidget(self.right_column)
                self.content_layout.setStretch(0, 11)
                self.content_layout.setStretch(1, 10)

                self.left_layout.addWidget(self.folder_card, 1)
                self.left_layout.setStretch(0, 1)

                self.right_layout.addWidget(self.control_card, 0)
                self.right_layout.addWidget(self.rules_card, 1)
                self.right_layout.setStretch(0, 0)
                self.right_layout.setStretch(1, 1)

                self.folder_card.setMinimumHeight(320)
                self.folder_list.setMinimumHeight(180)
                self.rules_card.setMinimumHeight(260)
            else:
                self.content_layout.setDirection(QBoxLayout.TopToBottom)
                self.content_layout.addWidget(self.folder_card)
                self.content_layout.addWidget(self.control_card)
                self.content_layout.addWidget(self.rules_card)
                self.content_layout.addWidget(self.log_card)
                for index in range(4):
                    self.content_layout.setStretch(index, 0)

                self.folder_card.setMinimumHeight(0)
                self.folder_list.setMinimumHeight(128)
                self.rules_card.setMinimumHeight(260)

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
        card = self._card(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = self._card_layout(card)

        self.folder_title_label = self._label("监控文件夹（0）", "cardTitle")
        self.folder_caption_label = self._label(
            "选择当前要整理的文件夹；开始自动整理后会监听所有文件夹。",
            "caption",
            wrap=True,
        )

        self.folder_list.setObjectName("folderList")
        self.folder_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.folder_list.setFocusPolicy(Qt.NoFocus)
        self.folder_list.setUniformItemSizes(False)
        self.folder_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.folder_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.folder_list.setResizeMode(QListWidget.Adjust)
        self.folder_list.setWordWrap(True)
        self.folder_list.setMinimumHeight(128)
        self.folder_list.setMinimumWidth(0)
        self.folder_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.folder_list.itemClicked.connect(self._select_folder_item)

        self.folder_empty_widget.setObjectName("folderEmptyState")
        self.folder_empty_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        empty_layout = QGridLayout(self.folder_empty_widget)
        empty_layout.setContentsMargins(12, 12, 12, 12)
        empty_group = QWidget()
        empty_group.setObjectName("folderEmptyTextGroup")
        empty_group.setMinimumWidth(300)
        empty_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        empty_group_layout = QVBoxLayout(empty_group)
        empty_group_layout.setContentsMargins(0, 0, 0, 0)
        empty_group_layout.setSpacing(8)
        empty_title = QLabel("还没有添加监控文件夹")
        empty_title.setObjectName("folderEmptyTitle")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_hint = QLabel("点击“添加文件夹”开始使用。")
        empty_hint.setObjectName("folderEmptyHint")
        empty_hint.setAlignment(Qt.AlignCenter)
        empty_hint.setWordWrap(False)
        empty_group_layout.addWidget(empty_title)
        empty_group_layout.addWidget(empty_hint)
        empty_layout.addWidget(empty_group, 0, 0, Qt.AlignCenter)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self._prepare_button(self.folder_add_button, "secondaryButton")
        self._prepare_button(self.folder_remove_button, "secondaryButton")
        self.folder_add_button.clicked.connect(self._add_monitored_folder)
        self.folder_remove_button.clicked.connect(self._confirm_remove_active_folder)
        action_row.addWidget(self.folder_add_button)
        action_row.addWidget(self.folder_remove_button)

        layout.addWidget(self.folder_title_label, 0, Qt.AlignTop)
        layout.addWidget(self.folder_caption_label, 0, Qt.AlignTop)
        layout.addWidget(self.folder_empty_widget, 1)
        layout.addWidget(self.folder_list, 1)
        layout.addLayout(action_row, 0)
        return card

    def _rules_card(self) -> QFrame:
        card = self._card(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = self._card_layout(card)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(SPACING)

        title_label = self._label("自动整理规则", "cardTitle")

        self._prepare_button(self.suggestion_button, "secondaryButton")
        self.suggestion_button.setFixedWidth(116)
        self.suggestion_button.clicked.connect(self._handle_smart_suggestions_clicked)

        self._prepare_button(self.ignore_rules_button, "secondaryButton")
        self.ignore_rules_button.setFixedWidth(88)
        self.ignore_rules_button.clicked.connect(self._show_ignore_rules)

        add_button = self._button("+ 新建整理规则", "secondaryButton")
        add_button.setFixedWidth(132)
        add_button.clicked.connect(self._add_rule)

        header.addWidget(title_label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self.ignore_rules_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.suggestion_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(add_button, 0, Qt.AlignRight | Qt.AlignVCenter)

        description = QVBoxLayout()
        description.setContentsMargins(0, 0, 0, 0)
        description.setSpacing(4)
        description.addWidget(self._label("符合条件的文件会自动移动到对应文件夹。", "caption"))
        description.addWidget(self._label("上方规则会优先匹配。", "caption"))

        self.rules_list.setObjectName("rulesList")
        self.rules_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.rules_list.setFocusPolicy(Qt.NoFocus)
        self.rules_list.setUniformItemSizes(False)
        self.rules_list.setDragEnabled(True)
        self.rules_list.setAcceptDrops(True)
        self.rules_list.setDropIndicatorShown(True)
        self.rules_list.setDefaultDropAction(Qt.MoveAction)
        self.rules_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.rules_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rules_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.rules_list.setResizeMode(QListWidget.Adjust)
        self.rules_list.setWordWrap(True)
        self.rules_list.setMinimumHeight(180)
        self.rules_list.setMinimumWidth(0)
        self.rules_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.rules_list.model().rowsMoved.connect(self._save_dragged_rule_order)

        layout.addLayout(header)
        layout.addLayout(description)
        layout.setSpacing(10)
        layout.addWidget(self.rules_list, 1)
        return card

    def _control_center_card(self) -> QFrame:
        card = self._card(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setMaximumHeight(360)
        layout = self._card_layout(card)
        layout.setSpacing(12)

        self.status_badge.setObjectName("statusBadge")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setFixedHeight(60)
        self.status_badge.setMinimumWidth(0)
        self.status_badge.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.status_hint.setObjectName("statusHint")
        self.status_hint.setAlignment(Qt.AlignCenter)
        self.status_hint.setWordWrap(True)
        self.status_hint.setMinimumHeight(24)
        self.status_hint.setMaximumHeight(48)
        self.status_hint.setMinimumWidth(0)
        self.status_hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._prepare_button(self.start_button, "primaryButton")
        self._prepare_button(self.stop_button, "dangerButton")
        self._prepare_button(self.scan_button, "secondaryButton")

        self.start_button.clicked.connect(self._handle_start_clicked)
        self.stop_button.clicked.connect(self.service.stop)
        self.scan_button.clicked.connect(self._handle_scan_clicked)

        button_box = QVBoxLayout()
        button_box.setContentsMargins(0, 0, 0, 0)
        button_box.setSpacing(10)
        button_box.addWidget(self.start_button)
        button_box.addWidget(self.stop_button)
        button_box.addWidget(self.scan_button)

        layout.addWidget(self._label("控制中心", "cardTitle"))
        layout.addWidget(self.status_badge)
        layout.addWidget(self.status_hint)
        layout.addLayout(button_box)
        layout.addWidget(self._label("启动后会监听所有监控文件夹；也可以只整理当前选中的文件夹。", "caption", wrap=True))
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
        if hasattr(self.service, "settings_changed"):
            self.service.settings_changed.connect(self._apply_activity_limit)
        if hasattr(self.service, "folders_unavailable"):
            self.service.folders_unavailable.connect(self._notify_unavailable_folders)
        if hasattr(self.service, "auto_duplicate_skipped"):
            self.service.auto_duplicate_skipped.connect(self.notification_manager.aggregate_duplicate_skip)
        if hasattr(self.service, "batch_completed"):
            self.service.batch_completed.connect(self._notify_manual_batch_completed)
        if hasattr(self.service, "conflict_choice_handler"):
            self.service.conflict_choice_handler = self._choose_name_conflict_action
        self.service.error_occurred.connect(self._show_error)

    def _build_menu_bar(self) -> None:
        settings_menu = self.menuBar().addMenu("设置")
        open_settings_action = settings_menu.addAction("打开设置")
        open_settings_action.triggered.connect(self._show_settings)
        help_menu = self.menuBar().addMenu("帮助")
        about_action = help_menu.addAction(f"关于 {APP_NAME}")
        about_action.triggered.connect(self._show_about)

    def _build_system_tray(self) -> None:
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        tray_icon = QApplication.windowIcon()
        if tray_icon.isNull():
            tray_icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)

        self.tray_icon = QSystemTrayIcon(tray_icon, self)
        self.tray_icon.setToolTip(APP_NAME)
        tray_menu = QMenu(self)
        show_action = tray_menu.addAction(f"显示 {APP_NAME}")
        show_action.triggered.connect(self._restore_from_tray)
        tray_menu.addSeparator()
        self.tray_start_action = tray_menu.addAction("开始自动整理")
        self.tray_start_action.triggered.connect(self._handle_start_clicked)
        self.tray_stop_action = tray_menu.addAction("停止自动整理")
        self.tray_stop_action.triggered.connect(self.service.stop)
        settings_action = tray_menu.addAction("打开设置")
        settings_action.triggered.connect(self._open_settings_from_tray)
        tray_menu.addSeparator()
        exit_action = tray_menu.addAction("退出")
        exit_action.triggered.connect(self._exit_application)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._handle_tray_activation)
        if self._tray_available:
            self.tray_icon.show()
        try:
            supports_messages = QSystemTrayIcon.supportsMessages()
        except Exception:
            supports_messages = False
            self.service.logger.exception("Unable to query system tray message support")
        self.service.logger.info(
            "System tray initialized: available=%s, visible=%s, supports_messages=%s",
            self._tray_available,
            self.tray_icon.isVisible(),
            supports_messages,
        )
        self.notification_manager = NotificationManager(
            self.tray_icon,
            self.service.get_settings,
            self._is_main_window_foreground,
            self.service.logger,
        )

    def _is_main_window_foreground(self) -> bool:
        return self.isVisible() and not self.isMinimized() and self.isActiveWindow()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _handle_tray_activation(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_from_tray()

    def _open_settings_from_tray(self) -> None:
        self._restore_from_tray()
        QTimer.singleShot(0, self._show_settings)

    def _exit_application(self) -> None:
        if self._application_exit_requested:
            return
        self._application_exit_requested = True
        self.notification_manager.shutdown()
        self.service.stop()
        self.tray_icon.hide()
        QApplication.quit()

    def _show_settings(self) -> None:
        SettingsDialog(
            self,
            self.service,
            self._clear_recent_activity,
            self._send_test_notification,
        ).exec()

    def _send_test_notification(self) -> str:
        return self.notification_manager.notify(
            "这是一条测试通知。",
            allow_foreground=True,
            bypass_enabled=True,
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"关于 {APP_NAME}",
            about_information_text(),
        )

    def _refresh_from_service(self) -> None:
        self._set_folder(self.service.monitored_folder)
        self._set_status(self.service.is_running)
        self._set_rules(self.service.rules)
        self._set_undo_available(bool(getattr(self.service, "undo_stack", [])))
        for line in self.service.recent_logs:
            self._append_log(line)
        self._refresh_folder_list()

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择监控文件夹", self.service.monitored_folder)
        if folder:
            self.service.set_monitored_folder(folder)

    def _folder_dialog_start_path(self) -> str:
        active_path = str(getattr(self.service, "monitored_folder", "") or "")
        if active_path and Path(active_path).expanduser().exists():
            return active_path
        desktop = Path.home() / "Desktop"
        return str(desktop if desktop.exists() else Path.home())

    def _add_monitored_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择监控文件夹", self._folder_dialog_start_path())
        if not folder:
            return
        try:
            self.service.add_monitored_folder(folder)
        except ValueError as exc:
            QMessageBox.warning(self, "CleanDesk", str(exc))
            return
        self._refresh_folder_list()

    def _select_folder_item(self, item: QListWidgetItem) -> None:
        folder_id = str(item.data(Qt.UserRole) or "")
        if not folder_id:
            return
        try:
            self.service.set_active_folder(folder_id)
        except ValueError as exc:
            QMessageBox.warning(self, "CleanDesk", str(exc))
            self._refresh_folder_list()
            return
        self._refresh_folder_list()

    def _confirm_remove_active_folder(self) -> None:
        folder = self._active_folder()
        if not folder:
            self._refresh_folder_list()
            return
        folder_name = str(folder.get("display_name") or "文件夹")
        box = QMessageBox(self)
        box.setWindowTitle("移除监控文件夹")
        box.setText(f"确定要移除“{folder_name}”吗？\n\n这不会删除文件夹或其中的文件，只会停止 CleanDesk 管理它。")
        remove_button = box.addButton("移除", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(remove_button)
        box.exec()
        if box.clickedButton() != remove_button:
            return
        try:
            self.service.remove_monitored_folder(str(folder.get("id", "")))
        except ValueError as exc:
            QMessageBox.warning(self, "CleanDesk", str(exc))
            return
        self._refresh_folder_list()

    def _active_folder(self) -> dict | None:
        if hasattr(self.service, "get_active_folder"):
            return self.service.get_active_folder()
        folder_path = str(getattr(self.service, "monitored_folder", "") or "")
        return {"id": "", "path": folder_path, "display_name": Path(folder_path).name} if folder_path else None

    def _monitored_folders(self) -> list[dict]:
        if hasattr(self.service, "get_monitored_folders"):
            return self.service.get_monitored_folders()
        active = self._active_folder()
        return [active] if active else []

    def _refresh_folder_list(self) -> None:
        folders = self._monitored_folders()
        active_folder = self._active_folder() or {}
        active_id = str(active_folder.get("id", ""))
        running = bool(getattr(self.service, "is_running", False))

        self.folder_title_label.setText(f"监控文件夹（{len(folders)}）")
        self.folder_caption_label.setText(
            "自动整理运行中。停止后可管理监控文件夹。"
            if running
            else "选择当前要整理的文件夹；开始自动整理后会监听所有文件夹。"
        )
        self.folder_list.clear()
        for folder in folders:
            item = QListWidgetItem()
            folder_id = str(folder.get("id", ""))
            item.setData(Qt.UserRole, folder_id)
            row = FolderListItem(folder, active=(folder_id == active_id))
            item.setSizeHint(row.sizeHint())
            self.folder_list.addItem(item)
            self.folder_list.setItemWidget(item, row)
            if folder_id == active_id:
                self.folder_list.setCurrentItem(item)

        has_folders = bool(folders)
        self.folder_empty_widget.setVisible(not has_folders)
        self.folder_list.setVisible(has_folders)
        self.folder_add_button.setEnabled(not running)
        self.folder_remove_button.setEnabled(has_folders and not running and bool(active_id))
        active_path = str(getattr(self.service, "monitored_folder", "") or "")
        active_exists = bool(active_path) and Path(active_path).expanduser().exists()
        if hasattr(self, "start_button"):
            self.start_button.setEnabled(not running)
        if hasattr(self, "scan_button"):
            self.scan_button.setEnabled((not has_folders) or active_exists)
        if hasattr(self, "suggestion_button"):
            self.suggestion_button.setEnabled((not has_folders) or active_exists)

    def _add_rule(self) -> None:
        move_rules = [rule for rule in self.service.rules if rule.get("action", "move") != "ignore"]
        dialog = RuleDialog(self, existing_rules=move_rules, monitored_folder=self.service.monitored_folder)
        if dialog.exec() == QDialog.Accepted:
            self.service.add_rule(dialog.rule_data())

    def _edit_rule(self, rule: dict) -> None:
        move_rules = [item for item in self.service.rules if item.get("action", "move") != "ignore"]
        dialog = RuleDialog(self, rule, existing_rules=move_rules, monitored_folder=self.service.monitored_folder)
        if dialog.exec() == QDialog.Accepted:
            self.service.update_rule(rule.get("id", ""), dialog.rule_data())

    def _show_ignore_rules(self) -> None:
        IgnoreRulesDialog(self, self.service).exec()

    def _has_monitored_folders(self) -> bool:
        if hasattr(self.service, "get_monitored_folders"):
            return bool(self.service.get_monitored_folders())
        return bool(getattr(self.service, "monitored_folder", ""))

    def _show_no_folder_prompt(self, message: str) -> None:
        QMessageBox.information(self, "请先添加文件夹", message)

    def _handle_start_clicked(self) -> None:
        if not self._has_monitored_folders():
            self._show_no_folder_prompt("请先添加至少一个监控文件夹，再开始自动整理。")
            return
        self.service.start()

    def _handle_scan_clicked(self) -> None:
        if not self._has_monitored_folders():
            self._show_no_folder_prompt("请先添加一个监控文件夹，再整理当前文件夹。")
            return
        self.service.scan_now()

    def _handle_smart_suggestions_clicked(self) -> None:
        if not self._has_monitored_folders():
            self._show_no_folder_prompt("请先添加一个监控文件夹，再使用智能整理建议。")
            return
        self._show_smart_suggestions()

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
        box = QMessageBox(self)
        box.setWindowTitle("删除整理规则")
        box.setText(f"确定要删除“{rule_name}”吗？\n\n删除后，这条规则不会再用于自动整理。")
        confirm_button = box.addButton("确认", QMessageBox.DestructiveRole)
        cancel_button = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_button)
        box.exec()
        if box.clickedButton() == confirm_button:
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

        batch = undo_stack[-1]
        count = len(batch.get("items", []))
        box = QMessageBox(self)
        box.setWindowTitle("确认撤销")
        box.setText(self._undo_confirmation_text(batch, count))
        undo_button = box.addButton("撤销", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(undo_button)
        box.exec()
        if box.clickedButton() == undo_button:
            self.service.undo_last_batch()

    def _undo_confirmation_text(self, batch: dict, count: int) -> str:
        folder_names = []
        seen_names = set()
        for item in batch.get("items", []):
            if not isinstance(item, dict):
                continue
            folder_name = (
                str(item.get("folder_name") or "").strip()
                or str(item.get("source_folder_name") or "").strip()
                or str(item.get("display_name") or "").strip()
            )
            if not folder_name or folder_name in seen_names:
                continue
            seen_names.add(folder_name)
            folder_names.append(folder_name)

        if len(folder_names) == 1:
            return f"将把“{folder_names[0]}”中上一次整理的 {count} 个文件移回原位置。是否继续？"
        if len(folder_names) > 1:
            return f"将把以下文件夹中上一次整理的 {count} 个文件移回原位置：\n\n{chr(10).join(folder_names)}\n\n是否继续？"
        return f"将把上一次整理的 {count} 个文件移回原位置。是否继续？"

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
            confirm_box = QMessageBox(self)
            confirm_box.setIcon(QMessageBox.Warning)
            confirm_box.setWindowTitle("确认替换")
            confirm_box.setText(f"已有文件“{filename}”会被替换，此操作不可恢复。\n\n确定要替换吗？")
            confirm_button = confirm_box.addButton("确认", QMessageBox.DestructiveRole)
            cancel_button = confirm_box.addButton("取消", QMessageBox.RejectRole)
            confirm_box.setDefaultButton(cancel_button)
            confirm_box.exec()
            return "replace" if confirm_box.clickedButton() == confirm_button else "keep"
        if clicked == skip_button:
            return "skip"
        if clicked == cancel_button:
            return "cancel"
        return "keep"

    def _set_folder(self, folder: str) -> None:
        display = folder or "尚未选择文件夹"
        self.path_label.setText(display)
        self.path_label.setToolTip(display)
        self._refresh_folder_list()

    def _set_status(self, running: bool) -> None:
        self._status_hint_token += 1
        if running:
            self.status_badge.setText("运行中")
            self.status_badge.setProperty("state", "running")
            running_count = 0
            if hasattr(self.service, "get_running_folder_count"):
                running_count = int(self.service.get_running_folder_count())
            self.status_hint.setText(f"正在监听 {running_count} 个文件夹")
        else:
            self.status_badge.setText("已停止")
            self.status_badge.setProperty("state", "stopped")
            self.status_hint.setText("添加或选择文件夹后，可以整理当前文件夹。")

        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

        self.stop_button.setEnabled(running)
        if hasattr(self, "tray_start_action"):
            self.tray_start_action.setEnabled(not running)
            self.tray_stop_action.setEnabled(running)
        self._refresh_folder_list()

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
        self._updating_rules = True
        self.rules_list.clear()
        move_rules = [rule for rule in rules if rule.get("action", "move") != "ignore"]
        total = len(move_rules)
        for index, rule in enumerate(move_rules):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, str(rule.get("id", "")))
            row = RuleListItem(
                rule,
                self._edit_rule,
                self._delete_rule,
                index,
                total,
            )
            item.setSizeHint(row.sizeHint())
            self.rules_list.addItem(item)
            self.rules_list.setItemWidget(item, row)
        self._updating_rules = False
        self._refresh_rule_item_sizes()

    def _save_dragged_rule_order(self, *args) -> None:
        if self._updating_rules:
            return
        rule_ids = [
            str(self.rules_list.item(index).data(Qt.UserRole) or "")
            for index in range(self.rules_list.count())
        ]
        if hasattr(self.service, "reorder_rules"):
            self.service.reorder_rules(rule_ids)

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
        self._apply_activity_limit()
        scrollbar = self.activity_list.verticalScrollBar()
        scrollbar.setValue(scrollbar.minimum())
        self._refresh_activity_empty_state()

    def _clear_recent_activity(self) -> None:
        self.activity_list.clear()
        self._refresh_activity_empty_state()

    def _apply_activity_limit(self, settings: dict | None = None) -> None:
        current_settings = settings
        if current_settings is None and hasattr(self.service, "get_settings"):
            current_settings = self.service.get_settings()
        limit = int((current_settings or {}).get("recent_activity_limit", 50))
        while self.activity_list.count() > limit:
            self.activity_list.takeItem(self.activity_list.count() - 1)
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
        if self._startup_mode and not self.isVisible():
            self._notify_automatic_start_failed(message)
            return
        QMessageBox.warning(self, "CleanDesk", message)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_responsive_layout()

    def closeEvent(self, event) -> None:
        settings = self.service.get_settings() if hasattr(self.service, "get_settings") else {}
        if (
            not self._application_exit_requested
            and settings.get("close_behavior", "exit") == "minimize_to_tray"
            and self._tray_available
        ):
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.notification_manager.notify(
                    "CleanDesk 已最小化到系统托盘。\n你可以从托盘图标重新打开窗口。",
                    allow_foreground=True,
                )
            return
        event.accept()
        self._exit_application()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._finish_initial_show)

    def initialize_hidden_startup(self) -> None:
        self._startup_mode = True
        QTimer.singleShot(0, lambda: self._finish_initial_show(show_welcome=False))

    def _finish_initial_show(self, show_welcome: bool = True) -> None:
        if show_welcome:
            self._show_welcome_if_needed()
        self._schedule_automatic_start()

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

    def _schedule_automatic_start(self) -> None:
        if self._auto_start_scheduled or self._auto_start_attempted:
            return
        settings = self.service.get_settings() if hasattr(self.service, "get_settings") else {}
        if not settings.get("auto_start_organizing", False):
            self._auto_start_attempted = True
            return
        self._auto_start_scheduled = True
        QTimer.singleShot(50, self._run_automatic_start)

    def _run_automatic_start(self) -> None:
        self._auto_start_scheduled = False
        self._auto_start_attempted = True
        if getattr(self.service, "is_running", False):
            return
        if not self._has_monitored_folders():
            self._add_activity(
                {
                    "time": "刚刚",
                    "status": "skipped",
                    "title": "未自动开始整理",
                    "detail": "请先添加监控文件夹。",
                }
            )
            self._notify_automatic_start_failed("没有可用的监控文件夹。")
            return
        self.service.start()
        if self._startup_mode and self.service.is_running and not self._auto_start_success_notified:
            self._auto_start_success_notified = True
            count = int(self.service.get_running_folder_count())
            QTimer.singleShot(
                1000,
                lambda: self.notification_manager.notify(
                    f"自动整理已启动，正在监听 {count} 个文件夹。",
                    allow_foreground=True,
                ),
            )
        elif self._startup_mode and not self.service.is_running:
            self._notify_automatic_start_failed("")

    def _notify_automatic_start_failed(self, reason: str) -> None:
        if self._auto_start_failure_notified:
            return
        self._auto_start_failure_notified = True
        if "没有可用" in str(reason):
            message = "自动整理未启动，没有可用的监控文件夹。"
        else:
            message = "自动整理未启动，请打开 CleanDesk 查看。"
        self.notification_manager.notify(message, allow_foreground=True)

    def _notify_unavailable_folders(self, result: dict) -> None:
        names = [str(name).strip() for name in result.get("names", []) if str(name).strip()]
        if not names:
            return
        valid_count = int(result.get("valid_count", 0))
        if self._startup_mode and not self.isVisible() and not valid_count:
            return
        suffix = "其他文件夹会继续整理。" if valid_count else "请打开 CleanDesk 检查。"
        if len(names) == 1:
            message = f"“{names[0]}”当前不可用，{suffix}"
        else:
            message = f"{len(names)} 个监控文件夹当前不可用，{suffix}"
        self.notification_manager.notify(message, allow_foreground=True)

    def _notify_manual_batch_completed(self, summary: dict) -> None:
        if str(summary.get("mode", "")) != "manual":
            return
        active_folder = self.service.get_active_folder() or {}
        folder_path = str(active_folder.get("path", "")).strip()
        folder_name = str(active_folder.get("display_name", "")).strip()
        if not folder_name and folder_path:
            folder_name = Path(folder_path).name
        folder_name = folder_name or "当前文件夹"

        moved = int(summary.get("moved", 0))
        ignored = int(summary.get("ignored", 0))
        skipped = int(summary.get("skipped", 0))
        if not (moved or ignored or skipped):
            message = f"{folder_name} 暂无需要整理的文件。"
        elif moved and not skipped and not ignored:
            message = f"{folder_name} 整理完成：已整理 {moved} 个文件。"
        elif skipped and not moved and not ignored:
            message = f"{folder_name} 整理完成：{skipped} 个文件因名称重复被跳过。"
        elif ignored and not moved and not skipped:
            message = f"{folder_name} 整理完成：{ignored} 个文件已按规则忽略。"
        else:
            parts = []
            if moved:
                parts.append(f"已整理 {moved} 个")
            if skipped:
                parts.append(f"跳过 {skipped} 个")
            if ignored:
                parts.append(f"忽略 {ignored} 个")
            message = f"{folder_name} 整理完成：{'，'.join(parts)}。"
        self.notification_manager.notify(message)

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
            QFrame#settingsSection {
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
            QListWidget#folderList {
                background: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 10px;
                padding: 6px;
                color: #374151;
                selection-background-color: transparent;
            }
            QListWidget#folderList::item {
                border: none;
            }
            QWidget#folderItem {
                background: transparent;
                border-bottom: 1px solid #E5E7EB;
            }
            QWidget#folderItem[active="true"] {
                background: #EEF4FF;
                border: 1px solid #BFDBFE;
                border-radius: 9px;
            }
            QLabel#folderName {
                color: #111827;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#folderPath {
                color: #6B7280;
                font-size: 11px;
            }
            QLabel#folderBadge {
                color: #2563EB;
                font-size: 11px;
                font-weight: 700;
            }
            QWidget#folderEmptyState {
                background: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 10px;
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
            QWidget#ruleDragHandle {
                background: transparent;
            }
            QFrame#ruleDragLine {
                background: #9CA3AF;
                border: none;
                border-radius: 1px;
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
            QLabel#folderEmptyTitle {
                color: #6B7280;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#folderEmptyHint {
                color: #9CA3AF;
                font-size: 13px;
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
    def __init__(self, rule: dict, edit_callback, delete_callback, index: int, total: int):
        super().__init__()
        self.rule = dict(rule)
        self.edit_callback = edit_callback
        self.delete_callback = delete_callback
        self.setObjectName("ruleItem")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(0)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        drag_handle = QWidget()
        drag_handle.setObjectName("ruleDragHandle")
        drag_handle.setFixedWidth(24)
        drag_handle.setFixedHeight(28)
        drag_handle.setCursor(Qt.OpenHandCursor)
        drag_handle.setToolTip("拖动调整规则顺序")
        drag_layout = QVBoxLayout(drag_handle)
        drag_layout.setContentsMargins(5, 5, 5, 5)
        drag_layout.setSpacing(3)
        drag_layout.addStretch(1)
        for _ in range(3):
            line = QFrame()
            line.setObjectName("ruleDragLine")
            line.setFixedSize(14, 2)
            line.setFrameShape(QFrame.NoFrame)
            drag_layout.addWidget(line, 0, Qt.AlignCenter)
        drag_layout.addStretch(1)

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

        row.addWidget(drag_handle, 0, Qt.AlignVCenter)
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


class FolderListItem(QWidget):
    def __init__(self, folder: dict, active: bool = False):
        super().__init__()
        self.setObjectName("folderItem")
        self.setProperty("active", "true" if active else "false")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(3)

        name = QLabel(str(folder.get("display_name") or "文件夹"))
        name.setObjectName("folderName")
        name.setWordWrap(True)
        name.setMinimumWidth(0)
        name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        path = QLabel(str(folder.get("path") or ""))
        path.setObjectName("folderPath")
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path.setMinimumWidth(0)
        path.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        text_box.addWidget(name)
        text_box.addWidget(path)
        layout.addLayout(text_box, 1)

        if active:
            badge = QLabel("当前")
            badge.setObjectName("folderBadge")
            badge.setAlignment(Qt.AlignRight | Qt.AlignTop)
            badge.setFixedWidth(36)
            layout.addWidget(badge, 0, Qt.AlignTop)


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

        detail = self._detail_text(activity)
        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("activityDetail")
            detail_label.setWordWrap(True)
            detail_label.setMinimumWidth(0)
            detail_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            layout.addWidget(detail_label)

        if activity.get("status") in {"success", "ignored"} and activity.get("target_path") and open_callback:
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

    def _detail_text(self, activity: dict) -> str:
        parts = []
        source_name = str(activity.get("source_folder_name", "")).strip()
        if source_name:
            parts.append(f"来自：{source_name}")
        detail = str(activity.get("detail", "")).strip()
        if detail:
            parts.append(detail)
        return "\n".join(parts)


class SettingsDialog(QDialog):
    def __init__(self, parent, service, clear_activity_callback, test_notification_callback=None):
        super().__init__(parent)
        self.service = service
        self.clear_activity_callback = clear_activity_callback
        self.test_notification_callback = test_notification_callback
        self.setWindowTitle("设置")
        self.setMinimumSize(640, 600)
        self.resize(680, 640)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(20, 20, 20, 16)
        page_layout.setSpacing(12)

        page_layout.addWidget(self._general_section())
        page_layout.addWidget(self._organizing_section())
        page_layout.addWidget(self._activity_section())
        page_layout.addWidget(self._about_section())
        page_layout.addStretch(1)
        scroll.setWidget(page)
        outer_layout.addWidget(scroll, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(20, 12, 20, 20)
        actions.addStretch(1)
        save_button = QPushButton("保存")
        save_button.setObjectName("primaryButton")
        save_button.setFixedHeight(BUTTON_HEIGHT)
        save_button.setDefault(True)
        save_button.clicked.connect(self._save_settings)
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("secondaryButton")
        cancel_button.setFixedHeight(BUTTON_HEIGHT)
        cancel_button.clicked.connect(self.reject)
        actions.addWidget(save_button)
        actions.addWidget(cancel_button)
        outer_layout.addLayout(actions)

        self._load_settings()

    def _section(self, title: str, description: str = "") -> tuple[QFrame, QVBoxLayout]:
        section = QFrame()
        section.setObjectName("settingsSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        layout.addWidget(title_label)
        if description:
            hint = QLabel(description)
            hint.setObjectName("caption")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        return section, layout

    def _setting_row(self, label_text: str, control: QWidget, description: str = "") -> QWidget:
        row = QWidget()
        row.setMinimumWidth(0)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(5)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)
        label = QLabel(label_text)
        label.setMinimumWidth(0)
        label.setWordWrap(True)
        top.addWidget(label, 1)
        control.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        top.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        layout.addLayout(top)
        if description:
            detail = QLabel(description)
            detail.setObjectName("caption")
            detail.setWordWrap(True)
            detail.setMinimumWidth(0)
            layout.addWidget(detail)
        return row

    def _general_section(self) -> QFrame:
        section, layout = self._section("常规")
        self.auto_start_input = QCheckBox("启用")
        layout.addWidget(
            self._setting_row(
                "启动后自动整理",
                self.auto_start_input,
                "打开 CleanDesk 后，自动开始监听已添加的文件夹。\n将在下次启动时生效。",
            )
        )
        self.scan_existing_input = QCheckBox("启用")
        layout.addWidget(
            self._setting_row(
                "开始时整理已有文件",
                self.scan_existing_input,
                "开始自动整理时，先处理文件夹中已经存在的文件。\n关闭后，只整理之后新增的文件。",
            )
        )
        self.close_behavior_input = QComboBox()
        self.close_behavior_input.addItem("直接退出", "exit")
        self.close_behavior_input.addItem("最小化到系统托盘", "minimize_to_tray")
        layout.addWidget(
            self._setting_row(
                "关闭窗口时",
                self.close_behavior_input,
                "选择“最小化到系统托盘”后，点击关闭按钮不会退出 CleanDesk，自动整理会继续运行。",
            )
        )
        self.launch_at_login_input = QCheckBox("启用")
        layout.addWidget(
            self._setting_row(
                "开机自动启动",
                self.launch_at_login_input,
                "登录 Windows 后自动启动 CleanDesk。",
            )
        )
        self.notifications_input = QCheckBox("启用")
        notification_controls = QWidget()
        notification_controls_layout = QHBoxLayout(notification_controls)
        notification_controls_layout.setContentsMargins(0, 0, 0, 0)
        notification_controls_layout.setSpacing(8)
        notification_controls_layout.addWidget(self.notifications_input)
        test_notification_button = QPushButton("发送测试通知")
        test_notification_button.setObjectName("secondaryButton")
        test_notification_button.setFixedHeight(32)
        test_notification_button.clicked.connect(self._send_test_notification)
        notification_controls_layout.addWidget(test_notification_button)
        layout.addWidget(
            self._setting_row(
                "后台通知",
                notification_controls,
                "在整理完成、启动失败或文件夹不可用时显示通知。",
            )
        )
        return section

    def _organizing_section(self) -> QFrame:
        section, layout = self._section("整理")
        self.manual_duplicate_input = QComboBox()
        self.manual_duplicate_input.addItem("每次询问", "ask")
        self.manual_duplicate_input.addItem("自动保留两个", "keep_both")
        self.manual_duplicate_input.addItem("自动跳过", "skip")
        layout.addWidget(
            self._setting_row(
                "手动整理遇到同名文件",
                self.manual_duplicate_input,
                "适用于“整理当前文件夹”和开始自动整理前的已有文件。",
            )
        )
        self.auto_duplicate_input = QComboBox()
        self.auto_duplicate_input.addItem("自动保留两个", "keep_both")
        self.auto_duplicate_input.addItem("自动跳过", "skip")
        layout.addWidget(
            self._setting_row(
                "自动整理遇到同名文件",
                self.auto_duplicate_input,
                "后台自动整理不会弹出确认窗口，避免整理被中断。",
            )
        )
        return section

    def _activity_section(self) -> QFrame:
        section, layout = self._section("最近活动")
        self.activity_limit_input = QComboBox()
        for limit in (50, 100, 200):
            self.activity_limit_input.addItem(str(limit), limit)
        layout.addWidget(
            self._setting_row(
                "最多保留",
                self.activity_limit_input,
                "保存后，首页只保留最近的活动记录。",
            )
        )
        clear_button = QPushButton("清空最近活动")
        clear_button.setObjectName("secondaryButton")
        clear_button.setFixedHeight(BUTTON_HEIGHT)
        clear_button.clicked.connect(self._confirm_clear_activity)
        layout.addWidget(
            self._setting_row(
                "清空最近活动",
                clear_button,
                "只清空首页显示，不会删除详细日志，也不会影响撤销。",
            )
        )
        return section

    def _about_section(self) -> QFrame:
        section, layout = self._section("关于")
        information = QLabel(about_information_text())
        information.setObjectName("caption")
        information.setWordWrap(True)
        information.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(information)
        return section

    def _load_settings(self) -> None:
        settings = self.service.get_settings()
        self.auto_start_input.setChecked(bool(settings.get("auto_start_organizing", False)))
        self.scan_existing_input.setChecked(bool(settings.get("scan_existing_on_start", True)))
        self._set_combo_value(self.manual_duplicate_input, settings.get("manual_duplicate_policy", "ask"))
        self._set_combo_value(self.auto_duplicate_input, settings.get("auto_duplicate_policy", "keep_both"))
        self._set_combo_value(self.activity_limit_input, settings.get("recent_activity_limit", 50))
        self._set_combo_value(self.close_behavior_input, settings.get("close_behavior", "exit"))
        self.notifications_input.setChecked(bool(settings.get("notifications_enabled", True)))
        self._launch_at_login_enabled = is_launch_at_login_enabled()
        self._launch_at_login_registered = has_launch_at_login_entry()
        self.launch_at_login_input.setChecked(self._launch_at_login_enabled)

    def _set_combo_value(self, combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _save_settings(self) -> None:
        launch_at_login = self.launch_at_login_input.isChecked()
        system_state_changed = launch_at_login != self._launch_at_login_enabled
        if not launch_at_login and self._launch_at_login_registered:
            system_state_changed = True
        try:
            if system_state_changed:
                set_launch_at_login_enabled(launch_at_login)
            self.service.update_settings(
                {
                    "auto_start_organizing": self.auto_start_input.isChecked(),
                    "scan_existing_on_start": self.scan_existing_input.isChecked(),
                    "manual_duplicate_policy": self.manual_duplicate_input.currentData(),
                    "auto_duplicate_policy": self.auto_duplicate_input.currentData(),
                    "recent_activity_limit": self.activity_limit_input.currentData(),
                    "close_behavior": self.close_behavior_input.currentData(),
                    "launch_at_login": launch_at_login,
                    "notifications_enabled": self.notifications_input.isChecked(),
                }
            )
        except (StartupError, OSError) as exc:
            if system_state_changed:
                try:
                    set_launch_at_login_enabled(self._launch_at_login_enabled)
                except (StartupError, OSError):
                    pass
            QMessageBox.warning(self, "无法保存开机启动设置", str(exc) or "请稍后重试。")
            return
        self.accept()

    def _send_test_notification(self) -> None:
        if not self.notifications_input.isChecked():
            QMessageBox.information(self, "后台通知", "请先启用后台通知。")
            return
        try:
            result = self.test_notification_callback() if callable(self.test_notification_callback) else NOTIFICATION_FAILED
        except Exception:
            result = NOTIFICATION_FAILED
        if result == NOTIFICATION_SHOWN:
            return
        messages = {
            NOTIFICATION_DISABLED: "请先启用后台通知。",
            NOTIFICATION_TRAY_UNAVAILABLE: "系统托盘当前不可用，无法显示通知。",
            NOTIFICATION_UNSUPPORTED: "当前系统环境不支持托盘通知。",
            NOTIFICATION_FAILED: "测试通知发送失败，请稍后重试。",
        }
        QMessageBox.warning(self, "后台通知", messages.get(result, "测试通知发送失败，请稍后重试。"))

    def _confirm_clear_activity(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("清空最近活动")
        box.setText("确定要清空首页显示的最近活动吗？\n这不会删除详细日志，也不会影响撤销上一次整理。")
        confirm_button = box.addButton("确认", QMessageBox.DestructiveRole)
        cancel_button = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_button)
        box.exec()
        if box.clickedButton() == confirm_button:
            self.clear_activity_callback()
            completed_box = QMessageBox(self)
            completed_box.setWindowTitle("清理完成")
            completed_box.setText("最近活动已清空。")
            completed_button = completed_box.addButton("确定", QMessageBox.AcceptRole)
            completed_box.setDefaultButton(completed_button)
            completed_box.exec()


class IgnoreRulesDialog(QDialog):
    def __init__(self, parent, service):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("忽略规则")
        self.setMinimumSize(600, 430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("忽略规则")
        title.setObjectName("cardTitle")
        description = QLabel("符合忽略规则的文件会保留在原位置，不会被自动整理。")
        description.setObjectName("caption")
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("rulesList")
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setWordWrap(True)
        layout.addWidget(self.list_widget, 1)

        buttons = QHBoxLayout()
        add_button = QPushButton("+ 新增忽略规则")
        add_button.setObjectName("secondaryButton")
        add_button.setFixedHeight(BUTTON_HEIGHT)
        add_button.clicked.connect(self._add_rule)
        close_button = QPushButton("关闭")
        close_button.setObjectName("secondaryButton")
        close_button.setFixedHeight(BUTTON_HEIGHT)
        close_button.clicked.connect(self.accept)
        buttons.addWidget(add_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.service.rules_changed.connect(self._refresh)
        self._refresh(self.service.rules)

    def _refresh(self, rules: list[dict]) -> None:
        self.list_widget.clear()
        ignore_rules = [rule for rule in rules if rule.get("action", "move") == "ignore"]
        if not ignore_rules:
            item = QListWidgetItem("还没有忽略规则。")
            item.setFlags(Qt.NoItemFlags)
            item.setTextAlignment(Qt.AlignCenter)
            self.list_widget.addItem(item)
            return
        for rule in ignore_rules:
            item = QListWidgetItem()
            row = IgnoreRuleListItem(rule, self._edit_rule, self._delete_rule)
            item.setSizeHint(row.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)

    def _add_rule(self) -> None:
        dialog = IgnoreRuleDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.service.add_ignore_rule(dialog.rule_data())

    def _edit_rule(self, rule: dict) -> None:
        dialog = IgnoreRuleDialog(self, rule)
        if dialog.exec() == QDialog.Accepted:
            self.service.update_ignore_rule(str(rule.get("id", "")), dialog.rule_data())

    def _delete_rule(self, rule: dict) -> None:
        name = natural_rule_name(rule)
        box = QMessageBox(self)
        box.setWindowTitle("删除忽略规则")
        box.setText(f"确定要删除“{name}”吗？\n删除后，符合此规则的文件可能会被其他规则整理。")
        confirm = box.addButton("确认", QMessageBox.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() == confirm:
            self.service.delete_ignore_rule(str(rule.get("id", "")))


class IgnoreRuleListItem(QWidget):
    def __init__(self, rule: dict, edit_callback, delete_callback):
        super().__init__()
        self.setObjectName("ruleItem")
        self.setMinimumWidth(0)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(3)
        name = QLabel(natural_rule_name(rule))
        name.setObjectName("ruleName")
        condition = QLabel(natural_rule_condition(rule))
        condition.setObjectName("ruleMeta")
        condition.setWordWrap(True)
        result = QLabel("忽略，不整理")
        result.setObjectName("ruleTarget")
        text.addWidget(name)
        text.addWidget(condition)
        text.addWidget(result)
        layout.addLayout(text, 1)
        edit = QPushButton("编辑")
        edit.setObjectName("linkButton")
        edit.setFixedSize(40, 26)
        edit.clicked.connect(lambda: edit_callback(dict(rule)))
        delete = QPushButton("删除")
        delete.setObjectName("linkButton")
        delete.setFixedSize(40, 26)
        delete.clicked.connect(lambda: delete_callback(dict(rule)))
        layout.addWidget(edit, 0, Qt.AlignVCenter)
        layout.addWidget(delete, 0, Qt.AlignVCenter)


class IgnoreRuleDialog(QDialog):
    def __init__(self, parent=None, rule: dict | None = None):
        super().__init__(parent)
        self.rule = dict(rule or {})
        self.setWindowTitle("编辑忽略规则" if rule else "新增忽略规则")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        title = QLabel("编辑忽略规则" if rule else "新增忽略规则")
        title.setObjectName("cardTitle")
        hint = QLabel("符合此规则的文件会留在原位置，不会被自动整理。")
        hint.setObjectName("caption")
        hint.setWordWrap(True)
        self.type_input = QComboBox()
        self.type_input.addItem("按文件类型", "extension")
        self.type_input.addItem("按文件名关键词", "name_contains")
        self.type_input.currentIndexChanged.connect(self._sync_fields)
        self.value_label = QLabel()
        self.value_input = QLineEdit()
        self.value_hint = QLabel()
        self.value_hint.setObjectName("fieldHint")
        self.value_error = QLabel()
        self.value_error.setObjectName("fieldError")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("可选，留空时自动生成")
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(QLabel("忽略哪些文件？"))
        layout.addWidget(self.type_input)
        layout.addWidget(self.value_label)
        layout.addWidget(self.value_input)
        layout.addWidget(self.value_hint)
        layout.addWidget(self.value_error)
        layout.addWidget(QLabel("规则名称（可选）"))
        layout.addWidget(self.name_input)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("保存规则")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._load_rule()
        self._sync_fields()

    def _load_rule(self) -> None:
        rule_type = str(self.rule.get("type", "extension"))
        self.type_input.setCurrentIndex(max(0, self.type_input.findData(rule_type)))
        values = self.rule.get("extensions", []) if rule_type == "extension" else self.rule.get("keywords", [])
        self.value_input.setText("，".join(str(value).lstrip(".") if rule_type == "extension" else str(value) for value in values))
        name = str(self.rule.get("name", ""))
        self.name_input.setText("" if name == "Untitled Rule" else name)

    def _sync_fields(self) -> None:
        if self.type_input.currentData() == "extension":
            self.value_label.setText("文件类型")
            self.value_input.setPlaceholderText("例如：tmp, part, crdownload")
            self.value_hint.setText("支持用逗号分隔多个扩展名。")
        else:
            self.value_label.setText("文件名包含的关键词")
            self.value_input.setPlaceholderText("例如：不要整理")
            self.value_hint.setText("支持用逗号分隔多个关键词。")

    def rule_data(self) -> dict:
        rule_type = str(self.type_input.currentData())
        values = split_values(self.value_input.text())
        name = self.name_input.text().strip()
        if not name:
            if rule_type == "extension":
                first = normalize_extension_text(values[0]).lstrip(".").upper() if values else "指定"
                name = "临时文件" if set(value.lower().lstrip(".") for value in values) & {"tmp", "part", "crdownload"} else f"忽略 {first} 文件"
            else:
                name = f"忽略{values[0]}文件" if values else "忽略指定文件"
        data = {"id": self.rule.get("id", ""), "name": name, "type": rule_type, "action": "ignore", "target": "", "enabled": True}
        if rule_type == "extension":
            data["extensions"] = [normalize_extension_text(value) for value in values]
        else:
            data["keywords"] = values
        return data

    def _accept_if_valid(self) -> None:
        if not split_values(self.value_input.text()):
            self.value_error.setText("请至少填写一个文件类型或关键词。")
            return
        self.accept()


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
        self.target_hint = QLabel("可以留空，CleanDesk 会用规则名称或关键词自动生成文件夹名；也可以点击“选择...”选择位置。")
        self.target_hint.setObjectName("fieldHint")
        self.target_hint.setWordWrap(True)
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
        generated_name = auto_rule_name(rule_type, values)
        target = self.target_input.text().strip() or default_rule_target(rule_type, values, name, generated_name)
        rule = {
            "id": self.rule.get("id", ""),
            "name": name or generated_name,
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


def default_rule_target(rule_type: str, values: list[str], name: str, generated_name: str) -> str:
    if name:
        return name
    if rule_type == "name_contains" and values:
        return values[0]
    return generated_name.replace(" ", "")
