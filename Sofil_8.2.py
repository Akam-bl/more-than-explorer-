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
import hashlib
import logging
import tarfile
from datetime import datetime
from collections import defaultdict, deque
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Optional, Any, Tuple, Literal
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QLabel, QLineEdit, QPushButton,
    QComboBox, QProgressBar, QSplitter, QFileDialog, QMessageBox,
    QMenu, QAction, QInputDialog, QToolBar, QStatusBar, QCheckBox,
    QGroupBox, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem,
    QScrollArea, QFrame, QGridLayout, QSpinBox, QTabWidget, QRadioButton,
    QTextEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QRect, QPoint, QTimer, QSettings
from PyQt5.QtGui import QIcon, QPalette, QColor, QPainter, QPen, QBrush, QFont


# ==================== КОНФИГУРАЦИОННЫЕ МОДЕЛИ ДЛЯ ПАКЕТНОЙ ОБРАБОТКИ ====================

class SortField(Enum):
    NAME = "name"
    DATE = "date"
    SIZE = "size"

class Direction(Enum):
    ASC = "asc"
    DESC = "desc"

class ArchiveFormat(Enum):
    ZIP = "zip"
    TAR = "tar"
    TAR_GZ = "tar.gz"
    SEVEN_ZIP = "7z"
    RAR = "rar"

@dataclass
class SortKeyConfig:
    """Конфигурация сортировки файлов"""
    field: SortField = SortField.NAME
    direction: Direction = Direction.ASC
    date_field: Literal["mtime", "ctime"] = "mtime"
    case_sensitive: bool = False
    tie_breaker: Literal["path", "hash_prefix"] = "path"
    
    def get_sort_key(self, file_path: Path) -> tuple:
        if self.field == SortField.NAME:
            name = file_path.name
            if not self.case_sensitive:
                name = name.lower()
            return (name, str(file_path))
        elif self.field == SortField.DATE:
            stat = file_path.stat()
            timestamp = stat.st_mtime if self.date_field == "mtime" else stat.st_ctime
            return (timestamp, str(file_path))
        elif self.field == SortField.SIZE:
            size = file_path.stat().st_size
            return (size, str(file_path))
        return (str(file_path),)

@dataclass
class NamingConfig:
    """Конфигурация именования целевых файлов/папок"""
    base_template: str = "{base}"
    counter_enabled: bool = True
    counter_style: Literal["space_paren", "dot", "underscore", "bracket"] = "space_paren"
    counter_start: int = 1
    collision_strategy: Literal["increment", "append_hash"] = "increment"
    preserve_extension: bool = True
    
    def format_name(self, base_name: str, counter: Optional[int] = None, extension: str = "") -> str:
        if self.base_template == "{base}":
            key = base_name
        else:
            key = self.base_template.format(base=base_name)
        
        if counter is not None and self.counter_enabled:
            if self.counter_style == "space_paren":
                name_part = f"{key} ({counter})"
            elif self.counter_style == "dot":
                name_part = f"{key}.{counter}"
            elif self.counter_style == "underscore":
                name_part = f"{key}_{counter}"
            elif self.counter_style == "bracket":
                name_part = f"{key}[{counter}]"
            else:
                name_part = key
        else:
            name_part = key
        
        if self.preserve_extension and extension:
            return name_part + extension
        return name_part

@dataclass
class QueueConfig:
    """Конфигурация очереди имен"""
    queue_templates: List[str] = field(default_factory=list)
    repeat_last: bool = True
    
    def get_target_name(self, index: int, extension: str = "") -> str:
        if index < len(self.queue_templates):
            template = self.queue_templates[index]
            if any(template.endswith(ext) for ext in ['.zip', '.7z', '.rar', '.tar', '.gz']):
                return template
            return template + extension
        elif self.repeat_last and self.queue_templates:
            last_template = self.queue_templates[-1]
            extra_num = index - len(self.queue_templates) + 1
            return f"{last_template} ({extra_num}){extension}"
        return f"item_{index}{extension}"

@dataclass
class Operation:
    src: Path
    dst: Path
    action: Literal["extract", "pack"]
    archive_format: str = "zip"
    meta: Dict = field(default_factory=dict)


# ==================== ОБРАБОТЧИКИ АРХИВОВ ====================

class ArchiveHandler:
    @staticmethod
    def extract(src: Path, dst_dir: Path) -> bool:
        raise NotImplementedError
    
    @staticmethod
    def pack(src_dir: Path, dst_archive: Path, files: List[Path] = None) -> bool:
        raise NotImplementedError
    
    @staticmethod
    def supports_format(archive_path: Path) -> bool:
        raise NotImplementedError

class ZipHandler(ArchiveHandler):
    @staticmethod
    def extract(src: Path, dst_dir: Path) -> bool:
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(src, 'r') as zf:
                zf.extractall(dst_dir)
            return True
        except Exception as e:
            return False
    
    @staticmethod
    def pack(src_dir: Path, dst_archive: Path, files: List[Path] = None) -> bool:
        try:
            dst_archive.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(dst_archive, 'w', zipfile.ZIP_DEFLATED) as zf:
                if files is None:
                    files = list(src_dir.rglob('*'))
                for file_path in files:
                    if file_path.is_file():
                        arcname = file_path.relative_to(src_dir)
                        zf.write(file_path, arcname)
            return True
        except Exception as e:
            return False
    
    @staticmethod
    def supports_format(archive_path: Path) -> bool:
        return archive_path.suffix.lower() in ['.zip', '.zipx']

