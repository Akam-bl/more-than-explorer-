import os
import json
import subprocess
import sys
import zipfile
import tempfile
import shutil
import threading
import math
import platform
import re
import time
import traceback
from datetime import datetime
from collections import defaultdict, deque
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Optional, Any
from enum import Enum

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QLabel, QLineEdit, QPushButton,
    QComboBox, QProgressBar, QSplitter, QFileDialog, QMessageBox,
    QMenu, QAction, QInputDialog, QToolBar, QStatusBar, QCheckBox,
    QGroupBox, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem,
    QScrollArea, QFrame, QGridLayout, QSpinBox, QTabWidget, QRadioButton
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QRect, QPoint, QTimer, QSettings
from PyQt5.QtGui import QIcon, QPalette, QColor, QPainter, QPen, QBrush, QFont


# ==================== СИСТЕМА ОТЧЁТОВ ОБ ОШИБКАХ ====================

class CrashReporter:
    def __init__(self, data_folder):
        self.data_folder = data_folder
        self.crash_file = os.path.join(data_folder, "crashs.json")
        self._ensure_data_folder()
    
    def _ensure_data_folder(self):
        try:
            os.makedirs(self.data_folder, exist_ok=True)
        except:
            pass
    
    def report_error(self, error_type, error_message, stack_trace=None, additional_info=None):
        try:
            crash_data = []
            if os.path.exists(self.crash_file):
                try:
                    with open(self.crash_file, 'r', encoding='utf-8') as f:
                        crash_data = json.load(f)
                except:
                    crash_data = []
            
            report = {
                'timestamp': datetime.now().isoformat(),
                'error_type': error_type,
                'error_message': error_message,
                'stack_trace': stack_trace or traceback.format_exc(),
                'additional_info': additional_info or {},
                'system_info': {
                    'platform': platform.platform(),
                    'python_version': sys.version,
                    'qt_version': QApplication.instance().applicationName()
                }
            }
            crash_data.append(report)
            if len(crash_data) > 50:
                crash_data = crash_data[-50:]
            with open(self.crash_file, 'w', encoding='utf-8') as f:
                json.dump(crash_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Не удалось сохранить отчёт об ошибке: {e}")
    
    def get_recent_crashes(self, count=10):
        try:
            if os.path.exists(self.crash_file):
                with open(self.crash_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data[-count:]
        except:
            pass
        return []
    
    def clear_crashes(self):
        try:
            if os.path.exists(self.crash_file):
                os.remove(self.crash_file)
        except:
            pass


# ==================== КЛАССЫ ДЛЯ УПРАВЛЕНИЯ НАСТРОЙКАМИ ====================

class ToolbarMode(Enum):
    FULL = "full"
    VIEWER = "viewer"
    MINIMAL = "minimal"
    CUSTOM = "custom"


@dataclass
class ToolbarItem:
    id: str
    text: str
    visible: bool = True
    position: int = 0
    is_separator: bool = False


@dataclass
class ToolbarConfig:
    mode: str = "full"
    items: List[Dict] = field(default_factory=list)
    show_toolbar: bool = True
    custom_name: str = ""


@dataclass
class AppSettings:
    main_folder: str = ""
    data_folder: str = ""
    temp_folder: str = tempfile.gettempdir()
    scan_history: List[str] = field(default_factory=list)
    file_history: List[str] = field(default_factory=list)
    unrar_path: str = ""
    archive_extensions: List[str] = field(default_factory=lambda: [".zip", ".rar", ".7z"])
    sort_mode: str = "name_asc"
    hide_duplicates: bool = False
    hide_blockbench_children: bool = True
    dark_mode: bool = False
    auto_load_textures: bool = False
    search_mode: str = "name"
    multicriteria_search: bool = False
    favorites: List[str] = field(default_factory=list)
    virtual_folders: Dict[str, List] = field(default_factory=dict)
    toolbar_configs: Dict[str, Dict] = field(default_factory=dict)
    current_toolbar_mode: str = "full"
    total_scan_time: float = 0
    total_files_scanned: int = 0
    
    def to_dict(self):
        result = {}
        for key, value in self.__dict__.items():
            if key == 'toolbar_configs':
                result[key] = {}
                for name, config in value.items():
                    if isinstance(config, ToolbarConfig):
                        result[key][name] = {
                            'mode': config.mode,
                            'items': config.items,
                            'show_toolbar': config.show_toolbar,
                            'custom_name': config.custom_name
                        }
                    elif isinstance(config, dict):
                        result[key][name] = config
                    else:
                        result[key][name] = {}
            else:
                result[key] = value
        return result
    
    @classmethod
    def from_dict(cls, data):
        instance = cls()
        for key, value in data.items():
            if key == 'toolbar_configs' and isinstance(value, dict):
                instance.toolbar_configs = {}
                for name, config_data in value.items():
                    if isinstance(config_data, dict):
                        instance.toolbar_configs[name] = config_data
                    else:
                        instance.toolbar_configs[name] = {}
            else:
                setattr(instance, key, value)
        return instance


class SettingsManager:
    VERSION = "1.0"
    
    def __init__(self, app_name="Sofil"):
        self.app_name = app_name
        self.settings = AppSettings()
        self.settings_path = self._get_settings_path()
        self.crash_reporter = None
        self.load()
        if self.settings.data_folder:
            self.crash_reporter = CrashReporter(self.settings.data_folder)
    
    def _get_settings_path(self):
        home = os.path.expanduser("~")
        return os.path.join(home, f".{self.app_name.lower()}_settings.json")
    
    def load(self):
        try:
            if os.path.exists(self.settings_path):
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'version' not in data:
                        data = self._migrate_v1(data)
                    self.settings = AppSettings.from_dict(data)
        except Exception as e:
            print(f"Ошибка загрузки настроек: {e}")
            self.report_error("Ошибка загрузки настроек", str(e))
            self.settings = AppSettings()
    
    def save(self):
        try:
            data = self.settings.to_dict()
            data['version'] = self.VERSION
            os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения настроек: {e}")
            self.report_error("Ошибка сохранения настроек", str(e))
    
    def _migrate_v1(self, old_data):
        migrated = AppSettings()
        mapping = {
            'main_folder': 'main_folder',
            'data_folder': 'data_folder',
            'temp_folder': 'temp_folder',
            'scan_history': 'scan_history',
            'unrar_path': 'unrar_path',
            'archive_extensions': 'archive_extensions',
            'sort_mode': 'sort_mode',
            'hide_duplicates': 'hide_duplicates',
            'hide_blockbench_children': 'hide_blockbench_children',
            'dark_mode': 'dark_mode',
            'auto_load_textures': 'auto_load_textures',
            'search_mode': 'search_mode',
            'multicriteria_search': 'multicriteria_search',
            'favorites': 'favorites',
            'virtual_folders': 'virtual_folders'
        }
        for old_key, new_key in mapping.items():
            if old_key in old_data:
                setattr(migrated, new_key, old_data[old_key])
        if 'file_history' not in migrated.__dict__:
            migrated.file_history = []
        migrated.toolbar_configs = {
            'full': {'mode': 'full', 'items': [], 'show_toolbar': True, 'custom_name': ''},
            'viewer': {'mode': 'viewer', 'items': [], 'show_toolbar': True, 'custom_name': ''},
            'minimal': {'mode': 'minimal', 'items': [], 'show_toolbar': True, 'custom_name': ''}
        }
        return migrated.to_dict()
    
    def get_data_folder(self):
        folder = self.settings.data_folder
        if folder and os.path.exists(folder):
            return folder
        return None
    
    def set_data_folder(self, path):
        if path and os.path.exists(path):
            self.settings.data_folder = path
            self.crash_reporter = CrashReporter(path)
            self.save()
            return True
        return False
    
    def report_error(self, error_type, error_message, additional_info=None):
        if self.crash_reporter:
            self.crash_reporter.report_error(error_type, error_message, None, additional_info)
    
    def add_to_scan_history(self, path):
        if not path or not os.path.exists(path):
            return
        if path in self.settings.scan_history:
            self.settings.scan_history.remove(path)
        self.settings.scan_history.insert(0, path)
        self.settings.scan_history = self.settings.scan_history[:20]
        self.settings.main_folder = path
        self.save()
    
    def add_to_file_history(self, path):
        if not path or not os.path.exists(path):
            return
        if path in self.settings.file_history:
            self.settings.file_history.remove(path)
        self.settings.file_history.insert(0, path)
        self.settings.file_history = self.settings.file_history[:50]
        self.save()


# ==================== ТАЙМЕР СКАНИРОВАНИЯ ====================

class ScanTimer(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.start_time = None
        self.elapsed = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_time)
        self.timer.setInterval(100)
        self.setStyleSheet("QLabel { color: #666; padding: 0 10px; }")
        self.reset()
    
    def start(self):
        self.start_time = time.time()
        self.elapsed = 0
        self.timer.start()
        self.update_time()
    
    def stop(self):
        self.timer.stop()
        if self.start_time:
            self.elapsed = time.time() - self.start_time
        self.update_time()
    
    def reset(self):
        self.start_time = None
        self.elapsed = 0
        self.setText("⏱ 0:00.0")
    
    def update_time(self):
        if self.start_time:
            self.elapsed = time.time() - self.start_time
        minutes = int(self.elapsed // 60)
        seconds = int(self.elapsed % 60)
        tenths = int((self.elapsed * 10) % 10)
        self.setText(f"⏱ {minutes}:{seconds:02d}.{tenths}")


# ==================== ДИАЛОГ ПРЕДУПРЕЖДЕНИЯ О ПАПКЕ ====================

class DataFolderWarningDialog(QDialog):
    def __init__(self, parent=None, is_startup=False):
        super().__init__(parent)
        self.is_startup = is_startup
        self.selected_folder = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Предупреждение")
        self.setModal(True)
        self.setFixedSize(500, 200)
        layout = QVBoxLayout()
        warning_label = QLabel("⚠️")
        warning_label.setAlignment(Qt.AlignCenter)
        warning_label.setStyleSheet("QLabel { font-size: 48px; }")
        layout.addWidget(warning_label)
        if self.is_startup:
            message = "Папка для сохранения кэша приложения не указана.\nНекоторые функции могут не сохраниться при перезапуске.\n\nХотите указать папку сейчас?"
        else:
            message = "Вы не указали папку для сохранения кэша приложения.\nНекоторые функции могут не сохраниться при перезапуске.\n\nХотите указать папку?"
        text_label = QLabel(message)
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setWordWrap(True)
        layout.addWidget(text_label)
        button_box = QDialogButtonBox()
        self.yes_button = QPushButton("Да")
        self.yes_button.clicked.connect(self.on_yes)
        button_box.addButton(self.yes_button, QDialogButtonBox.AcceptRole)
        self.no_button = QPushButton("Нет")
        self.no_button.clicked.connect(self.reject)
        button_box.addButton(self.no_button, QDialogButtonBox.RejectRole)
        layout.addWidget(button_box)
        self.setLayout(layout)
    
    def on_yes(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для хранения данных")
        if folder:
            self.selected_folder = folder
            self.accept()


# ==================== РЕДАКТОР ПАНЕЛИ ИНСТРУМЕНТОВ ====================

class ToolbarEditorDialog(QDialog):
    def __init__(self, parent=None, settings_manager=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.current_mode = settings_manager.settings.current_toolbar_mode
        self.toolbar_configs = {}
        for name, config in settings_manager.settings.toolbar_configs.items():
            if isinstance(config, dict):
                self.toolbar_configs[name] = {
                    'mode': config.get('mode', 'full'),
                    'items': config.get('items', []).copy() if config.get('items') else [],
                    'show_toolbar': config.get('show_toolbar', True),
                    'custom_name': config.get('custom_name', '')
                }
            elif isinstance(config, ToolbarConfig):
                self.toolbar_configs[name] = {
                    'mode': config.mode,
                    'items': config.items.copy() if config.items else [],
                    'show_toolbar': config.show_toolbar,
                    'custom_name': config.custom_name
                }
            else:
                self.toolbar_configs[name] = {
                    'mode': 'full',
                    'items': [],
                    'show_toolbar': True,
                    'custom_name': name
                }
        self.available_items = self._get_available_items()
        self.init_ui()
    
    def _get_available_items(self):
        return [
            {'id': 'folder_select', 'text': 'Выбор папки', 'category': 'Основные'},
            {'id': 'scan_buttons', 'text': 'Кнопки сканирования', 'category': 'Основные'},
            {'id': 'undo_redo', 'text': 'Отмена/повтор', 'category': 'Правка'},
            {'id': 'search', 'text': 'Поиск', 'category': 'Поиск'},
            {'id': 'view_options', 'text': 'Параметры просмотра', 'category': 'Вид'},
            {'id': 'sort', 'text': 'Сортировка', 'category': 'Вид'},
            {'id': 'favorites', 'text': 'Избранное', 'category': 'Вид'},
            {'id': 'separator', 'text': '--- Разделитель ---', 'category': 'Служебные', 'is_separator': True}
        ]
    
    def init_ui(self):
        self.setWindowTitle("Настройка панели инструментов")
        self.setModal(True)
        self.setMinimumSize(800, 600)
        layout = QVBoxLayout()
        self.tab_widget = QTabWidget()
        self.preset_tab = self._create_preset_tab()
        self.tab_widget.addTab(self.preset_tab, "Предустановленные")
        self.custom_tab = self._create_custom_tab()
        self.tab_widget.addTab(self.custom_tab, "Пользовательские")
        layout.addWidget(self.tab_widget)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        self.setLayout(layout)
    
    def _create_preset_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        modes_group = QGroupBox("Выберите режим")
        modes_layout = QVBoxLayout()
        self.full_radio = QRadioButton("Полный режим")
        self.full_radio.setToolTip("Все функции приложения")
        modes_layout.addWidget(self.full_radio)
        self.viewer_radio = QRadioButton("Режим просмотра")
        self.viewer_radio.setToolTip("Только основные функции для просмотра")
        modes_layout.addWidget(self.viewer_radio)
        self.minimal_radio = QRadioButton("Минимальный режим")
        self.minimal_radio.setToolTip("Минимальный набор функций")
        modes_layout.addWidget(self.minimal_radio)
        if self.current_mode == 'full':
            self.full_radio.setChecked(True)
        elif self.current_mode == 'viewer':
            self.viewer_radio.setChecked(True)
        elif self.current_mode == 'minimal':
            self.minimal_radio.setChecked(True)
        modes_group.setLayout(modes_layout)
        layout.addWidget(modes_group)
        preview_group = QGroupBox("Предпросмотр")
        preview_layout = QVBoxLayout()
        self.preview_label = QLabel()
        self.preview_label.setMinimumHeight(60)
        self.preview_label.setStyleSheet("""
            QLabel {
                border: 1px solid #ccc;
                background: #f5f5f5;
                padding: 5px;
            }
        """)
        preview_layout.addWidget(self.preview_label)
        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)
        self.full_radio.toggled.connect(self._update_preview)
        self.viewer_radio.toggled.connect(self._update_preview)
        self.minimal_radio.toggled.connect(self._update_preview)
        widget.setLayout(layout)
        self._update_preview()
        return widget
    
    def _create_custom_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        list_group = QGroupBox("Мои режимы")
        list_layout = QVBoxLayout()
        self.custom_list = QListWidget()
        self.custom_list.itemClicked.connect(self._on_custom_item_clicked)
        list_layout.addWidget(self.custom_list)
        btn_layout = QHBoxLayout()
        self.add_custom_btn = QPushButton("➕ Добавить")
        self.add_custom_btn.clicked.connect(self._add_custom_mode)
        btn_layout.addWidget(self.add_custom_btn)
        self.edit_custom_btn = QPushButton("✏️ Редактировать")
        self.edit_custom_btn.clicked.connect(self._edit_custom_mode)
        self.edit_custom_btn.setEnabled(False)
        btn_layout.addWidget(self.edit_custom_btn)
        self.delete_custom_btn = QPushButton("🗑️ Удалить")
        self.delete_custom_btn.clicked.connect(self._delete_custom_mode)
        self.delete_custom_btn.setEnabled(False)
        btn_layout.addWidget(self.delete_custom_btn)
        list_layout.addLayout(btn_layout)
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)
        editor_group = QGroupBox("Редактор элементов")
        editor_layout = QVBoxLayout()
        editor_layout.addWidget(QLabel("Доступные элементы:"))
        self.available_items_list = QListWidget()
        self.available_items_list.setMaximumHeight(150)
        self.available_items_list.itemDoubleClicked.connect(self._add_item_to_custom)
        for item in self.available_items:
            list_item = QListWidgetItem(f"{item['text']}")
            list_item.setData(Qt.UserRole, item)
            self.available_items_list.addItem(list_item)
        editor_layout.addWidget(self.available_items_list)
        editor_layout.addWidget(QLabel("Элементы режима:"))
        self.current_items_list = QListWidget()
        self.current_items_list.setMaximumHeight(150)
        self.current_items_list.itemDoubleClicked.connect(self._remove_item_from_custom)
        editor_layout.addWidget(self.current_items_list)
        move_layout = QHBoxLayout()
        self.move_up_btn = QPushButton("⬆️ Вверх")
        self.move_up_btn.clicked.connect(self._move_item_up)
        move_layout.addWidget(self.move_up_btn)
        self.move_down_btn = QPushButton("⬇️ Вниз")
        self.move_down_btn.clicked.connect(self._move_item_down)
        move_layout.addWidget(self.move_down_btn)
        editor_layout.addLayout(move_layout)
        editor_group.setLayout(editor_layout)
        layout.addWidget(editor_group)
        self._load_custom_modes()
        widget.setLayout(layout)
        return widget
    
    def _load_custom_modes(self):
        self.custom_list.clear()
        for name, config in self.toolbar_configs.items():
            if config.get('mode') == 'custom':
                display_name = config.get('custom_name', name)
                item = QListWidgetItem(f"🔧 {display_name}")
                item.setData(Qt.UserRole, name)
                self.custom_list.addItem(item)
    
    def _on_custom_item_clicked(self, item):
        self.edit_custom_btn.setEnabled(True)
        self.delete_custom_btn.setEnabled(True)
        mode_name = item.data(Qt.UserRole)
        config = self.toolbar_configs.get(mode_name, {})
        if config:
            self.current_items_list.clear()
            for item_data in config.get('items', []):
                list_item = QListWidgetItem(item_data.get('text', ''))
                list_item.setData(Qt.UserRole, item_data)
                self.current_items_list.addItem(list_item)
    
    def _add_custom_mode(self):
        name, ok = QInputDialog.getText(self, "Новый режим", "Введите название режима:")
        if ok and name:
            if name in self.toolbar_configs:
                QMessageBox.warning(self, "Ошибка", "Режим с таким именем уже существует")
                return
            self.toolbar_configs[name] = {
                'mode': 'custom',
                'items': [],
                'show_toolbar': True,
                'custom_name': name
            }
            self._load_custom_modes()
    
    def _edit_custom_mode(self):
        current_item = self.custom_list.currentItem()
        if not current_item:
            return
        mode_name = current_item.data(Qt.UserRole)
        current_config = self.toolbar_configs.get(mode_name, {})
        current_display_name = current_config.get('custom_name', mode_name)
        new_name, ok = QInputDialog.getText(
            self, "Редактировать", "Введите новое название:",
            text=current_display_name
        )
        if ok and new_name and new_name != mode_name:
            if new_name in self.toolbar_configs and new_name != mode_name:
                QMessageBox.warning(self, "Ошибка", "Режим с таким именем уже существует")
                return
            config = self.toolbar_configs.pop(mode_name)
            config['custom_name'] = new_name
            self.toolbar_configs[new_name] = config
            self._load_custom_modes()
    
    def _delete_custom_mode(self):
        current_item = self.custom_list.currentItem()
        if not current_item:
            return
        mode_name = current_item.data(Qt.UserRole)
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить режим '{mode_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if mode_name in self.toolbar_configs:
                del self.toolbar_configs[mode_name]
                self._load_custom_modes()
                self.current_items_list.clear()
                self.edit_custom_btn.setEnabled(False)
                self.delete_custom_btn.setEnabled(False)
    
    def _add_item_to_custom(self, item):
        current_mode_item = self.custom_list.currentItem()
        if not current_mode_item:
            QMessageBox.warning(self, "Ошибка", "Сначала выберите режим для редактирования")
            return
        item_data = item.data(Qt.UserRole)
        new_item = item_data.copy()
        list_item = QListWidgetItem(new_item['text'])
        list_item.setData(Qt.UserRole, new_item)
        self.current_items_list.addItem(list_item)
        mode_name = current_mode_item.data(Qt.UserRole)
        if mode_name in self.toolbar_configs:
            if 'items' not in self.toolbar_configs[mode_name]:
                self.toolbar_configs[mode_name]['items'] = []
            self.toolbar_configs[mode_name]['items'].append(new_item)
    
    def _remove_item_from_custom(self, item):
        current_mode_item = self.custom_list.currentItem()
        if not current_mode_item:
            return
        row = self.current_items_list.row(item)
        self.current_items_list.takeItem(row)
        mode_name = current_mode_item.data(Qt.UserRole)
        if mode_name in self.toolbar_configs:
            items = self.toolbar_configs[mode_name].get('items', [])
            if row < len(items):
                del items[row]
                self.toolbar_configs[mode_name]['items'] = items
    
    def _move_item_up(self):
        current = self.current_items_list.currentItem()
        if not current:
            return
        row = self.current_items_list.row(current)
        if row <= 0:
            return
        item = self.current_items_list.takeItem(row)
        self.current_items_list.insertItem(row - 1, item)
        self.current_items_list.setCurrentItem(item)
        current_mode_item = self.custom_list.currentItem()
        if current_mode_item:
            mode_name = current_mode_item.data(Qt.UserRole)
            if mode_name in self.toolbar_configs:
                items = self.toolbar_configs[mode_name].get('items', [])
                if row < len(items):
                    items[row - 1], items[row] = items[row], items[row - 1]
                    self.toolbar_configs[mode_name]['items'] = items
    
    def _move_item_down(self):
        current = self.current_items_list.currentItem()
        if not current:
            return
        row = self.current_items_list.row(current)
        if row >= self.current_items_list.count() - 1:
            return
        item = self.current_items_list.takeItem(row)
        self.current_items_list.insertItem(row + 1, item)
        self.current_items_list.setCurrentItem(item)
        current_mode_item = self.custom_list.currentItem()
        if current_mode_item:
            mode_name = current_mode_item.data(Qt.UserRole)
            if mode_name in self.toolbar_configs:
                items = self.toolbar_configs[mode_name].get('items', [])
                if row + 1 < len(items):
                    items[row], items[row + 1] = items[row + 1], items[row]
                    self.toolbar_configs[mode_name]['items'] = items
    
    def _update_preview(self):
        if self.full_radio.isChecked():
            preview = "🔍 Поиск | 📁 Папка | 🔄 Сканировать | ↩️ Отмена | ↪️ Повтор | ⭐ Избранное | 📊 Сортировка"
            self.current_mode = 'full'
        elif self.viewer_radio.isChecked():
            preview = "🔍 Поиск | 📁 Папка | ⭐ Избранное"
            self.current_mode = 'viewer'
        elif self.minimal_radio.isChecked():
            preview = "📁 Папка | 🔄 Сканировать"
            self.current_mode = 'minimal'
        self.preview_label.setText(preview)
    
    def get_result(self):
        return {
            'mode': self.current_mode,
            'configs': self.toolbar_configs
        }


# ==================== КАСТОМНАЯ ПАНЕЛЬ ИНСТРУМЕНТОВ ====================

class CustomToolBar(QToolBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.config = None
        self.items = {}
    
    def apply_config(self, config):
        if isinstance(config, dict):
            self.config = ToolbarConfig(
                mode=config.get('mode', 'full'),
                items=config.get('items', []),
                show_toolbar=config.get('show_toolbar', True),
                custom_name=config.get('custom_name', '')
            )
        elif isinstance(config, ToolbarConfig):
            self.config = config
        else:
            self.config = ToolbarConfig()
        self.clear()
        self.items.clear()
        if not self.config.show_toolbar:
            self.hide()
            return
        self.show()
        try:
            if self.config.mode == 'full':
                self._build_full_toolbar()
            elif self.config.mode == 'viewer':
                self._build_viewer_toolbar()
            elif self.config.mode == 'minimal':
                self._build_minimal_toolbar()
            elif self.config.mode == 'custom':
                self._build_custom_toolbar(self.config.items)
            else:
                self._build_minimal_toolbar()
        except Exception as e:
            print(f"Ошибка при построении панели инструментов: {e}")
            self._build_minimal_toolbar()
    
    def _build_full_toolbar(self):
        self.addWidget(QLabel("Папка:"))
        if hasattr(self.parent_app, 'folder_combo'):
            self.items['folder_combo'] = self.parent_app.folder_combo
            self.addWidget(self.parent_app.folder_combo)
        if hasattr(self.parent_app, 'browse_folder_btn'):
            self.addWidget(self.parent_app.browse_folder_btn)
        if hasattr(self.parent_app, 'browse_archive_btn'):
            self.addWidget(self.parent_app.browse_archive_btn)
        self.addSeparator()
        if hasattr(self.parent_app, 'undo_btn'):
            self.items['undo_btn'] = self.parent_app.undo_btn
            self.addWidget(self.parent_app.undo_btn)
        if hasattr(self.parent_app, 'redo_btn'):
            self.items['redo_btn'] = self.parent_app.redo_btn
            self.addWidget(self.parent_app.redo_btn)
        self.addSeparator()
        self.addWidget(QLabel("Поиск:"))
        if hasattr(self.parent_app, 'search_mode_btn'):
            self.items['search_mode_btn'] = self.parent_app.search_mode_btn
            self.addWidget(self.parent_app.search_mode_btn)
        if hasattr(self.parent_app, 'multicriteria_btn'):
            self.items['multicriteria_btn'] = self.parent_app.multicriteria_btn
            self.addWidget(self.parent_app.multicriteria_btn)
        if hasattr(self.parent_app, 'search_input'):
            self.items['search_input'] = self.parent_app.search_input
            self.addWidget(self.parent_app.search_input)
        self.addSeparator()
        self.addWidget(QLabel("Вид:"))
        if hasattr(self.parent_app, 'hide_duplicates_cb'):
            self.items['hide_duplicates_cb'] = self.parent_app.hide_duplicates_cb
            self.addWidget(self.parent_app.hide_duplicates_cb)
        self.addSeparator()
        if hasattr(self.parent_app, 'sort_btn'):
            self.items['sort_btn'] = self.parent_app.sort_btn
            self.addWidget(self.parent_app.sort_btn)
        if hasattr(self.parent_app, 'favorites_btn'):
            self.items['favorites_btn'] = self.parent_app.favorites_btn
            self.addWidget(self.parent_app.favorites_btn)
        self.addSeparator()
        if hasattr(self.parent_app, 'scan_btn'):
            self.items['scan_btn'] = self.parent_app.scan_btn
            self.addWidget(self.parent_app.scan_btn)
    
    def _build_viewer_toolbar(self):
        self.addWidget(QLabel("Папка:"))
        if hasattr(self.parent_app, 'folder_combo'):
            self.items['folder_combo'] = self.parent_app.folder_combo
            self.addWidget(self.parent_app.folder_combo)
        if hasattr(self.parent_app, 'browse_folder_btn'):
            self.addWidget(self.parent_app.browse_folder_btn)
        self.addSeparator()
        self.addWidget(QLabel("Поиск:"))
        if hasattr(self.parent_app, 'search_input'):
            self.items['search_input'] = self.parent_app.search_input
            self.addWidget(self.parent_app.search_input)
        self.addSeparator()
        if hasattr(self.parent_app, 'favorites_btn'):
            self.items['favorites_btn'] = self.parent_app.favorites_btn
            self.addWidget(self.parent_app.favorites_btn)
        self.addSeparator()
        if hasattr(self.parent_app, 'scan_btn'):
            self.items['scan_btn'] = self.parent_app.scan_btn
            self.addWidget(self.parent_app.scan_btn)
    
    def _build_minimal_toolbar(self):
        self.addWidget(QLabel("Папка:"))
        if hasattr(self.parent_app, 'folder_combo'):
            self.items['folder_combo'] = self.parent_app.folder_combo
            self.addWidget(self.parent_app.folder_combo)
        if hasattr(self.parent_app, 'browse_folder_btn'):
            self.addWidget(self.parent_app.browse_folder_btn)
        self.addSeparator()
        if hasattr(self.parent_app, 'scan_btn'):
            self.items['scan_btn'] = self.parent_app.scan_btn
            self.addWidget(self.parent_app.scan_btn)
    
    def _build_custom_toolbar(self, items):
        for item_data in items:
            try:
                if not isinstance(item_data, dict):
                    continue
                item_id = item_data.get('id')
                if item_data.get('is_separator'):
                    self.addSeparator()
                    continue
                if item_id == 'folder_select':
                    self.addWidget(QLabel("Папка:"))
                    if hasattr(self.parent_app, 'folder_combo'):
                        self.addWidget(self.parent_app.folder_combo)
                    if hasattr(self.parent_app, 'browse_folder_btn'):
                        self.addWidget(self.parent_app.browse_folder_btn)
                    if hasattr(self.parent_app, 'browse_archive_btn'):
                        self.addWidget(self.parent_app.browse_archive_btn)
                elif item_id == 'scan_buttons':
                    if hasattr(self.parent_app, 'scan_btn'):
                        self.addWidget(self.parent_app.scan_btn)
                elif item_id == 'undo_redo':
                    if hasattr(self.parent_app, 'undo_btn'):
                        self.addWidget(self.parent_app.undo_btn)
                    if hasattr(self.parent_app, 'redo_btn'):
                        self.addWidget(self.parent_app.redo_btn)
                elif item_id == 'search':
                    self.addWidget(QLabel("Поиск:"))
                    if hasattr(self.parent_app, 'search_mode_btn'):
                        self.addWidget(self.parent_app.search_mode_btn)
                    if hasattr(self.parent_app, 'multicriteria_btn'):
                        self.addWidget(self.parent_app.multicriteria_btn)
                    if hasattr(self.parent_app, 'search_input'):
                        self.addWidget(self.parent_app.search_input)
                elif item_id == 'view_options':
                    self.addWidget(QLabel("Вид:"))
                    if hasattr(self.parent_app, 'hide_duplicates_cb'):
                        self.addWidget(self.parent_app.hide_duplicates_cb)
                elif item_id == 'sort':
                    if hasattr(self.parent_app, 'sort_btn'):
                        self.addWidget(self.parent_app.sort_btn)
                elif item_id == 'favorites':
                    if hasattr(self.parent_app, 'favorites_btn'):
                        self.addWidget(self.parent_app.favorites_btn)
            except Exception as e:
                print(f"Ошибка при добавлении элемента {item_data.get('id', 'unknown')}: {e}")
                continue


# ==================== ПОТОК СКАНИРОВАНИЯ ====================

class ScanThread(QThread):
    progress_update = pyqtSignal(str, int)
    scan_complete = pyqtSignal(list, dict, set, dict, dict, float)
    error = pyqtSignal(str)
    
    def __init__(self, folder_path, settings):
        super().__init__()
        self.folder_path = folder_path
        self.settings = settings
        self.stop_flag = False
        self.start_time = None
        
    def run(self):
        try:
            self.start_time = time.time()
            all_files = []
            extension_data = defaultdict(list)
            available_extensions = set()
            all_folders = set()
            duplicate_files = defaultdict(list)
            if os.path.isfile(self.folder_path):
                self.scan_archive(self.folder_path, all_files, extension_data, available_extensions)
            else:
                self.scan_real_folder(self.folder_path, all_files, extension_data, available_extensions, all_folders)
            file_groups = defaultdict(list)
            for file_info in all_files:
                key = file_info['name']
                file_groups[key].append(file_info)
            for filename, files in file_groups.items():
                if len(files) > 1:
                    duplicate_files[filename] = files
            scan_time = time.time() - self.start_time
            self.scan_complete.emit(all_files, extension_data, available_extensions, 
                                   duplicate_files, dict(file_groups), scan_time)
        except Exception as e:
            self.error.emit(str(e))
    
    def scan_real_folder(self, folder_path, all_files, extension_data, available_extensions, all_folders):
        total_files = 0
        for root, dirs, files in os.walk(folder_path):
            total_files += len(files)
        processed = 0
        for root, dirs, files in os.walk(folder_path):
            if self.stop_flag:
                break
            for dir_name in dirs:
                full_dir_path = os.path.join(root, dir_name)
                all_folders.add(full_dir_path)
            for file in files:
                if self.stop_flag:
                    break
                processed += 1
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, folder_path)
                try:
                    file_size = os.path.getsize(file_path)
                    modified_time = os.path.getmtime(file_path)
                except (OSError, IOError):
                    file_size = 0
                    modified_time = 0
                file_info = {
                    'name': file,
                    'path': file_path,
                    'relative_path': relative_path,
                    'size': file_size,
                    'modified': datetime.fromtimestamp(modified_time),
                    'is_favorite': file_path in self.settings.get("favorites", []),
                    'extension': os.path.splitext(file)[1].lower() or "(без расширения)",
                    'has_parent': False
                }
                if file_info['extension'] in ['.json', '.bbmodel']:
                    file_info['has_parent'] = self.check_file_has_parent(file_path)
                all_files.append(file_info)
                ext = file_info['extension']
                if ext:
                    available_extensions.add(ext)
                    extension_data[ext].append(file_info)
                if processed % 100 == 0:
                    progress = int((processed / total_files) * 100) if total_files > 0 else 0
                    self.progress_update.emit(f"Сканирование... {processed}/{total_files} файлов", progress)
    
    def check_file_has_parent(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return '"parent":' in content
        except:
            return False
    
    def scan_archive(self, archive_path, all_files, extension_data, available_extensions):
        if archive_path.lower().endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                file_list = zip_ref.infolist()
                total_files = len([f for f in file_list if not f.is_dir()])
                processed = 0
                for file_info in file_list:
                    if not file_info.is_dir():
                        processed += 1
                        file_name = os.path.basename(file_info.filename)
                        file_path = file_info.filename
                        file_data = {
                            'name': file_name,
                            'path': file_path,
                            'relative_path': file_path,
                            'archive_path': archive_path,
                            'size': file_info.file_size,
                            'modified': datetime(*file_info.date_time[:6]),
                            'is_favorite': False,
                            'extension': os.path.splitext(file_name)[1].lower() or "(без расширения)",
                            'has_parent': False
                        }
                        if file_data['extension'] in ['.json', '.bbmodel']:
                            try:
                                with zip_ref.open(file_info.filename) as f:
                                    content = f.read().decode('utf-8')
                                    file_data['has_parent'] = '"parent":' in content
                            except:
                                pass
                        all_files.append(file_data)
                        ext = file_data['extension']
                        if ext:
                            available_extensions.add(ext)
                            extension_data[ext].append(file_data)
                        if processed % 50 == 0:
                            progress = int((processed / total_files) * 100) if total_files > 0 else 0
                            self.progress_update.emit(f"Сканирование архива... {processed}/{total_files} файлов", progress)
    
    def stop(self):
        self.stop_flag = True


class QTreeWidgetItemIterator:
    def __init__(self, tree_widget):
        self.tree_widget = tree_widget
        self.current_index = -1
        self.all_items = []
        self._collect_items(tree_widget.invisibleRootItem())
    
    def _collect_items(self, parent):
        for i in range(parent.childCount()):
            child = parent.child(i)
            self.all_items.append(child)
            self._collect_items(child)
    
    def __iter__(self):
        return self
    
    def __next__(self):
        self.current_index += 1
        if self.current_index < len(self.all_items):
            return self.all_items[self.current_index]
        raise StopIteration
    
    def value(self):
        if 0 <= self.current_index < len(self.all_items):
            return self.all_items[self.current_index]
        return None


class CustomTreeWidget(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        self.drag_select_start = None
        self.drag_select_rect = None
        self.is_drag_selecting = False
        self.drag_select_items = []
        self.last_selection = []
        self.last_clicked_item = None
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            self.last_selection = self.selectedItems()[:]
            self.last_clicked_item = item
            if event.modifiers() & Qt.ControlModifier:
                if item:
                    if item in self.last_selection:
                        item.setSelected(False)
                    else:
                        item.setSelected(True)
                    event.accept()
                    return
            elif event.modifiers() & Qt.ShiftModifier:
                if item and self.last_clicked_item and self.last_clicked_item != item:
                    all_items = []
                    it = QTreeWidgetItemIterator(self)
                    for it_item in it:
                        all_items.append(it_item)
                    try:
                        start_index = all_items.index(self.last_clicked_item)
                        end_index = all_items.index(item)
                        min_idx = min(start_index, end_index)
                        max_idx = max(start_index, end_index)
                        self.clearSelection()
                        for i in range(min_idx, max_idx + 1):
                            if i < len(all_items):
                                all_items[i].setSelected(True)
                    except ValueError:
                        pass
                    event.accept()
                    return
            if not item:
                self.is_drag_selecting = True
                self.drag_select_start = event.pos()
                self.drag_select_rect = QRect(self.drag_select_start, QSize())
                self.drag_select_items.clear()
                self.clearSelection()
                event.accept()
                return
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        if self.is_drag_selecting and event.buttons() & Qt.LeftButton:
            if self.drag_select_start:
                self.drag_select_rect = QRect(
                    self.drag_select_start,
                    event.pos()
                ).normalized()
                new_selection = []
                it = QTreeWidgetItemIterator(self)
                for item in it:
                    rect = self.visualItemRect(item)
                    if self.drag_select_rect.intersects(rect):
                        new_selection.append(item)
                for item in new_selection:
                    item.setSelected(True)
                for item in self.drag_select_items:
                    if item not in new_selection:
                        item.setSelected(False)
                self.drag_select_items = new_selection[:]
                self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_drag_selecting:
            self.is_drag_selecting = False
            self.drag_select_start = None
            self.drag_select_rect = None
            self.viewport().update()
            event.accept()
            return
        super().mouseReleaseEvent(event)
    
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.is_drag_selecting and self.drag_select_rect:
            painter = QPainter(self.viewport())
            painter.setPen(QPen(QColor(100, 150, 255), 1, Qt.DashLine))
            painter.setBrush(QBrush(QColor(100, 150, 255, 50)))
            painter.drawRect(self.drag_select_rect)


# ==================== ОСНОВНОЙ КЛАСС ПРИЛОЖЕНИЯ ====================

class FolderScannerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        sys.excepthook = self._handle_exception
        self.settings_manager = SettingsManager()
        self.settings = self.settings_manager.settings.__dict__
        self.dark_mode = self.settings.get("dark_mode", False)
        self.all_files = []
        self.virtual_folders = self.settings.get("virtual_folders", {})
        self.available_extensions = set()
        self.duplicate_files = defaultdict(list)
        self.extension_data = defaultdict(list)
        self.all_folders = set()
        self.file_content_cache = {}
        self.current_extension_filter = ""
        self.show_favorites_only = False
        self.scan_thread = None
        self.virtual_folders_expanded = {}
        self.action_history = deque(maxlen=50)
        self.current_action_index = -1
        self.is_undo_redo_in_progress = False
        self.file_groups = defaultdict(list)
        self.search_modes = ["name", "content", "date", "size"]
        self.current_search_mode = self.settings.get("search_mode", "name")
        self.multicriteria_search_enabled = self.settings.get("multicriteria_search", False)
        self.is_refreshing = False
        self.total_scan_time = 0
        self.total_files_scanned = 0
        self.init_ui()
        self.apply_theme()
        self.update_search_mode_text()
        self.check_data_folder_on_startup()
    
    def _handle_exception(self, exctype, value, tb):
        error_msg = ''.join(traceback.format_exception(exctype, value, tb))
        print(f"Необработанное исключение: {error_msg}")
        if hasattr(self, 'settings_manager') and self.settings_manager.crash_reporter:
            self.settings_manager.crash_reporter.report_error(
                str(exctype.__name__),
                str(value),
                error_msg
            )
        QMessageBox.critical(
            self,
            "Критическая ошибка",
            f"Произошла неожиданная ошибка:\n\n{value}\n\n"
            f"Отчёт сохранён в папке данных."
        )
        sys.__excepthook__(exctype, value, tb)
    
    def check_data_folder_on_startup(self):
        if not self.settings_manager.get_data_folder():
            dialog = DataFolderWarningDialog(self, is_startup=True)
            if dialog.exec_() == QDialog.Accepted and dialog.selected_folder:
                self.settings_manager.set_data_folder(dialog.selected_folder)
                QMessageBox.information(self, "Успех", "Папка для данных успешно установлена")
    
    def check_data_folder_on_close(self):
        if not self.settings_manager.get_data_folder():
            dialog = DataFolderWarningDialog(self, is_startup=False)
            result = dialog.exec_()
            if result == QDialog.Accepted and dialog.selected_folder:
                self.settings_manager.set_data_folder(dialog.selected_folder)
                return True
            elif result == QDialog.Rejected:
                return True
            else:
                return False
        return True
    
    def init_ui(self):
        self.setWindowTitle("Sofil - Сканер папок")
        self.setGeometry(100, 100, 1900, 1000)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        self.create_main_widgets()
        self.custom_toolbar = CustomToolBar(self)
        self.addToolBar(self.custom_toolbar)
        current_mode = self.settings.get('current_toolbar_mode', 'full')
        configs = self.settings.get('toolbar_configs', {})
        if current_mode in configs:
            self.custom_toolbar.apply_config(configs[current_mode])
        else:
            default_config = {
                'mode': current_mode,
                'items': [],
                'show_toolbar': True,
                'custom_name': ''
            }
            self.custom_toolbar.apply_config(default_config)
        self.create_menu()
        splitter = QSplitter(Qt.Horizontal)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        extensions_group = QGroupBox("Расширения файлов")
        extensions_layout = QVBoxLayout(extensions_group)
        self.extensions_tree = QTreeWidget()
        self.extensions_tree.setHeaderLabels(["Расширение", "Файлов"])
        self.extensions_tree.setColumnWidth(0, 150)
        self.extensions_tree.setColumnWidth(1, 80)
        self.extensions_tree.itemSelectionChanged.connect(self.on_extension_selected)
        extensions_layout.addWidget(self.extensions_tree)
        left_layout.addWidget(extensions_group)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        files_group = QGroupBox("Файлы")
        files_layout = QVBoxLayout(files_group)
        self.files_tree = CustomTreeWidget()
        self.files_tree.setHeaderLabels(["Имя", "Размер", "Изменен", "Путь", "Тип"])
        self.files_tree.setColumnWidth(0, 300)
        self.files_tree.setColumnWidth(1, 100)
        self.files_tree.setColumnWidth(2, 120)
        self.files_tree.setColumnHidden(3, True)
        self.files_tree.setColumnHidden(4, True)
        self.files_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files_tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.files_tree.itemDoubleClicked.connect(self.on_file_double_click)
        files_layout.addWidget(self.files_tree)
        right_layout.addWidget(files_group)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([300, 1300])
        main_layout.addWidget(splitter)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Готов к работе")
        self.file_count_label = QLabel("Файлов: 0")
        self.scan_timer = ScanTimer()
        self.status_bar.addWidget(self.status_label)
        self.status_bar.addWidget(self.file_count_label, 1)
        self.status_bar.addPermanentWidget(self.scan_timer)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.load_folder_history()
    
    def create_main_widgets(self):
        self.folder_combo = QComboBox()
        self.folder_combo.setEditable(True)
        self.folder_combo.setMinimumWidth(500)
        self.folder_combo.setMaxVisibleItems(20)
        self.folder_combo.setStyleSheet("""
            QComboBox {
                min-height: 25px;
                padding: 2px;
            }
        """)
        history = self.settings_manager.settings.scan_history
        for path in history:
            if path and os.path.exists(path):
                self.folder_combo.addItem(path)
        main_folder = self.settings.get("main_folder", "")
        if main_folder and os.path.exists(main_folder):
            index = self.folder_combo.findText(main_folder)
            if index >= 0:
                self.folder_combo.setCurrentIndex(index)
            else:
                self.folder_combo.insertItem(0, main_folder)
                self.folder_combo.setCurrentIndex(0)
        self.browse_folder_btn = QPushButton("📁 Обзор папки...")
        self.browse_folder_btn.clicked.connect(self.browse_folder)
        self.browse_folder_btn.setFixedWidth(120)
        self.browse_archive_btn = QPushButton("📦 Обзор архива...")
        self.browse_archive_btn.clicked.connect(self.browse_archive)
        self.browse_archive_btn.setFixedWidth(120)
        self.undo_btn = QPushButton("↶")
        self.undo_btn.setToolTip("Отменить последнее действие (Ctrl+Z)")
        self.undo_btn.clicked.connect(self.undo_action)
        self.undo_btn.setEnabled(False)
        self.undo_btn.setFixedWidth(30)
        self.redo_btn = QPushButton("↷")
        self.redo_btn.setToolTip("Повторить отмененное действие (Ctrl+Y)")
        self.redo_btn.clicked.connect(self.redo_action)
        self.redo_btn.setEnabled(False)
        self.redo_btn.setFixedWidth(30)
        self.search_mode_btn = QPushButton("🔤 Название")
        self.search_mode_btn.clicked.connect(self.toggle_search_mode)
        self.search_mode_btn.setFixedWidth(120)
        self.multicriteria_btn = QPushButton("🔍 Мультипоиск")
        self.multicriteria_btn.setCheckable(True)
        self.multicriteria_btn.setChecked(self.multicriteria_search_enabled)
        self.multicriteria_btn.toggled.connect(self.toggle_multicriteria_search)
        self.multicriteria_btn.setFixedWidth(100)
        # Стиль для кнопки мультипоиска - темнее когда включена
        self.update_multicriteria_btn_style()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите текст для поиска...")
        self.search_input.textChanged.connect(self.on_search_changed)
        self.search_input.setMinimumWidth(300)
        self.hide_duplicates_cb = QCheckBox("📑 Группировать дубликаты")
        self.hide_duplicates_cb.setChecked(self.settings.get("hide_duplicates", False))
        self.hide_duplicates_cb.stateChanged.connect(self.on_hide_duplicates_changed)
        self.sort_btn = QPushButton("A-Z ↑")
        self.sort_btn.clicked.connect(self.toggle_sorting)
        self.sort_btn.setFixedWidth(60)
        self.favorites_btn = QPushButton("⭐")
        self.favorites_btn.setCheckable(True)
        self.favorites_btn.clicked.connect(self.toggle_favorites_filter)
        self.favorites_btn.setFixedWidth(30)
        self.scan_btn = QPushButton("🔄 Сканировать")
        self.scan_btn.clicked.connect(self.scan_selected)
        self.scan_btn.setFixedWidth(120)
    
    def update_multicriteria_btn_style(self):
        """Обновить стиль кнопки мультипоиска в зависимости от состояния"""
        if self.multicriteria_search_enabled:
            self.multicriteria_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2D2D2D;
                    border: 1px solid #888;
                    border-radius: 3px;
                    padding: 5px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #6a6a6a;
                }
            """)
        else:
            self.multicriteria_btn.setStyleSheet("")
    
    def create_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("Файл")
        open_folder_action = QAction("📁 Открыть папку...", self)
        open_folder_action.setShortcut("Ctrl+O")
        open_folder_action.triggered.connect(self.browse_folder)
        file_menu.addAction(open_folder_action)
        open_archive_action = QAction("📦 Открыть архив...", self)
        open_archive_action.setShortcut("Ctrl+Shift+O")
        open_archive_action.triggered.connect(self.browse_archive)
        file_menu.addAction(open_archive_action)
        file_menu.addSeparator()
        scan_action = QAction("🔄 Сканировать", self)
        scan_action.setShortcut("Ctrl+S")
        scan_action.triggered.connect(self.scan_selected)
        file_menu.addAction(scan_action)
        file_menu.addSeparator()
        history_menu = file_menu.addMenu("📜 История")
        self.history_scan_action = QAction("История сканирования", self)
        self.history_scan_action.triggered.connect(self.show_scan_history)
        history_menu.addAction(self.history_scan_action)
        self.history_files_action = QAction("История файлов", self)
        self.history_files_action.triggered.connect(self.show_file_history)
        history_menu.addAction(self.history_files_action)
        history_menu.addSeparator()
        self.clear_history_action = QAction("Очистить историю", self)
        self.clear_history_action.triggered.connect(self.clear_history)
        history_menu.addAction(self.clear_history_action)
        file_menu.addSeparator()
        exit_action = QAction("🚪 Выход", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        settings_menu = menubar.addMenu("Настройки")
        special_menu = settings_menu.addMenu("⚙️ Спец настройки")
        toolbar_config_action = QAction("🎨 Настройка панели инструментов", self)
        toolbar_config_action.triggered.connect(self.show_toolbar_editor)
        special_menu.addAction(toolbar_config_action)
        special_menu.addSeparator()
        self.hide_bb_children_cb_menu = QAction("👶 Скрыть дочерние файлы Blockbench", self, checkable=True)
        self.hide_bb_children_cb_menu.setChecked(self.settings.get("hide_blockbench_children", True))
        self.hide_bb_children_cb_menu.triggered.connect(self.on_hide_bb_children_changed)
        special_menu.addAction(self.hide_bb_children_cb_menu)
        self.auto_load_textures_cb = QAction("🖼️ Автозагрузка текстур", self, checkable=True)
        self.auto_load_textures_cb.setChecked(self.settings.get("auto_load_textures", False))
        self.auto_load_textures_cb.triggered.connect(self.on_auto_load_textures_changed)
        special_menu.addAction(self.auto_load_textures_cb)
        settings_menu.addSeparator()
        data_folder_action = QAction("📂 Папка для данных...", self)
        data_folder_action.triggered.connect(self.set_data_folder)
        settings_menu.addAction(data_folder_action)
        temp_folder_action = QAction("🗑️ Временная папка...", self)
        temp_folder_action.triggered.connect(self.set_temp_folder)
        settings_menu.addAction(temp_folder_action)
        unrar_path_action = QAction("🔧 Путь к UnRAR...", self)
        unrar_path_action.triggered.connect(self.set_unrar_path)
        settings_menu.addAction(unrar_path_action)
        view_menu = menubar.addMenu("Вид")
        self.dark_mode_action = QAction("🌙 Тёмная тема", self, checkable=True)
        self.dark_mode_action.setChecked(self.dark_mode)
        self.dark_mode_action.triggered.connect(self.toggle_dark_mode)
        view_menu.addAction(self.dark_mode_action)
        help_menu = menubar.addMenu("Помощь")
        hotkeys_action = QAction("⌨️ Сочетания клавиш", self)
        hotkeys_action.triggered.connect(self.show_hotkeys)
        help_menu.addAction(hotkeys_action)
        help_menu.addSeparator()
        about_action = QAction("ℹ️ О программе", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        stats_action = QAction("📊 Статистика", self)
        stats_action.triggered.connect(self.show_statistics)
        help_menu.addAction(stats_action)
        crash_menu = help_menu.addMenu("💥 Отчёты об ошибках")
        show_crashes_action = QAction("Показать последние ошибки", self)
        show_crashes_action.triggered.connect(self.show_crash_reports)
        crash_menu.addAction(show_crashes_action)
        clear_crashes_action = QAction("Очистить отчёты", self)
        clear_crashes_action.triggered.connect(self.clear_crash_reports)
        crash_menu.addAction(clear_crashes_action)
    
    def show_toolbar_editor(self):
        try:
            dialog = ToolbarEditorDialog(self, self.settings_manager)
            if dialog.exec_() == QDialog.Accepted:
                result = dialog.get_result()
                self.settings['current_toolbar_mode'] = result['mode']
                self.settings['toolbar_configs'] = result['configs']
                mode = result['mode']
                configs = result['configs']
                if mode in configs:
                    self.custom_toolbar.apply_config(configs[mode])
                self.settings_manager.save()
                self.status_label.setText("Настройки панели инструментов сохранены")
        except Exception as e:
            error_msg = str(e)
            self.settings_manager.report_error("Ошибка редактора панели инструментов", error_msg)
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть редактор панели инструментов:\n{error_msg}")
    
    # ==================== МЕТОДЫ ДЛЯ ИСТОРИИ ====================
    
    def show_scan_history(self):
        history = self.settings_manager.settings.scan_history
        if not history:
            QMessageBox.information(self, "История", "История сканирования пуста")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("История сканирования")
        dialog.setMinimumWidth(600)
        dialog.setMinimumHeight(400)
        layout = QVBoxLayout()
        label = QLabel("Дважды кликните для загрузки пути:")
        layout.addWidget(label)
        list_widget = QListWidget()
        for path in history:
            item = QListWidgetItem(path)
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            list_widget.addItem(item)
        list_widget.itemDoubleClicked.connect(lambda item: self._load_from_history(item.data(Qt.UserRole)))
        layout.addWidget(list_widget)
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        dialog.setLayout(layout)
        dialog.exec_()
    
    def show_file_history(self):
        history = self.settings_manager.settings.file_history
        if not history:
            QMessageBox.information(self, "История", "История файлов пуста")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("История файлов")
        dialog.setMinimumWidth(600)
        dialog.setMinimumHeight(400)
        layout = QVBoxLayout()
        label = QLabel("Дважды кликните для открытия файла:")
        layout.addWidget(label)
        list_widget = QListWidget()
        for path in history:
            item = QListWidgetItem(os.path.basename(path))
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            list_widget.addItem(item)
        list_widget.itemDoubleClicked.connect(lambda item: self._open_file_from_history(item.data(Qt.UserRole)))
        layout.addWidget(list_widget)
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        dialog.setLayout(layout)
        dialog.exec_()
    
    def _load_from_history(self, path):
        if os.path.exists(path):
            self.folder_combo.setCurrentText(path)
            self.scan_selected()
        else:
            QMessageBox.warning(self, "Ошибка", f"Путь не существует:\n{path}")
    
    def _open_file_from_history(self, path):
        if os.path.exists(path):
            self.open_file_default(path)
        else:
            QMessageBox.warning(self, "Ошибка", f"Файл не существует:\n{path}")
    
    def clear_history(self):
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Очистить всю историю?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.settings_manager.settings.scan_history = []
            self.settings_manager.settings.file_history = []
            self.settings_manager.save()
            self.folder_combo.clear()
            self.folder_combo.addItem("Выберите папку или архив...")
            QMessageBox.information(self, "Успех", "История очищена")
    
    # ==================== МЕТОДЫ ДЛЯ ОТЧЁТОВ ОБ ОШИБКАХ ====================
    
    def show_crash_reports(self):
        if not self.settings_manager.crash_reporter:
            QMessageBox.information(self, "Отчёты", "Папка для данных не указана")
            return
        crashes = self.settings_manager.crash_reporter.get_recent_crashes(20)
        if not crashes:
            QMessageBox.information(self, "Отчёты", "Нет сохранённых отчётов об ошибках")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Отчёты об ошибках")
        dialog.setMinimumSize(700, 500)
        layout = QVBoxLayout()
        list_widget = QListWidget()
        for crash in crashes:
            timestamp = crash.get('timestamp', 'Неизвестно')
            error_type = crash.get('error_type', 'Неизвестно')
            error_msg = crash.get('error_message', '')[:50]
            item_text = f"[{timestamp}] {error_type}: {error_msg}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, crash)
            list_widget.addItem(item)
        list_widget.itemClicked.connect(lambda item: self._show_crash_details(item.data(Qt.UserRole)))
        layout.addWidget(QLabel("Кликните для просмотра деталей:"))
        layout.addWidget(list_widget)
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        dialog.setLayout(layout)
        dialog.exec_()
    
    def _show_crash_details(self, crash_data):
        if not crash_data:
            return
        details = f"""
Время: {crash_data.get('timestamp', 'Неизвестно')}
Тип ошибки: {crash_data.get('error_type', 'Неизвестно')}
Сообщение: {crash_data.get('error_message', 'Нет сообщения')}

Система: {crash_data.get('system_info', {}).get('platform', 'Неизвестно')}
Python: {crash_data.get('system_info', {}).get('python_version', 'Неизвестно')}

Стек вызовов:
{crash_data.get('stack_trace', 'Нет стека вызовов')}
        """
        QMessageBox.information(self, "Детали ошибки", details)
    
    def clear_crash_reports(self):
        if not self.settings_manager.crash_reporter:
            return
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Очистить все отчёты об ошибках?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.settings_manager.crash_reporter.clear_crashes()
            QMessageBox.information(self, "Успех", "Отчёты очищены")
    
    def show_statistics(self):
        stats_text = f"""📊 Статистика работы

⏱ Общее время сканирования: {self.total_scan_time:.1f} сек
📄 Всего просканировано файлов: {self.total_files_scanned}
📁 Текущих файлов: {len(self.all_files)}
🔁 Дубликатов: {len(self.duplicate_files)}
⭐ В избранном: {len(self.settings.get('favorites', []))}
📂 Виртуальных папок: {len(self.virtual_folders)}
📜 В истории сканирования: {len(self.settings_manager.settings.scan_history)}
📜 В истории файлов: {len(self.settings_manager.settings.file_history)}"""
        QMessageBox.information(self, "Статистика", stats_text)
    
    # ==================== МЕТОДЫ ДЛЯ ПОИСКА (ИСПРАВЛЕНЫ) ====================
    
    def update_search_mode_text(self):
        mode_texts = {
            "name": "🔤 Название",
            "content": "📄 Содержание", 
            "date": "📅 Дата",
            "size": "📊 Размер"
        }
        self.search_mode_btn.setText(mode_texts.get(self.current_search_mode, "🔤 Название"))
        placeholders = {
            "name": "Введите название файла...",
            "content": "Введите текст для поиска в содержимом...",
            "date": "Введите дату (ГГГГ-ММ-ДД) или период...",
            "size": "Введите размер (например: >1MB, <500KB, 100-200KB)..."
        }
        self.search_input.setPlaceholderText(placeholders.get(self.current_search_mode, "Введите текст для поиска..."))
    
    def toggle_search_mode(self):
        current_index = self.search_modes.index(self.current_search_mode)
        next_index = (current_index + 1) % len(self.search_modes)
        self.current_search_mode = self.search_modes[next_index]
        self.update_search_mode_text()
        self.settings["search_mode"] = self.current_search_mode
        self.settings_manager.save()
        self.refresh_files_tree()
        mode_names = {
            "name": "названию",
            "content": "содержимому",
            "date": "дате",
            "size": "размеру"
        }
        self.status_label.setText(f"🔍 Поиск по {mode_names.get(self.current_search_mode, 'названию')}")
    
    def toggle_multicriteria_search(self, enabled):
        self.multicriteria_search_enabled = enabled
        if enabled:
            self.search_input.setPlaceholderText("Введите критерии через ';' (название; содержание; дата; размер)")
        else:
            self.update_search_mode_text()
        self.settings["multicriteria_search"] = enabled
        self.settings_manager.save()
        self.update_multicriteria_btn_style()
        self.refresh_files_tree()
    
    def parse_search_criteria(self, search_text):
        """Разобрать строку поиска на критерии"""
        # Если мультипоиск ВЫКЛЮЧЕН
        if not self.multicriteria_search_enabled:
            return {self.current_search_mode: search_text}
        
        # Если мультипоиск ВКЛЮЧЕН но строка пустая
        if not search_text:
            return {}
        
        # Если нет точки с запятой - ищем по текущему режиму (удобно)
        if ';' not in search_text:
            return {self.current_search_mode: search_text}
        
        # Разбираем по точке с запятой
        parts = [part.strip() for part in search_text.split(';')]
        criteria = {}
        mode_order = ["name", "content", "date", "size"]
        
        for i, part in enumerate(parts):
            if i < len(mode_order) and part:
                criteria[mode_order[i]] = part
        
        # Если после разбора нет критериев - ищем по текущему режиму
        if not criteria:
            return {self.current_search_mode: search_text}
        
        return criteria
    
    def matches_search_criteria(self, file_info, criteria):
        try:
            if "name" in criteria and criteria["name"]:
                if criteria["name"].lower() not in file_info['name'].lower():
                    return False
            if "content" in criteria and criteria["content"]:
                content = self.load_file_content(file_info).lower()
                if criteria["content"].lower() not in content:
                    return False
            if "date" in criteria and criteria["date"]:
                date_str = file_info['modified'].strftime("%Y-%m-%d")
                search_date = criteria["date"].strip()
                try:
                    if re.match(r'^\d{4}-\d{2}-\d{2}$', search_date):
                        if date_str != search_date:
                            return False
                    elif '-' in search_date and len(search_date.split('-')) == 2:
                        start_str, end_str = search_date.split('-')
                        start_date = datetime.strptime(start_str.strip(), "%Y-%m-%d")
                        end_date = datetime.strptime(end_str.strip(), "%Y-%m-%d")
                        file_date = file_info['modified']
                        if not (start_date <= file_date <= end_date):
                            return False
                except:
                    if search_date not in date_str:
                        return False
            if "size" in criteria and criteria["size"]:
                size_bytes = file_info['size']
                search_size = criteria["size"].strip().upper()
                match = re.match(r'^([<>]=?)?\s*([\d.]+)\s*([KMGT]?B?)$', search_size)
                if match:
                    op, num_str, unit = match.groups()
                    if not op:
                        op = "="
                    num = float(num_str)
                    multiplier = 1
                    if unit.endswith('KB'):
                        multiplier = 1024
                    elif unit.endswith('MB'):
                        multiplier = 1024**2
                    elif unit.endswith('GB'):
                        multiplier = 1024**3
                    num_bytes = num * multiplier
                    if op == "=" or op == "":
                        if not (abs(size_bytes - num_bytes) < 1024):
                            return False
                    elif op == "<":
                        if not (size_bytes < num_bytes):
                            return False
                    elif op == "<=":
                        if not (size_bytes <= num_bytes):
                            return False
                    elif op == ">":
                        if not (size_bytes > num_bytes):
                            return False
                    elif op == ">=":
                        if not (size_bytes >= num_bytes):
                            return False
                elif '-' in search_size:
                    try:
                        start_str, end_str = search_size.split('-')
                        start_bytes = self.parse_size_to_bytes(start_str.strip())
                        end_bytes = self.parse_size_to_bytes(end_str.strip())
                        if not (start_bytes <= size_bytes <= end_bytes):
                            return False
                    except:
                        pass
            return True
        except:
            return False
    
    def parse_size_to_bytes(self, size_str):
        try:
            size_str = size_str.upper().replace(" ", "")
            match = re.match(r'^([\d.]+)([KMGT]?B?)$', size_str)
            if match:
                num_str, unit = match.groups()
                num = float(num_str)
                multiplier = 1
                if unit.endswith('KB'):
                    multiplier = 1024
                elif unit.endswith('MB'):
                    multiplier = 1024**2
                elif unit.endswith('GB'):
                    multiplier = 1024**3
                return int(num * multiplier)
        except:
            pass
        return 0
    
    def on_search_changed(self):
        self.refresh_files_tree()
    
    def toggle_dark_mode(self):
        self.dark_mode = self.dark_mode_action.isChecked()
        self.settings["dark_mode"] = self.dark_mode
        self.apply_theme()
        self.settings_manager.save()
    
    def apply_theme(self):
        app = QApplication.instance()
        if self.dark_mode:
            dark_palette = QPalette()
            dark_palette.setColor(QPalette.Window, QColor(45, 45, 48))
            dark_palette.setColor(QPalette.WindowText, QColor(240, 240, 240))
            dark_palette.setColor(QPalette.Base, QColor(30, 30, 32))
            dark_palette.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
            dark_palette.setColor(QPalette.ToolTipBase, QColor(60, 60, 60))
            dark_palette.setColor(QPalette.ToolTipText, QColor(240, 240, 240))
            dark_palette.setColor(QPalette.Text, QColor(240, 240, 240))
            dark_palette.setColor(QPalette.Button, QColor(60, 60, 62))
            dark_palette.setColor(QPalette.ButtonText, QColor(240, 240, 240))
            dark_palette.setColor(QPalette.BrightText, QColor(255, 150, 150))
            dark_palette.setColor(QPalette.Link, QColor(100, 150, 255))
            dark_palette.setColor(QPalette.Highlight, QColor(100, 150, 255, 100))
            dark_palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
            dark_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(150, 150, 150))
            dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(150, 150, 150))
            app.setPalette(dark_palette)
            self.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #555;
                    border-radius: 3px;
                    margin-top: 10px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                }
                QPushButton {
                    background-color: #3c3c3c;
                    border: 1px solid #555;
                    border-radius: 3px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #4a4a4a;
                }
                QPushButton:pressed {
                    background-color: #2d2d2d;
                }
                QLineEdit, QComboBox {
                    background-color: #2d2d2d;
                    border: 1px solid #555;
                    border-radius: 3px;
                    padding: 3px;
                }
            """)
        else:
            light_palette = QPalette()
            light_palette.setColor(QPalette.Window, QColor(240, 240, 242))
            light_palette.setColor(QPalette.WindowText, QColor(30, 30, 32))
            light_palette.setColor(QPalette.Base, QColor(255, 255, 255))
            light_palette.setColor(QPalette.AlternateBase, QColor(248, 248, 250))
            light_palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
            light_palette.setColor(QPalette.ToolTipText, QColor(30, 30, 32))
            light_palette.setColor(QPalette.Text, QColor(30, 30, 32))
            light_palette.setColor(QPalette.Button, QColor(240, 240, 242))
            light_palette.setColor(QPalette.ButtonText, QColor(30, 30, 32))
            light_palette.setColor(QPalette.BrightText, QColor(255, 50, 50))
            light_palette.setColor(QPalette.Link, QColor(70, 130, 220))
            light_palette.setColor(QPalette.Highlight, QColor(70, 130, 220, 100))
            light_palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
            light_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(150, 150, 150))
            light_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(150, 150, 150))
            app.setPalette(light_palette)
            self.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    margin-top: 10px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                }
                QPushButton {
                    background-color: #f0f0f0;
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                }
                QPushButton:pressed {
                    background-color: #d0d0d0;
                }
                QLineEdit, QComboBox {
                    background-color: white;
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    padding: 3px;
                }
            """)
    
    def load_folder_history(self):
        pass
    
    def add_to_scan_history(self, folder_path):
        if folder_path and os.path.exists(folder_path):
            self.settings_manager.add_to_scan_history(folder_path)
            index = self.folder_combo.findText(folder_path)
            if index < 0:
                self.folder_combo.insertItem(0, folder_path)
                self.folder_combo.setCurrentIndex(0)
            else:
                self.folder_combo.setCurrentIndex(index)
    
    def add_to_file_history(self, file_path):
        if file_path and os.path.exists(file_path):
            self.settings_manager.add_to_file_history(file_path)
    
    def browse_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку для сканирования")
        if folder_path:
            self.folder_combo.setCurrentText(folder_path)
            self.scan_selected()
    
    def browse_archive(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите архив",
            "",
            "Archives (*.zip *.rar *.7z);;ZIP files (*.zip);;All files (*.*)"
        )
        if file_path:
            self.folder_combo.setCurrentText(file_path)
            self.scan_selected()
    
    def scan_selected(self):
        folder_path = self.folder_combo.currentText().strip()
        if not folder_path:
            QMessageBox.warning(self, "Предупреждение", "Выберите папку или архив для сканирования")
            return
        if not os.path.exists(folder_path):
            QMessageBox.critical(self, "Ошибка", f"Указанный путь не существует:\n{folder_path}")
            return
        self.add_to_scan_history(folder_path)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("Сканирование...")
        self.scan_btn.setEnabled(False)
        self.scan_timer.start()
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.stop()
            self.scan_thread.wait()
        self.scan_thread = ScanThread(folder_path, self.settings)
        self.scan_thread.scan_complete.connect(self.on_scan_complete)
        self.scan_thread.error.connect(self.on_scan_error)
        self.scan_thread.progress_update.connect(self.on_scan_progress)
        self.scan_thread.start()
    
    def on_scan_progress(self, message, value):
        self.status_label.setText(message)
        if value > 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(value)
    
    def on_scan_complete(self, all_files, extension_data, available_extensions, 
                        duplicate_files, file_groups, scan_time):
        self.all_files = all_files
        self.extension_data = extension_data
        self.available_extensions = available_extensions
        self.duplicate_files = duplicate_files
        self.file_groups = file_groups
        self.total_scan_time += scan_time
        self.total_files_scanned += len(all_files)
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.scan_timer.stop()
        self.update_extensions_tree()
        self.refresh_files_tree()
        file_count = len(all_files)
        self.status_label.setText(f"Сканирование завершено за {scan_time:.1f} сек")
        self.file_count_label.setText(f"Файлов: {file_count}")
    
    def on_scan_error(self, error_msg):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.scan_timer.stop()
        self.settings_manager.report_error("Ошибка сканирования", error_msg)
        QMessageBox.critical(self, "Ошибка сканирования", f"Не удалось выполнить сканирование:\n{error_msg}")
        self.status_label.setText("Ошибка сканирования")
    
    def update_extensions_tree(self):
        self.extensions_tree.clear()
        all_count = len(self.all_files)
        all_item = QTreeWidgetItem(self.extensions_tree, ["Все расширения", str(all_count)])
        all_item.setData(0, Qt.UserRole, "")
        no_extension_count = len(self.extension_data.get("(без расширения)", []))
        if no_extension_count > 0:
            no_ext_item = QTreeWidgetItem(["(без расширения)", str(no_extension_count)])
            no_ext_item.setData(0, Qt.UserRole, "(без расширения)")
            self.extensions_tree.addTopLevelItem(no_ext_item)
        for ext in sorted(self.available_extensions):
            if ext != "(без расширения)":
                count = len(self.extension_data[ext])
                item = QTreeWidgetItem([ext, str(count)])
                item.setData(0, Qt.UserRole, ext)
                self.extensions_tree.addTopLevelItem(item)
    
    def on_extension_selected(self):
        selected_items = self.extensions_tree.selectedItems()
        if not selected_items:
            self.current_extension_filter = ""
        else:
            item = selected_items[0]
            self.current_extension_filter = item.data(0, Qt.UserRole)
        self.refresh_files_tree()
    
    def refresh_files_tree(self):
        if self.is_refreshing:
            return
        self.is_refreshing = True
        try:
            self.files_tree.clear()
            search_text = self.search_input.text()
            criteria = self.parse_search_criteria(search_text)
            filtered_files = []
            for file_info in self.all_files:
                if self.show_favorites_only and not file_info.get('is_favorite', False):
                    continue
                if self.current_extension_filter and self.current_extension_filter != "Все расширения":
                    file_ext = file_info.get('extension', '')
                    if file_ext != self.current_extension_filter:
                        continue
                if search_text and not self.matches_search_criteria(file_info, criteria):
                    continue
                if self.hide_bb_children_cb_menu and self.hide_bb_children_cb_menu.isChecked():
                    if file_info.get('has_parent', False):
                        continue
                filtered_files.append(file_info)
            sort_mode = self.settings.get("sort_mode", "name_asc")
            if sort_mode == "name_asc":
                filtered_files.sort(key=lambda x: x['name'].lower())
            elif sort_mode == "name_desc":
                filtered_files.sort(key=lambda x: x['name'].lower(), reverse=True)
            elif sort_mode == "date_asc":
                filtered_files.sort(key=lambda x: x['modified'])
            elif sort_mode == "date_desc":
                filtered_files.sort(key=lambda x: x['modified'], reverse=True)
            elif sort_mode == "size_asc":
                filtered_files.sort(key=lambda x: x['size'])
            elif sort_mode == "size_desc":
                filtered_files.sort(key=lambda x: x['size'], reverse=True)
            self.add_virtual_folders_to_tree(filtered_files)
            if self.hide_duplicates_cb.isChecked():
                self.add_files_with_duplicates_grouping(filtered_files)
            else:
                self.add_files_normal(filtered_files)
            self.file_count_label.setText(f"Файлов: {len(filtered_files)}")
        finally:
            self.is_refreshing = False
    
    def load_file_content(self, file_info):
        file_path = file_info['path']
        if file_path in self.file_content_cache:
            return self.file_content_cache[file_path]
        content = ""
        try:
            text_extensions = ['.txt', '.json', '.js', '.py', '.html', '.css', '.xml', '.md', '.csv', '.log']
            file_ext = file_info.get('extension', '').lower()
            if file_ext in text_extensions and os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
        except Exception:
            content = ""
        self.file_content_cache[file_path] = content
        return content
    
    def add_virtual_folders_to_tree(self, filtered_files):
        if not self.virtual_folders:
            return
        for folder_name, files in list(self.virtual_folders.items()):
            if self.show_favorites_only and folder_name not in self.settings.get("favorites", []):
                continue
            if self.current_extension_filter and self.current_extension_filter != "Все расширения":
                has_matching = False
                for file_info in files:
                    if isinstance(file_info, dict):
                        file_ext = os.path.splitext(file_info.get('name', ''))[1].lower()
                    else:
                        file_ext = os.path.splitext(file_info)[1].lower()
                    if file_ext == self.current_extension_filter:
                        has_matching = True
                        break
                if not has_matching:
                    continue
            is_favorite = folder_name in self.settings.get("favorites", [])
            folder_text = f"⭐ {folder_name}" if is_favorite else f"📁 {folder_name}"
            folder_item = QTreeWidgetItem(self.files_tree, [folder_text, "", "", "", "virtual_folder"])
            if folder_name in self.virtual_folders_expanded:
                folder_item.setExpanded(self.virtual_folders_expanded[folder_name])
            for file_info in files:
                if isinstance(file_info, dict) and 'path' in file_info:
                    file_path = file_info['path']
                    file_name = file_info.get('name', os.path.basename(file_path))
                    full_file_info = None
                    for f in self.all_files:
                        if f['path'] == file_path:
                            full_file_info = f
                            break
                    if not full_file_info:
                        continue
                    is_file_favorite = full_file_info.get('is_favorite', False)
                    file_text = f"⭐ {file_name}" if is_file_favorite else file_name
                    size_str = self.format_file_size(full_file_info['size'])
                    modified_str = full_file_info['modified'].strftime("%Y-%m-%d %H:%M")
                    QTreeWidgetItem(folder_item, [
                        file_text,
                        size_str,
                        modified_str,
                        file_path,
                        'file'
                    ])
    
    def add_files_normal(self, files):
        file_paths_in_folders = set()
        for folder_files in self.virtual_folders.values():
            for f in folder_files:
                if isinstance(f, dict):
                    file_paths_in_folders.add(f['path'])
                else:
                    file_paths_in_folders.add(f)
        for file_info in files:
            if file_info['path'] in file_paths_in_folders:
                continue
            is_favorite = file_info.get('is_favorite', False)
            display_name = f"⭐ {file_info['name']}" if is_favorite else file_info['name']
            size_str = self.format_file_size(file_info['size'])
            modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
            QTreeWidgetItem(self.files_tree, [
                display_name,
                size_str,
                modified_str,
                file_info['path'],
                'file'
            ])
    
    def add_files_with_duplicates_grouping(self, files):
        file_paths_in_folders = set()
        for folder_files in self.virtual_folders.values():
            for f in folder_files:
                if isinstance(f, dict):
                    file_paths_in_folders.add(f['path'])
                else:
                    file_paths_in_folders.add(f)
        name_groups = defaultdict(list)
        for file_info in files:
            if file_info['path'] in file_paths_in_folders:
                continue
            name_groups[file_info['name']].append(file_info)
        for filename, file_list in name_groups.items():
            if len(file_list) == 1:
                file_info = file_list[0]
                is_favorite = file_info.get('is_favorite', False)
                display_name = f"⭐ {filename}" if is_favorite else filename
                size_str = self.format_file_size(file_info['size'])
                modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
                QTreeWidgetItem(self.files_tree, [
                    display_name,
                    size_str,
                    modified_str,
                    file_info['path'],
                    'file'
                ])
            else:
                folder_item = QTreeWidgetItem(self.files_tree, [
                    f"📁 {filename} ({len(file_list)} файлов)",
                    "",
                    "",
                    "",
                    'folder'
                ])
                for file_info in file_list:
                    is_favorite = file_info.get('is_favorite', False)
                    display_name = f"⭐ {filename}" if is_favorite else filename
                    size_str = self.format_file_size(file_info['size'])
                    modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
                    QTreeWidgetItem(folder_item, [
                        display_name,
                        size_str,
                        modified_str,
                        file_info['path'],
                        'file'
                    ])
    
    def format_file_size(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB"]
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"
    
    def on_hide_duplicates_changed(self):
        self.settings["hide_duplicates"] = self.hide_duplicates_cb.isChecked()
        self.settings_manager.save()
        self.refresh_files_tree()
    
    def on_hide_bb_children_changed(self):
        if self.hide_bb_children_cb_menu:
            self.settings["hide_blockbench_children"] = self.hide_bb_children_cb_menu.isChecked()
            self.settings_manager.save()
            self.refresh_files_tree()
    
    def on_auto_load_textures_changed(self):
        if self.auto_load_textures_cb:
            self.settings["auto_load_textures"] = self.auto_load_textures_cb.isChecked()
            self.settings_manager.save()
    
    def toggle_favorites_filter(self):
        self.show_favorites_only = self.favorites_btn.isChecked()
        self.refresh_files_tree()
        self.status_label.setText("Показаны только избранные файлы" if self.show_favorites_only else "Показаны все файлы")
    
    def toggle_sorting(self):
        current_mode = self.settings.get("sort_mode", "name_asc")
        modes = ["name_asc", "name_desc", "date_asc", "date_desc", "size_asc", "size_desc"]
        current_index = modes.index(current_mode) if current_mode in modes else 0
        next_index = (current_index + 1) % len(modes)
        new_mode = modes[next_index]
        self.settings["sort_mode"] = new_mode
        self.settings_manager.save()
        texts = {
            "name_asc": "A-Z ↑",
            "name_desc": "Z-A ↓", 
            "date_asc": "📅 ↑",
            "date_desc": "📅 ↓",
            "size_asc": "📊 ↑",
            "size_desc": "📊 ↓"
        }
        self.sort_btn.setText(texts.get(new_mode, "A-Z ↑"))
        self.refresh_files_tree()
    
    def show_tree_context_menu(self, position):
        item = self.files_tree.itemAt(position)
        if not item:
            return
        menu = QMenu()
        item_type = item.text(4)
        if item_type == 'file':
            file_path = item.text(3)
            open_location = QAction("📂 Открыть расположение файла", self)
            open_location.triggered.connect(lambda: self.open_file_location(file_path))
            menu.addAction(open_location)
            open_with = QAction("🖥️ Открыть с помощью...", self)
            open_with.triggered.connect(lambda: self.open_file_with_dialog(file_path))
            menu.addAction(open_with)
            menu.addSeparator()
            rename = QAction("✏️ Переименовать", self)
            rename.triggered.connect(lambda: self.rename_file(item))
            menu.addAction(rename)
            delete = QAction("🗑️ Удалить", self)
            delete.triggered.connect(self.delete_selected_with_warning)
            menu.addAction(delete)
            menu.addSeparator()
            favorites = self.settings.get("favorites", [])
            if file_path in favorites:
                unfavorite = QAction("⭐ Убрать из избранного", self)
                unfavorite.triggered.connect(lambda: self.toggle_favorite(item))
                menu.addAction(unfavorite)
            else:
                favorite = QAction("☆ Добавить в избранное", self)
                favorite.triggered.connect(lambda: self.toggle_favorite(item))
                menu.addAction(favorite)
            menu.addSeparator()
            add_to_folder = QMenu("📁 Добавить в виртуальную папку", menu)
            create_new = QAction("➕ Создать новую папку...", self)
            create_new.triggered.connect(lambda: self.create_virtual_folder_from_selection())
            add_to_folder.addAction(create_new)
            if self.virtual_folders:
                add_to_folder.addSeparator()
                for folder_name in self.virtual_folders.keys():
                    folder_action = QAction(folder_name, self)
                    folder_action.triggered.connect(lambda checked, fn=folder_name: self.add_to_virtual_folder(fn))
                    add_to_folder.addAction(folder_action)
            menu.addMenu(add_to_folder)
        elif item_type == 'virtual_folder':
            folder_name = item.text(0)
            if folder_name.startswith("⭐ "):
                folder_name = folder_name[2:]
            elif folder_name.startswith("📁 "):
                folder_name = folder_name[2:]
            favorites = self.settings.get("favorites", [])
            if folder_name in favorites:
                unfavorite = QAction("⭐ Убрать из избранного", self)
                unfavorite.triggered.connect(lambda: self.toggle_virtual_folder_favorite(folder_name))
                menu.addAction(unfavorite)
            else:
                favorite = QAction("☆ Добавить в избранное", self)
                favorite.triggered.connect(lambda: self.toggle_virtual_folder_favorite(folder_name))
                menu.addAction(favorite)
            menu.addSeparator()
            rename = QAction("✏️ Переименовать папку", self)
            rename.triggered.connect(lambda: self.rename_virtual_folder(folder_name))
            menu.addAction(rename)
            delete = QAction("🗑️ Удалить папку", self)
            delete.triggered.connect(lambda: self.delete_virtual_folder_with_warning(folder_name))
            menu.addAction(delete)
        elif item_type == 'folder':
            if item.isExpanded():
                collapse = QAction("📂 Свернуть все", self)
                collapse.triggered.connect(lambda: self.collapse_folder(item))
                menu.addAction(collapse)
            else:
                expand = QAction("📂 Развернуть все", self)
                expand.triggered.connect(lambda: self.expand_folder(item))
                menu.addAction(expand)
        if menu.actions():
            menu.exec_(self.files_tree.viewport().mapToGlobal(position))
    
    # ==================== МЕТОДЫ ДЛЯ ОТКРЫТИЯ ФАЙЛОВ ====================
    
    def open_file_default(self, file_path):
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Предупреждение", f"Файл не существует:\n{file_path}")
            return False
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(os.path.normpath(file_path))
            elif system == "Darwin":
                subprocess.run(["open", file_path], check=True)
            else:
                subprocess.run(["xdg-open", file_path], check=True)
            self.add_to_file_history(file_path)
            self.status_label.setText(f"Открыт файл: {os.path.basename(file_path)}")
            return True
        except Exception as e:
            self.settings_manager.report_error("Ошибка открытия файла", str(e), {"file_path": file_path})
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{str(e)}")
            return False
    
    def open_file_with_dialog(self, file_path):
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Предупреждение", f"Файл не существует:\n{file_path}")
            return
        system = platform.system()
        try:
            if system == "Windows":
                try:
                    subprocess.run(
                        ["rundll32.exe", "shell32.dll,OpenAs_RunDLL", file_path],
                        shell=True,
                        check=True
                    )
                except subprocess.CalledProcessError:
                    os.startfile(os.path.normpath(file_path))
            elif system == "Darwin":
                subprocess.run(["open", "-a", "Finder", file_path], check=True)
            else:
                reply = QMessageBox.question(
                    self, 
                    "Открытие файла",
                    "На Linux нет стандартного диалога 'Открыть с помощью'.\n"
                    "Открыть файл стандартной программой?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self.open_file_default(file_path)
                else:
                    return
            self.add_to_file_history(file_path)
            self.status_label.setText(f"Выбор программы для: {os.path.basename(file_path)}")
        except Exception as e:
            self.settings_manager.report_error("Ошибка диалога открытия", str(e), {"file_path": file_path})
            try:
                self.open_file_default(file_path)
            except:
                QMessageBox.critical(
                    self, 
                    "Ошибка", 
                    f"Не удалось открыть диалог выбора программы:\n{str(e)}"
                )
    
    def add_to_virtual_folder(self, folder_name):
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            return
        if folder_name not in self.virtual_folders:
            return
        files_to_add = []
        duplicate_warning = False
        existing_files = []
        for file_info in self.virtual_folders[folder_name]:
            if isinstance(file_info, dict):
                existing_files.append(file_info['path'])
            else:
                existing_files.append(file_info)
        for item in selected_items:
            if item.text(4) == 'file':
                file_path = item.text(3)
                if file_path in existing_files:
                    duplicate_warning = True
                    continue
                file_name = item.text(0)
                if file_name.startswith("⭐ "):
                    file_name = file_name[2:]
                files_to_add.append({
                    'path': file_path,
                    'name': file_name
                })
        if not files_to_add:
            if duplicate_warning:
                QMessageBox.warning(self, "Предупреждение", "Все выбранные файлы уже находятся в этой папке!")
            return
        old_files = self.virtual_folders[folder_name].copy()
        self.virtual_folders[folder_name].extend(files_to_add)
        self.add_to_action_history('virtual_folder_add_files', {
            'folder_name': folder_name,
            'files_added': files_to_add,
            'old_files': old_files
        })
        self.settings["virtual_folders"] = self.virtual_folders
        self.settings_manager.save()
        self.refresh_files_tree()
        if duplicate_warning:
            QMessageBox.warning(self, "Предупреждение", 
                              f"Некоторые файлы уже находятся в папке и не были добавлены повторно.")
        self.status_label.setText(f"Добавлено {len(files_to_add)} файлов в папку")
    
    def create_virtual_folder_from_selection(self):
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Предупреждение", "Выберите файлы для добавления в папку")
            return
        files_to_add = []
        for item in selected_items:
            if item.text(4) == 'file':
                file_path = item.text(3)
                file_name = item.text(0)
                if file_name.startswith("⭐ "):
                    file_name = file_name[2:]
                files_to_add.append({
                    'path': file_path,
                    'name': file_name
                })
        if not files_to_add:
            QMessageBox.warning(self, "Предупреждение", "Выберите файлы для добавления в папку")
            return
        folder_name, ok = QInputDialog.getText(self, "Создать папку", "Введите название папки:")
        if ok and folder_name:
            if folder_name in self.virtual_folders:
                QMessageBox.warning(self, "Предупреждение", "Папка с таким именем уже существует")
                return
            self.virtual_folders[folder_name] = files_to_add
            self.add_to_action_history('virtual_folder_create', {
                'folder_name': folder_name,
                'files': files_to_add.copy()
            })
            self.settings["virtual_folders"] = self.virtual_folders
            self.settings_manager.save()
            self.refresh_files_tree()
            self.status_label.setText(f"Создана папка '{folder_name}' с {len(files_to_add)} файлами")
    
    def expand_folder(self, item):
        item.setExpanded(True)
        for i in range(item.childCount()):
            child = item.child(i)
            if child.text(4) == 'folder':
                child.setExpanded(True)
    
    def collapse_folder(self, item):
        item.setExpanded(False)
        for i in range(item.childCount()):
            child = item.child(i)
            if child.text(4) == 'folder':
                child.setExpanded(False)
    
    def on_file_double_click(self, item, column):
        item_type = item.text(4)
        if item_type == 'file':
            file_path = item.text(3)
            self.open_file_default(file_path)
        elif item_type == 'folder':
            item.setExpanded(not item.isExpanded())
        elif item_type == 'virtual_folder':
            folder_name = item.text(0)
            if folder_name.startswith("⭐ "):
                folder_name = folder_name[2:]
            elif folder_name.startswith("📁 "):
                folder_name = folder_name[2:]
            self.virtual_folders_expanded[folder_name] = not item.isExpanded()
            item.setExpanded(not item.isExpanded())
    
    def open_file_location(self, file_path):
        if os.path.exists(file_path):
            folder_path = os.path.dirname(file_path)
            if sys.platform == "win32":
                subprocess.run(['explorer', '/select,', os.path.normpath(file_path)], shell=True)
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", file_path])
            else:
                subprocess.run(["xdg-open", folder_path])
            self.status_label.setText(f"Открыта папка: {folder_path}")
        else:
            QMessageBox.warning(self, "Предупреждение", "Файл не существует")
    
    def rename_file(self, item):
        if not item:
            return
        old_path = item.text(3)
        old_name = os.path.basename(old_path)
        if not os.path.exists(old_path):
            QMessageBox.critical(self, "Ошибка", f"Файл не найден: {old_path}")
            return
        new_name, ok = QInputDialog.getText(self, "Переименовать файл", "Введите новое имя файла:", text=old_name)
        if ok and new_name and new_name != old_name:
            new_path = os.path.join(os.path.dirname(old_path), new_name)
            if os.path.exists(new_path):
                QMessageBox.critical(self, "Ошибка", f"Файл с именем '{new_name}' уже существует")
                return
            try:
                self.add_to_action_history('file_rename', {
                    'old_path': old_path,
                    'new_path': new_path
                })
                os.rename(old_path, new_path)
                for file_info in self.all_files:
                    if file_info['path'] == old_path:
                        file_info['path'] = new_path
                        file_info['name'] = new_name
                        break
                for folder_name, files in self.virtual_folders.items():
                    for i, file_info in enumerate(files):
                        if isinstance(file_info, dict) and file_info.get('path') == old_path:
                            file_info['path'] = new_path
                            file_info['name'] = new_name
                        elif file_info == old_path:
                            files[i] = new_path
                if old_path in self.settings.get("favorites", []):
                    favorites = self.settings["favorites"]
                    favorites.remove(old_path)
                    favorites.append(new_path)
                    self.settings["favorites"] = favorites
                self.settings["virtual_folders"] = self.virtual_folders
                self.settings_manager.save()
                self.refresh_files_tree()
                self.status_label.setText(f"Файл переименован")
            except Exception as e:
                self.settings_manager.report_error("Ошибка переименования", str(e), {"old_path": old_path, "new_path": new_path})
                QMessageBox.critical(self, "Ошибка", f"Не удалось переименовать файл")
    
    def toggle_favorite(self, item):
        if not item:
            return
        file_path = item.text(3)
        favorites = self.settings.get("favorites", [])
        was_favorite = file_path in favorites
        self.add_to_action_history('favorite_toggle', {
            'file_paths': [file_path],
            'was_favorite': was_favorite
        })
        if was_favorite:
            favorites.remove(file_path)
        else:
            favorites.append(file_path)
        self.settings["favorites"] = favorites
        self.settings_manager.save()
        for file_info in self.all_files:
            if file_info['path'] == file_path:
                file_info['is_favorite'] = file_path in favorites
        self.refresh_files_tree()
        self.status_label.setText("Избранное обновлено")
    
    def toggle_virtual_folder_favorite(self, folder_name):
        favorites = self.settings.get("favorites", [])
        if folder_name in favorites:
            favorites.remove(folder_name)
        else:
            favorites.append(folder_name)
        self.settings["favorites"] = favorites
        self.settings_manager.save()
        self.refresh_files_tree()
        self.status_label.setText("Избранное обновлено")
    
    def rename_virtual_folder(self, folder_name):
        new_name, ok = QInputDialog.getText(self, "Переименовать папку", "Введите новое название папки:", text=folder_name)
        if ok and new_name and new_name != folder_name:
            if new_name in self.virtual_folders:
                QMessageBox.warning(self, "Предупреждение", "Папка с таким именем уже существует")
                return
            old_files = self.virtual_folders[folder_name].copy()
            self.virtual_folders[new_name] = self.virtual_folders.pop(folder_name)
            if folder_name in self.virtual_folders_expanded:
                self.virtual_folders_expanded[new_name] = self.virtual_folders_expanded.pop(folder_name)
            favorites = self.settings.get("favorites", [])
            if folder_name in favorites:
                favorites.remove(folder_name)
                favorites.append(new_name)
                self.settings["favorites"] = favorites
            self.add_to_action_history('virtual_folder_rename', {
                'old_name': folder_name,
                'new_name': new_name,
                'files': old_files
            })
            self.settings["virtual_folders"] = self.virtual_folders
            self.settings_manager.save()
            self.refresh_files_tree()
            self.status_label.setText(f"Папка переименована")
    
    def delete_virtual_folder_with_warning(self, folder_name):
        reply = QMessageBox.question(self, "Подтверждение", 
                                   f"Вы уверены, что хотите удалить папку '{folder_name}'?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.delete_virtual_folder(folder_name)
    
    def delete_virtual_folder(self, folder_name):
        if folder_name in self.virtual_folders:
            old_files = self.virtual_folders[folder_name].copy()
            favorites = self.settings.get("favorites", [])
            if folder_name in favorites:
                favorites.remove(folder_name)
                self.settings["favorites"] = favorites
            if folder_name in self.virtual_folders_expanded:
                del self.virtual_folders_expanded[folder_name]
            del self.virtual_folders[folder_name]
            self.add_to_action_history('virtual_folder_delete', {
                'folder_name': folder_name,
                'files': old_files
            })
            self.settings["virtual_folders"] = self.virtual_folders
            self.settings_manager.save()
            self.refresh_files_tree()
            self.status_label.setText(f"Папка удалена")
    
    def delete_selected_with_warning(self):
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            return
        file_count = sum(1 for item in selected_items if item.text(4) == 'file')
        if file_count == 0:
            return
        reply = QMessageBox.question(self, "Подтверждение", 
                                   f"Удалить {file_count} выбранных файл(ов)?\n\nЭто действие можно отменить (Ctrl+Z).",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.delete_selected()
    
    def delete_selected(self):
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            return
        files_to_delete = []
        for item in selected_items:
            if item.text(4) == 'file':
                file_path = item.text(3)
                if os.path.exists(file_path):
                    try:
                        with open(file_path, 'rb') as f:
                            content = f.read()
                        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.bak')
                        temp_file.write(content)
                        temp_file.close()
                        files_to_delete.append({
                            'path': file_path,
                            'content': content,
                            'temp_path': temp_file.name,
                            'is_favorite': file_path in self.settings.get("favorites", [])
                        })
                    except Exception as e:
                        self.settings_manager.report_error("Ошибка удаления файла", str(e), {"file_path": file_path})
                        QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать файл {file_path}")
                        continue
        if files_to_delete:
            self.add_to_action_history('file_delete', {'files': files_to_delete})
            deleted_count = 0
            for file_info in files_to_delete:
                try:
                    os.remove(file_info['path'])
                    if file_info['is_favorite']:
                        favorites = self.settings.get("favorites", [])
                        if file_info['path'] in favorites:
                            favorites.remove(file_info['path'])
                            self.settings["favorites"] = favorites
                    self.all_files = [f for f in self.all_files if f['path'] != file_info['path']]
                    for folder_name, files in self.virtual_folders.items():
                        self.virtual_folders[folder_name] = [
                            f for f in files 
                            if (isinstance(f, dict) and f.get('path') != file_info['path']) or f != file_info['path']
                        ]
                    deleted_count += 1
                except Exception as e:
                    self.settings_manager.report_error("Ошибка удаления файла", str(e), {"file_path": file_info['path']})
                    QMessageBox.critical(self, "Ошибка", f"Не удалось удалить файл {file_info['path']}")
            self.settings["virtual_folders"] = self.virtual_folders
            self.settings_manager.save()
            self.refresh_files_tree()
            self.status_label.setText(f"Удалено файлов: {deleted_count}")
    
    def add_to_action_history(self, action_type, data):
        if self.is_undo_redo_in_progress:
            return
        if self.current_action_index < len(self.action_history) - 1:
            self.action_history = deque(list(self.action_history)[:self.current_action_index + 1], maxlen=50)
        self.action_history.append({'type': action_type, 'data': data})
        self.current_action_index = len(self.action_history) - 1
        self.update_undo_redo_buttons()
    
    def undo_action(self):
        if self.current_action_index < 0:
            return
        self.is_undo_redo_in_progress = True
        action = self.action_history[self.current_action_index]
        try:
            if action['type'] == 'file_rename':
                old_path = action['data']['old_path']
                new_path = action['data']['new_path']
                if os.path.exists(new_path) and not os.path.exists(old_path):
                    os.rename(new_path, old_path)
                    for file_info in self.all_files:
                        if file_info['path'] == new_path:
                            file_info['path'] = old_path
                            file_info['name'] = os.path.basename(old_path)
                            break
                    favorites = self.settings.get("favorites", [])
                    if new_path in favorites:
                        favorites.remove(new_path)
                        favorites.append(old_path)
                        self.settings["favorites"] = favorites
                    self.settings_manager.save()
                    self.refresh_files_tree()
            elif action['type'] == 'file_delete':
                for file_info in action['data']['files']:
                    if os.path.exists(file_info['temp_path']):
                        with open(file_info['temp_path'], 'rb') as f:
                            content = f.read()
                        with open(file_info['path'], 'wb') as f:
                            f.write(content)
                        os.remove(file_info['temp_path'])
                    self.all_files.append({
                        'name': os.path.basename(file_info['path']),
                        'path': file_info['path'],
                        'size': len(file_info['content']),
                        'modified': datetime.now(),
                        'is_favorite': file_info['is_favorite'],
                        'extension': os.path.splitext(file_info['path'])[1].lower() or "(без расширения)",
                        'has_parent': False
                    })
                    if file_info['is_favorite']:
                        favorites = self.settings.get("favorites", [])
                        if file_info['path'] not in favorites:
                            favorites.append(file_info['path'])
                            self.settings["favorites"] = favorites
                self.settings_manager.save()
                self.refresh_files_tree()
            elif action['type'] == 'favorite_toggle':
                file_paths = action['data']['file_paths']
                was_favorite = action['data']['was_favorite']
                favorites = self.settings.get("favorites", [])
                for file_path in file_paths:
                    if was_favorite:
                        if file_path not in favorites:
                            favorites.append(file_path)
                    else:
                        if file_path in favorites:
                            favorites.remove(file_path)
                self.settings["favorites"] = favorites
                self.settings_manager.save()
                for file_info in self.all_files:
                    if file_info['path'] in file_paths:
                        file_info['is_favorite'] = file_info['path'] in favorites
                self.refresh_files_tree()
            elif action['type'] == 'virtual_folder_create':
                folder_name = action['data']['folder_name']
                if folder_name in self.virtual_folders:
                    del self.virtual_folders[folder_name]
                    self.settings["virtual_folders"] = self.virtual_folders
                    self.settings_manager.save()
                    self.refresh_files_tree()
            elif action['type'] == 'virtual_folder_delete':
                folder_name = action['data']['folder_name']
                files = action['data']['files']
                self.virtual_folders[folder_name] = files
                self.settings["virtual_folders"] = self.virtual_folders
                self.settings_manager.save()
                self.refresh_files_tree()
            elif action['type'] == 'virtual_folder_add_files':
                folder_name = action['data']['folder_name']
                old_files = action['data']['old_files']
                self.virtual_folders[folder_name] = old_files
                self.settings["virtual_folders"] = self.virtual_folders
                self.settings_manager.save()
                self.refresh_files_tree()
        except Exception as e:
            print(f"Ошибка при отмене: {e}")
        self.current_action_index -= 1
        self.is_undo_redo_in_progress = False
        self.update_undo_redo_buttons()
    
    def redo_action(self):
        if self.current_action_index >= len(self.action_history) - 1:
            return
        self.is_undo_redo_in_progress = True
        self.current_action_index += 1
        action = self.action_history[self.current_action_index]
        try:
            if action['type'] == 'file_rename':
                old_path = action['data']['old_path']
                new_path = action['data']['new_path']
                if os.path.exists(old_path) and not os.path.exists(new_path):
                    os.rename(old_path, new_path)
                    for file_info in self.all_files:
                        if file_info['path'] == old_path:
                            file_info['path'] = new_path
                            file_info['name'] = os.path.basename(new_path)
                            break
                    favorites = self.settings.get("favorites", [])
                    if old_path in favorites:
                        favorites.remove(old_path)
                        favorites.append(new_path)
                        self.settings["favorites"] = favorites
                    self.settings_manager.save()
                    self.refresh_files_tree()
            elif action['type'] == 'file_delete':
                for file_info in action['data']['files']:
                    if os.path.exists(file_info['path']):
                        os.remove(file_info['path'])
                        if file_info['is_favorite']:
                            favorites = self.settings.get("favorites", [])
                            if file_info['path'] in favorites:
                                favorites.remove(file_info['path'])
                                self.settings["favorites"] = favorites
                        self.all_files = [f for f in self.all_files if f['path'] != file_info['path']]
                self.settings_manager.save()
                self.refresh_files_tree()
            elif action['type'] == 'favorite_toggle':
                file_paths = action['data']['file_paths']
                was_favorite = action['data']['was_favorite']
                favorites = self.settings.get("favorites", [])
                for file_path in file_paths:
                    if was_favorite:
                        if file_path in favorites:
                            favorites.remove(file_path)
                    else:
                        if file_path not in favorites:
                            favorites.append(file_path)
                self.settings["favorites"] = favorites
                self.settings_manager.save()
                for file_info in self.all_files:
                    if file_info['path'] in file_paths:
                        file_info['is_favorite'] = file_info['path'] in favorites
                self.refresh_files_tree()
            elif action['type'] == 'virtual_folder_create':
                folder_name = action['data']['folder_name']
                files = action['data']['files']
                self.virtual_folders[folder_name] = files
                self.settings["virtual_folders"] = self.virtual_folders
                self.settings_manager.save()
                self.refresh_files_tree()
            elif action['type'] == 'virtual_folder_delete':
                folder_name = action['data']['folder_name']
                if folder_name in self.virtual_folders:
                    del self.virtual_folders[folder_name]
                    self.settings["virtual_folders"] = self.virtual_folders
                    self.settings_manager.save()
                    self.refresh_files_tree()
            elif action['type'] == 'virtual_folder_add_files':
                folder_name = action['data']['folder_name']
                files_added = action['data']['files_added']
                if folder_name not in self.virtual_folders:
                    self.virtual_folders[folder_name] = []
                self.virtual_folders[folder_name].extend(files_added)
                self.settings["virtual_folders"] = self.virtual_folders
                self.settings_manager.save()
                self.refresh_files_tree()
        except Exception as e:
            print(f"Ошибка при повторе: {e}")
        self.is_undo_redo_in_progress = False
        self.update_undo_redo_buttons()
    
    def update_undo_redo_buttons(self):
        self.undo_btn.setEnabled(self.current_action_index >= 0)
        self.redo_btn.setEnabled(self.current_action_index < len(self.action_history) - 1)
    
    def set_data_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Выберите папку для данных")
        if path:
            self.settings_manager.set_data_folder(path)
            QMessageBox.information(self, "Успех", f"Папка для данных установлена")
    
    def set_temp_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Выберите временную папку")
        if path:
            self.settings["temp_folder"] = path
            self.settings_manager.save()
            QMessageBox.information(self, "Успех", f"Временная папка установлена")
    
    def set_unrar_path(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите исполняемый файл UnRAR", "", "Executable files (*.exe);;All files (*.*)")
        if path:
            self.settings["unrar_path"] = path
            self.settings_manager.save()
            QMessageBox.information(self, "Успех", f"Путь к UnRAR установлен")
    
    def show_hotkeys(self):
        text = """⌨️ Сочетания клавиш

