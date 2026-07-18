# [file name]: 6.5_fixed.py
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
    QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QRect, QPoint
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor, QTextCursor, QBrush

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
    """Кастомное дерево файлов с поддержкой drag-select"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setDragEnabled(False)  # Отключаем DnD для дерева
        self.setAcceptDrops(False)
        
        # Переменные для drag-select
        self.drag_select_rect = None
        self.drag_select_start = None
        self.is_drag_selecting = False
        
        # Список элементов для быстрого доступа
        self.all_items = []
        
    def update_all_items(self):
        """Обновить список всех элементов"""
        self.all_items = []
        self.collect_items(self.invisibleRootItem())
    
    def collect_items(self, parent):
        """Собрать все элементы рекурсивно"""
        for i in range(parent.childCount()):
            item = parent.child(i)
            self.all_items.append(item)
            if item.childCount() > 0:
                self.collect_items(item)
    
    def mousePressEvent(self, event):
        """Обработка нажатия мыши для drag-select"""
        if event.button() == Qt.LeftButton:
            self.drag_select_start = event.pos()
            self.is_drag_selecting = True
            
            # Если не зажат Ctrl или Shift, сбрасываем выделение
            modifiers = QApplication.keyboardModifiers()
            if not (modifiers & Qt.ControlModifier) and not (modifiers & Qt.ShiftModifier):
                self.clearSelection()
            
            super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Обработка движения мыши для drag-select"""
        if self.is_drag_selecting:
            # Обновляем область выделения
            self.drag_select_rect = QRect(self.drag_select_start, event.pos()).normalized()
            self.viewport().update()
            
            # Выделяем элементы в области
            if self.drag_select_rect:
                visible_rect = self.viewport().rect()
                
                for item in self.all_items:
                    rect = self.visualItemRect(item)
                    if self.drag_select_rect.intersects(rect) and rect.intersects(visible_rect):
                        item.setSelected(True)
                    elif not (QApplication.keyboardModifiers() & Qt.ControlModifier):
                        # Если не зажат Ctrl, снимаем выделение с элементов вне области
                        item.setSelected(False)
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Обработка отпускания мыши"""
        if event.button() == Qt.LeftButton and self.is_drag_selecting:
            self.is_drag_selecting = False
            self.drag_select_rect = None
            self.drag_select_start = None
            self.viewport().update()
        super().mouseReleaseEvent(event)
    
    def paintEvent(self, event):
        """Отрисовка с областью drag-select"""
        super().paintEvent(event)
        
        if self.is_drag_selecting and self.drag_select_rect:
            painter = QPainter(self.viewport())
            painter.setPen(QPen(QColor(100, 150, 255), 2))
            painter.setBrush(QBrush(QColor(100, 150, 255, 50)))
            painter.drawRect(self.drag_select_rect)
    
    def keyPressEvent(self, event):
        """Обработка нажатий клавиш для Ctrl+Click и Shift+Click"""
        if event.key() == Qt.Key_Control or event.key() == Qt.Key_Shift:
            # Сохраняем текущее выделение при нажатии Ctrl/Shift
            self.selection_before_modifier = self.selectedItems()
        super().keyPressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """Обработка двойного клика"""
        item = self.itemAt(event.pos())
        if item:
            self.itemDoubleClicked.emit(item, 0)


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
        
        # Для расширенного поиска
        self.search_criteria = {
            'name': '',
            'content': '',
            'size_min': '',
            'size_max': '',
            'date_from': '',
            'date_to': ''
        }
        
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
        self.setGeometry(100, 100, 1600, 900)
        
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
        
        # Строка состояния с прогресс-баром
        self.create_status_bar()
        
        # Загрузка истории папок
        self.load_folder_history()
        
    def create_status_bar(self):
        """Создание строки состояния с прогресс-баром"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Счетчик файлов
        self.file_count_label = QLabel("Файлов: 0")
        self.status_bar.addWidget(self.file_count_label)
        
        # Статус
        self.status_label = QLabel("Готов к работе")
        self.status_bar.addWidget(self.status_label, 1)  # Растягиваемый
        
        # Прогресс бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.status_bar.addPermanentWidget(self.progress_bar)
    
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
        
        # Кнопки отмены/повтора с иконками из 5.10
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
        self.create_advanced_search_widgets(toolbar)
        
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
    
    def create_advanced_search_widgets(self, toolbar):
        """Создание виджетов расширенного поиска"""
        # Режим поиска
        self.search_mode = self.settings.get("search_mode", "name")
        self.search_mode_btn = QPushButton("Имя")
        self.search_mode_btn.clicked.connect(self.toggle_search_mode)
        self.search_mode_btn.setFixedWidth(80)
        self.search_mode_btn.setToolTip("Режим поиска: по имени файла или по содержанию")
        toolbar.addWidget(self.search_mode_btn)
        
        # Поле поиска
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите текст для поиска...")
        self.search_input.textChanged.connect(self.on_search_changed)
        self.search_input.setMinimumWidth(200)
        self.search_input.setToolTip("Введите текст для поиска файлов. Разделяйте критерии через '; '")
        toolbar.addWidget(self.search_input)
        
        # Кнопка расширенного поиска
        self.advanced_search_btn = QPushButton("...")
        self.advanced_search_btn.setFixedWidth(30)
        self.advanced_search_btn.setToolTip("Расширенный поиск")
        self.advanced_search_btn.clicked.connect(self.show_advanced_search_dialog)
        toolbar.addWidget(self.advanced_search_btn)
    
    def show_advanced_search_dialog(self):
        """Показать диалог расширенного поиска"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Расширенный поиск")
        dialog.setModal(True)
        dialog.resize(400, 300)
        
        layout = QVBoxLayout(dialog)
        
        # Имя файла
        name_frame = QFrame()
        name_layout = QHBoxLayout(name_frame)
        name_layout.addWidget(QLabel("Имя файла:"))
        self.name_search_input = QLineEdit(self.search_criteria['name'])
        self.name_search_input.textChanged.connect(self.on_search_criteria_changed)
        name_layout.addWidget(self.name_search_input)
        layout.addWidget(name_frame)
        
        # Содержание
        content_frame = QFrame()
        content_layout = QHBoxLayout(content_frame)
        content_layout.addWidget(QLabel("Содержание:"))
        self.content_search_input = QLineEdit(self.search_criteria['content'])
        self.content_search_input.textChanged.connect(self.on_search_criteria_changed)
        content_layout.addWidget(self.content_search_input)
        layout.addWidget(content_frame)
        
        # Размер
        size_frame = QFrame()
        size_layout = QHBoxLayout(size_frame)
        size_layout.addWidget(QLabel("Размер:"))
        self.size_min_input = QLineEdit(self.search_criteria['size_min'])
        self.size_min_input.setPlaceholderText("мин (байт)")
        self.size_min_input.textChanged.connect(self.on_search_criteria_changed)
        size_layout.addWidget(self.size_min_input)
        
        size_layout.addWidget(QLabel("-"))
        
        self.size_max_input = QLineEdit(self.search_criteria['size_max'])
        self.size_max_input.setPlaceholderText("макс (байт)")
        self.size_max_input.textChanged.connect(self.on_search_criteria_changed)
        size_layout.addWidget(self.size_max_input)
        layout.addWidget(size_frame)
        
        # Дата
        date_frame = QFrame()
        date_layout = QHBoxLayout(date_frame)
        date_layout.addWidget(QLabel("Дата изменения:"))
        self.date_from_input = QLineEdit(self.search_criteria['date_from'])
        self.date_from_input.setPlaceholderText("ГГГГ-ММ-ДД")
        self.date_from_input.textChanged.connect(self.on_search_criteria_changed)
        date_layout.addWidget(self.date_from_input)
        
        date_layout.addWidget(QLabel("-"))
        
        self.date_to_input = QLineEdit(self.search_criteria['date_to'])
        self.date_to_input.setPlaceholderText("ГГГГ-ММ-ДД")
        self.date_to_input.textChanged.connect(self.on_search_criteria_changed)
        date_layout.addWidget(self.date_to_input)
        layout.addWidget(date_frame)
        
        # Кнопки
        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)
        
        apply_btn = QPushButton("Применить")
        apply_btn.clicked.connect(lambda: self.apply_advanced_search(dialog))
        button_layout.addWidget(apply_btn)
        
        clear_btn = QPushButton("Очистить")
        clear_btn.clicked.connect(self.clear_advanced_search)
        button_layout.addWidget(clear_btn)
        
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addWidget(button_frame)
        
        dialog.exec_()
    
    def on_search_criteria_changed(self):
        """Обработка изменения критериев поиска"""
        self.search_criteria['name'] = self.name_search_input.text()
        self.search_criteria['content'] = self.content_search_input.text()
        self.search_criteria['size_min'] = self.size_min_input.text()
        self.search_criteria['size_max'] = self.size_max_input.text()
        self.search_criteria['date_from'] = self.date_from_input.text()
        self.search_criteria['date_to'] = self.date_to_input.text()
    
    def apply_advanced_search(self, dialog):
        """Применить расширенный поиск"""
        # Обновляем поле поиска с объединенными критериями
        criteria_parts = []
        
        if self.search_criteria['name']:
            criteria_parts.append(f"имя:{self.search_criteria['name']}")
        
        if self.search_criteria['content']:
            criteria_parts.append(f"содержание:{self.search_criteria['content']}")
        
        if self.search_criteria['size_min'] or self.search_criteria['size_max']:
            size_range = ""
            if self.search_criteria['size_min']:
                size_range += f">{self.search_criteria['size_min']}"
            if self.search_criteria['size_max']:
                if size_range:
                    size_range += "-"
                size_range += f"<{self.search_criteria['size_max']}"
            criteria_parts.append(f"размер:{size_range}")
        
        if self.search_criteria['date_from'] or self.search_criteria['date_to']:
            date_range = ""
            if self.search_criteria['date_from']:
                date_range += f">{self.search_criteria['date_from']}"
            if self.search_criteria['date_to']:
                if date_range:
                    date_range += "-"
                date_range += f"<{self.search_criteria['date_to']}"
            criteria_parts.append(f"дата:{date_range}")
        
        if criteria_parts:
            self.search_input.setText("; ".join(criteria_parts))
        
        dialog.accept()
        self.refresh_files_tree()
    
    def clear_advanced_search(self):
        """Очистить критерии расширенного поиска"""
        self.search_criteria = {
            'name': '',
            'content': '',
            'size_min': '',
            'size_max': '',
            'date_from': '',
            'date_to': ''
        }
        
        self.name_search_input.clear()
        self.content_search_input.clear()
        self.size_min_input.clear()
        self.size_max_input.clear()
        self.date_from_input.clear()
        self.date_to_input.clear()
        
        self.search_input.clear()
        self.refresh_files_tree()
    
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
        
        # Подменю Спец настройки (перенесено из основного меню)
        special_menu = settings_menu.addMenu("Специальные настройки")
        
        # Переносим настройку Blockbench в специальные настройки
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
            # Смягченная тёмная тема
            dark_palette = QPalette()
            
            # Базовые цвета
            dark_palette.setColor(QPalette.Window, QColor(60, 60, 60))
            dark_palette.setColor(QPalette.WindowText, Qt.white)
            dark_palette.setColor(QPalette.Base, QColor(40, 40, 40))
            dark_palette.setColor(QPalette.AlternateBase, QColor(60, 60, 60))
            dark_palette.setColor(QPalette.ToolTipBase, QColor(30, 30, 30))
            dark_palette.setColor(QPalette.ToolTipText, Qt.white)
            dark_palette.setColor(QPalette.Text, Qt.white)
            dark_palette.setColor(QPalette.Button, QColor(70, 70, 70))
            dark_palette.setColor(QPalette.ButtonText, Qt.white)
            dark_palette.setColor(QPalette.BrightText, Qt.red)
            dark_palette.setColor(QPalette.Link, QColor(80, 160, 240))
            dark_palette.setColor(QPalette.Highlight, QColor(80, 160, 240))
            dark_palette.setColor(QPalette.HighlightedText, Qt.black)
            
            # Отключенные элементы
            dark_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(150, 150, 150))
            dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(150, 150, 150))
            
            app.setPalette(dark_palette)
            
            # Стили для виджетов
            dark_stylesheet = """
            QMainWindow {
                background-color: #3c3c3c;
            }
            QTreeWidget {
                background-color: #2d2d2d;
                color: #e0e0e0;
                alternate-background-color: #353535;
                selection-background-color: #5080f0;
                selection-color: white;
            }
            QTreeWidget::item:selected {
                background-color: #5080f0;
                color: white;
            }
            QTreeWidget::item:hover {
                background-color: #454545;
            }
            QGroupBox {
                color: #e0e0e0;
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
                background-color: #505050;
                color: #e0e0e0;
                border: 1px solid #666;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #606060;
                border: 1px solid #777;
            }
            QPushButton:pressed {
                background-color: #404040;
            }
            QPushButton:disabled {
                background-color: #333;
                color: #777;
            }
            QLineEdit, QComboBox {
                background-color: #353535;
                color: #e0e0e0;
                border: 1px solid #555;
                padding: 3px;
                border-radius: 3px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #353535;
                color: #e0e0e0;
                selection-background-color: #5080f0;
            }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 3px;
                text-align: center;
                color: #e0e0e0;
                background-color: #353535;
            }
            QProgressBar::chunk {
                background-color: #5080f0;
                border-radius: 3px;
            }
            QMenuBar {
                background-color: #3c3c3c;
                color: #e0e0e0;
            }
            QMenuBar::item:selected {
                background-color: #505050;
            }
            QMenu {
                background-color: #3c3c3c;
                color: #e0e0e0;
                border: 1px solid #555;
            }
            QMenu::item:selected {
                background-color: #5080f0;
            }
            QCheckBox {
                color: #e0e0e0;
            }
            QCheckBox::indicator {
                width: 13px;
                height: 13px;
            }
            QLabel {
                color: #e0e0e0;
            }
            QToolBar {
                background-color: #454545;
                border: none;
                spacing: 3px;
                padding: 2px;
            }
            QStatusBar {
                background-color: #454545;
                color: #e0e0e0;
            }
            QScrollBar:vertical {
                background-color: #353535;
                width: 15px;
                margin: 15px 0 15px 0;
            }
            QScrollBar::handle:vertical {
                background-color: #606060;
                min-height: 20px;
                border-radius: 7px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #707070;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                background: none;
            }
            """
            app.setStyleSheet(dark_stylesheet)
        else:
            # Смягченная светлая тема
            light_palette = QPalette()
            
            # Базовые цвета
            light_palette.setColor(QPalette.Window, QColor(240, 240, 240))
            light_palette.setColor(QPalette.WindowText, Qt.black)
            light_palette.setColor(QPalette.Base, Qt.white)
            light_palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
            light_palette.setColor(QPalette.ToolTipBase, Qt.white)
            light_palette.setColor(QPalette.ToolTipText, Qt.black)
            light_palette.setColor(QPalette.Text, Qt.black)
            light_palette.setColor(QPalette.Button, QColor(230, 230, 230))
            light_palette.setColor(QPalette.ButtonText, Qt.black)
            light_palette.setColor(QPalette.BrightText, Qt.red)
            light_palette.setColor(QPalette.Link, QColor(42, 130, 218))
            light_palette.setColor(QPalette.Highlight, QColor(100, 150, 255))
            light_palette.setColor(QPalette.HighlightedText, Qt.white)
            
            app.setPalette(light_palette)
            
            # Стили для виджетов
            light_stylesheet = """
            QMainWindow {
                background-color: #f0f0f0;
            }
            QTreeWidget {
                background-color: white;
                alternate-background-color: #f8f8f8;
                selection-background-color: #6496ff;
                selection-color: white;
            }
            QTreeWidget::item:selected {
                background-color: #6496ff;
                color: white;
            }
            QTreeWidget::item:hover {
                background-color: #e8e8e8;
            }
            QGroupBox {
                border: 1px solid #ccc;
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
                background-color: #e6e6e6;
                border: 1px solid #ccc;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
                border: 1px solid #aaa;
            }
            QPushButton:pressed {
                background-color: #d6d6d6;
            }
            QPushButton:disabled {
                background-color: #f5f5f5;
                color: #999;
            }
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 3px;
                text-align: center;
                background-color: white;
            }
            QProgressBar::chunk {
                background-color: #6496ff;
                border-radius: 3px;
            }
            QMenuBar {
                background-color: #f0f0f0;
            }
            QMenuBar::item:selected {
                background-color: #e0e0e0;
            }
            QMenu {
                background-color: white;
                border: 1px solid #ccc;
            }
            QMenu::item:selected {
                background-color: #6496ff;
                color: white;
            }
            QStatusBar {
                background-color: #f0f0f0;
            }
            QScrollBar:vertical {
                background-color: #f5f5f5;
                width: 15px;
                margin: 15px 0 15px 0;
            }
            QScrollBar::handle:vertical {
                background-color: #c0c0c0;
                min-height: 20px;
                border-radius: 7px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #a0a0a0;
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
        self.file_count_label.setText("Файлов: 0")
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
        # Обновляем счетчик файлов в сообщении
        if "файлов" in message:
            try:
                count = int(message.split()[-2])
                self.file_count_label.setText(f"Файлов: {count}")
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
        
        self.status_label.setText(f"Сканирование завершено")
        self.file_count_label.setText(f"Файлов: {len(all_files)}")
    
    def on_scan_error(self, error_msg):
        """Ошибка сканирования"""
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        QMessageBox.critical(self, "Ошибка сканирования", f"Не удалось выполнить сканирование:\n{error_msg}")
        self.status_label.setText("Ошибка сканирования")
        self.file_count_label.setText("Файлов: 0")
    
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
    
    def parse_search_query(self, query):
        """Разбор поискового запроса с множественными критериями"""
        criteria = {
            'name': '',
            'content': '',
            'size_min': '',
            'size_max': '',
            'date_from': '',
            'date_to': ''
        }
        
        if not query:
            return criteria
        
        # Разделяем по точке с запятой
        parts = [p.strip() for p in query.split(';') if p.strip()]
        
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                
                if key == 'имя' or key == 'name':
                    criteria['name'] = value
                elif key == 'содержание' or key == 'content' or key == 'текст':
                    criteria['content'] = value
                elif key == 'размер' or key == 'size':
                    # Обработка диапазона размера
                    if '>' in value:
                        criteria['size_min'] = value.replace('>', '').strip()
                    if '<' in value:
                        criteria['size_max'] = value.replace('<', '').strip()
                    if '-' in value:
                        min_max = value.split('-')
                        if len(min_max) == 2:
                            criteria['size_min'] = min_max[0].strip()
                            criteria['size_max'] = min_max[1].strip()
                elif key == 'дата' or key == 'date':
                    # Обработка диапазона даты
                    if '>' in value:
                        criteria['date_from'] = value.replace('>', '').strip()
                    if '<' in value:
                        criteria['date_to'] = value.replace('<', '').strip()
                    if '-' in value:
                        from_to = value.split('-')
                        if len(from_to) == 2:
                            criteria['date_from'] = from_to[0].strip()
                            criteria['date_to'] = from_to[1].strip()
            else:
                # Если нет ключа, считаем это поиском по имени
                criteria['name'] = part
        
        return criteria
    
    def refresh_files_tree(self):
        """Обновление дерева файлов"""
        self.files_tree.clear()
        
        search_query = self.search_input.text()
        search_criteria = self.parse_search_query(search_query)
        
        filtered_files = []
        for file_info in self.all_files:
            if self.show_favorites_only and not file_info.get('is_favorite', False):
                continue
            
            if self.current_extension_filter and self.current_extension_filter != "Все расширения":
                file_ext = file_info.get('extension', '')
                if file_ext != self.current_extension_filter:
                    continue
            
            # Проверка по имени
            if search_criteria['name']:
                filename = file_info['name'].lower()
                if search_criteria['name'].lower() not in filename:
                    continue
            
            # Проверка по содержимому
            if search_criteria['content']:
                content = self.load_file_content(file_info).lower()
                if search_criteria['content'].lower() not in content:
                    continue
            
            # Проверка по размеру
            try:
                if search_criteria['size_min']:
                    min_size = float(search_criteria['size_min'])
                    if file_info['size'] < min_size:
                        continue
                
                if search_criteria['size_max']:
                    max_size = float(search_criteria['size_max'])
                    if file_info['size'] > max_size:
                        continue
            except ValueError:
                pass
            
            # Проверка по дате
            try:
                file_date = file_info['modified'].date()
                
                if search_criteria['date_from']:
                    from_date = datetime.strptime(search_criteria['date_from'], "%Y-%m-%d").date()
                    if file_date < from_date:
                        continue
                
                if search_criteria['date_to']:
                    to_date = datetime.strptime(search_criteria['date_to'], "%Y-%m-%d").date()
                    if file_date > to_date:
                        continue
            except ValueError:
                pass
            
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
        
        self.files_tree.update_all_items()
        self.status_label.setText(f"Показано файлов: {len(filtered_files)}")
        self.file_count_label.setText(f"Файлов: {len(filtered_files)}")
    
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
    
    def toggle_search_mode(self):
        """Переключить режим поиска"""
        self.search_mode = "content" if self.search_mode == "name" else "name"
        self.search_mode_btn.setText("Имя" if self.search_mode == "name" else "Содержание")
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
            
            menu.addSeparator()
            
            # Добавить в виртуальную папку (через подменю)
            add_to_folder_menu = QMenu("Добавить в папку", self)
            menu.addMenu(add_to_folder_menu)
            
            # Создать новую папку
            new_folder_action = QAction("Создать новую...", self)
            new_folder_action.triggered.connect(lambda: self.create_virtual_folder_from_selection())
            add_to_folder_menu.addAction(new_folder_action)
            
            # Добавить в существующие папки
            if self.virtual_folders:
                add_to_folder_menu.addSeparator()
                for folder_name in self.virtual_folders.keys():
                    folder_action = QAction(folder_name, self)
                    folder_action.triggered.connect(lambda checked, f=folder_name: self.add_selected_to_virtual_folder(f))
                    add_to_folder_menu.addAction(folder_action)
        
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
        """Создать виртуальную папку из выделенных файлов"""
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Предупреждение", "Выберите файлы для объединения в папку")
            return
        
        files_to_add = []
        for item in selected_items:
            item_type = item.text(4)
            if item_type == 'file':
                file_path = item.text(3)
                file_name = item.text(0).replace('⭐ ', '')
                files_to_add.append({
                    'path': file_path,
                    'name': file_name
                })
        
        if not files_to_add:
            QMessageBox.warning(self, "Предупреждение", "Выберите файлы для объединения в папку")
            return
        
        # Проверка на дубликаты в папке
        file_names = [f['name'] for f in files_to_add]
        duplicates = [name for name in file_names if file_names.count(name) > 1]
        
        if duplicates:
            reply = QMessageBox.question(self, "Предупреждение",
                f"В выбранных файлах есть дубликаты имен:\n{', '.join(set(duplicates))}\n\n"
                "Хотите продолжить? Файлы с одинаковыми именами могут быть перезаписаны.",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        
        folder_name, ok = QInputDialog.getText(self, "Создать папку", "Введите название папки:")
        if ok and folder_name:
            if folder_name in self.virtual_folders:
                QMessageBox.warning(self, "Предупреждение", "Папка с таким именем уже существует")
                return
            
            # Копируем файлы (создаем ссылки)
            for file_info in files_to_add:
                file_info['is_copy'] = True
            
            self.virtual_folders[folder_name] = files_to_add
            
            # Добавляем в историю действий
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
        for item in selected_items:
            item_type = item.text(4)
            if item_type == 'file':
                file_path = item.text(3)
                file_name = item.text(0).replace('⭐ ', '')
                files_to_add.append({
                    'path': file_path,
                    'name': file_name
                })
        
        if not files_to_add:
            return
        
        # Проверка на дубликаты
        existing_files = []
        for item in self.virtual_folders.get(folder_name, []):
            if isinstance(item, dict):
                existing_files.append(item['name'])
            else:
                existing_files.append(os.path.basename(item))
        
        new_duplicates = []
        for file_info in files_to_add:
            if file_info['name'] in existing_files:
                new_duplicates.append(file_info['name'])
        
        if new_duplicates:
            reply = QMessageBox.question(self, "Предупреждение",
                f"В папке '{folder_name}' уже есть файлы с именами:\n{', '.join(set(new_duplicates))}\n\n"
                "Хотите продолжить? Существующие файлы будут заменены.",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        
        # Добавляем файлы в папку
        old_files = self.virtual_folders.get(folder_name, []).copy()
        if folder_name not in self.virtual_folders:
            self.virtual_folders[folder_name] = []
        
        # Удаляем существующие дубликаты
        for file_info in files_to_add:
            self.virtual_folders[folder_name] = [
                f for f in self.virtual_folders[folder_name]
                if not (isinstance(f, dict) and f.get('name') == file_info['name'])
            ]
        
        # Добавляем новые файлы
        for file_info in files_to_add:
            file_info['is_copy'] = True
            self.virtual_folders[folder_name].append(file_info)
        
        # Добавляем в историю действий
        self.add_to_action_history('virtual_folder_add_files', {
            'folder_name': folder_name,
            'files_added': files_to_add.copy(),
            'old_files': old_files
        })
        
        self.save_settings()
        self.refresh_files_tree()
        self.status_label.setText(f"Добавлено {len(files_to_add)} файлов в папку '{folder_name}'")
    
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
        """Открыть файл через диалог 'Открыть с помощью' (исправлено для Windows 11)"""
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Предупреждение", f"Файл не существует:\n{file_path}")
            return
        
        try:
            if sys.platform == "win32":
                # Исправленный способ для Windows 10/11
                import win32api
                import win32con
                import win32gui
                
                # Получаем handle окна
                hwnd = self.winId() if hasattr(self, 'winId') else 0
                
                # Открываем диалог "Открыть с помощью"
                result = win32api.ShellExecute(
                    hwnd,
                    "openas",  # Команда "Открыть с помощью"
                    file_path,
                    None,
                    os.path.dirname(file_path),
                    win32con.SW_SHOWNORMAL
                )
                
                if result <= 32:
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
        
        was_favorite = file_path in favorites
        
        if file_path in favorites:
            favorites.remove(file_path)
            self.status_label.setText(f"Файл убран из избранного")
        else:
            favorites.append(file_path)
            self.status_label.setText(f"Файл добавлен в избранное")
        
        # Добавляем в историю действий
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
        
        was_favorite = folder_name in favorites
        
        if folder_name in favorites:
            favorites.remove(folder_name)
            self.status_label.setText(f"Папка '{folder_name}' убрана из избранного")
        else:
            favorites.append(folder_name)
            self.status_label.setText(f"Папка '{folder_name}' добавлена в избранное")
        
        # Добавляем в историю действий
        self.add_to_action_history('favorite_toggle', {
            'file_paths': [folder_name],
            'was_favorite': was_favorite
        })
        
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
        """Корректное удаление файлов с отменой"""
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            return
        
        # Собираем информацию о файлах для удаления
        files_to_delete = []
        file_paths = []
        
        for item in selected_items:
            item_type = item.text(4)
            if item_type == 'file':
                file_path = item.text(3)
                
                if os.path.exists(file_path):
                    try:
                        # Читаем содержимое файла для возможности отмены
                        with open(file_path, 'rb') as f:
                            content = f.read()
                        
                        files_to_delete.append({
                            'path': file_path,
                            'content': content,
                            'temp_path': tempfile.mktemp()
                        })
                        file_paths.append(file_path)
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать файл {file_path}: {str(e)}")
                        continue
        
        if not files_to_delete:
            return
        
        reply = QMessageBox.question(self, "Подтверждение", 
                                   f"Удалить выбранные файлы ({len(files_to_delete)})?",
                                   QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            # Сохраняем копии файлов для возможности отмены
            for file_info in files_to_delete:
                try:
                    with open(file_info['temp_path'], 'wb') as f:
                        f.write(file_info['content'])
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", f"Не удалось создать резервную копию: {str(e)}")
                    return
            
            # Добавляем в историю действий перед удалением
            self.add_to_action_history('file_delete', {
                'files': files_to_delete.copy()
            })
            
            # Удаляем файлы
            deleted_count = 0
            for file_info in files_to_delete:
                try:
                    os.remove(file_info['path'])
                    deleted_count += 1
                    
                    # Удаляем из списка файлов
                    self.all_files = [f for f in self.all_files if f['path'] != file_info['path']]
                    
                    # Удаляем из избранного
                    if file_info['path'] in self.settings.get("favorites", []):
                        self.settings["favorites"].remove(file_info['path'])
                    
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", f"Не удалось удалить файл {file_info['path']}: {str(e)}")
            
            # Обновляем виртуальные папки
            for folder_name in list(self.virtual_folders.keys()):
                self.virtual_folders[folder_name] = [
                    f for f in self.virtual_folders[folder_name]
                    if not (isinstance(f, dict) and f.get('path') in file_paths)
                ]
                
                # Удаляем пустые папки
                if not self.virtual_folders[folder_name]:
                    del self.virtual_folders[folder_name]
            
            self.save_settings()
            self.refresh_files_tree()
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
            
            elif action['type'] == 'file_delete':
                # Восстанавливаем удаленные файлы
                for file_info in action['data']['files']:
                    try:
                        # Копируем обратно из временного файла
                        if os.path.exists(file_info['temp_path']):
                            with open(file_info['temp_path'], 'rb') as src:
                                content = src.read()
                            with open(file_info['path'], 'wb') as dst:
                                dst.write(content)
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось восстановить файл: {str(e)}")
                
                self.refresh_files_tree()
                self.status_label.setText("Отменено удаление файлов")
            
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
            
            elif action['type'] == 'virtual_folder_rename':
                old_name = action['data']['old_name']
                new_name = action['data']['new_name']
                files = action['data']['files']
                
                if new_name in self.virtual_folders:
                    self.virtual_folders[old_name] = self.virtual_folders.pop(new_name)
                    
                    # Восстанавливаем состояние раскрытия
                    if new_name in self.virtual_folders_expanded:
                        self.virtual_folders_expanded[old_name] = self.virtual_folders_expanded.pop(new_name)
                    
                    self.save_settings()
                    self.refresh_files_tree()
                    self.status_label.setText(f"Отменено переименование папки: {new_name} -> {old_name}")
            
            elif action['type'] == 'virtual_folder_add_files':
                folder_name = action['data']['folder_name']
                files_added = action['data']['files_added']
                old_files = action['data']['old_files']
                
                if folder_name in self.virtual_folders:
                    # Удаляем добавленные файлы
                    added_paths = [f['path'] for f in files_added]
                    self.virtual_folders[folder_name] = [
                        f for f in self.virtual_folders[folder_name]
                        if not (isinstance(f, dict) and f.get('path') in added_paths)
                    ]
                    
                    # Восстанавливаем старые файлы
                    self.virtual_folders[folder_name].extend(old_files)
                    self.save_settings()
                    self.refresh_files_tree()
                    self.status_label.setText(f"Отменено добавление файлов в папку '{folder_name}'")
            
            self.current_action_index -= 1
            self.is_undo_redo_in_progress = False
            self.update_undo_redo_buttons()
    
    def redo_action(self):
        """Повторить отмененное действие"""
        if self.current_action_index < len(self.action_history) - 1:
            self.is_undo_redo_in_progress = True
            self.current_action_index += 1
            action = self.action_history[self.current_action_index]
            
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
            
            elif action['type'] == 'file_delete':
                # Повторяем удаление файлов
                for file_info in action['data']['files']:
                    try:
                        if os.path.exists(file_info['path']):
                            os.remove(file_info['path'])
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось удалить файл: {str(e)}")
                
                self.refresh_files_tree()
                self.status_label.setText("Повторено удаление файлов")
            
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
            
            elif action['type'] == 'virtual_folder_rename':
                old_name = action['data']['old_name']
                new_name = action['data']['new_name']
                files = action['data']['files']
                
                if old_name in self.virtual_folders:
                    self.virtual_folders[new_name] = self.virtual_folders.pop(old_name)
                    
                    # Переносим состояние раскрытия
                    if old_name in self.virtual_folders_expanded:
                        self.virtual_folders_expanded[new_name] = self.virtual_folders_expanded.pop(old_name)
                    
                    self.save_settings()
                    self.refresh_files_tree()
                    self.status_label.setText(f"Повторено переименование папки: {old_name} -> {new_name}")
            
            elif action['type'] == 'virtual_folder_add_files':
                folder_name = action['data']['folder_name']
                files_added = action['data']['files_added']
                
                if folder_name in self.virtual_folders:
                    # Добавляем файлы обратно
                    for file_info in files_added:
                        # Удаляем существующие дубликаты
                        self.virtual_folders[folder_name] = [
                            f for f in self.virtual_folders[folder_name]
                            if not (isinstance(f, dict) and f.get('name') == file_info['name'])
                        ]
                        self.virtual_folders[folder_name].append(file_info)
                    
                    self.save_settings()
                    self.refresh_files_tree()
                    self.status_label.setText(f"Повторено добавление файлов в папку '{folder_name}'")
            
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
Ctrl+F — Добавить в избранное

Навигация:
↑/↓ — Выбор файлов
Enter — Открыть файл
ЛКМ + перемещение — Выделение области"""
        
        QMessageBox.information(self, "Сочетания клавиш", hotkeys_text)
    
    def show_about(self):
        """Показать информацию о программе"""
        about_text = """Sofil - Сканер папок
Версия: 6.6 
Создатель: Akami_bl
Обратная связь: akami.bl@gmail.com

Основное:
📁 Сканирует папки и архивы (ZIP)
🗂️ Создает виртуальные папки
🔍 Ищет и фильтрует файлы
⭐ Добавляет файлы в избранное

Новые функции:
🔍 Расширенный поиск по имени, содержанию, размеру и дате
🖱️ Drag-select выделение файлов
↩️ Полная поддержка отмены/повтора действий
📊 Группировка дубликатов

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