class TarHandler(ArchiveHandler):
    @staticmethod
    def extract(src: Path, dst_dir: Path) -> bool:
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            mode = 'r:gz' if src.suffix == '.gz' or str(src).endswith('.tar.gz') else 'r'
            with tarfile.open(src, mode) as tf:
                tf.extractall(dst_dir)
            return True
        except Exception as e:
            return False
    
    @staticmethod
    def pack(src_dir: Path, dst_archive: Path, files: List[Path] = None) -> bool:
        try:
            dst_archive.parent.mkdir(parents=True, exist_ok=True)
            mode = 'w:gz' if dst_archive.suffix == '.gz' or str(dst_archive).endswith('.tar.gz') else 'w'
            with tarfile.open(dst_archive, mode) as tf:
                if files is None:
                    files = list(src_dir.rglob('*'))
                for file_path in files:
                    if file_path.is_file():
                        arcname = file_path.relative_to(src_dir)
                        tf.add(file_path, arcname)
            return True
        except Exception as e:
            return False
    
    @staticmethod
    def supports_format(archive_path: Path) -> bool:
        ext = archive_path.suffix.lower()
        return ext in ['.tar', '.gz'] or str(archive_path).endswith('.tar.gz')

class SevenZipHandler(ArchiveHandler):
    @staticmethod
    def _get_7z_cmd() -> str:
        for cmd in ['7z', '7zz', '7za']:
            if shutil.which(cmd):
                return cmd
        return '7z'
    
    @staticmethod
    def extract(src: Path, dst_dir: Path) -> bool:
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run([SevenZipHandler._get_7z_cmd(), 'x', str(src), f'-o{dst_dir}', '-y'], 
                         check=True, capture_output=True)
            return True
        except Exception as e:
            return False
    
    @staticmethod
    def pack(src_dir: Path, dst_archive: Path, files: List[Path] = None) -> bool:
        try:
            dst_archive.parent.mkdir(parents=True, exist_ok=True)
            if files is None:
                files = list(src_dir.rglob('*'))
            file_args = [str(f) for f in files if f.is_file()]
            subprocess.run([SevenZipHandler._get_7z_cmd(), 'a', str(dst_archive)] + file_args, 
                         check=True, capture_output=True)
            return True
        except Exception as e:
            return False
    
    @staticmethod
    def supports_format(archive_path: Path) -> bool:
        return archive_path.suffix.lower() == '.7z'

class RarHandler(ArchiveHandler):
    @staticmethod
    def _get_rar_cmd() -> Optional[str]:
        for cmd in ['unrar', 'rar']:
            if shutil.which(cmd):
                return cmd
        return None
    
    @staticmethod
    def extract(src: Path, dst_dir: Path) -> bool:
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            cmd = RarHandler._get_rar_cmd()
            if not cmd:
                return False
            subprocess.run([cmd, 'x', str(src), str(dst_dir)], check=True)
            return True
        except Exception as e:
            return False
    
    @staticmethod
    def pack(src_dir: Path, dst_archive: Path, files: List[Path] = None) -> bool:
        try:
            dst_archive.parent.mkdir(parents=True, exist_ok=True)
            cmd = shutil.which('rar')
            if not cmd:
                return False
            if files is None:
                files = list(src_dir.rglob('*'))
            file_args = [str(f) for f in files if f.is_file()]
            subprocess.run([cmd, 'a', str(dst_archive)] + file_args, check=True)
            return True
        except Exception as e:
            return False
    
    @staticmethod
    def supports_format(archive_path: Path) -> bool:
        return archive_path.suffix.lower() == '.rar'

def get_archive_handler(archive_path: Path) -> Optional[ArchiveHandler]:
    handlers = [ZipHandler, TarHandler, SevenZipHandler, RarHandler]
    for handler in handlers:
        if handler.supports_format(archive_path):
            return handler
    return None


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
                    'python_version': sys.version
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
                    else:
                        result[key][name] = config
            else:
                result[key] = value
        return result
    
    @classmethod
    def from_dict(cls, data):
        instance = cls()
        for key, value in data.items():
            if key == 'toolbar_configs' and isinstance(value, dict):
                instance.toolbar_configs = value
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
                    self.settings = AppSettings.from_dict(data)
        except Exception as e:
            print(f"Ошибка загрузки настроек: {e}")
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


# ==================== КАСТОМНЫЙ QTreeWidget С ВЫДЕЛЕНИЕМ ОБЛАСТИ ====================

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


# ==================== ДИАЛОГ ПАКЕТНОЙ УПАКОВКИ/РАСПАКОВКИ ====================

