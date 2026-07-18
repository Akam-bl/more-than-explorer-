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
from datetime import datetime
from collections import defaultdict, deque
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QLabel, QLineEdit, QPushButton,
    QComboBox, QProgressBar, QSplitter, QFileDialog, QMessageBox,
    QMenu, QAction, QInputDialog, QToolBar, QStatusBar, QCheckBox,
    QGroupBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QRect
from PyQt5.QtGui import QIcon, QPalette, QColor, QPainter, QPen, QBrush


class ScanThread(QThread):
    """Поток для сканирования папки"""
    progress_update = pyqtSignal(str, int)
    scan_complete = pyqtSignal(list, dict, set, dict, dict)
    error = pyqtSignal(str)
    
    def __init__(self, folder_path, settings):
        super().__init__()
        self.folder_path = folder_path
        self.settings = settings
        self.stop_flag = False
        
    def run(self):
        try:
            all_files = []
            extension_data = defaultdict(list)
            available_extensions = set()
            all_folders = set()
            duplicate_files = defaultdict(list)
            
            if os.path.isfile(self.folder_path):
                self.scan_archive(self.folder_path, all_files, extension_data, available_extensions)
            else:
                self.scan_real_folder(self.folder_path, all_files, extension_data, available_extensions, all_folders)
            
            # Находим дубликаты
            file_groups = defaultdict(list)
            for file_info in all_files:
                key = file_info['name']
                file_groups[key].append(file_info)
            
            for filename, files in file_groups.items():
                if len(files) > 1:
                    duplicate_files[filename] = files
            
            self.scan_complete.emit(all_files, extension_data, available_extensions, duplicate_files, dict(file_groups))
            
        except Exception as e:
            self.error.emit(str(e))
    
    def scan_real_folder(self, folder_path, all_files, extension_data, available_extensions, all_folders):
        for root, dirs, files in os.walk(folder_path):
            if self.stop_flag:
                break
                
            for dir_name in dirs:
                full_dir_path = os.path.join(root, dir_name)
                all_folders.add(full_dir_path)
            
            for i, file in enumerate(files):
                if self.stop_flag:
                    break
                    
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
                
                if i % 100 == 0:
                    self.progress_update.emit(f"Сканирование... {len(all_files)} файлов", 0)
    
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
                for i, file_info in enumerate(file_list):
                    if not file_info.is_dir():
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
                        
                        if i % 100 == 0:
                            self.progress_update.emit(f"Сканирование архива... {len(all_files)} файлов", 0)
    
    def stop(self):
        self.stop_flag = True


