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
    QTextEdit, QTabWidget, QGroupBox, QGridLayout, QSizePolicy
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QRect, QPoint
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor, QTextCursor

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
    
    def stop(self):
        self.stop_flag = True


class FileTreeWidget(QTreeWidget):
    """Кастомное дерево файлов с поддержкой перетаскивания"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return
        super().mouseMoveEvent(event)


class FolderScannerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = self.load_settings()
        self.init_ui()
        self.init_variables()
        self.apply_theme()
        
    def init_variables(self):
        """Инициализация переменных"""
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
        self.dark_mode = self.settings.get("dark_mode", False)
        self.virtual_folders_expanded = {}
        
        # История действий
        self.action_history = deque(maxlen=50)
        self.current_action_index = -1
        self.is_undo_redo_in_progress = False
        
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
            "dark_mode": False
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
        self.files_tree.setHeaderLabels(["Имя", "Размер", "Изменен", "Путь", "Тип"])
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
        
        # Прогресс бар
        self.progress_bar = QProgressBar()
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
        search_label.setToolTip("Поиск файлов по имени или содержимому")
        toolbar.addWidget(search_label)
        
        self.search_mode = self.settings.get("search_mode", "name")
        self.search_mode_btn = QPushButton("Имя" if self.search_mode == "name" else "Текст")
        self.search_mode_btn.clicked.connect(self.toggle_search_mode)
        self.search_mode_btn.setFixedWidth(60)
        self.search_mode_btn.setToolTip("Режим поиска: по имени файла или по тексту содержимого")
        toolbar.addWidget(self.search_mode_btn)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите текст для поиска...")
        self.search_input.textChanged.connect(self.on_search_changed)
        self.search_input.setMinimumWidth(200)
        self.search_input.setToolTip("Введите текст для поиска файлов")
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
        
        # Чекбокс скрытия Blockbench children
        self.hide_bb_children_cb = QCheckBox("Скрыть Blockbench children")
        self.hide_bb_children_cb.setChecked(self.settings.get("hide_blockbench_children", True))
        self.hide_bb_children_cb.stateChanged.connect(self.on_hide_bb_children_changed)
        self.hide_bb_children_cb.setToolTip("Скрыть дочерние файлы Blockbench моделей")
        toolbar.addWidget(self.hide_bb_children_cb)
        
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
            # Тёмная тема
            dark_palette = QPalette()
            
            # Базовые цвета
            dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
            dark_palette.setColor(QPalette.WindowText, Qt.white)
            dark_palette.setColor(QPalette.Base, QColor(35, 35, 35))
            dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
            dark_palette.setColor(QPalette.ToolTipBase, QColor(25, 25, 25))
            dark_palette.setColor(QPalette.ToolTipText, Qt.white)
            dark_palette.setColor(QPalette.Text, Qt.white)
            dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
            dark_palette.setColor(QPalette.ButtonText, Qt.white)
            dark_palette.setColor(QPalette.BrightText, Qt.red)
            dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
            dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
            dark_palette.setColor(QPalette.HighlightedText, Qt.black)
            
            # Отключенные элементы
            dark_palette.setColor(QPalette.Disabled, QPalette.Text, Qt.darkGray)
            dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.darkGray)
            
            app.setPalette(dark_palette)
            
            # Стили для виджетов
            dark_stylesheet = """
            QMainWindow {
                background-color: #353535;
            }
            QTreeWidget {
                background-color: #252525;
                color: white;
                alternate-background-color: #2d2d2d;
            }
            QTreeWidget::item:selected {
                background-color: #2a82da;
                color: white;
            }
            QTreeWidget::item:hover {
                background-color: #3d3d3d;
            }
            QGroupBox {
                color: white;
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #555;
                color: white;
                border: 1px solid #666;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #666;
                border: 1px solid #777;
            }
            QPushButton:pressed {
                background-color: #444;
            }
            QPushButton:disabled {
                background-color: #333;
                color: #777;
            }
            QLineEdit, QComboBox {
                background-color: #252525;
                color: white;
                border: 1px solid #555;
                padding: 3px;
                border-radius: 3px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #252525;
                color: white;
                selection-background-color: #2a82da;
            }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 3px;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #2a82da;
                border-radius: 3px;
            }
            QMenuBar {
                background-color: #353535;
                color: white;
            }
            QMenuBar::item:selected {
                background-color: #454545;
            }
            QMenu {
                background-color: #353535;
                color: white;
                border: 1px solid #555;
            }
            QMenu::item:selected {
                background-color: #2a82da;
            }
            QCheckBox {
                color: white;
            }
            QCheckBox::indicator {
                width: 13px;
                height: 13px;
            }
            QLabel {
                color: white;
            }
            QToolBar {
                background-color: #404040;
                border: none;
                spacing: 3px;
                padding: 2px;
            }
            QStatusBar {
                background-color: #404040;
                color: white;
            }
            QScrollBar:vertical {
                background-color: #252525;
                width: 15px;
                margin: 15px 0 15px 0;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                min-height: 20px;
                border-radius: 7px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                background: none;
            }
            """
            app.setStyleSheet(dark_stylesheet)
        else:
            # Светлая тема (стандартная)
            app.setPalette(app.style().standardPalette())
            app.setStyleSheet("")
    
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
        self.files_tree.clear()
        
        search_query = self.search_input.text().lower()
        search_mode = self.search_mode
        
        filtered_files = []
        for file_info in self.all_files:
            if self.show_favorites_only and not file_info.get('is_favorite', False):
                continue
            
            if self.current_extension_filter and self.current_extension_filter != "Все расширения":
                file_ext = file_info.get('extension', '')
                if file_ext != self.current_extension_filter:
                    continue
            
            if search_query:
                if search_mode == "name":
                    filename = file_info['name'].lower()
                    if search_query not in filename:
                        continue
                else:
                    # Поиск по содержимому (упрощённая версия)
                    content = self.load_file_content(file_info).lower()
                    if search_query not in content:
                        continue
            
            if self.hide_bb_children_cb.isChecked():
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
    
    def load_file_content(self, file_info):
        """Загрузить содержимое файла для поиска (упрощённая версия)"""
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
    
    def toggle_search_mode(self):
        """Переключить режим поиска"""
        self.search_mode = "content" if self.search_mode == "name" else "name"
        self.search_mode_btn.setText("Имя" if self.search_mode == "name" else "Текст")
        self.refresh_files_tree()
    
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
            
            # Открыть с помощью
            open_with_action = QAction("Открыть с помощью...", self)
            open_with_action.triggered.connect(lambda: self.open_file_with_dialog(file_path))
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
            delete_action.triggered.connect(self.delete_selected)
            delete_action.setToolTip("Удалить выбранные файлы")
            menu.addAction(delete_action)
            
            menu.addSeparator()
            
            # Избранное
            favorites = self.settings.get("favorites", [])
            if file_path in favorites:
                unfavorite_action = QAction("Убрать из избранного", self)
                unfavorite_action.triggered.connect(lambda: self.toggle_favorite(item))
                unfavorite_action.setToolTip("Убрать файл из избранного")
                menu.addAction(unfavorite_action)
            else:
                favorite_action = QAction("Добавить в избранное", self)
                favorite_action.triggered.connect(lambda: self.toggle_favorite(item))
                favorite_action.setToolTip("Добавить файл в избранное")
                menu.addAction(favorite_action)
        
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
    
    def open_file_with_dialog(self, file_path):
        """Открыть файл через диалог 'Открыть с помощью'"""
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Предупреждение", f"Файл не существует:\n{file_path}")
            return
        
        try:
            if sys.platform == "win32":
                # Для Windows используем shell32 для вызова диалога "Открыть с помощью"
                import ctypes
                import ctypes.wintypes
                
                # Определение необходимых структур и функций
                class ShellExecuteInfo(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", ctypes.wintypes.DWORD),
                        ("fMask", ctypes.c_ulong),
                        ("hwnd", ctypes.wintypes.HWND),
                        ("lpVerb", ctypes.c_wchar_p),
                        ("lpFile", ctypes.c_wchar_p),
                        ("lpParameters", ctypes.c_wchar_p),
                        ("lpDirectory", ctypes.c_wchar_p),
                        ("nShow", ctypes.c_int),
                        ("hInstApp", ctypes.wintypes.HINSTANCE),
                        ("lpIDList", ctypes.c_void_p),
                        ("lpClass", ctypes.c_wchar_p),
                        ("hkeyClass", ctypes.wintypes.HKEY),
                        ("dwHotKey", ctypes.wintypes.DWORD),
                        ("hIcon", ctypes.wintypes.HANDLE),
                        ("hProcess", ctypes.wintypes.HANDLE)
                    ]
                
                # Константы
                SEE_MASK_INVOKEIDLIST = 0x0000000C
                SEE_MASK_NOCLOSEPROCESS = 0x00000040
                SW_SHOW = 5
                
                # Создаем структуру
                sei = ShellExecuteInfo()
                sei.cbSize = ctypes.sizeof(sei)
                sei.fMask = SEE_MASK_INVOKEIDLIST
                sei.hwnd = 0
                sei.lpVerb = "openas"  # "Открыть с помощью"
                sei.lpFile = os.path.normpath(file_path)
                sei.lpParameters = None
                sei.lpDirectory = os.path.dirname(file_path)
                sei.nShow = SW_SHOW
                sei.hInstApp = 0
                sei.lpIDList = None
                
                # Вызываем ShellExecuteEx
                result = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
                
                if not result:
                    # Если не удалось, пробуем стандартный способ
                    os.startfile(os.path.normpath(file_path))
            elif sys.platform == "darwin":
                # Для macOS
                subprocess.run(["open", "-a", "Finder", file_path])
            else:
                # Для Linux
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
    
    def toggle_favorite(self, item):
        """Добавить/убрать файл из избранного"""
        if not item:
            return
        
        file_path = item.text(3)
        favorites = self.settings.get("favorites", [])
        
        if file_path in favorites:
            favorites.remove(file_path)
            self.status_label.setText(f"Файл убран из избранного")
        else:
            favorites.append(file_path)
            self.status_label.setText(f"Файл добавлен в избранное")
        
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
    
    def delete_selected(self):
        """Удалить выбранные элементы"""
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
                            
                            files_to_delete.append({
                                'path': file_path,
                                'content': content,
                                'temp_path': tempfile.mktemp()
                            })
                        except Exception as e:
                            QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать файл {file_path}: {str(e)}")
                            continue
            
            if files_to_delete:
                self.add_to_action_history('file_delete', {
                    'files': files_to_delete
                })
                
                for file_info in files_to_delete:
                    try:
                        with open(file_info['temp_path'], 'wb') as f:
                            f.write(file_info['content'])
                        
                        os.remove(file_info['path'])
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось удалить файл {file_info['path']}: {str(e)}")
                
                self.refresh_files_tree()
                self.status_label.setText(f"Удалено файлов: {len(files_to_delete)}")
    
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
            
            # Реализация отмены действий (упрощённая версия)
            if action['type'] == 'file_rename':
                old_path = action['data']['old_path']
                new_path = action['data']['new_path']
                
                if os.path.exists(new_path) and not os.path.exists(old_path):
                    try:
                        os.rename(new_path, old_path)
                        self.refresh_files_tree()
                        self.status_label.setText(f"Отменено переименование: {os.path.basename(new_path)} -> {os.path.basename(old_path)}")
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось отменить переименование: {str(e)}")
            
            self.current_action_index -= 1
            self.is_undo_redo_in_progress = False
            self.update_undo_redo_buttons()
    
    def redo_action(self):
        """Повторить отмененное действие"""
        if self.current_action_index < len(self.action_history) - 1:
            self.is_undo_redo_in_progress = True
            self.current_action_index += 1
            action = self.action_history[self.current_action_index]
            
            # Реализация повтора действий (упрощённая версия)
            if action['type'] == 'file_rename':
                old_path = action['data']['old_path']
                new_path = action['data']['new_path']
                
                if os.path.exists(old_path) and not os.path.exists(new_path):
                    try:
                        os.rename(old_path, new_path)
                        self.refresh_files_tree()
                        self.status_label.setText(f"Повторено переименование: {os.path.basename(old_path)} -> {os.path.basename(new_path)}")
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось повторить переименование: {str(e)}")
            
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

Навигация:
↑/↓ — Выбор файлов
Enter — Открыть файл"""
        
        QMessageBox.information(self, "Сочетания клавиш", hotkeys_text)
    
    def show_about(self):
        """Показать информацию о программе"""
        about_text = """Sofil - Сканер папок
Версия: 6.2 (PyQt5)
Создатель: Akami_bl
Обратная связь: akami.bl@gmail.com

Основное:
📁 Сканирует папки и архивы (ZIP)
🗂️ Создает виртуальные папки
🔍 Ищет и фильтрует файлы
⭐ Добавляет файлы в избранное

Фишки:
📊 Показывает дубликаты файлов
↩️ Отмена действий и повтор
🎨 Светлая и тёмная темы"""
        
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