class PackUnpackExecutor(QThread):
    progress_update = pyqtSignal(int, int)
    operation_complete = pyqtSignal(Operation, bool, str)
    finished = pyqtSignal(dict)
    
    def __init__(self, operations: List[Operation], concurrency: int = 1, error_policy: str = "continue"):
        super().__init__()
        self.operations = operations
        self.concurrency = concurrency
        self.error_policy = error_policy
        self._is_cancelled = False
    
    def cancel(self):
        self._is_cancelled = True
    
    def run(self):
        results = {"ok": [], "failed": [], "cancelled": False}
        
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            future_to_op = {}
            for i, op in enumerate(self.operations):
                if self._is_cancelled:
                    results["cancelled"] = True
                    break
                future = executor.submit(self._execute_operation, op)
                future_to_op[future] = (op, i)
            
            for future in as_completed(future_to_op):
                if self._is_cancelled:
                    results["cancelled"] = True
                    executor.shutdown(wait=False)
                    break
                
                op, idx = future_to_op[future]
                try:
                    success, error_msg = future.result()
                    if success:
                        results["ok"].append(op)
                        self.operation_complete.emit(op, True, "")
                    else:
                        results["failed"].append((op, error_msg))
                        self.operation_complete.emit(op, False, error_msg)
                        if self.error_policy == "stop":
                            self._is_cancelled = True
                            executor.shutdown(wait=False)
                            break
                except Exception as e:
                    results["failed"].append((op, str(e)))
                    self.operation_complete.emit(op, False, str(e))
                    if self.error_policy == "stop":
                        self._is_cancelled = True
                        executor.shutdown(wait=False)
                        break
                
                self.progress_update.emit(len(results["ok"]) + len(results["failed"]), len(self.operations))
        
        self.finished.emit(results)
    
    def _execute_operation(self, op: Operation) -> Tuple[bool, str]:
        try:
            if op.action == "extract":
                handler = get_archive_handler(op.src)
                if not handler:
                    return False, f"No handler for {op.src.suffix}"
                success = handler.extract(op.src, op.dst)
                return success, "" if success else "Extraction failed"
            elif op.action == "pack":
                if op.src.is_file():
                    parent = op.src.parent
                    files = [op.src]
                    handler = get_archive_handler(op.dst)
                    if not handler:
                        handler = ZipHandler()
                    success = handler.pack(parent, op.dst, files)
                else:
                    handler = get_archive_handler(op.dst)
                    if not handler:
                        handler = ZipHandler()
                    success = handler.pack(op.src, op.dst)
                return success, "" if success else "Packing failed"
            return False, f"Unknown action: {op.action}"
        except Exception as e:
            return False, str(e)


class FileProcessor:
    def __init__(self, sort_config: SortKeyConfig, naming_config: NamingConfig, 
                 queue_config: Optional[QueueConfig] = None):
        self.sort_config = sort_config
        self.naming_config = naming_config
        self.queue_config = queue_config
    
    @staticmethod
    def list_input_files(in_dir: Path, patterns: List[str] = None, recursive: bool = True) -> List[Path]:
        if patterns is None:
            patterns = ['*']
        files = []
        for pattern in patterns:
            if recursive:
                files.extend(in_dir.rglob(pattern))
            else:
                files.extend(in_dir.glob(pattern))
        return [f for f in files if f.is_file()]
    
    def sort_files(self, files: List[Path]) -> List[Path]:
        return sorted(files, key=lambda f: self.sort_config.get_sort_key(f),
                     reverse=(self.sort_config.direction == Direction.DESC))
    
    def get_file_hash(self, file_path: Path, length: int = 1024) -> str:
        try:
            with open(file_path, 'rb') as f:
                content = f.read(length)
                return hashlib.md5(content).hexdigest()[:8]
        except:
            return "00000000"
    
    def build_target_names(self, sorted_files: List[Path]) -> List[str]:
        used_names = set()
        target_names = []
        name_groups = defaultdict(list)
        for file_path in sorted_files:
            name_groups[file_path.stem].append(file_path)
        
        for idx, src_path in enumerate(sorted_files):
            base_name = src_path.stem
            extension = src_path.suffix if self.naming_config.preserve_extension else ""
            
            if self.queue_config and self.queue_config.queue_templates:
                target_name = self.queue_config.get_target_name(idx, extension)
            else:
                same_name_count = len(name_groups[base_name])
                if same_name_count > 1 and self.naming_config.counter_enabled:
                    current_idx = name_groups[base_name].index(src_path) + 1
                    target_name = self.naming_config.format_name(base_name, current_idx, extension)
                else:
                    target_name = self.naming_config.format_name(base_name, None, extension)
            
            final_name = target_name
            if self.naming_config.collision_strategy == "increment":
                counter = 1
                while final_name in used_names:
                    final_name = self.naming_config.format_name(Path(target_name).stem, counter, extension)
                    counter += 1
            else:
                file_hash = self.get_file_hash(src_path)
                final_name = f"{Path(target_name).stem}__{file_hash}{extension}"
                if final_name in used_names:
                    final_name = f"{Path(target_name).stem}__dup{counter}{extension}"
            
            used_names.add(final_name)
            target_names.append(final_name)
        
        return target_names
    
    def create_operations(self, src_dir: Path, dst_dir: Path, 
                         mode: Literal["extract", "pack"],
                         archive_format: str = "zip") -> List[Operation]:
        files = self.list_input_files(src_dir)
        sorted_files = self.sort_files(files)
        target_names = self.build_target_names(sorted_files)
        
        operations = []
        for src, target_name in zip(sorted_files, target_names):
            if mode == "extract":
                dst_subdir = dst_dir / Path(target_name).stem
                operations.append(Operation(src=src, dst=dst_subdir, action="extract", archive_format=archive_format))
            else:
                dst_archive = dst_dir / target_name
                if not dst_archive.suffix:
                    dst_archive = dst_archive.with_suffix(f'.{archive_format}')
                operations.append(Operation(src=src, dst=dst_archive, action="pack", archive_format=archive_format))
        
        return operations