class CustomTreeWidget(QTreeWidget):
    """Кастомное дерево файлов с поддержкой перетаскивания мышью для выделения"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        
        # Переменные для выделения перетаскиванием
        self.drag_select_start = None
        self.drag_select_rect = None
        self.is_drag_selecting = False
        self.drag_select_items = set()
        
        # Переменные для Ctrl+ЛКМ и Shift+ЛКМ
        self.last_selection_state = set()
        self.last_clicked_item = None
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            
            # Сохраняем текущее состояние выделения
            self.last_selection_state = set(self.selectedItems())
            self.last_clicked_item = item
            
            # Обработка Ctrl+ЛКМ
            if event.modifiers() & Qt.ControlModifier:
                if item:
                    if item in self.last_selection_state:
                        item.setSelected(False)
                    else:
                        item.setSelected(True)
                    event.accept()
                    return
                
            # Обработка Shift+ЛКМ
            elif event.modifiers() & Qt.ShiftModifier:
                if item and self.last_clicked_item and self.last_clicked_item != item:
                    # Получаем все видимые элементы
                    all_items = []
                    it = QTreeWidgetItemIterator(self)
                    while it.value():
                        all_items.append(it.value())
                        it += 1
                    
                    # Находим индексы
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
                
            # Начало выделения перетаскиванием
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
                # Обновляем прямоугольник выделения
                self.drag_select_rect = QRect(
                    self.drag_select_start,
                    event.pos()
                ).normalized()
                
                # Находим все элементы в прямоугольнике
                new_selection = set()
                
                # Перебираем все видимые элементы
                it = QTreeWidgetItemIterator(self)
                while it.value():
                    item = it.value()
                    rect = self.visualItemRect(item)
                    if self.drag_select_rect.intersects(rect):
                        new_selection.add(item)
                    it += 1
                
                # Обновляем выделение
                for item in new_selection:
                    item.setSelected(True)
                for item in self.drag_select_items - new_selection:
                    item.setSelected(False)
                
                self.drag_select_items = new_selection
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
        
        # Рисуем прямоугольник выделения
        if self.is_drag_selecting and self.drag_select_rect:
            painter = QPainter(self.viewport())
            painter.setPen(QPen(QColor(100, 150, 255), 1, Qt.DashLine))
            painter.setBrush(QBrush(QColor(100, 150, 255, 50)))
            painter.drawRect(self.drag_select_rect)


class FolderScannerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = self.load_settings()
        
        # ИНИЦИАЛИЗИРУЕМ ПЕРЕМЕННЫЕ
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
        
        # Переменные для расширенного поиска
        self.search_modes = ["name", "content", "date", "size"]
        self.current_search_mode = self.settings.get("search_mode", "name")
        self.multicriteria_search_enabled = self.settings.get("multicriteria_search", False)
        
        # Переменные для меню
        self.hide_bb_children_cb_menu = None
        self.auto_load_textures_cb = None
        
        # Флаг для предотвращения повторного вызова refresh
        self.is_refreshing = False
        
        self.init_ui()
        self.apply_theme()
        
    def load_settings(self):
        """Загрузка настроек из файла"""
        default_settings = {
            "main_folder": "",
            "data_folder": "",
            "temp_folder": tempfile.gettempdir(),
            "scan_history": [],
            "unrar_path": "",
            "sort_mode": "name_asc",
            "archive_extensions": [".zip", ".rar", ".7z"],
            "hide_duplicates": False,
            "favorites": [],
            "last_extension": "",
            "hide_blockbench_children": True,
            "virtual_folders": {},
            "search_mode": "name",
            "auto_load_textures": False,
            "dark_mode": False,
            "multicriteria_search": False
        }
        
        settings_path = self.get_settings_path()
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                    default_settings.update(loaded_settings)
            except Exception as e:
                print(f"Ошибка загрузки настроек: {e}")
        
        return default_settings
    
    def get_settings_path(self):
        """Получить путь к файлу настроек"""
        home_settings = os.path.join(os.path.expanduser("~"), "folder_scanner_settings.json")
        return home_settings
    
    def save_settings(self):
        """Сохранение настроек в файл"""
        try:
            settings_path = self.get_settings_path()
            os.makedirs(os.path.dirname(settings_path), exist_ok=True)
            
            self.settings["virtual_folders"] = self.virtual_folders
            if self.hide_bb_children_cb_menu:
                self.settings["hide_blockbench_children"] = self.hide_bb_children_cb_menu.isChecked()
            if hasattr(self, 'hide_duplicates_cb'):
                self.settings["hide_duplicates"] = self.hide_duplicates_cb.isChecked()
            if self.auto_load_textures_cb:
                self.settings["auto_load_textures"] = self.auto_load_textures_cb.isChecked()
            self.settings["dark_mode"] = self.dark_mode
            self.settings["search_mode"] = self.current_search_mode
            self.settings["multicriteria_search"] = self.multicriteria_search_enabled
            
            if hasattr(self, 'folder_combo') and self.folder_combo.currentText():
                current_folder = self.folder_combo.currentText()
                if os.path.exists(current_folder):
                    self.settings["main_folder"] = current_folder
            
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения настроек: {e}")
    
    def init_ui(self):
        """Инициализация пользовательского интерфейса"""
        self.setWindowTitle("Sofil - Сканер папок")
        self.setGeometry(100, 100, 1600, 800)
        
        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Панель инструментов
        self.create_toolbar()
        
        # Меню
        self.create_menu()
        
        # Основная область
        splitter = QSplitter(Qt.Horizontal)
        
        # Левая панель - расширения
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
        
        # Правая панель - файлы
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
        
        # Строка состояния
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.status_label = QLabel("Готов к работе")
        self.file_count_label = QLabel("Файлов: 0")
        self.status_bar.addWidget(self.status_label)
        self.status_bar.addWidget(self.file_count_label, 1)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
        
        # Загрузка истории папок
        self.load_folder_history()
        
    def create_toolbar(self):
        """Создание панели инструментов"""
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)
        
        # Папка
        folder_label = QLabel("Папка:")
        toolbar.addWidget(folder_label)
        
        self.folder_combo = QComboBox()
        self.folder_combo.setEditable(True)
        self.folder_combo.setMinimumWidth(400)
        toolbar.addWidget(self.folder_combo)
        
        self.browse_folder_btn = QPushButton("Обзор папки...")
        self.browse_folder_btn.clicked.connect(self.browse_folder)
        toolbar.addWidget(self.browse_folder_btn)
        
        self.browse_archive_btn = QPushButton("Обзор архива...")
        self.browse_archive_btn.clicked.connect(self.browse_archive)
        toolbar.addWidget(self.browse_archive_btn)
        
        toolbar.addSeparator()
        
        # Кнопки отмены/повтора
        self.undo_btn = QPushButton("↶")
        self.undo_btn.setToolTip("Отменить последнее действие (Ctrl+Z)")
        self.undo_btn.clicked.connect(self.undo_action)
        self.undo_btn.setEnabled(False)
        toolbar.addWidget(self.undo_btn)
        
        self.redo_btn = QPushButton("↷")
        self.redo_btn.setToolTip("Повторить отмененное действие (Ctrl+Y)")
        self.redo_btn.clicked.connect(self.redo_action)
        self.redo_btn.setEnabled(False)
        toolbar.addWidget(self.redo_btn)
        
        toolbar.addSeparator()
        
        # Поиск
        search_label = QLabel("Поиск:")
        toolbar.addWidget(search_label)
        
        self.search_mode_btn = QPushButton("Название")
        self.search_mode_btn.clicked.connect(self.toggle_search_mode)
        self.search_mode_btn.setFixedWidth(100)
        toolbar.addWidget(self.search_mode_btn)
        
        self.multicriteria_btn = QPushButton("Мультипоиск")
        self.multicriteria_btn.setCheckable(True)
        self.multicriteria_btn.setChecked(self.multicriteria_search_enabled)
        self.multicriteria_btn.toggled.connect(self.toggle_multicriteria_search)
        self.multicriteria_btn.setFixedWidth(100)
        toolbar.addWidget(self.multicriteria_btn)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите текст для поиска...")
        self.search_input.textChanged.connect(self.on_search_changed)
        self.search_input.setMinimumWidth(300)
        toolbar.addWidget(self.search_input)
        
        toolbar.addSeparator()
        
        # Вид и настройки
        view_settings_label = QLabel("Вид:")
        toolbar.addWidget(view_settings_label)
        
        self.hide_duplicates_cb = QCheckBox("Группировать дубликаты")
        self.hide_duplicates_cb.setChecked(self.settings.get("hide_duplicates", False))
        self.hide_duplicates_cb.stateChanged.connect(self.on_hide_duplicates_changed)
        toolbar.addWidget(self.hide_duplicates_cb)
        
        toolbar.addSeparator()
        
        self.sort_btn = QPushButton("A-Z ↑")
        self.sort_btn.clicked.connect(self.toggle_sorting)
        toolbar.addWidget(self.sort_btn)
        
        self.favorites_btn = QPushButton("⭐")
        self.favorites_btn.setCheckable(True)
        self.favorites_btn.clicked.connect(self.toggle_favorites_filter)
        toolbar.addWidget(self.favorites_btn)
        
        toolbar.addSeparator()
        
        self.scan_btn = QPushButton("Сканировать")
        self.scan_btn.clicked.connect(self.scan_selected)
        toolbar.addWidget(self.scan_btn)
        
        # Устанавливаем начальный текст для режима поиска
        self.update_search_mode_text()
        
    def create_menu(self):
        """Создание меню"""
        menubar = self.menuBar()
        
        # Меню Файл
        file_menu = menubar.addMenu("Файл")
        
        open_folder_action = QAction("Открыть папку...", self)
        open_folder_action.setShortcut("Ctrl+O")
        open_folder_action.triggered.connect(self.browse_folder)
        file_menu.addAction(open_folder_action)
        
        open_archive_action = QAction("Открыть архив...", self)
        open_archive_action.setShortcut("Ctrl+Shift+O")
        open_archive_action.triggered.connect(self.browse_archive)
        file_menu.addAction(open_archive_action)
        
        file_menu.addSeparator()
        
        scan_action = QAction("Сканировать", self)
        scan_action.setShortcut("Ctrl+S")
        scan_action.triggered.connect(self.scan_selected)
        file_menu.addAction(scan_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Меню Настройки
        settings_menu = menubar.addMenu("Настройки")
        
        # Подменю Спец настройки
        special_menu = settings_menu.addMenu("Спец настройки")
        
        self.hide_bb_children_cb_menu = QAction("Скрыть дочерние файлы Blockbench", self, checkable=True)
        self.hide_bb_children_cb_menu.setChecked(self.settings.get("hide_blockbench_children", True))
        self.hide_bb_children_cb_menu.triggered.connect(self.on_hide_bb_children_changed)
        special_menu.addAction(self.hide_bb_children_cb_menu)
        
        self.auto_load_textures_cb = QAction("Автозагрузка текстур", self, checkable=True)
        self.auto_load_textures_cb.setChecked(self.settings.get("auto_load_textures", False))
        self.auto_load_textures_cb.triggered.connect(self.on_auto_load_textures_changed)
        special_menu.addAction(self.auto_load_textures_cb)
        
        settings_menu.addSeparator()
        
        data_folder_action = QAction("Папка для данных...", self)
        data_folder_action.triggered.connect(self.set_data_folder)
        settings_menu.addAction(data_folder_action)
        
        temp_folder_action = QAction("Временная папка...", self)
        temp_folder_action.triggered.connect(self.set_temp_folder)
        settings_menu.addAction(temp_folder_action)
        
        unrar_path_action = QAction("Путь к UnRAR...", self)
        unrar_path_action.triggered.connect(self.set_unrar_path)
        settings_menu.addAction(unrar_path_action)
        
        # Меню Вид
        view_menu = menubar.addMenu("Вид")
        
        self.dark_mode_action = QAction("Тёмная тема", self, checkable=True)
        self.dark_mode_action.setChecked(self.dark_mode)
        self.dark_mode_action.triggered.connect(self.toggle_dark_mode)
        view_menu.addAction(self.dark_mode_action)
        
        # Меню Помощь
        help_menu = menubar.addMenu("Помощь")
        
        hotkeys_action = QAction("Сочетания клавиш", self)
        hotkeys_action.triggered.connect(self.show_hotkeys)
        help_menu.addAction(hotkeys_action)
        
        help_menu.addSeparator()
        
        about_action = QAction("О программе", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def update_search_mode_text(self):
        """Обновить текст кнопки режима поиска"""
        mode_texts = {
            "name": "Название",
            "content": "Содержание",
            "date": "Дата изменения",
            "size": "Размер"
        }
        self.search_mode_btn.setText(mode_texts.get(self.current_search_mode, "Название"))
        
        placeholders = {
            "name": "Введите название файла...",
            "content": "Введите текст для поиска в содержимом...",
            "date": "Введите дату (ГГГГ-ММ-ДД) или период...",
            "size": "Введите размер (например: >1MB, <500KB, 100-200KB)..."
        }
        self.search_input.setPlaceholderText(placeholders.get(self.current_search_mode, "Введите текст для поиска..."))
    
    def toggle_dark_mode(self):
        """Переключение тёмной темы"""
        self.dark_mode = self.dark_mode_action.isChecked()
        self.apply_theme()
        self.save_settings()
    
    def apply_theme(self):
        """Применение темы (светлая/тёмная)"""
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
    
    def toggle_search_mode(self):
        """Переключить режим поиска"""
        current_index = self.search_modes.index(self.current_search_mode)
        next_index = (current_index + 1) % len(self.search_modes)
        self.current_search_mode = self.search_modes[next_index]
        
        self.update_search_mode_text()
        self.save_settings()
        
        if not self.multicriteria_search_enabled:
            self.refresh_files_tree()
    
    def toggle_multicriteria_search(self, enabled):
        """Включить/выключить мультикритериальный поиск"""
        self.multicriteria_search_enabled = enabled
        if enabled:
            self.search_input.setPlaceholderText("Введите критерии через ';' (название; содержание; дата; размер)")
        else:
            self.update_search_mode_text()
        self.save_settings()
        self.refresh_files_tree()
    
    def parse_search_criteria(self, search_text):
        """Разобрать строку поиска на критерии"""
        if not self.multicriteria_search_enabled or not search_text:
            return {self.current_search_mode: search_text}
        
        parts = [part.strip() for part in search_text.split(';')]
        criteria = {"name": "", "content": "", "date": "", "size": ""}
        
        keys = list(criteria.keys())
        for i, part in enumerate(parts):
            if i < len(keys) and part:
                criteria[keys[i]] = part
        
        return criteria
    
    def matches_search_criteria(self, file_info, criteria):
        """Проверить файл на соответствие всем критериям поиска"""
        try:
            # Проверка по названию
            if "name" in criteria and criteria["name"]:
                if criteria["name"].lower() not in file_info['name'].lower():
                    return False
            
            # Проверка по содержанию
            if "content" in criteria and criteria["content"]:
                content = self.load_file_content(file_info).lower()
                if criteria["content"].lower() not in content:
                    return False
            
            # Проверка по дате
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
            
            # Проверка по размеру
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
        """Конвертировать строку размера в байты"""
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
        """Обработка изменения поискового запроса"""
        self.refresh_files_tree()
    
    def load_folder_history(self):
        """Загрузка истории папок"""
        history = self.settings.get("scan_history", [])
        self.folder_combo.clear()
        self.folder_combo.addItems(history)
        
        if self.settings.get("main_folder") and os.path.exists(self.settings["main_folder"]):
            self.folder_combo.setCurrentText(self.settings["main_folder"])
    
    def add_to_scan_history(self, folder_path):
        """Добавить папку в историю сканирования"""
        if not folder_path:
            return
            
        scan_history = self.settings.get("scan_history", [])
        
        if folder_path in scan_history:
            scan_history.remove(folder_path)
        
        scan_history.insert(0, folder_path)
        scan_history = scan_history[:10]
        
        self.settings["scan_history"] = scan_history
        self.save_settings()
        self.load_folder_history()
    
    def browse_folder(self):
        """Выбор папки для сканирования"""
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку для сканирования")
        if folder_path:
            self.folder_combo.setCurrentText(folder_path)
            self.scan_selected()
    
    def browse_archive(self):
        """Выбор архива для сканирования"""
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
        """Сканирование выбранной папки или архива"""
        folder_path = self.folder_combo.currentText()
        if not folder_path:
            QMessageBox.warning(self, "Предупреждение", "Выберите папку или архив для сканирования")
            return
        
        if not os.path.exists(folder_path):
            QMessageBox.critical(self, "Ошибка", "Указанный путь не существует")
            return
        
        self.add_to_scan_history(folder_path)
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("Сканирование...")
        self.scan_btn.setEnabled(False)
        
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.stop()
            self.scan_thread.wait()
        
        self.scan_thread = ScanThread(folder_path, self.settings)
        self.scan_thread.scan_complete.connect(self.on_scan_complete)
        self.scan_thread.error.connect(self.on_scan_error)
        self.scan_thread.progress_update.connect(self.on_scan_progress)
        self.scan_thread.start()
    
    def on_scan_progress(self, message, value):
        """Обновление прогресса сканирования"""
        self.status_label.setText(message)
    
    def on_scan_complete(self, all_files, extension_data, available_extensions, duplicate_files, file_groups):
        """Завершение сканирования"""
        self.all_files = all_files
        self.extension_data = extension_data
        self.available_extensions = available_extensions
        self.duplicate_files = duplicate_files
        self.file_groups = file_groups
        
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        
        self.update_extensions_tree()
        self.refresh_files_tree()
        
        file_count = len(all_files)
        self.status_label.setText("Сканирование завершено")
        self.file_count_label.setText(f"Файлов: {file_count}")
    
    def on_scan_error(self, error_msg):
        """Ошибка сканирования"""
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        QMessageBox.critical(self, "Ошибка сканирования", f"Не удалось выполнить сканирование:\n{error_msg}")
        self.status_label.setText("Ошибка сканирования")
    
    def update_extensions_tree(self):
        """Обновление дерева расширений"""
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
        """Обработка выбора расширения"""
        selected_items = self.extensions_tree.selectedItems()
        if not selected_items:
            self.current_extension_filter = ""
        else:
            item = selected_items[0]
            self.current_extension_filter = item.data(0, Qt.UserRole)
        
        self.refresh_files_tree()
    
    def refresh_files_tree(self):
        """Обновление дерева файлов"""
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
            
            # Сортировка
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
        """Загрузить содержимое файла для поиска"""
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
        """Добавить виртуальные папки в дерево"""
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
        """Добавить файлы в обычном режиме"""
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
        """Добавить файлы с группировкой дубликатов"""
        file_paths_in_folders = set()
        for folder_files in self.virtual_folders.values():
            for f in folder_files:
                if isinstance(f, dict):
                    file_paths_in_folders.add(f['path'])
                else:
                    file_paths_in_folders.add(f)
        
        # Группируем по имени
        name_groups = defaultdict(list)
        for file_info in files:
            if file_info['path'] in file_paths_in_folders:
                continue
            name_groups[file_info['name']].append(file_info)
        
        # Добавляем одиночные файлы и группы
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
        """Форматирование размера файла"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB"]
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        
        return f"{s} {size_names[i]}"
    
    def on_hide_duplicates_changed(self):
        """Обработка изменения настройки группировки дубликатов"""
        self.settings["hide_duplicates"] = self.hide_duplicates_cb.isChecked()
        self.save_settings()
        self.refresh_files_tree()
    
    def on_hide_bb_children_changed(self):
        """Обработка изменения настройки скрытия дочерних файлов Blockbench"""
        if self.hide_bb_children_cb_menu:
            self.settings["hide_blockbench_children"] = self.hide_bb_children_cb_menu.isChecked()
            self.save_settings()
            self.refresh_files_tree()
    
    def on_auto_load_textures_changed(self):
        """Обработка изменения настройки автозагрузки текстур"""
        if self.auto_load_textures_cb:
            self.settings["auto_load_textures"] = self.auto_load_textures_cb.isChecked()
            self.save_settings()
    
    def toggle_favorites_filter(self):
        """Переключить фильтр избранного"""
        self.show_favorites_only = self.favorites_btn.isChecked()
        self.refresh_files_tree()
        self.status_label.setText("Показаны только избранные файлы" if self.show_favorites_only else "Показаны все файлы")
    
    def toggle_sorting(self):
        """Переключение сортировки"""
        current_mode = self.settings.get("sort_mode", "name_asc")
        modes = ["name_asc", "name_desc", "date_asc", "date_desc", "size_asc", "size_desc"]
        
        current_index = modes.index(current_mode)
        next_index = (current_index + 1) % len(modes)
        new_mode = modes[next_index]
        
        self.settings["sort_mode"] = new_mode
        self.save_settings()
        
        texts = {
            "name_asc": "A-Z ↑",
            "name_desc": "Z-A ↓", 
            "date_asc": "Дата ↑",
            "date_desc": "Дата ↓",
            "size_asc": "Размер ↑",
            "size_desc": "Размер ↓"
        }
        self.sort_btn.setText(texts.get(new_mode, "A-Z ↑"))
        
        self.refresh_files_tree()
    
    def show_tree_context_menu(self, position):
        """Показать контекстное меню для дерева файлов"""
        item = self.files_tree.itemAt(position)
        if not item:
            return
        
        menu = QMenu()
        item_type = item.text(4)
        
        if item_type == 'file':
            file_path = item.text(3)
            
            open_location = QAction("Открыть расположение файла", self)
            open_location.triggered.connect(lambda: self.open_file_location(file_path))
            menu.addAction(open_location)
            
            open_with = QAction("Открыть с помощью...", self)
            open_with.triggered.connect(lambda: self.open_file_with_dialog_win11(file_path))
            menu.addAction(open_with)
            
            menu.addSeparator()
            
            rename = QAction("Переименовать", self)
            rename.triggered.connect(lambda: self.rename_file(item))
            menu.addAction(rename)
            
            delete = QAction("Удалить", self)
            delete.triggered.connect(self.delete_selected_with_warning)
            menu.addAction(delete)
            
            menu.addSeparator()
            
            favorites = self.settings.get("favorites", [])
            if file_path in favorites:
                unfavorite = QAction("Убрать из избранного", self)
                unfavorite.triggered.connect(lambda: self.toggle_favorite(item))
                menu.addAction(unfavorite)
            else:
                favorite = QAction("Добавить в избранное", self)
                favorite.triggered.connect(lambda: self.toggle_favorite(item))
                menu.addAction(favorite)
            
            menu.addSeparator()
            
            add_to_folder = QMenu("Добавить в виртуальную папку", menu)
            
            create_new = QAction("Создать новую папку...", self)
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
                unfavorite = QAction("Убрать из избранного", self)
                unfavorite.triggered.connect(lambda: self.toggle_virtual_folder_favorite(folder_name))
                menu.addAction(unfavorite)
            else:
                favorite = QAction("Добавить в избранное", self)
                favorite.triggered.connect(lambda: self.toggle_virtual_folder_favorite(folder_name))
                menu.addAction(favorite)
            
            menu.addSeparator()
            
            rename = QAction("Переименовать папку", self)
            rename.triggered.connect(lambda: self.rename_virtual_folder(folder_name))
            menu.addAction(rename)
            
            delete = QAction("Удалить папку", self)
            delete.triggered.connect(lambda: self.delete_virtual_folder_with_warning(folder_name))
            menu.addAction(delete)
        
        elif item_type == 'folder':
            if item.isExpanded():
                collapse = QAction("Свернуть все", self)
                collapse.triggered.connect(lambda: self.collapse_folder(item))
                menu.addAction(collapse)
            else:
                expand = QAction("Развернуть все", self)
                expand.triggered.connect(lambda: self.expand_folder(item))
                menu.addAction(expand)
        
        if menu.actions():
            menu.exec_(self.files_tree.viewport().mapToGlobal(position))
    
    def add_to_virtual_folder(self, folder_name):
        """Добавить выбранные файлы в виртуальную папку"""
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
        
        self.save_settings()
        self.refresh_files_tree()
        
        if duplicate_warning:
            QMessageBox.warning(self, "Предупреждение", 
                              f"Некоторые файлы уже находятся в папке и не были добавлены повторно.")
        
        self.status_label.setText(f"Добавлено {len(files_to_add)} файлов в папку")
    
    def create_virtual_folder_from_selection(self):
        """Создать новую виртуальную папку из выбранных файлов"""
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
            
            self.save_settings()
            self.refresh_files_tree()
            self.status_label.setText(f"Создана папка '{folder_name}' с {len(files_to_add)} файлами")
    
    def expand_folder(self, item):
        """Развернуть папку и все подпапки"""
        item.setExpanded(True)
        for i in range(item.childCount()):
            child = item.child(i)
            if child.text(4) == 'folder':
                child.setExpanded(True)
    
    def collapse_folder(self, item):
        """Свернуть папку и все подпапки"""
        item.setExpanded(False)
        for i in range(item.childCount()):
            child = item.child(i)
            if child.text(4) == 'folder':
                child.setExpanded(False)
    
    def on_file_double_click(self, item, column):
        """Обработка двойного клика по файлу"""
        item_type = item.text(4)
        
        if item_type == 'file':
            file_path = item.text(3)
            self.open_file_with_dialog_win11(file_path)
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
        """Открыть расположение файла в проводнике"""
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
    
    def open_file_with_dialog_win11(self, file_path):
        """Открыть файл с помощью диалога 'Открыть с помощью'"""
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Предупреждение", f"Файл не существует:\n{file_path}")
            return
        
        try:
            if sys.platform == "win32":
                subprocess.run(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", file_path], shell=True)
            elif sys.platform == "darwin":
                subprocess.run(["open", "-a", "Finder", file_path])
            else:
                subprocess.run(["xdg-open", file_path])
            
            self.status_label.setText(f"Открытие файла: {os.path.basename(file_path)}")
        except Exception as e:
            try:
                if sys.platform == "win32":
                    os.startfile(os.path.normpath(file_path))
                else:
                    subprocess.run(["xdg-open", file_path])
            except:
                QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл")
    
    def rename_file(self, item):
        """Переименовать файл"""
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
                
                self.save_settings()
                self.refresh_files_tree()
                self.status_label.setText(f"Файл переименован")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось переименовать файл")
    
    def toggle_favorite(self, item):
        """Добавить/убрать файл из избранного"""
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
        self.save_settings()
        
        for file_info in self.all_files:
            if file_info['path'] == file_path:
                file_info['is_favorite'] = file_path in favorites
        
        self.refresh_files_tree()
        self.status_label.setText("Избранное обновлено")
    
    def toggle_virtual_folder_favorite(self, folder_name):
        """Добавить/убрать виртуальную папку из избранного"""
        favorites = self.settings.get("favorites", [])
        
        if folder_name in favorites:
            favorites.remove(folder_name)
        else:
            favorites.append(folder_name)
        
        self.settings["favorites"] = favorites
        self.save_settings()
        self.refresh_files_tree()
        self.status_label.setText("Избранное обновлено")
    
    def rename_virtual_folder(self, folder_name):
        """Переименовать виртуальную папку"""
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
            
            self.save_settings()
            self.refresh_files_tree()
            self.status_label.setText(f"Папка переименована")
    
    def delete_virtual_folder_with_warning(self, folder_name):
        """Удалить виртуальную папку с предупреждением"""
        reply = QMessageBox.question(self, "Подтверждение", 
                                   f"Вы уверены, что хотите удалить папку '{folder_name}'?",
                                   QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.delete_virtual_folder(folder_name)
    
    def delete_virtual_folder(self, folder_name):
        """Удалить виртуальную папку"""
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
            
            self.save_settings()
            self.refresh_files_tree()
            self.status_label.setText(f"Папка удалена")
    
    def delete_selected_with_warning(self):
        """Удалить выбранные элементы с предупреждением"""
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
        """Удалить выбранные элементы"""
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
                    QMessageBox.critical(self, "Ошибка", f"Не удалось удалить файл {file_info['path']}")
            
            self.save_settings()
            self.refresh_files_tree()
            self.status_label.setText(f"Удалено файлов: {deleted_count}")
    
    def add_to_action_history(self, action_type, data):
        """Добавить действие в историю"""
        if self.is_undo_redo_in_progress:
            return
            
        if self.current_action_index < len(self.action_history) - 1:
            self.action_history = deque(list(self.action_history)[:self.current_action_index + 1], maxlen=50)
        
        self.action_history.append({'type': action_type, 'data': data})
        self.current_action_index = len(self.action_history) - 1
        self.update_undo_redo_buttons()
    
    def undo_action(self):
        """Отменить последнее действие"""
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
                    
                    self.save_settings()
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
                
                self.save_settings()
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
                self.save_settings()
                
                for file_info in self.all_files:
                    if file_info['path'] in file_paths:
                        file_info['is_favorite'] = file_info['path'] in favorites
                
                self.refresh_files_tree()
            
            elif action['type'] == 'virtual_folder_create':
                folder_name = action['data']['folder_name']
                if folder_name in self.virtual_folders:
                    del self.virtual_folders[folder_name]
                    self.save_settings()
                    self.refresh_files_tree()
            
            elif action['type'] == 'virtual_folder_delete':
                folder_name = action['data']['folder_name']
                files = action['data']['files']
                self.virtual_folders[folder_name] = files
                self.save_settings()
                self.refresh_files_tree()
            
            elif action['type'] == 'virtual_folder_add_files':
                folder_name = action['data']['folder_name']
                old_files = action['data']['old_files']
                self.virtual_folders[folder_name] = old_files
                self.save_settings()
                self.refresh_files_tree()
        
        except Exception as e:
            print(f"Ошибка при отмене: {e}")
        
        self.current_action_index -= 1
        self.is_undo_redo_in_progress = False
        self.update_undo_redo_buttons()
    
    def redo_action(self):
        """Повторить отмененное действие"""
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
                    
                    self.save_settings()
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
                
                self.save_settings()
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
                self.save_settings()
                
                for file_info in self.all_files:
                    if file_info['path'] in file_paths:
                        file_info['is_favorite'] = file_info['path'] in favorites
                
                self.refresh_files_tree()
            
            elif action['type'] == 'virtual_folder_create':
                folder_name = action['data']['folder_name']
                files = action['data']['files']
                self.virtual_folders[folder_name] = files
                self.save_settings()
                self.refresh_files_tree()
            
            elif action['type'] == 'virtual_folder_delete':
                folder_name = action['data']['folder_name']
                if folder_name in self.virtual_folders:
                    del self.virtual_folders[folder_name]
                    self.save_settings()
                    self.refresh_files_tree()
            
            elif action['type'] == 'virtual_folder_add_files':
                folder_name = action['data']['folder_name']
                files_added = action['data']['files_added']
                if folder_name not in self.virtual_folders:
                    self.virtual_folders[folder_name] = []
                self.virtual_folders[folder_name].extend(files_added)
                self.save_settings()
                self.refresh_files_tree()
        
        except Exception as e:
            print(f"Ошибка при повторе: {e}")
        
        self.is_undo_redo_in_progress = False
        self.update_undo_redo_buttons()
    
    def update_undo_redo_buttons(self):
        """Обновить состояние кнопок отмены/повтора"""
        self.undo_btn.setEnabled(self.current_action_index >= 0)
        self.redo_btn.setEnabled(self.current_action_index < len(self.action_history) - 1)
    
    def set_data_folder(self):
        """Установить папку для данных"""
        path = QFileDialog.getExistingDirectory(self, "Выберите папку для данных")
        if path:
            self.settings["data_folder"] = path
            self.save_settings()
            QMessageBox.information(self, "Успех", f"Папка для данных установлена")
    
    def set_temp_folder(self):
        """Установить временную папку"""
        path = QFileDialog.getExistingDirectory(self, "Выберите временную папку")
        if path:
            self.settings["temp_folder"] = path
            self.save_settings()
            QMessageBox.information(self, "Успех", f"Временная папка установлена")
    
    def set_unrar_path(self):
        """Установить путь к UnRAR"""
        path, _ = QFileDialog.getOpenFileName(self, "Выберите исполняемый файл UnRAR", "", "Executable files (*.exe);;All files (*.*)")
        if path:
            self.settings["unrar_path"] = path
            self.save_settings()
            QMessageBox.information(self, "Успех", f"Путь к UnRAR установлен")
    
    def show_hotkeys(self):
        """Показать диалоговое окно с сочетаниями клавиш"""
        text = """Сочетания клавиш

Основные:
Ctrl+O — Открыть папку
Ctrl+Shift+O — Открыть архив
Ctrl+S — Сканировать
Delete — Удалить выбранные файлы

Работа с файлами:
Ctrl+Z — Отменить действие
Ctrl+Y — Повторить действие

Навигация и выделение:
↑/↓ — Выбор файлов
Ctrl+ЛКМ — Множественный выбор
Shift+ЛКМ — Выделение диапазона
Зажатие ЛКМ — Выделение области
Enter — Открыть файл"""
        
        QMessageBox.information(self, "Сочетания клавиш", text)
    
    def show_about(self):
        """Показать информацию о программе"""
        text = """Sofil - Сканер папок
Версия: 6.13

Создатель: Akami_bl
Обратная связь: akami.bl@gmail.com

Основное:
📁 Сканирование папок и ZIP-архивов
🗂️ Виртуальные папки для группировки файлов
🔍 Поиск по названию, содержимому, дате и размеру
⭐ Избранное для быстрого доступа

Новые возможности:
🔍 Мультикритериальный поиск
🖱️ Выделение перетаскиванием мыши
↩️ Отмена/повтор действий
🎨 Улучшенные темы оформления"""
        
        QMessageBox.information(self, "О программе", text)
    
    def closeEvent(self, event):
        """Обработка закрытия окна"""
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.stop()
            self.scan_thread.wait()
        
        self.save_settings()
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