📁 Основные:
Ctrl+O — Открыть папку
Ctrl+Shift+O — Открыть архив
Ctrl+S — Сканировать
Delete — Удалить выбранные файлы

✏️ Работа с файлами:
Ctrl+Z — Отменить действие
Ctrl+Y — Повторить действие

🖱️ Навигация и выделение:
↑/↓ — Выбор файлов
Ctrl+ЛКМ — Множественный выбор
Shift+ЛКМ — Выделение диапазона
Зажатие ЛКМ — Выделение области
Enter — Открыть файл"""
        QMessageBox.information(self, "Сочетания клавиш", text)
    
    def show_about(self):
        text = """Sofil - Сканер папок
Версия: 8.0

Создатель: Akami_bl
Обратная связь: akami.bl@gmail.com

📋 Основное:
📁 Сканирование папок и ZIP-архивов
🗂️ Виртуальные папки для группировки файлов
🔍 Поиск по названию, содержимому, дате и размеру
⭐ Избранное для быстрого доступа

✨ Новые возможности:
🎨 Настраиваемая панель инструментов
⏱ Таймер сканирования
💾 Система предупреждений о папке данных
📊 Статистика использования
📜 История сканирования и файлов
💥 Отчёты об ошибках в crashs.json
🔧 Расширенные настройки"""
        QMessageBox.information(self, "О программе", text)
    
    def closeEvent(self, event):
        if not self.check_data_folder_on_close():
            event.ignore()
            return
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.stop()
            self.scan_thread.wait()
        self.settings["virtual_folders"] = self.virtual_folders
        self.settings_manager.save()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Sofil")
    app.setStyle("Fusion")
    window = FolderScannerApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()