class PackUnpackDialog(QDialog):
    def __init__(self, parent=None, current_folder: str = ""):
        super().__init__(parent)
        self.current_folder = current_folder
        self.executor = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Пакетная упаковка/распаковка")
        self.setModal(True)
        self.setMinimumSize(750, 650)
        
        layout = QVBoxLayout()
        tabs = QTabWidget()
        
        # Вкладка 1: Источник
        source_tab = QWidget()
        source_layout = QVBoxLayout()
        
        mode_group = QGroupBox("Режим")
        mode_layout = QHBoxLayout()
        self.extract_radio = QRadioButton("Распаковать архивы")
        self.extract_radio.setChecked(True)
        self.pack_radio = QRadioButton("Упаковать в архивы")
        mode_layout.addWidget(self.extract_radio)
        mode_layout.addWidget(self.pack_radio)
        mode_group.setLayout(mode_layout)
        source_layout.addWidget(mode_group)
        
        source_group = QGroupBox("Исходная папка")
        source_layout_inner = QHBoxLayout()
        self.source_edit = QLineEdit()
        self.source_edit.setText(self.current_folder)
        self.source_browse = QPushButton("Обзор...")
        self.source_browse.clicked.connect(self.browse_source)
        source_layout_inner.addWidget(self.source_edit)
        source_layout_inner.addWidget(self.source_browse)
        source_group.setLayout(source_layout_inner)
        source_layout.addWidget(source_group)
        
        dest_group = QGroupBox("Целевая папка")
        dest_layout = QHBoxLayout()
        self.dest_edit = QLineEdit()
        self.dest_browse = QPushButton("Обзор...")
        self.dest_browse.clicked.connect(self.browse_dest)
        dest_layout.addWidget(self.dest_edit)
        dest_layout.addWidget(self.dest_browse)
        dest_group.setLayout(dest_layout)
        source_layout.addWidget(dest_group)
        
        format_group = QGroupBox("Формат архива")
        format_layout = QHBoxLayout()
        self.format_combo = QComboBox()
        self.format_combo.addItems(["zip", "tar", "tar.gz", "7z", "rar"])
        format_layout.addWidget(QLabel("Формат:"))
        format_layout.addWidget(self.format_combo)
        format_layout.addStretch()
        format_group.setLayout(format_layout)
        source_layout.addWidget(format_group)
        source_layout.addStretch()
        source_tab.setLayout(source_layout)
        tabs.addTab(source_tab, "Источник")
        
        # Вкладка 2: Сортировка
        sort_tab = QWidget()
        sort_layout = QVBoxLayout()
        
        sort_group = QGroupBox("Параметры сортировки")
        sort_grid = QHBoxLayout()
        sort_field_layout = QVBoxLayout()
        sort_field_layout.addWidget(QLabel("Поле:"))
        self.sort_field_combo = QComboBox()
        self.sort_field_combo.addItems(["name", "date", "size"])
        sort_field_layout.addWidget(self.sort_field_combo)
        sort_dir_layout = QVBoxLayout()
        sort_dir_layout.addWidget(QLabel("Направление:"))
        self.sort_dir_combo = QComboBox()
        self.sort_dir_combo.addItems(["asc", "desc"])
        sort_dir_layout.addWidget(self.sort_dir_combo)
        sort_grid.addLayout(sort_field_layout)
        sort_grid.addLayout(sort_dir_layout)
        sort_group.setLayout(sort_grid)
        sort_layout.addWidget(sort_group)
        
        options_group = QGroupBox("Дополнительные опции")
        options_layout = QVBoxLayout()
        self.case_sensitive_cb = QCheckBox("Учитывать регистр (для сортировки по имени)")
        options_layout.addWidget(self.case_sensitive_cb)
        self.tie_breaker_combo = QComboBox()
        self.tie_breaker_combo.addItems(["path", "hash_prefix"])
        options_layout.addWidget(QLabel("Разрешение коллизий:"))
        options_layout.addWidget(self.tie_breaker_combo)
        options_group.setLayout(options_layout)
        sort_layout.addWidget(options_group)
        sort_layout.addStretch()
        sort_tab.setLayout(sort_layout)
        tabs.addTab(sort_tab, "Сортировка")
        
        # Вкладка 3: Именование
        naming_tab = QWidget()
        naming_layout = QVBoxLayout()
        
        template_group = QGroupBox("Шаблон имени")
        template_layout = QHBoxLayout()
        self.template_edit = QLineEdit("{base}")
        self.template_edit.setToolTip("{base} - исходное имя файла")
        template_layout.addWidget(QLabel("Шаблон:"))
        template_layout.addWidget(self.template_edit)
        template_group.setLayout(template_layout)
        naming_layout.addWidget(template_group)
        
        counter_group = QGroupBox("Нумерация")
        counter_layout = QGridLayout()
        self.counter_enabled_cb = QCheckBox("Включить нумерацию")
        self.counter_enabled_cb.setChecked(True)
        counter_layout.addWidget(self.counter_enabled_cb, 0, 0, 1, 2)
        counter_layout.addWidget(QLabel("Стиль:"), 1, 0)
        self.counter_style_combo = QComboBox()
        self.counter_style_combo.addItems(["space_paren", "dot", "underscore", "bracket"])
        counter_layout.addWidget(self.counter_style_combo, 1, 1)
        counter_layout.addWidget(QLabel("Начать с:"), 2, 0)
        self.counter_start_spin = QSpinBox()
        self.counter_start_spin.setRange(1, 9999)
        self.counter_start_spin.setValue(1)
        counter_layout.addWidget(self.counter_start_spin, 2, 1)
        counter_group.setLayout(counter_layout)
        naming_layout.addWidget(counter_group)
        
        queue_group = QGroupBox("Очередь шаблонов")
        queue_layout = QVBoxLayout()
        self.use_queue_cb = QCheckBox("Использовать очередь")
        self.use_queue_cb.toggled.connect(self.toggle_queue)
        queue_layout.addWidget(self.use_queue_cb)
        self.queue_list = QListWidget()
        self.queue_list.setMaximumHeight(100)
        queue_layout.addWidget(self.queue_list)
        queue_btns = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить")
        add_btn.clicked.connect(self.add_queue_template)
        remove_btn = QPushButton("🗑️ Удалить")
        remove_btn.clicked.connect(self.remove_queue_template)
        queue_btns.addWidget(add_btn)
        queue_btns.addWidget(remove_btn)
        queue_layout.addLayout(queue_btns)
        self.repeat_last_cb = QCheckBox("Повторять последний шаблон с нумерацией")
        self.repeat_last_cb.setChecked(True)
        queue_layout.addWidget(self.repeat_last_cb)
        queue_group.setLayout(queue_layout)
        naming_layout.addWidget(queue_group)
        
        collision_group = QGroupBox("Разрешение коллизий имён")
        collision_layout = QHBoxLayout()
        self.collision_combo = QComboBox()
        self.collision_combo.addItems(["increment", "append_hash"])
        collision_layout.addWidget(QLabel("Стратегия:"))
        collision_layout.addWidget(self.collision_combo)
        collision_group.setLayout(collision_layout)
        naming_layout.addWidget(collision_group)
        naming_layout.addStretch()
        naming_tab.setLayout(naming_layout)
        tabs.addTab(naming_tab, "Именование")
        
        # Вкладка 4: Выполнение
        exec_tab = QWidget()
        exec_layout = QVBoxLayout()
        
        parallel_group = QGroupBox("Параллельность")
        parallel_layout = QHBoxLayout()
        parallel_layout.addWidget(QLabel("Количество потоков:"))
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 16)
        self.concurrency_spin.setValue(4)
        parallel_layout.addWidget(self.concurrency_spin)
        parallel_layout.addStretch()
        parallel_group.setLayout(parallel_layout)
        exec_layout.addWidget(parallel_group)
        
        error_group = QGroupBox("Обработка ошибок")
        error_layout = QHBoxLayout()
        self.error_policy_combo = QComboBox()
        self.error_policy_combo.addItems(["continue", "stop"])
        error_layout.addWidget(QLabel("При ошибке:"))
        error_layout.addWidget(self.error_policy_combo)
        error_group.setLayout(error_layout)
        exec_layout.addWidget(error_group)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        exec_layout.addWidget(self.progress_bar)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        exec_layout.addWidget(QLabel("Лог операций:"))
        exec_layout.addWidget(self.log_text)
        exec_layout.addStretch()
        exec_tab.setLayout(exec_layout)
        tabs.addTab(exec_tab, "Выполнение")
        
        layout.addWidget(tabs)
        
        self.execute_btn = QPushButton("▶ Выполнить")
        self.execute_btn.clicked.connect(self.execute)
        self.cancel_btn = QPushButton("⏹ Отмена")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        self.close_btn = QPushButton("Закрыть")
        self.close_btn.clicked.connect(self.reject)
        
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.execute_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
        self.toggle_queue()
    
    def browse_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите исходную папку")
        if folder:
            self.source_edit.setText(folder)
    
    def browse_dest(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите целевую папку")
        if folder:
            self.dest_edit.setText(folder)
    
    def toggle_queue(self):
        enabled = self.use_queue_cb.isChecked()
        self.queue_list.setEnabled(enabled)
        self.repeat_last_cb.setEnabled(enabled)
    
    def add_queue_template(self):
        template, ok = QInputDialog.getText(self, "Добавить шаблон", "Введите шаблон имени:")
        if ok and template:
            self.queue_list.addItem(template)
    
    def remove_queue_template(self):
        current = self.queue_list.currentRow()
        if current >= 0:
            self.queue_list.takeItem(current)
    
    def get_configs(self):
        sort_config = SortKeyConfig(
            field=SortField(self.sort_field_combo.currentText()),
            direction=Direction(self.sort_dir_combo.currentText()),
            case_sensitive=self.case_sensitive_cb.isChecked(),
            tie_breaker=self.tie_breaker_combo.currentText()
        )
        naming_config = NamingConfig(
            base_template=self.template_edit.text(),
            counter_enabled=self.counter_enabled_cb.isChecked(),
            counter_style=self.counter_style_combo.currentText(),
            counter_start=self.counter_start_spin.value(),
            collision_strategy=self.collision_combo.currentText()
        )
        queue_config = None
        if self.use_queue_cb.isChecked() and self.queue_list.count() > 0:
            templates = [self.queue_list.item(i).text() for i in range(self.queue_list.count())]
            queue_config = QueueConfig(queue_templates=templates, repeat_last=self.repeat_last_cb.isChecked())
        return sort_config, naming_config, queue_config
    
    def log_message(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {msg}")
        QApplication.processEvents()
    
    def execute(self):
        src_dir = Path(self.source_edit.text())
        dst_dir = Path(self.dest_edit.text())
        
        if not src_dir.exists():
            QMessageBox.warning(self, "Ошибка", "Исходная папка не существует")
            return
        
        if not dst_dir.exists():
            reply = QMessageBox.question(self, "Подтверждение", f"Папка {dst_dir} не существует. Создать?",
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                dst_dir.mkdir(parents=True, exist_ok=True)
            else:
                return
        
        mode = "extract" if self.extract_radio.isChecked() else "pack"
        archive_format = self.format_combo.currentText()
        sort_config, naming_config, queue_config = self.get_configs()
        
        self.log_message(f"Начинаем {'распаковку' if mode == 'extract' else 'упаковку'}")
        self.log_message(f"Источник: {src_dir}")
        self.log_message(f"Цель: {dst_dir}")
        
        try:
            processor = FileProcessor(sort_config, naming_config, queue_config)
            operations = processor.create_operations(src_dir, dst_dir, mode, archive_format)
            
            if not operations:
                self.log_message("Нет файлов для обработки!")
                return
            
            self.log_message(f"Создано операций: {len(operations)}")
            for op in operations[:10]:
                self.log_message(f"  {op.src.name} -> {op.dst.name}")
            if len(operations) > 10:
                self.log_message(f"  ... и ещё {len(operations) - 10} операций")
            
            self.execute_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, len(operations))
            self.progress_bar.setValue(0)
            
            self.executor = PackUnpackExecutor(
                operations,
                concurrency=self.concurrency_spin.value(),
                error_policy=self.error_policy_combo.currentText()
            )
            self.executor.progress_update.connect(self.on_progress)
            self.executor.operation_complete.connect(self.on_operation_complete)
            self.executor.finished.connect(self.on_finished)
            self.executor.start()
            
        except Exception as e:
            self.log_message(f"Ошибка: {e}")
            QMessageBox.critical(self, "Ошибка", str(e))
            self.execute_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
    
    def on_progress(self, current, total):
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"{current}/{total}")
    
    def on_operation_complete(self, op, success, error_msg):
        status = "✓" if success else "✗"
        self.log_message(f"{status} {op.src.name} -> {op.dst.name}")
        if not success and error_msg:
            self.log_message(f"  Ошибка: {error_msg}")
    
    def on_finished(self, results):
        self.progress_bar.setVisible(False)
        self.execute_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
        self.log_message(f"\n{'='*50}")
        self.log_message(f"Завершено! Успешно: {len(results['ok'])}, Ошибок: {len(results['failed'])}")
        if results.get('cancelled'):
            self.log_message("Операция отменена")
        
        if results['failed']:
            QMessageBox.warning(self, "Предупреждение", f"Завершено с ошибками. Успешно: {len(results['ok'])}, Ошибок: {len(results['failed'])}")
        else:
            QMessageBox.information(self, "Успех", f"Операция завершена успешно! Обработано: {len(results['ok'])}")
    
    def cancel(self):
        if self.executor and self.executor.isRunning():
            self.executor.cancel()
            self.log_message("Отмена операции...")
            self.cancel_btn.setEnabled(False)


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
        
        # Настройка интерфейса
        self.init_ui()
        self.apply_theme()
        self.update_search_mode_text()
        self.check_data_folder_on_startup()
        
        # Загрузка состояния панели инструментов
        current_mode = self.settings.get('current_toolbar_mode', 'full')
        configs = self.settings.get('toolbar_configs', {})
        if current_mode in configs:
            self.custom_toolbar.apply_config(configs[current_mode])
        else:
            default_config = {'mode': current_mode, 'items': [], 'show_toolbar': True, 'custom_name': ''}
            self.custom_toolbar.apply_config(default_config)
    
    def _handle_exception(self, exctype, value, tb):
        error_msg = ''.join(traceback.format_exception(exctype, value, tb))
        print(f"Необработанное исключение: {error_msg}")
        if hasattr(self, 'settings_manager') and self.settings_manager.crash_reporter:
            self.settings_manager.crash_reporter.report_error(str(exctype.__name__), str(value), error_msg)
        QMessageBox.critical(self, "Критическая ошибка", f"Произошла неожиданная ошибка:\n\n{value}\n\nОтчёт сохранён.")
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
        self.setWindowTitle("Sofil - Сканер папок и пакетная обработка")
        self.setGeometry(100, 100, 1900, 1000)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Создаём основные виджеты
        self.create_main_widgets()
        
        # Создаём кастомную панель инструментов
        self.custom_toolbar = CustomToolBar(self)
        self.addToolBar(self.custom_toolbar)
        
        # Создаём меню
        self.create_menu()
        
        # Основной сплиттер
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
        
        # Статус бар
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
        self.folder_combo.setStyleSheet("QComboBox { min-height: 25px; padding: 2px; }")
        
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
        if self.multicriteria_search_enabled:
            self.multicriteria_btn.setStyleSheet("""
                QPushButton {
                    background-color: #5a5a5a;
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
        
        # Файл
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
        
        # Инструменты (НОВОЕ!)
        tools_menu = menubar.addMenu("🔧 Инструменты")
        pack_unpack_action = QAction("📦 Пакетная упаковка/распаковка", self)
        pack_unpack_action.setShortcut("Ctrl+P")
        pack_unpack_action.triggered.connect(self.open_pack_unpack_wizard)
        tools_menu.addAction(pack_unpack_action)
        
        # Настройки
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
        
        # Вид
        view_menu = menubar.addMenu("Вид")
        self.dark_mode_action = QAction("🌙 Тёмная тема", self, checkable=True)
        self.dark_mode_action.setChecked(self.dark_mode)
        self.dark_mode_action.triggered.connect(self.toggle_dark_mode)
        view_menu.addAction(self.dark_mode_action)
        
        # Помощь
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
    
    def open_pack_unpack_wizard(self):
        current_folder = self.folder_combo.currentText()
        if not current_folder or not os.path.exists(current_folder):
            current_folder = self.settings.get("main_folder", "")
        dialog = PackUnpackDialog(self, current_folder)
        dialog.exec_()
    
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
        reply = QMessageBox.question(self, "Подтверждение", "Очистить всю историю?", QMessageBox.Yes | QMessageBox.No)
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
        reply = QMessageBox.question(self, "Подтверждение", "Очистить все отчёты об ошибках?", QMessageBox.Yes | QMessageBox.No)
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
    
    # ==================== МЕТОДЫ ДЛЯ ПОИСКА ====================
    
    def update_search_mode_text(self):
        mode_texts = {"name": "🔤 Название", "content": "📄 Содержание", "date": "📅 Дата", "size": "📊 Размер"}
        self.search_mode_btn.setText(mode_texts.get(self.current_search_mode, "🔤 Название"))
        
        if not self.multicriteria_search_enabled:
            placeholders = {
                "name": "Введите название файла...",
                "content": "Введите текст для поиска в содержимом файлов...",
                "date": "Введите дату (ГГГГ-ММ-ДД) или период (ГГГГ-ММ-ДД-ГГГГ-ММ-ДД)...",
                "size": "Введите размер: >1MB, <500KB, 100-200KB, =2MB..."
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
        mode_names = {"name": "названию", "content": "содержимому", "date": "дате", "size": "размеру"}
        self.status_label.setText(f"🔍 Поиск по {mode_names.get(self.current_search_mode, 'названию')}")
    
    def toggle_multicriteria_search(self, enabled):
        self.multicriteria_search_enabled = enabled
        if enabled:
            self.search_input.setPlaceholderText(
                "Мультипоиск: слово1;слово2 (оба в одном файле) | слово1:слово2 (любое в разных файлах)\n"
                "Пример: hello;world | test:123 | ;content"
            )
        else:
            self.update_search_mode_text()
        self.settings["multicriteria_search"] = enabled
        self.settings_manager.save()
        self.update_multicriteria_btn_style()
        self.refresh_files_tree()
    
    def parse_search_criteria(self, search_text):
        if not self.multicriteria_search_enabled:
            return {self.current_search_mode: search_text}
        if not search_text:
            return {}
        if ';' not in search_text and ':' not in search_text:
            return {self.current_search_mode: search_text}
        if ';' in search_text:
            operator = 'AND'
            parts = [part.strip() for part in search_text.split(';')]
        else:
            operator = 'OR'
            parts = [part.strip() for part in search_text.split(':')]
        return {'operator': operator, 'parts': parts, 'mode': self.current_search_mode}
    
    def matches_search_criteria(self, file_info, criteria):
        try:
            if isinstance(criteria, dict) and 'operator' in criteria:
                operator = criteria['operator']
                parts = criteria['parts']
                mode = criteria['mode']
                matches = []
                for part in parts:
                    if not part:
                        matches.append(True)
                        continue
                    if mode == "name":
                        match = part.lower() in file_info['name'].lower()
                    elif mode == "content":
                        content = self.load_file_content(file_info).lower()
                        match = part.lower() in content
                    elif mode == "date":
                        date_str = file_info['modified'].strftime("%Y-%m-%d")
                        try:
                            if re.match(r'^\d{4}-\d{2}-\d{2}$', part):
                                match = date_str == part
                            elif '-' in part and len(part.split('-')) == 2:
                                start_str, end_str = part.split('-')
                                start_date = datetime.strptime(start_str.strip(), "%Y-%m-%d")
                                end_date = datetime.strptime(end_str.strip(), "%Y-%m-%d")
                                file_date = file_info['modified']
                                match = start_date <= file_date <= end_date
                            else:
                                match = part in date_str
                        except:
                            match = part in date_str
                    elif mode == "size":
                        size_bytes = file_info['size']
                        match = self.check_size_match(size_bytes, part)
                    else:
                        match = True
                    matches.append(match)
                if operator == 'AND':
                    return all(matches)
                else:
                    return any(matches)
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
                if not self.check_size_match(size_bytes, criteria["size"]):
                    return False
            return True
        except:
            return False
    
    def check_size_match(self, size_bytes, search_size):
        search_size = search_size.strip().upper()
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
                return abs(size_bytes - num_bytes) < 1024
            elif op == "<":
                return size_bytes < num_bytes
            elif op == "<=":
                return size_bytes <= num_bytes
            elif op == ">":
                return size_bytes > num_bytes
            elif op == ">=":
                return size_bytes >= num_bytes
        elif '-' in search_size:
            try:
                start_str, end_str = search_size.split('-')
                start_bytes = self.parse_size_to_bytes(start_str.strip())
                end_bytes = self.parse_size_to_bytes(end_str.strip())
                return start_bytes <= size_bytes <= end_bytes
            except:
                pass
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
    
    # ==================== МЕТОДЫ ОСНОВНОЙ ФУНКЦИОНАЛЬНОСТИ ====================
    
    def browse_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку для сканирования")
        if folder_path:
            self.folder_combo.setCurrentText(folder_path)
            self.scan_selected()
    
    def browse_archive(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите архив", "", "Archives (*.zip *.rar *.7z)")
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
        self.settings_manager.add_to_scan_history(folder_path)
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
    
    def on_scan_complete(self, all_files, extension_data, available_extensions, duplicate_files, file_groups, scan_time):
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
        self.status_label.setText(f"Сканирование завершено за {scan_time:.1f} сек")
        self.file_count_label.setText(f"Файлов: {len(all_files)}")
    
    def on_scan_error(self, error_msg):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.scan_timer.stop()
        self.settings_manager.report_error("Ошибка сканирования", error_msg)
        QMessageBox.critical(self, "Ошибка", f"Не удалось выполнить сканирование:\n{error_msg}")
        self.status_label.setText("Ошибка сканирования")
    
    def update_extensions_tree(self):
        self.extensions_tree.clear()
        all_item = QTreeWidgetItem(self.extensions_tree, ["Все расширения", str(len(self.all_files))])
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
                if self.settings.get("hide_blockbench_children", True):
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
            is_favorite = folder_name in self.settings.get("favorites", [])
            folder_text = f"⭐ {folder_name}" if is_favorite else f"📁 {folder_name}"
            folder_item = QTreeWidgetItem(self.files_tree, [folder_text, "", "", "", "virtual_folder"])
            if folder_name in self.virtual_folders_expanded:
                folder_item.setExpanded(self.virtual_folders_expanded[folder_name])
            for file_info in files:
                if isinstance(file_info, dict) and 'path' in file_info:
                    file_path = file_info['path']
                    for f in self.all_files:
                        if f['path'] == file_path:
                            is_file_favorite = f.get('is_favorite', False)
                            file_text = f"⭐ {f['name']}" if is_file_favorite else f['name']
                            size_str = self.format_file_size(f['size'])
                            modified_str = f['modified'].strftime("%Y-%m-%d %H:%M")
                            QTreeWidgetItem(folder_item, [file_text, size_str, modified_str, file_path, 'file'])
                            break
    
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
            QTreeWidgetItem(self.files_tree, [display_name, size_str, modified_str, file_info['path'], 'file'])
    
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
                QTreeWidgetItem(self.files_tree, [display_name, size_str, modified_str, file_info['path'], 'file'])
            else:
                folder_item = QTreeWidgetItem(self.files_tree, [f"📁 {filename} ({len(file_list)} файлов)", "", "", "", 'folder'])
                for file_info in file_list:
                    is_favorite = file_info.get('is_favorite', False)
                    display_name = f"⭐ {filename}" if is_favorite else filename
                    size_str = self.format_file_size(file_info['size'])
                    modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
                    QTreeWidgetItem(folder_item, [display_name, size_str, modified_str, file_info['path'], 'file'])
    
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
        texts = {"name_asc": "A-Z ↑", "name_desc": "Z-A ↓", "date_asc": "📅 ↑", "date_desc": "📅 ↓", "size_asc": "📊 ↑", "size_desc": "📊 ↓"}
        self.sort_btn.setText(texts.get(new_mode, "A-Z ↑"))
        self.refresh_files_tree()
    
    # ==================== КОНТЕКСТНОЕ МЕНЮ ====================
    
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
    
    # ==================== ОТКРЫТИЕ ФАЙЛОВ ====================
    
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
            self.settings_manager.add_to_file_history(file_path)
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
                    subprocess.run(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", file_path], shell=True, check=True)
                except subprocess.CalledProcessError:
                    os.startfile(os.path.normpath(file_path))
            elif system == "Darwin":
                subprocess.run(["open", "-a", "Finder", file_path], check=True)
            else:
                reply = QMessageBox.question(self, "Открытие файла",
                    "На Linux нет стандартного диалога 'Открыть с помощью'.\nОткрыть файл стандартной программой?",
                    QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.open_file_default(file_path)
                else:
                    return
            self.settings_manager.add_to_file_history(file_path)
            self.status_label.setText(f"Выбор программы для: {os.path.basename(file_path)}")
        except Exception as e:
            self.settings_manager.report_error("Ошибка диалога открытия", str(e), {"file_path": file_path})
            try:
                self.open_file_default(file_path)
            except:
                QMessageBox.critical(self, "Ошибка", f"Не удалось открыть диалог выбора программы:\n{str(e)}")
    
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
    
    # ==================== ВИРТУАЛЬНЫЕ ПАПКИ ====================
    
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
                files_to_add.append({'path': file_path, 'name': file_name})
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
            QMessageBox.warning(self, "Предупреждение", "Некоторые файлы уже находятся в папке и не были добавлены повторно.")
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
                files_to_add.append({'path': file_path, 'name': file_name})
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
                self.add_to_action_history('file_rename', {'old_path': old_path, 'new_path': new_path})
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
        reply = QMessageBox.question(self, "Подтверждение", f"Вы уверены, что хотите удалить папку '{folder_name}'?",
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
        reply = QMessageBox.question(self, "Подтверждение", f"Удалить {file_count} выбранных файл(ов)?\n\nЭто действие можно отменить (Ctrl+Z).",
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
    
    # ==================== UNDO/REDO ====================
    
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
    
    # ==================== НАСТРОЙКИ ====================
    
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
            dark_palette.setColor(QPalette.Text, QColor(240, 240, 240))
            dark_palette.setColor(QPalette.Button, QColor(60, 60, 62))
            dark_palette.setColor(QPalette.ButtonText, QColor(240, 240, 240))
            app.setPalette(dark_palette)
        else:
            app.setPalette(app.style().standardPalette())
    
    def load_folder_history(self):
        pass
    
    # ==================== ДИАЛОГИ ====================
    
    def show_hotkeys(self):
        text = """⌨️ Сочетания клавиш

📁 Основные:
Ctrl+O — Открыть папку
Ctrl+Shift+O — Открыть архив
Ctrl+S — Сканировать
Ctrl+P — Пакетная упаковка/распаковка

✏️ Работа с файлами:
Ctrl+Z — Отменить действие
Ctrl+Y — Повторить действие

🖱️ Навигация и выделение:
↑/↓ — Выбор файлов
Ctrl+ЛКМ — Множественный выбор
Shift+ЛКМ — Выделение диапазона
Зажатие ЛКМ — Выделение области
Enter — Открыть файл

🔍 Поиск:
; - логическое И (оба слова в одном файле)
: - логическое ИЛИ (слова в разных файлах)
Пример: hello;world | test:123"""
        QMessageBox.information(self, "Сочетания клавиш", text)
    
    def show_about(self):
        text = """Sofil - Сканер папок и пакетная обработка
Версия: 8.1

Автор: Akami_bl

📋 Основное:
📁 Сканирование папок и ZIP-архивов
🗂️ Виртуальные папки для группировки файлов
🔍 Поиск по названию, содержимому, дате и размеру
⭐ Избранное для быстрого доступа

✨ Новое в версии 8.1:
📦 Пакетная упаковка и распаковка файлов
📊 Сортировка по имени, дате, размеру
🔤 Гибкая система именования с шаблонами
📋 Очередь шаблонов для точного сопоставления
🎯 Поддержка ZIP, TAR, 7z, RAR архивов
⚡ Параллельное выполнение (1-16 потоков)

🎨 Настраиваемая панель инструментов
⏱ Таймер сканирования
📊 Статистика использования
💥 Отчёты об ошибках в crashs.json

Обратная связь: akami.bl@gmail.com"""
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