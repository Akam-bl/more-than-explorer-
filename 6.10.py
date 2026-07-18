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
from datetime import datetime
from collections import defaultdict, deque
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QLabel, QLineEdit, QPushButton,
    QComboBox, QProgressBar, QSplitter, QFileDialog, QMessageBox,
    QMenu, QAction, QInputDialog, QToolBar, QStatusBar, QCheckBox,
    QTextEdit, QTabWidget, QGroupBox, QGridLayout, QSizePolicy,
    QRadioButton, QButtonGroup
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QRect, QPoint
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor, QTextCursor, QDrag

# Если нужны дополнительные библиотеки для работы с RAR архивами:
# pip install rarfile unrar

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
                            'modified': datetime(*file_info.date_time),
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


class FileTreeWidget(QTreeWidget):
    """Кастомное дерево файлов с поддержкой множественного выделения"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setDragEnabled(False)  # Отключаем перетаскивание
        self.setAcceptDrops(False)  # Отключаем прием перетаскивания
        
        # Для выделения мышью
        self.drag_selecting = False
        self.drag_start_pos = None
        self.drag_rect = None
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_pos = event.pos()
            item = self.itemAt(event.pos())
            
            # Обработка Ctrl+ЛКМ и Shift+ЛКМ
            if event.modifiers() & Qt.ControlModifier:
                if item:
                    if item.isSelected():
                        self.setItemSelected(item, False)
                    else:
                        self.setItemSelected(item, True)
                event.accept()
                return
            elif event.modifiers() & Qt.ShiftModifier:
                items = self.selectedItems()
                if items and item:
                    top_item = items[0]
                    self.clearSelection()
                    
                    # Находим все элементы между top_item и item
                    all_items = []
                    for i in range(self.topLevelItemCount()):
                        all_items.append(self.topLevelItem(i))
                        # Рекурсивно добавляем дочерние элементы
                        self.collect_items(self.topLevelItem(i), all_items)
                    
                    try:
                        start_idx = all_items.index(top_item)
                        end_idx = all_items.index(item)
                        if start_idx > end_idx:
                            start_idx, end_idx = end_idx, start_idx
                        
                        for i in range(start_idx, end_idx + 1):
                            self.setItemSelected(all_items[i], True)
                    except ValueError:
                        pass
                event.accept()
                return
            
            # Обычный клик - начинаем выделение
            self.drag_selecting = True
            self.drag_rect = QRect(self.drag_start_pos, QSize(1, 1))
            
            if not item:
                self.clearSelection()
            
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        if self.drag_selecting and self.drag_start_pos:
            self.drag_rect = QRect(self.drag_start_pos, event.pos()).normalized()
            self.viewport().update()
            
            # Выделяем элементы внутри прямоугольника
            rect = QRect(self.visualRect(self.indexAt(self.drag_start_pos)).topLeft(),
                        self.visualRect(self.indexAt(event.pos())).bottomRight())
            
            for i in range(self.topLevelItemCount()):
                item = self.topLevelItem(i)
                item_rect = self.visualItemRect(item)
                if rect.intersects(item_rect):
                    self.setItemSelected(item, True)
                else:
                    if not (event.modifiers() & Qt.ControlModifier):
                        self.setItemSelected(item, False)
        
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_selecting = False
            self.drag_start_pos = None
            self.drag_rect = None
            self.viewport().update()
        
        super().mouseReleaseEvent(event)
    
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.drag_selecting and self.drag_rect:
            painter = QPainter(self.viewport())
            painter.setPen(QPen(QColor(100, 150, 255), 1, Qt.DashLine))
            painter.setBrush(QBrush(QColor(100, 150, 255, 50)))
            painter.drawRect(self.drag_rect)
    
    def collect_items(self, parent_item, items_list):
        """Собрать все дочерние элементы"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            items_list.append(child)
            self.collect_items(child, items_list)


class FolderScannerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = self.load_settings()
        
        # ИНИЦИАЛИЗИРУЕМ ПЕРЕМЕННЫЕ ПРЯМО ЗДЕСЬ
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
            "search_size_min": "",
            "search_size_max": "",
            "search_date_from": "",
            "search_date_to": ""
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
            self.settings["hide_blockbench_children"] = self.hide_bb_children_cb.isChecked()
            self.settings["hide_duplicates"] = self.hide_duplicates_cb.isChecked()
            self.settings["auto_load_textures"] = self.auto_load_textures_cb.isChecked()
            self.settings["dark_mode"] = self.dark_mode
            
            if self.folder_combo.currentText():
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
        
        self.files_tree = FileTreeWidget()
        self.files_tree.setHeaderLabels(["Имя", "Размер", "Дата изменения", "Путь", "Тип"])
        self.files_tree.setColumnWidth(0, 300)
        self.files_tree.setColumnWidth(1, 100)
        self.files_tree.setColumnWidth(2, 120)
        self.files_tree.setColumnHidden(3, True)  # Скрываем путь
        self.files_tree.setColumnHidden(4, True)  # Скрываем тип
        
        self.files_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files_tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.files_tree.itemDoubleClicked.connect(self.on_file_double_click)
        self.files_tree.itemClicked.connect(self.on_file_clicked)
        
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
        self.status_bar.addWidget(self.status_label)
        
        # Прогресс бар и счетчик файлов
        self.files_count_label = QLabel("Файлов: 0")
        self.status_bar.addPermanentWidget(self.files_count_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(200)
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
        folder_label.setToolTip("Путь к сканируемой папке или архиву")
        toolbar.addWidget(folder_label)
        
        self.folder_combo = QComboBox()
        self.folder_combo.setEditable(True)
        self.folder_combo.setMinimumWidth(400)
        self.folder_combo.setToolTip("Выберите или введите путь к папке или архиву")
        toolbar.addWidget(self.folder_combo)
        
        self.browse_folder_btn = QPushButton("Обзор папки...")
        self.browse_folder_btn.clicked.connect(self.browse_folder)
        self.browse_folder_btn.setToolTip("Выбрать папку для сканирования")
        toolbar.addWidget(self.browse_folder_btn)
        
        self.browse_archive_btn = QPushButton("Обзор архива...")
        self.browse_archive_btn.clicked.connect(self.browse_archive)
        self.browse_archive_btn.setToolTip("Выбрать архив для сканирования")
        toolbar.addWidget(self.browse_archive_btn)
        
        toolbar.addSeparator()
        
        # Кнопки отмены/повтора (обновленные иконки)
        self.undo_btn = QPushButton("↶ Отменить")
        self.undo_btn.setToolTip("Отменить последнее действие (Ctrl+Z)")
        self.undo_btn.clicked.connect(self.undo_action)
        self.undo_btn.setEnabled(False)
        toolbar.addWidget(self.undo_btn)
        
        self.redo_btn = QPushButton("↷ Повторить")
        self.redo_btn.setToolTip("Повторить отмененное действие (Ctrl+Y)")
        self.redo_btn.clicked.connect(self.redo_action)
        self.redo_btn.setEnabled(False)
        toolbar.addWidget(self.redo_btn)
        
        toolbar.addSeparator()
        
        # Расширенный поиск
        search_label = QLabel("Расширенный поиск:")
        search_label.setToolTip("Расширенный поиск файлов по нескольким критериям")
        toolbar.addWidget(search_label)
        
        # Поле для многострочного поиска
        self.search_input = QTextEdit()
        self.search_input.setPlaceholderText("Введите критерии поиска через ';'\nПример: текст; размер>1MB; дата>2023")
        self.search_input.setMaximumHeight(60)
        self.search_input.textChanged.connect(self.on_search_changed)
        self.search_input.setToolTip("Поиск по нескольким критериям через ';'")
        toolbar.addWidget(self.search_input)
        
        toolbar.addSeparator()
        
        # Вид и настройки
        view_settings_label = QLabel("Вид:")
        view_settings_label.setToolTip("Настройки отображения файлов")
        toolbar.addWidget(view_settings_label)
        
        # Чекбокс группировки дубликатов
        self.hide_duplicates_cb = QCheckBox("Группировать дубликаты")
        self.hide_duplicates_cb.setChecked(self.settings.get("hide_duplicates", False))
        self.hide_duplicates_cb.stateChanged.connect(self.on_hide_duplicates_changed)
        self.hide_duplicates_cb.setToolTip("Группировать файлы с одинаковыми именами")
        toolbar.addWidget(self.hide_duplicates_cb)
        
        toolbar.addSeparator()
        
        # Сортировка
        self.sort_btn = QPushButton("A-Z ↑")
        self.sort_btn.clicked.connect(self.toggle_sorting)
        self.sort_btn.setToolTip("Изменить тип сортировки файлов")
        toolbar.addWidget(self.sort_btn)
        
        # Кнопка избранного
        self.favorites_btn = QPushButton("⭐")
        self.favorites_btn.setCheckable(True)
        self.favorites_btn.setToolTip("Показать только избранные файлы")
        self.favorites_btn.clicked.connect(self.toggle_favorites_filter)
        toolbar.addWidget(self.favorites_btn)
        
        toolbar.addSeparator()
        
        # Кнопка сканирования
        self.scan_btn = QPushButton("Сканировать")
        self.scan_btn.clicked.connect(self.scan_selected)
        self.scan_btn.setToolTip("Начать сканирование выбранной папки или архива")
        toolbar.addWidget(self.scan_btn)
        
    def create_menu(self):
        """Создание меню"""
        menubar = self.menuBar()
        
        # Меню Файл
        file_menu = menubar.addMenu("Файл")
        
        open_folder_action = QAction("Открыть папку...", self)
        open_folder_action.setShortcut("Ctrl+O")
        open_folder_action.triggered.connect(self.browse_folder)
        open_folder_action.setToolTip("Выбрать папку для сканирования")
        file_menu.addAction(open_folder_action)
        
        open_archive_action = QAction("Открыть архив...", self)
        open_archive_action.setShortcut("Ctrl+Shift+O")
        open_archive_action.triggered.connect(self.browse_archive)
        open_archive_action.setToolTip("Выбрать архив для сканирования")
        file_menu.addAction(open_archive_action)
        
        file_menu.addSeparator()
        
        scan_action = QAction("Сканировать", self)
        scan_action.setShortcut("Ctrl+S")
        scan_action.triggered.connect(self.scan_selected)
        scan_action.setToolTip("Начать сканирование")
        file_menu.addAction(scan_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close)
        exit_action.setToolTip("Закрыть приложение")
        file_menu.addAction(exit_action)
        
        # Меню Настройки
        settings_menu = menubar.addMenu("Настройки")
        
        # Подменю Спец настройки
        special_menu = settings_menu.addMenu("Спец настройки")
        
        # Скрыть дочерние файлы Blockbench перенесено сюда
        self.hide_bb_children_cb = QAction("Скрыть дочерние файлы Blockbench", self, checkable=True)
        self.hide_bb_children_cb.setChecked(self.settings.get("hide_blockbench_children", True))
        self.hide_bb_children_cb.triggered.connect(self.on_hide_bb_children_changed)
        self.hide_bb_children_cb.setToolTip("Скрыть дочерние файлы Blockbench моделей")
        special_menu.addAction(self.hide_bb_children_cb)
        
        self.auto_load_textures_cb = QAction("Автозагрузка текстур", self, checkable=True)
        self.auto_load_textures_cb.setChecked(self.settings.get("auto_load_textures", False))
        self.auto_load_textures_cb.triggered.connect(self.on_auto_load_textures_changed)
        self.auto_load_textures_cb.setToolTip("Автоматически загружать текстуры при просмотре")
        special_menu.addAction(self.auto_load_textures_cb)
        
        settings_menu.addSeparator()
        
        data_folder_action = QAction("Папка для данных...", self)
        data_folder_action.triggered.connect(self.set_data_folder)
        data_folder_action.setToolTip("Установить папку для хранения данных приложения")
        settings_menu.addAction(data_folder_action)
        
        temp_folder_action = QAction("Временная папка...", self)
        temp_folder_action.triggered.connect(self.set_temp_folder)
        temp_folder_action.setToolTip("Установить папку для временных файлов")
        settings_menu.addAction(temp_folder_action)
        
        unrar_path_action = QAction("Путь к UnRAR...", self)
        unrar_path_action.triggered.connect(self.set_unrar_path)
        unrar_path_action.setToolTip("Указать путь к программе UnRAR для работы с RAR архивами")
        settings_menu.addAction(unrar_path_action)
        
        # Меню Вид
        view_menu = menubar.addMenu("Вид")
        
        self.dark_mode_action = QAction("Тёмная тема", self, checkable=True)
        self.dark_mode_action.setChecked(self.dark_mode)
        self.dark_mode_action.triggered.connect(self.toggle_dark_mode)
        self.dark_mode_action.setToolTip("Включить/выключить темную тему")
        view_menu.addAction(self.dark_mode_action)
        
        # Меню Помощь
        help_menu = menubar.addMenu("Помощь")
        
        hotkeys_action = QAction("Сочетания клавиш", self)
        hotkeys_action.triggered.connect(self.show_hotkeys)
        hotkeys_action.setToolTip("Показать список сочетаний клавиш")
        help_menu.addAction(hotkeys_action)
        
        help_menu.addSeparator()
        
        about_action = QAction("О программе", self)
        about_action.triggered.connect(self.show_about)
        about_action.setToolTip("Информация о программе")
        help_menu.addAction(about_action)
        
    def toggle_dark_mode(self):
        """Переключение тёмной темы"""
        self.dark_mode = self.dark_mode_action.isChecked()
        self.apply_theme()
        self.save_settings()
    
    def apply_theme(self):
        """Применение темы (светлая/тёмная)"""
        app = QApplication.instance()
        
        if self.dark_mode:
            # Улучшенная тёмная тема с мягкой палитрой
            dark_palette = QPalette()
            
            # Базовые цвета (более мягкие оттенки)
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
            dark_palette.setColor(QPalette.Link, QColor(0, 120, 215))
            dark_palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
            dark_palette.setColor(QPalette.HighlightedText, Qt.white)
            
            # Отключенные элементы
            dark_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(150, 150, 150))
            dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(150, 150, 150))
            
            app.setPalette(dark_palette)
            
            # Улучшенные стили для виджетов
            dark_stylesheet = """
            QMainWindow {
                background-color: #2d2d30;
            }
            QTreeWidget {
                background-color: #252526;
                color: #f0f0f0;
                alternate-background-color: #2d2d30;
                border: 1px solid #3e3e40;
                border-radius: 2px;
            }
            QTreeWidget::item {
                padding: 2px;
            }
            QTreeWidget::item:selected {
                background-color: #0078d7;
                color: white;
                border-radius: 2px;
            }
            QTreeWidget::item:hover {
                background-color: #3e3e40;
                border-radius: 2px;
            }
            QGroupBox {
                color: #f0f0f0;
                border: 1px solid #3e3e40;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #2d2d30;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #f0f0f0;
            }
            QPushButton {
                background-color: #3e3e40;
                color: #f0f0f0;
                border: 1px solid #555555;
                padding: 5px 10px;
                border-radius: 3px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #505052;
                border: 1px solid #666666;
            }
            QPushButton:pressed {
                background-color: #2d2d30;
            }
            QPushButton:disabled {
                background-color: #2d2d30;
                color: #777777;
                border: 1px solid #444444;
            }
            QLineEdit, QComboBox, QTextEdit {
                background-color: #252526;
                color: #f0f0f0;
                border: 1px solid #3e3e40;
                padding: 3px;
                border-radius: 3px;
                selection-background-color: #0078d7;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #252526;
                color: #f0f0f0;
                selection-background-color: #0078d7;
                border: 1px solid #3e3e40;
            }
            QProgressBar {
                border: 1px solid #3e3e40;
                border-radius: 3px;
                text-align: center;
                color: #f0f0f0;
                background-color: #252526;
            }
            QProgressBar::chunk {
                background-color: #0078d7;
                border-radius: 3px;
            }
            QMenuBar {
                background-color: #2d2d30;
                color: #f0f0f0;
                border-bottom: 1px solid #3e3e40;
            }
            QMenuBar::item:selected {
                background-color: #3e3e40;
            }
            QMenu {
                background-color: #2d2d30;
                color: #f0f0f0;
                border: 1px solid #3e3e40;
            }
            QMenu::item:selected {
                background-color: #0078d7;
            }
            QCheckBox {
                color: #f0f0f0;
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 13px;
                height: 13px;
                border: 1px solid #555555;
                border-radius: 2px;
                background-color: #252526;
            }
            QCheckBox::indicator:checked {
                background-color: #0078d7;
                border: 1px solid #0078d7;
            }
            QLabel {
                color: #f0f0f0;
            }
            QToolBar {
                background-color: #2d2d30;
                border: none;
                spacing: 3px;
                padding: 2px;
                border-bottom: 1px solid #3e3e40;
            }
            QStatusBar {
                background-color: #2d2d30;
                color: #f0f0f0;
                border-top: 1px solid #3e3e40;
            }
            QScrollBar:vertical {
                background-color: #252526;
                width: 12px;
                margin: 0px 0px 0px 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #555555;
                min-height: 20px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666666;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background-color: #252526;
                height: 12px;
                margin: 0px 0px 0px 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background-color: #555555;
                min-width: 20px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #666666;
            }
            QTextEdit {
                background-color: #252526;
                color: #f0f0f0;
                border: 1px solid #3e3e40;
                selection-background-color: #0078d7;
            }
            """
            app.setStyleSheet(dark_stylesheet)
        else:
            # Улучшенная светлая тема с мягкой палитрой
            app.setPalette(app.style().standardPalette())
            light_stylesheet = """
            QMainWindow {
                background-color: #f5f5f5;
            }
            QTreeWidget {
                background-color: white;
                color: #333333;
                alternate-background-color: #f8f8f8;
                border: 1px solid #dddddd;
                border-radius: 2px;
            }
            QTreeWidget::item {
                padding: 2px;
            }
            QTreeWidget::item:selected {
                background-color: #e3f2fd;
                color: #333333;
                border-radius: 2px;
            }
            QTreeWidget::item:hover {
                background-color: #f0f0f0;
                border-radius: 2px;
            }
            QGroupBox {
                color: #333333;
                border: 1px solid #dddddd;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #333333;
            }
            QPushButton {
                background-color: #f0f0f0;
                color: #333333;
                border: 1px solid #cccccc;
                padding: 5px 10px;
                border-radius: 3px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #e6e6e6;
                border: 1px solid #bbbbbb;
            }
            QPushButton:pressed {
                background-color: #d9d9d9;
            }
            QPushButton:disabled {
                background-color: #f5f5f5;
                color: #999999;
                border: 1px solid #dddddd;
            }
            QLineEdit, QComboBox, QTextEdit {
                background-color: white;
                color: #333333;
                border: 1px solid #cccccc;
                padding: 3px;
                border-radius: 3px;
                selection-background-color: #e3f2fd;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                color: #333333;
                selection-background-color: #e3f2fd;
                border: 1px solid #cccccc;
            }
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 3px;
                text-align: center;
                color: #333333;
                background-color: white;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
            QMenuBar {
                background-color: white;
                color: #333333;
                border-bottom: 1px solid #dddddd;
            }
            QMenuBar::item:selected {
                background-color: #f0f0f0;
            }
            QMenu {
                background-color: white;
                color: #333333;
                border: 1px solid #cccccc;
            }
            QMenu::item:selected {
                background-color: #e3f2fd;
            }
            QCheckBox {
                color: #333333;
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 13px;
                height: 13px;
                border: 1px solid #999999;
                border-radius: 2px;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border: 1px solid #4CAF50;
            }
            QLabel {
                color: #333333;
            }
            QToolBar {
                background-color: white;
                border: none;
                spacing: 3px;
                padding: 2px;
                border-bottom: 1px solid #dddddd;
            }
            QStatusBar {
                background-color: white;
                color: #333333;
                border-top: 1px solid #dddddd;
            }
            QScrollBar:vertical {
                background-color: #f5f5f5;
                width: 12px;
                margin: 0px 0px 0px 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #cccccc;
                min-height: 20px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #bbbbbb;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background-color: #f5f5f5;
                height: 12px;
                margin: 0px 0px 0px 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background-color: #cccccc;
                min-width: 20px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #bbbbbb;
            }
            QTextEdit {
                background-color: white;
                color: #333333;
                border: 1px solid #cccccc;
                selection-background-color: #e3f2fd;
            }
            """
            app.setStyleSheet(light_stylesheet)
    
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
            "Archives (*.zip *.rar *.7z);;ZIP files (*.zip);;RAR files (*.rar);;7z files (*.7z);;All files (*.*)"
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
        self.progress_bar.setRange(0, 0)  # Неопределённый прогресс
        self.status_label.setText("Сканирование...")
        self.scan_btn.setEnabled(False)
        
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.stop()
        
        self.scan_thread = ScanThread(folder_path, self.settings)
        self.scan_thread.scan_complete.connect(self.on_scan_complete)
        self.scan_thread.error.connect(self.on_scan_error)
        self.scan_thread.progress_update.connect(self.on_scan_progress)
        self.scan_thread.start()
    
    def on_scan_progress(self, message, value):
        """Обновление прогресса сканирования"""
        self.status_label.setText(message)
        # Обновляем счетчик файлов
        if "файлов" in message:
            try:
                count = int(message.split()[-2])
                self.files_count_label.setText(f"Файлов: {count}")
            except:
                pass
    
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
        
        self.status_label.setText(f"Сканирование завершено. Найдено файлов: {len(all_files)}")
        self.files_count_label.setText(f"Файлов: {len(all_files)}")
    
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
    
    def parse_search_criteria(self, search_text):
        """Парсинг многофакторного поиска"""
        criteria = {
            'name': '',
            'content': '',
            'size_min': None,
            'size_max': None,
            'date_from': None,
            'date_to': None
        }
        
        if not search_text:
            return criteria
        
        # Разделяем по точке с запятой
        parts = search_text.split(';')
        
        for part in parts:
            part = part.strip().lower()
            if not part:
                continue
            
            # Поиск по размеру
            if 'размер>' in part or 'size>' in part:
                try:
                    size_str = part.split('>')[1].strip()
                    if 'kb' in size_str:
                        size = float(size_str.replace('kb', '').strip()) * 1024
                    elif 'mb' in size_str:
                        size = float(size_str.replace('mb', '').strip()) * 1024 * 1024
                    elif 'gb' in size_str:
                        size = float(size_str.replace('gb', '').strip()) * 1024 * 1024 * 1024
                    else:
                        size = float(size_str)
                    
                    if 'размер>' in part or 'size>' in part:
                        criteria['size_min'] = size
                except:
                    pass
            elif 'размер<' in part or 'size<' in part:
                try:
                    size_str = part.split('<')[1].strip()
                    if 'kb' in size_str:
                        size = float(size_str.replace('kb', '').strip()) * 1024
                    elif 'mb' in size_str:
                        size = float(size_str.replace('mb', '').strip()) * 1024 * 1024
                    elif 'gb' in size_str:
                        size = float(size_str.replace('gb', '').strip()) * 1024 * 1024 * 1024
                    else:
                        size = float(size_str)
                    
                    criteria['size_max'] = size
                except:
                    pass
            
            # Поиск по дате
            elif 'дата>' in part or 'date>' in part:
                try:
                    date_str = part.split('>')[1].strip()
                    criteria['date_from'] = datetime.strptime(date_str, "%Y-%m-%d")
                except:
                    pass
            elif 'дата<' in part or 'date<' in part:
                try:
                    date_str = part.split('<')[1].strip()
                    criteria['date_to'] = datetime.strptime(date_str, "%Y-%m-%d")
                except:
                    pass
            
            # Поиск по содержимому
            elif 'содержание:' in part or 'content:' in part:
                criteria['content'] = part.split(':')[1].strip()
            
            # Поиск по имени (по умолчанию)
            else:
                criteria['name'] = part
        
        return criteria
    
    def refresh_files_tree(self):
        """Обновление дерева файлов с многофакторным поиском"""
        self.files_tree.clear()
        
        search_text = self.search_input.toPlainText().strip()
        search_criteria = self.parse_search_criteria(search_text)
        
        filtered_files = []
        for file_info in self.all_files:
            if self.show_favorites_only and not file_info.get('is_favorite', False):
                continue
            
            if self.current_extension_filter and self.current_extension_filter != "Все расширения":
                file_ext = file_info.get('extension', '')
                if file_ext != self.current_extension_filter:
                    continue
            
            # Проверка критериев поиска
            passes_search = True
            
            # Поиск по имени
            if search_criteria['name']:
                if search_criteria['name'] not in file_info['name'].lower():
                    passes_search = False
            
            # Поиск по содержимому
            if search_criteria['content']:
                content = self.load_file_content(file_info).lower()
                if search_criteria['content'] not in content:
                    passes_search = False
            
            # Фильтр по размеру
            if search_criteria['size_min'] is not None:
                if file_info['size'] < search_criteria['size_min']:
                    passes_search = False
            
            if search_criteria['size_max'] is not None:
                if file_info['size'] > search_criteria['size_max']:
                    passes_search = False
            
            # Фильтр по дате
            if search_criteria['date_from'] is not None:
                if file_info['modified'] < search_criteria['date_from']:
                    passes_search = False
            
            if search_criteria['date_to'] is not None:
                if file_info['modified'] > search_criteria['date_to']:
                    passes_search = False
            
            if not passes_search:
                continue
            
            if self.settings.get("hide_blockbench_children", True):
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
        
        # Добавляем виртуальные папки
        self.add_virtual_folders_to_tree(filtered_files)
        
        # Добавляем файлы
        if self.hide_duplicates_cb.isChecked():
            self.add_files_with_duplicates_grouping(filtered_files)
        else:
            self.add_files_normal(filtered_files)
        
        self.status_label.setText(f"Показано файлов: {len(filtered_files)}")
        self.files_count_label.setText(f"Файлов: {len(filtered_files)}")
    
    def load_file_content(self, file_info):
        """Загрузить содержимое файла для поиска"""
        file_path = file_info['path']
        
        if file_path in self.file_content_cache:
            return self.file_content_cache[file_path]
        
        content = ""
        try:
            text_extensions = ['.txt', '.json', '.js', '.py', '.html', '.css', '.xml', '.md', '.csv', '.log']
            file_ext = file_info.get('extension', '').lower()
            
            if file_ext in text_extensions:
                if os.path.exists(file_path):
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
        
        for folder_name, files in self.virtual_folders.items():
            if self.show_favorites_only:
                if folder_name not in self.settings.get("favorites", []):
                    continue
            
            if self.current_extension_filter and self.current_extension_filter != "Все расширения":
                has_matching_extension = False
                for file_info in files:
                    if isinstance(file_info, dict):
                        file_ext = os.path.splitext(file_info.get('name', ''))[1].lower()
                    else:
                        file_ext = os.path.splitext(file_info)[1].lower()
                    
                    if file_ext == self.current_extension_filter:
                        has_matching_extension = True
                        break
                
                if not has_matching_extension:
                    continue
            
            is_favorite = folder_name in self.settings.get("favorites", [])
            folder_text = f"⭐ {folder_name}" if is_favorite else f"📁 {folder_name}"
            
            folder_item = QTreeWidgetItem(self.files_tree, [folder_text, "", "", "", "virtual_folder"])
            
            # Восстанавливаем состояние раскрытия
            if folder_name in self.virtual_folders_expanded:
                folder_item.setExpanded(self.virtual_folders_expanded[folder_name])
            
            for file_info in files:
                if isinstance(file_info, dict) and 'path' in file_info:
                    file_path = file_info['path']
                    file_name = file_info.get('name', os.path.basename(file_path))
                    
                    file_passes_filters = False
                    full_file_info = None
                    
                    for filtered_file in filtered_files:
                        if filtered_file['path'] == file_path:
                            file_passes_filters = True
                            full_file_info = filtered_file
                            break
                    
                    if not file_passes_filters and not self.show_favorites_only:
                        continue
                    
                    if not file_passes_filters:
                        for f in self.all_files:
                            if f['path'] == file_path:
                                full_file_info = f
                                break
                        else:
                            continue
                    
                    is_file_favorite = full_file_info.get('is_favorite', False)
                    file_text = f"⭐ {file_name}" if is_file_favorite else file_name
                    
                    size_str = self.format_file_size(full_file_info['size'])
                    modified_str = full_file_info['modified'].strftime("%Y-%m-%d %H:%M")
                    
                    file_item = QTreeWidgetItem(folder_item, [
                        file_text,
                        size_str,
                        modified_str,
                        file_path,
                        'file'
                    ])
    
    def add_files_normal(self, files):
        """Добавить файлы в обычном режиме"""
        for file_info in files:
            in_virtual_folder = False
            for folder_files in self.virtual_folders.values():
                for f in folder_files:
                    file_path_in_folder = f['path'] if isinstance(f, dict) else f
                    if file_path_in_folder == file_info['path']:
                        in_virtual_folder = True
                        break
                if in_virtual_folder:
                    break
            
            if in_virtual_folder:
                continue
            
            is_favorite = file_info.get('is_favorite', False)
            display_name = f"⭐ {file_info['name']}" if is_favorite else file_info['name']
            
            size_str = self.format_file_size(file_info['size'])
            modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
            
            item = QTreeWidgetItem(self.files_tree, [
                display_name,
                size_str,
                modified_str,
                file_info['path'],
                'file'
            ])
    
    def add_files_with_duplicates_grouping(self, files):
        """Добавить файлы с группировкой дубликатов"""
        single_files = []
        duplicate_groups = {}
        
        for file_info in files:
            in_virtual_folder = False
            for folder_files in self.virtual_folders.values():
                for f in folder_files:
                    file_path_in_folder = f['path'] if isinstance(f, dict) else f
                    if file_path_in_folder == file_info['path']:
                        in_virtual_folder = True
                        break
                if in_virtual_folder:
                    break
            
            if not in_virtual_folder:
                if file_info['name'] in self.file_groups:
                    if len(self.file_groups[file_info['name']]) > 1:
                        if file_info['name'] not in duplicate_groups:
                            duplicate_groups[file_info['name']] = []
                        duplicate_groups[file_info['name']].append(file_info)
                    else:
                        single_files.append(file_info)
        
        # Добавляем одиночные файлы
        for file_info in single_files:
            is_favorite = file_info.get('is_favorite', False)
            display_name = f"⭐ {file_info['name']}" if is_favorite else file_info['name']
            
            size_str = self.format_file_size(file_info['size'])
            modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
            
            item = QTreeWidgetItem(self.files_tree, [
                display_name,
                size_str,
                modified_str,
                file_info['path'],
                'file'
            ])
        
        # Добавляем группы дубликатов
        for filename, file_list in duplicate_groups.items():
            folder_item = QTreeWidgetItem(self.files_tree, [
                f"📁 {filename} ({len(file_list)} файлов)",
                "",
                "",
                "",
                'folder'
            ])
            
            for file_info in file_list:
                is_favorite = file_info.get('is_favorite', False)
                display_name = f"⭐ {file_info['name']}" if is_favorite else file_info['name']
                
                size_str = self.format_file_size(file_info['size'])
                modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
                
                file_item = QTreeWidgetItem(folder_item, [
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
    
    def on_search_changed(self):
        """Обработка изменения поискового запроса"""
        self.refresh_files_tree()
    
    def on_hide_duplicates_changed(self):
        """Обработка изменения настройки группировки дубликатов"""
        self.settings["hide_duplicates"] = self.hide_duplicates_cb.isChecked()
        self.save_settings()
        self.refresh_files_tree()
    
    def on_hide_bb_children_changed(self):
        """Обработка изменения настройки скрытия дочерних файлов Blockbench"""
        self.settings["hide_blockbench_children"] = self.hide_bb_children_cb.isChecked()
        self.save_settings()
        self.refresh_files_tree()
    
    def on_auto_load_textures_changed(self):
        """Обработка изменения настройки автозагрузки текстур"""
        self.settings["auto_load_textures"] = self.auto_load_textures_cb.isChecked()
        self.save_settings()
    
    def toggle_favorites_filter(self):
        """Переключить фильтр избранного"""
        self.show_favorites_only = self.favorites_btn.isChecked()
        self.refresh_files_tree()
        
        if self.show_favorites_only:
            self.status_label.setText("Показаны только избранные файлы")
        else:
            self.status_label.setText("Показаны все файлы")
    
    def toggle_sorting(self):
        """Переключение сортировки"""
        current_mode = self.settings.get("sort_mode", "name_asc")
        
        modes_forward = ["name_asc", "name_desc", "date_asc", "date_desc", "size_asc", "size_desc"]
        
        current_index = modes_forward.index(current_mode)
        next_index = (current_index + 1) % len(modes_forward)
        new_mode = modes_forward[next_index]
        
        self.settings["sort_mode"] = new_mode
        self.save_settings()
        
        # Обновляем текст кнопки
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
        
        item_type = item.text(4)  # Тип из последней колонки
        
        if item_type == 'file':
            file_path = item.text(3)
            
            # Открыть расположение
            open_location_action = QAction("Открыть расположение файла", self)
            open_location_action.triggered.connect(lambda: self.open_file_location(file_path))
            open_location_action.setToolTip("Открыть папку, содержащую файл")
            menu.addAction(open_location_action)
            
            # Открыть с помощью (исправленная версия для Windows 11)
            open_with_action = QAction("Открыть с помощью...", self)
            open_with_action.triggered.connect(lambda: self.open_file_with_dialog_win11(file_path))
            open_with_action.setToolTip("Открыть файл выбранной программой")
            menu.addAction(open_with_action)
            
            menu.addSeparator()
            
            # Переименовать
            rename_action = QAction("Переименовать", self)
            rename_action.triggered.connect(lambda: self.rename_file(item))
            rename_action.setToolTip("Переименовать файл")
            menu.addAction(rename_action)
            
            # Удалить
            delete_action = QAction("Удалить", self)
            delete_action.triggered.connect(self.delete_selected_with_undo)
            delete_action.setToolTip("Удалить выбранные файлы")
            menu.addAction(delete_action)
            
            menu.addSeparator()
            
            # Избранное
            favorites = self.settings.get("favorites", [])
            if file_path in favorites:
                unfavorite_action = QAction("Убрать из избранного", self)
                unfavorite_action.triggered.connect(lambda: self.toggle_favorite_with_undo(item))
                unfavorite_action.setToolTip("Убрать файл из избранного")
                menu.addAction(unfavorite_action)
            else:
                favorite_action = QAction("Добавить в избранное", self)
                favorite_action.triggered.connect(lambda: self.toggle_favorite_with_undo(item))
                favorite_action.setToolTip("Добавить файл в избранное")
                menu.addAction(favorite_action)
            
            menu.addSeparator()
            
            # Добавить в виртуальную папку (вместо drag & drop)
            add_to_virtual_menu = QMenu("Добавить в виртуальную папку", self)
            menu.addMenu(add_to_virtual_menu)
            
            # Создать новую папку
            create_folder_action = QAction("Создать новую папку...", self)
            create_folder_action.triggered.connect(self.create_virtual_folder_from_selection)
            add_to_virtual_menu.addAction(create_folder_action)
            
            add_to_virtual_menu.addSeparator()
            
            # Существующие папки
            for folder_name in self.virtual_folders.keys():
                folder_action = QAction(folder_name, self)
                folder_action.triggered.connect(lambda checked, f=folder_name: self.add_selected_to_virtual_folder(f))
                add_to_virtual_menu.addAction(folder_action)
        
        elif item_type == 'virtual_folder':
            folder_name = item.text(0)
            if folder_name.startswith("⭐ "):
                folder_name = folder_name[2:]
            elif folder_name.startswith("📁 "):
                folder_name = folder_name[2:]
            
            # Добавить/убрать из избранного
            favorites = self.settings.get("favorites", [])
            if folder_name in favorites:
                unfavorite_action = QAction("Убрать из избранного", self)
                unfavorite_action.triggered.connect(lambda: self.toggle_virtual_folder_favorite(folder_name))
                unfavorite_action.setToolTip("Убрать папку из избранного")
                menu.addAction(unfavorite_action)
            else:
                favorite_action = QAction("Добавить в избранное", self)
                favorite_action.triggered.connect(lambda: self.toggle_virtual_folder_favorite(folder_name))
                favorite_action.setToolTip("Добавить папку в избранное")
                menu.addAction(favorite_action)
            
            menu.addSeparator()
            
            # Переименовать папку
            rename_action = QAction("Переименовать папку", self)
            rename_action.triggered.connect(lambda: self.rename_virtual_folder(folder_name))
            rename_action.setToolTip("Переименовать виртуальную папку")
            menu.addAction(rename_action)
            
            # Удалить папку
            delete_action = QAction("Удалить папку", self)
            delete_action.triggered.connect(lambda: self.delete_virtual_folder(folder_name))
            delete_action.setToolTip("Удалить виртуальную папку")
            menu.addAction(delete_action)
        
        elif item_type == 'folder':
            if item.isExpanded():
                collapse_action = QAction("Свернуть все", self)
                collapse_action.triggered.connect(lambda: self.collapse_folder(item))
                collapse_action.setToolTip("Свернуть все подпапки")
                menu.addAction(collapse_action)
            else:
                expand_action = QAction("Развернуть все", self)
                expand_action.triggered.connect(lambda: self.expand_folder(item))
                expand_action.setToolTip("Развернуть все подпапки")
                menu.addAction(expand_action)
        
        menu.exec_(self.files_tree.viewport().mapToGlobal(position))
    
    def create_virtual_folder_from_selection(self):
        """Создать новую виртуальную папку из выделенных файлов"""
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Предупреждение", "Выберите файлы для добавления в папку")
            return
        
        files_to_add = []
        file_names = set()
        
        for item in selected_items:
            item_type = item.text(4)
            if item_type == 'file':
                file_path = item.text(3)
                file_name = item.text(0).replace('⭐ ', '')
                
                # Проверка на дубликаты
                if file_name in file_names:
                    QMessageBox.warning(self, "Предупреждение", 
                                      f"Файл с именем '{file_name}' уже выбран. "
                                      "Один файл может быть добавлен только один раз.")
                    return
                
                file_names.add(file_name)
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
            
            # Проверка на одинаковые имена файлов в папке
            existing_files = self.virtual_folders.get(folder_name, [])
            for existing_file in existing_files:
                existing_name = existing_file['name'] if isinstance(existing_file, dict) else os.path.basename(existing_file)
                for new_file in files_to_add:
                    if new_file['name'] == existing_name:
                        reply = QMessageBox.question(
                            self, "Подтверждение",
                            f"Файл с именем '{existing_name}' уже есть в папке. Добавить все равно?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        if reply == QMessageBox.No:
                            return
                        break
            
            self.virtual_folders[folder_name] = files_to_add
            
            self.add_to_action_history('virtual_folder_create', {
                'folder_name': folder_name,
                'files': files_to_add.copy()
            })
            
            self.save_settings()
            self.refresh_files_tree()
            self.status_label.setText(f"Создана новая папка '{folder_name}' с {len(files_to_add)} файлами")
    
    def add_selected_to_virtual_folder(self, folder_name):
        """Добавить выбранные файлы в существующую виртуальную папку"""
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            return
        
        files_to_add = []
        file_names = set()
        
        for item in selected_items:
            item_type = item.text(4)
            if item_type == 'file':
                file_path = item.text(3)
                file_name = item.text(0).replace('⭐ ', '')
                
                # Проверка на дубликаты
                if file_name in file_names:
                    QMessageBox.warning(self, "Предупреждение", 
                                      f"Файл с именем '{file_name}' уже выбран. "
                                      "Один файл может быть добавлен только один раз.")
                    return
                
                file_names.add(file_name)
                files_to_add.append({
                    'path': file_path,
                    'name': file_name
                })
        
        if not files_to_add:
            return
        
        # Проверка на одинаковые имена файлов в папке
        existing_files = self.virtual_folders.get(folder_name, [])
        existing_names = set()
        for existing_file in existing_files:
            if isinstance(existing_file, dict):
                existing_names.add(existing_file['name'])
            else:
                existing_names.add(os.path.basename(existing_file))
        
        duplicates = []
        for new_file in files_to_add:
            if new_file['name'] in existing_names:
                duplicates.append(new_file['name'])
        
        if duplicates:
            reply = QMessageBox.question(
                self, "Подтверждение",
                f"Найдены файлы с одинаковыми именами: {', '.join(duplicates[:3])}...\n"
                "Добавить все равно?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        # Копируем файлы перед добавлением
        copied_files = []
        for file_info in files_to_add:
            file_path = file_info['path']
            if os.path.exists(file_path):
                # Создаем копию в папке приложения
                data_folder = self.settings.get("data_folder", "")
                if not data_folder:
                    data_folder = os.path.join(os.path.expanduser("~"), "folder_scanner_data")
                    os.makedirs(data_folder, exist_ok=True)
                    self.settings["data_folder"] = data_folder
                
                # Создаем подпапку для виртуальной папки
                folder_path = os.path.join(data_folder, "virtual_folders", folder_name)
                os.makedirs(folder_path, exist_ok=True)
                
                # Копируем файл
                dest_path = os.path.join(folder_path, file_info['name'])
                try:
                    shutil.copy2(file_path, dest_path)
                    copied_files.append({
                        'path': dest_path,
                        'name': file_info['name'],
                        'original_path': file_path
                    })
                except Exception as e:
                    QMessageBox.warning(self, "Ошибка", f"Не удалось скопировать файл {file_info['name']}: {str(e)}")
        
        if folder_name not in self.virtual_folders:
            self.virtual_folders[folder_name] = []
        
        old_files = self.virtual_folders[folder_name].copy()
        
        # Добавляем скопированные файлы
        self.virtual_folders[folder_name].extend(copied_files)
        
        self.add_to_action_history('virtual_folder_add_files', {
            'folder_name': folder_name,
            'files_added': copied_files.copy(),
            'old_files': old_files
        })
        
        self.save_settings()
        self.refresh_files_tree()
        self.status_label.setText(f"Добавлено {len(copied_files)} файлов в папку '{folder_name}'")
    
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
            self.open_file_with_default(file_path)
        elif item_type == 'folder':
            item.setExpanded(not item.isExpanded())
        elif item_type == 'virtual_folder':
            # Сохраняем состояние раскрытия
            folder_name = item.text(0)
            if folder_name.startswith("⭐ "):
                folder_name = folder_name[2:]
            elif folder_name.startswith("📁 "):
                folder_name = folder_name[2:]
            
            self.virtual_folders_expanded[folder_name] = not item.isExpanded()
            item.setExpanded(not item.isExpanded())
    
    def on_file_clicked(self, item, column):
        """Обработка клика по файлу"""
        item_type = item.text(4)
        
        if item_type == 'virtual_folder':
            # Сохраняем состояние раскрытия при клике
            folder_name = item.text(0)
            if folder_name.startswith("⭐ "):
                folder_name = folder_name[2:]
            elif folder_name.startswith("📁 "):
                folder_name = folder_name[2:]
            
            self.virtual_folders_expanded[folder_name] = item.isExpanded()
    
    def open_file_location(self, file_path):
        """Открыть расположение файла в проводнике"""
        if os.path.exists(file_path):
            folder_path = os.path.dirname(file_path)
            if sys.platform == "win32":
                # Для Windows используем explorer с параметром /select
                subprocess.run(['explorer', '/select,', os.path.normpath(file_path)], shell=True)
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", file_path])
            else:
                folder_path = os.path.dirname(file_path)
                subprocess.run(["xdg-open", folder_path])
            self.status_label.setText(f"Открыта папка: {folder_path}")
        else:
            QMessageBox.warning(self, "Предупреждение", "Файл не существует или путь недоступен")
    
    def open_file_with_default(self, file_path):
        """Открыть файл с помощью программы по умолчанию"""
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Предупреждение", f"Файл не существует:\n{file_path}")
            return
        
        try:
            if sys.platform == "win32":
                # Используем os.startfile для Windows 10/11
                os.startfile(os.path.normpath(file_path))
            elif sys.platform == "darwin":
                subprocess.run(["open", file_path])
            else:
                subprocess.run(["xdg-open", file_path])
            
            self.status_label.setText(f"Открытие файла: {os.path.basename(file_path)}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{str(e)}")
    
    def open_file_with_dialog_win11(self, file_path):
        """Открыть файл через диалог 'Открыть с помощью' для Windows 11"""
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Предупреждение", f"Файл не существует:\n{file_path}")
            return
        
        try:
            if sys.platform == "win32":
                # Улучшенная версия для Windows 10/11
                import ctypes
                from ctypes import wintypes
                
                # Используем ShellExecuteEx для Windows 11
                SEE_MASK_NOCLOSEPROCESS = 0x00000040
                SEE_MASK_INVOKEIDLIST = 0x0000000C
                
                class ShellExecuteInfo(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", wintypes.DWORD),
                        ("fMask", ctypes.c_ulong),
                        ("hwnd", wintypes.HWND),
                        ("lpVerb", ctypes.c_wchar_p),
                        ("lpFile", ctypes.c_wchar_p),
                        ("lpParameters", ctypes.c_wchar_p),
                        ("lpDirectory", ctypes.c_wchar_p),
                        ("nShow", ctypes.c_int),
                        ("hInstApp", wintypes.HINSTANCE),
                        ("lpIDList", ctypes.c_void_p),
                        ("lpClass", ctypes.c_wchar_p),
                        ("hkeyClass", wintypes.HKEY),
                        ("dwHotKey", wintypes.DWORD),
                        ("hIcon", wintypes.HANDLE),
                        ("hProcess", wintypes.HANDLE)
                    ]
                
                sei = ShellExecuteInfo()
                sei.cbSize = ctypes.sizeof(sei)
                sei.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_INVOKEIDLIST
                sei.hwnd = 0
                sei.lpVerb = "openas"  # Ключевое изменение для Windows 11
                sei.lpFile = os.path.normpath(file_path)
                sei.lpParameters = None
                sei.lpDirectory = os.path.dirname(file_path)
                sei.nShow = 1  # SW_SHOWNORMAL
                
                # Пробуем несколько способов
                try:
                    # Способ 1: ShellExecuteEx
                    result = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
                    if not result:
                        # Способ 2: Стандартный ShellExecute
                        result = ctypes.windll.shell32.ShellExecuteW(
                            0, "openas", os.path.normpath(file_path), None, None, 1
                        )
                        if result <= 32:
                            # Способ 3: Через rundll32
                            ctypes.windll.shell32.ShellExecuteW(
                                0, "open", "rundll32.exe",
                                f"shell32.dll,OpenAs_RunDLL {os.path.normpath(file_path)}",
                                None, 1
                            )
                except Exception as e:
                    # В крайнем случае используем стандартный способ
                    os.startfile(os.path.normpath(file_path))
                    
            elif sys.platform == "darwin":
                subprocess.run(["open", "-a", "Finder", file_path])
            else:
                subprocess.run(["xdg-open", file_path])
            
            self.status_label.setText(f"Открытие файла с помощью: {os.path.basename(file_path)}")
        except Exception as e:
            # В случае ошибки, пробуем стандартный способ
            try:
                self.open_file_with_default(file_path)
            except:
                QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{str(e)}")
    
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
                # Добавляем в историю действий
                self.add_to_action_history('file_rename', {
                    'old_path': old_path,
                    'new_path': new_path
                })
                
                os.rename(old_path, new_path)
                
                # Обновляем информацию
                for file_info in self.all_files:
                    if file_info['path'] == old_path:
                        file_info['path'] = new_path
                        file_info['name'] = new_name
                        break
                
                # Обновляем виртуальные папки
                for folder_name, files in self.virtual_folders.items():
                    for i, file_info in enumerate(files):
                        if isinstance(file_info, dict) and file_info.get('path') == old_path:
                            file_info['path'] = new_path
                            file_info['name'] = new_name
                        elif file_info == old_path:
                            files[i] = new_path
                
                # Обновляем избранное
                if old_path in self.settings.get("favorites", []):
                    favorites = self.settings["favorites"]
                    favorites.remove(old_path)
                    favorites.append(new_path)
                    self.settings["favorites"] = favorites
                
                self.save_settings()
                self.refresh_files_tree()
                self.status_label.setText(f"Файл переименован: '{old_name}' -> '{new_name}'")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось переименовать файл: {str(e)}")
    
    def toggle_favorite_with_undo(self, item):
        """Добавить/убрать файл из избранного с поддержкой отмены"""
        if not item:
            return
        
        file_path = item.text(3)
        favorites = self.settings.get("favorites", [])
        
        was_favorite = file_path in favorites
        
        if was_favorite:
            favorites.remove(file_path)
            self.status_label.setText(f"Файл убран из избранного")
        else:
            favorites.append(file_path)
            self.status_label.setText(f"Файл добавлен в избранное")
        
        self.add_to_action_history('favorite_toggle', {
            'file_paths': [file_path],
            'was_favorite': was_favorite
        })
        
        self.settings["favorites"] = favorites
        self.save_settings()
        
        # Обновляем состояние файлов
        for file_info in self.all_files:
            if file_info['path'] == file_path:
                file_info['is_favorite'] = file_path in favorites
        
        self.refresh_files_tree()
    
    def toggle_virtual_folder_favorite(self, folder_name):
        """Добавить/убрать виртуальную папку из избранного"""
        favorites = self.settings.get("favorites", [])
        
        if folder_name in favorites:
            favorites.remove(folder_name)
            self.status_label.setText(f"Папка '{folder_name}' убрана из избранного")
        else:
            favorites.append(folder_name)
            self.status_label.setText(f"Папка '{folder_name}' добавлена в избранное")
        
        self.settings["favorites"] = favorites
        self.save_settings()
        self.refresh_files_tree()
    
    def rename_virtual_folder(self, folder_name):
        """Переименовать виртуальную папку"""
        new_name, ok = QInputDialog.getText(self, "Переименовать папку", "Введите новое название папки:", text=folder_name)
        
        if ok and new_name and new_name != folder_name:
            if new_name in self.virtual_folders:
                QMessageBox.warning(self, "Предупреждение", "Папка с таким именем уже существует")
                return
            
            old_files = self.virtual_folders[folder_name].copy()
            self.virtual_folders[new_name] = self.virtual_folders.pop(folder_name)
            
            # Сохраняем состояние раскрытия
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
            self.status_label.setText(f"Папка переименована: '{folder_name}' -> '{new_name}'")
    
    def delete_virtual_folder(self, folder_name):
        """Удалить виртуальную папку"""
        reply = QMessageBox.question(self, "Подтверждение", f"Вы уверены, что хотите удалить папку '{folder_name}'?",
                                   QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            if folder_name in self.virtual_folders:
                old_files = self.virtual_folders[folder_name].copy()
                
                favorites = self.settings.get("favorites", [])
                if folder_name in favorites:
                    favorites.remove(folder_name)
                    self.settings["favorites"] = favorites
                
                # Удаляем состояние раскрытия
                if folder_name in self.virtual_folders_expanded:
                    del self.virtual_folders_expanded[folder_name]
                
                del self.virtual_folders[folder_name]
                
                self.add_to_action_history('virtual_folder_delete', {
                    'folder_name': folder_name,
                    'files': old_files
                })
                
                self.save_settings()
                self.refresh_files_tree()
                self.status_label.setText(f"Папка '{folder_name}' удалена")
    
    def delete_selected_with_undo(self):
        """Удалить выбранные элементы с поддержкой отмены"""
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            return
        
        reply = QMessageBox.question(self, "Подтверждение", "Удалить выбранные элементы?",
                                   QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            files_to_delete = []
            
            for item in selected_items:
                item_type = item.text(4)
                if item_type == 'file':
                    file_path = item.text(3)
                    
                    if os.path.exists(file_path):
                        try:
                            with open(file_path, 'rb') as f:
                                content = f.read()
                            
                            # Создаем временную копию для возможности отмены
                            temp_dir = self.settings.get("temp_folder", tempfile.gettempdir())
                            os.makedirs(temp_dir, exist_ok=True)
                            temp_path = os.path.join(temp_dir, f"undo_{os.path.basename(file_path)}")
                            
                            # Сохраняем оригинальную копию
                            with open(temp_path, 'wb') as f:
                                f.write(content)
                            
                            files_to_delete.append({
                                'path': file_path,
                                'content': content,
                                'temp_path': temp_path,
                                'is_favorite': file_path in self.settings.get("favorites", [])
                            })
                        except Exception as e:
                            QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать файл {file_path}: {str(e)}")
                            continue
            
            if files_to_delete:
                self.add_to_action_history('file_delete', {
                    'files': files_to_delete
                })
                
                deleted_count = 0
                for file_info in files_to_delete:
                    try:
                        os.remove(file_info['path'])
                        deleted_count += 1
                        
                        # Удаляем из списка файлов
                        self.all_files = [f for f in self.all_files if f['path'] != file_info['path']]
                        
                        # Удаляем из избранного
                        if file_info['is_favorite']:
                            favorites = self.settings.get("favorites", [])
                            if file_info['path'] in favorites:
                                favorites.remove(file_info['path'])
                                self.settings["favorites"] = favorites
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось удалить файл {file_info['path']}: {str(e)}")
                
                self.refresh_files_tree()
                self.save_settings()
                self.status_label.setText(f"Удалено файлов: {deleted_count}")
    
    def add_to_action_history(self, action_type, data):
        """Добавить действие в историю"""
        if self.is_undo_redo_in_progress:
            return
            
        if self.current_action_index < len(self.action_history) - 1:
            self.action_history = deque(list(self.action_history)[:self.current_action_index + 1], maxlen=50)
        
        action = {
            'type': action_type,
            'data': data,
            'timestamp': datetime.now()
        }
        
        self.action_history.append(action)
        self.current_action_index = len(self.action_history) - 1
        self.update_undo_redo_buttons()
    
    def undo_action(self):
        """Отменить последнее действие"""
        if self.current_action_index >= 0:
            self.is_undo_redo_in_progress = True
            action = self.action_history[self.current_action_index]
            
            # Реализация отмены действий
            if action['type'] == 'file_rename':
                old_path = action['data']['old_path']
                new_path = action['data']['new_path']
                
                if os.path.exists(new_path) and not os.path.exists(old_path):
                    try:
                        os.rename(new_path, old_path)
                        
                        # Обновляем информацию
                        for file_info in self.all_files:
                            if file_info['path'] == new_path:
                                file_info['path'] = old_path
                                file_info['name'] = os.path.basename(old_path)
                                break
                        
                        self.refresh_files_tree()
                        self.status_label.setText(f"Отменено переименование: {os.path.basename(new_path)} -> {os.path.basename(old_path)}")
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось отменить переименование: {str(e)}")
            
            elif action['type'] == 'file_delete':
                restored_count = 0
                for file_info in action['data']['files']:
                    try:
                        if os.path.exists(file_info['temp_path']):
                            # Восстанавливаем из временной копии
                            with open(file_info['temp_path'], 'rb') as f:
                                content = f.read()
                            
                            with open(file_info['path'], 'wb') as f:
                                f.write(content)
                            
                            # Восстанавливаем в списке файлов
                            file_data = {
                                'name': os.path.basename(file_info['path']),
                                'path': file_info['path'],
                                'size': len(content),
                                'modified': datetime.now(),
                                'is_favorite': file_info.get('is_favorite', False),
                                'extension': os.path.splitext(file_info['path'])[1].lower() or "(без расширения)",
                                'has_parent': False
                            }
                            self.all_files.append(file_data)
                            
                            # Восстанавливаем в избранном
                            if file_info.get('is_favorite', False):
                                favorites = self.settings.get("favorites", [])
                                if file_info['path'] not in favorites:
                                    favorites.append(file_info['path'])
                                    self.settings["favorites"] = favorites
                            
                            restored_count += 1
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось восстановить файл: {str(e)}")
                
                self.refresh_files_tree()
                self.save_settings()
                self.status_label.setText(f"Отменено удаление: восстановлено {restored_count} файлов")
            
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
                
                # Обновляем состояние файлов
                for file_info in self.all_files:
                    if file_info['path'] in file_paths:
                        file_info['is_favorite'] = file_info['path'] in favorites
                
                self.refresh_files_tree()
                self.status_label.setText("Отменено изменение избранного")
            
            elif action['type'] == 'virtual_folder_create':
                folder_name = action['data']['folder_name']
                if folder_name in self.virtual_folders:
                    del self.virtual_folders[folder_name]
                    self.save_settings()
                    self.refresh_files_tree()
                    self.status_label.setText(f"Отменено создание папки: {folder_name}")
            
            elif action['type'] == 'virtual_folder_delete':
                folder_name = action['data']['folder_name']
                files = action['data']['files']
                self.virtual_folders[folder_name] = files
                self.save_settings()
                self.refresh_files_tree()
                self.status_label.setText(f"Отменено удаление папки: {folder_name}")
            
            self.current_action_index -= 1
            self.is_undo_redo_in_progress = False
            self.update_undo_redo_buttons()
    
    def redo_action(self):
        """Повторить отмененное действие"""
        if self.current_action_index < len(self.action_history) - 1:
            self.is_undo_redo_in_progress = True
            self.current_action_index += 1
            action = self.action_history[self.current_action_index]
            
            # Реализация повтора действий
            if action['type'] == 'file_rename':
                old_path = action['data']['old_path']
                new_path = action['data']['new_path']
                
                if os.path.exists(old_path) and not os.path.exists(new_path):
                    try:
                        os.rename(old_path, new_path)
                        
                        # Обновляем информацию
                        for file_info in self.all_files:
                            if file_info['path'] == old_path:
                                file_info['path'] = new_path
                                file_info['name'] = os.path.basename(new_path)
                                break
                        
                        self.refresh_files_tree()
                        self.status_label.setText(f"Повторено переименование: {os.path.basename(old_path)} -> {os.path.basename(new_path)}")
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось повторить переименование: {str(e)}")
            
            elif action['type'] == 'file_delete':
                deleted_count = 0
                for file_info in action['data']['files']:
                    try:
                        if os.path.exists(file_info['path']):
                            os.remove(file_info['path'])
                            
                            # Удаляем из списка файлов
                            self.all_files = [f for f in self.all_files if f['path'] != file_info['path']]
                            
                            deleted_count += 1
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось удалить файл: {str(e)}")
                
                self.refresh_files_tree()
                self.save_settings()
                self.status_label.setText(f"Повторено удаление: удалено {deleted_count} файлов")
            
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
                
                # Обновляем состояние файлов
                for file_info in self.all_files:
                    if file_info['path'] in file_paths:
                        file_info['is_favorite'] = file_info['path'] in favorites
                
                self.refresh_files_tree()
                self.status_label.setText("Повторено изменение избранного")
            
            elif action['type'] == 'virtual_folder_create':
                folder_name = action['data']['folder_name']
                files = action['data']['files']
                self.virtual_folders[folder_name] = files
                self.save_settings()
                self.refresh_files_tree()
                self.status_label.setText(f"Повторено создание папки: {folder_name}")
            
            elif action['type'] == 'virtual_folder_delete':
                folder_name = action['data']['folder_name']
                if folder_name in self.virtual_folders:
                    del self.virtual_folders[folder_name]
                    self.save_settings()
                    self.refresh_files_tree()
                    self.status_label.setText(f"Повторено удаление папки: {folder_name}")
            
            self.is_undo_redo_in_progress = False
            self.update_undo_redo_buttons()
    
    def update_undo_redo_buttons(self):
        """Обновить состояние кнопок отмены/повтора"""
        has_undo = self.current_action_index >= 0
        has_redo = self.current_action_index < len(self.action_history) - 1
        
        self.undo_btn.setEnabled(has_undo)
        self.redo_btn.setEnabled(has_redo)
    
    def set_data_folder(self):
        """Установить папку для данных"""
        path = QFileDialog.getExistingDirectory(self, "Выберите папку для данных")
        if path:
            self.settings["data_folder"] = path
            self.save_settings()
            QMessageBox.information(self, "Успех", f"Папка для данных установлена:\n{path}")
    
    def set_temp_folder(self):
        """Установить временную папку"""
        path = QFileDialog.getExistingDirectory(self, "Выберите временную папку")
        if path:
            self.settings["temp_folder"] = path
            self.save_settings()
            QMessageBox.information(self, "Успех", f"Временная папка установлена:\n{path}")
    
    def set_unrar_path(self):
        """Установить путь к UnRAR"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите исполняемый файл UnRAR",
            "",
            "Executable files (*.exe);;All files (*.*)"
        )
        if path:
            self.settings["unrar_path"] = path
            self.save_settings()
            QMessageBox.information(self, "Успех", f"Путь к UnRAR установлен:\n{path}")
    
    def show_hotkeys(self):
        """Показать диалоговое окно с сочетаниями клавиш"""
        hotkeys_text = """Сочетания клавиш

Основные:
Ctrl+O — Открыть папку
Ctrl+Shift+O — Открыть архив
Ctrl+S — Сканировать выбранную папку
Delete — Удалить выбранные файлы

Работа с файлами:
Ctrl+Z — Отменить действие
Ctrl+Y — Повторить действие
Ctrl+ЛКМ — Выбрать несколько файлов
Shift+ЛКМ — Выбрать диапазон файлов

Навигация:
↑/↓ — Выбор файлов
Enter — Открыть файл
ЛКМ + перетаскивание — Выделение файлов мышью

Расширенный поиск:
Используйте ';' для разделения критериев:
• текст — поиск по содержимому
• размер>1MB — файлы больше 1MB
• размер<100KB — файлы меньше 100KB
• дата>2023-01-01 — файлы после даты
• дата<2023-12-31 — файлы до даты

Пример: текст; размер>1MB; дата>2023"""
        
        QMessageBox.information(self, "Сочетания клавиш", hotkeys_text)
    
    def show_about(self):
        """Показать информацию о программе"""
        about_text = """Sofil - Сканер папок
Версия: 6.10
Создатель: Akami_bl
Обратная связь: akami.bl@gmail.com

Основное:
📁 Сканирует папки и архивы (ZIP)
🗂️ Создает виртуальные папки
🔍 Расширенный поиск по нескольким критериям
⭐ Добавляет файлы в избранное
↩️ Полная поддержка отмены/повтора действий

Новые возможности:
🎯 Многофакторный поиск (имя, содержание, размер, дата)
🖱️ Выделение файлов мышью (drag-select)
📋 Копирование файлов в виртуальные папки
⚠️ Проверка на дубликаты при добавлении
🎨 Улучшенные темы с мягкой палитрой

Совместимость:
✅ Windows 10
✅ Windows 11
✅ Поддержка темной и светлой тем"""
        
        QMessageBox.information(self, "О программе", about_text)
    
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
    app.setStyle("Fusion")  # Современный стиль для лучшей поддержки тем
    
    window = FolderScannerApp()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()