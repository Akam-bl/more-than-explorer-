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
    QStyledItemDelegate, QStyle
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QRect, QPoint, QEvent
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor, QTextCursor, QBrush, QMouseEvent

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
    """Кастомное дерево файлов с поддержкой перетаскивания и выделения мышью"""
    
    drag_selection_start = pyqtSignal(QPoint)
    drag_selection_update = pyqtSignal(QRect)
    drag_selection_end = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setDragEnabled(False)  # Отключаем DnD для файлов
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        
        # Для выделения мышью
        self.drag_selecting = False
        self.drag_start_pos = QPoint()
        self.drag_end_pos = QPoint()
        self.drag_rect = QRect()
        
        self.setMouseTracking(True)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_pos = event.pos()
            self.drag_end_pos = event.pos()
            self.drag_selecting = True
            
            # Проверяем модификаторы клавиш
            if event.modifiers() & Qt.ControlModifier:
                # Ctrl+ЛКМ - добавляем к выделению
                item = self.itemAt(event.pos())
                if item:
                    if item.isSelected():
                        item.setSelected(False)
                    else:
                        item.setSelected(True)
                self.drag_selecting = False
            elif event.modifiers() & Qt.ShiftModifier:
                # Shift+ЛКМ - выделяем диапазон
                self.handle_shift_click(event.pos())
                self.drag_selecting = False
            else:
                # Обычный клик
                super().mousePressEvent(event)
                self.drag_selection_start.emit(event.pos())
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        if self.drag_selecting and (event.buttons() & Qt.LeftButton):
            self.drag_end_pos = event.pos()
            self.drag_rect = QRect(self.drag_start_pos, self.drag_end_pos).normalized()
            
            # Выделяем элементы в пределах прямоугольника
            self.select_items_in_rect(self.drag_rect)
            
            self.drag_selection_update.emit(self.drag_rect)
            self.viewport().update()
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.drag_selecting:
            self.drag_selecting = False
            self.drag_rect = QRect()
            self.viewport().update()
            self.drag_selection_end.emit()
        super().mouseReleaseEvent(event)
    
    def select_items_in_rect(self, rect):
        """Выделить элементы в пределах прямоугольника"""
        items_to_select = []
        
        # Получаем все видимые элементы
        for i in range(self.topLevelItemCount()):
            top_item = self.topLevelItem(i)
            self._collect_items_in_rect(top_item, rect, items_to_select)
        
        # Обновляем выделение
        self.clearSelection()
        for item in items_to_select:
            item.setSelected(True)
    
    def _collect_items_in_rect(self, item, rect, items_list):
        """Рекурсивно собрать элементы в пределах прямоугольника"""
        # Проверяем текущий элемент
        visual_rect = self.visualItemRect(item)
        if rect.intersects(visual_rect):
            items_list.append(item)
        
        # Рекурсивно проверяем дочерние элементы
        if item.isExpanded():
            for i in range(item.childCount()):
                child_item = item.child(i)
                self._collect_items_in_rect(child_item, rect, items_list)
    
    def handle_shift_click(self, click_pos):
        """Обработка Shift+клик для выделения диапазона"""
        current_item = self.itemAt(click_pos)
        if not current_item:
            return
        
        # Находим все элементы в дереве
        all_items = []
        for i in range(self.topLevelItemCount()):
            self._collect_all_items(self.topLevelItem(i), all_items)
        
        # Находим индексы выделенных элементов
        selected_items = self.selectedItems()
        if not selected_items:
            current_item.setSelected(True)
            return
        
        # Находим первый выделенный элемент
        first_selected = selected_items[0]
        first_index = all_items.index(first_selected) if first_selected in all_items else 0
        current_index = all_items.index(current_item) if current_item in all_items else 0
        
        # Выделяем диапазон
        start_idx = min(first_index, current_index)
        end_idx = max(first_index, current_index)
        
        self.clearSelection()
        for i in range(start_idx, end_idx + 1):
            all_items[i].setSelected(True)
    
    def _collect_all_items(self, item, items_list):
        """Рекурсивно собрать все элементы"""
        items_list.append(item)
        for i in range(item.childCount()):
            child_item = item.child(i)
            self._collect_all_items(child_item, items_list)
    
    def paintEvent(self, event):
        super().paintEvent(event)
        
        # Рисуем прямоугольник выделения
        if self.drag_selecting and not self.drag_rect.isNull():
            painter = self.viewport().palette().window().color()
            from PyQt5.QtGui import QPainter
            qp = QPainter(self.viewport())
            qp.setPen(QColor(100, 100, 250, 150))
            qp.setBrush(QColor(100, 100, 250, 50))
            qp.drawRect(self.drag_rect)


class AdvancedSearchWidget(QWidget):
    """Виджет расширенного поиска"""
    
    search_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Основные поля поиска
        search_frame = QWidget()
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(0, 0, 0, 0)
        
        # Поле для поиска по имени/содержимому
        self.name_content_search = QLineEdit()
        self.name_content_search.setPlaceholderText("Имя или содержимое файлов...")
        self.name_content_search.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.name_content_search)
        
        # Поле для поиска по размеру
        self.size_search = QLineEdit()
        self.size_search.setPlaceholderText("Размер (например: >1MB, <100KB, 500B-2MB)")
        self.size_search.textChanged.connect(self.on_search_changed)
        self.size_search.setFixedWidth(150)
        search_layout.addWidget(self.size_search)
        
        # Поле для поиска по дате
        self.date_search = QLineEdit()
        self.date_search.setPlaceholderText("Дата (например: >2023-01-01, <2024-01-01)")
        self.date_search.textChanged.connect(self.on_search_changed)
        self.date_search.setFixedWidth(150)
        search_layout.addWidget(self.date_search)
        
        layout.addWidget(search_frame)
        
        # Пояснение
        help_label = QLabel("Примеры: 'report.txt; >1MB; >2023-01-01' или 'error.log; <100KB; сегодня'")
        help_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(help_label)
    
    def on_search_changed(self):
        self.search_changed.emit()
    
    def get_search_criteria(self):
        """Получить критерии поиска"""
        name_content = self.name_content_search.text().strip()
        size_criteria = self.size_search.text().strip()
        date_criteria = self.date_search.text().strip()
        
        # Объединяем все критерии
        criteria_parts = []
        if name_content:
            criteria_parts.append(name_content)
        if size_criteria:
            criteria_parts.append(size_criteria)
        if date_criteria:
            criteria_parts.append(date_criteria)
        
        return "; ".join(criteria_parts)
    
    def parse_search_criteria(self, search_text):
        """Разобрать строку поиска на отдельные критерии"""
        if not search_text:
            return {}, ""
        
        criteria = {}
        parts = search_text.split(';')
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # Проверяем, является ли критерием размера
            if any(op in part for op in ['>', '<', '=', 'KB', 'MB', 'GB', 'B']):
                if 'размер' not in criteria:
                    criteria['размер'] = []
                criteria['размер'].append(part)
            # Проверяем, является ли критерием даты
            elif any(keyword in part.lower() for keyword in ['сегодня', 'вчера', 'неделя', 'месяц', 'год']) or \
                 any(char in part for char in ['-', '>', '<', '=']):
                if 'дата' not in criteria:
                    criteria['дата'] = []
                criteria['дата'].append(part)
            else:
                # По умолчанию считаем поиском по имени/содержимому
                if 'текст' not in criteria:
                    criteria['текст'] = []
                criteria['текст'].append(part)
        
        return criteria


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
        
        # Счетчик файлов
        self.file_count_label = QLabel("Файлов: 0")
        self.status_bar.addWidget(self.file_count_label)
        
        # Прогресс бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setTextVisible(False)
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
        
        # Кнопки отмены/повтора (иконки как в версии 5.10)
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
        
        # Виджет расширенного поиска
        search_label = QLabel("Поиск:")
        search_label.setToolTip("Расширенный поиск файлов")
        toolbar.addWidget(search_label)
        
        self.advanced_search = AdvancedSearchWidget()
        self.advanced_search.search_changed.connect(self.on_search_changed)
        toolbar.addWidget(self.advanced_search)
        
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
        
        # Перемещен сюда: Скрыть Blockbench children
        self.hide_bb_children_cb = QAction("Скрыть Blockbench children", self, checkable=True)
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
            # Тёмная тема (смягченная)
            dark_palette = QPalette()
            
            # Базовые цвета (смягченные)
            dark_palette.setColor(QPalette.Window, QColor(60, 63, 65))
            dark_palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.Base, QColor(43, 43, 43))
            dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
            dark_palette.setColor(QPalette.ToolTipBase, QColor(70, 70, 70))
            dark_palette.setColor(QPalette.ToolTipText, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.Text, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.Button, QColor(70, 73, 75))
            dark_palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.BrightText, Qt.red)
            dark_palette.setColor(QPalette.Link, QColor(100, 160, 220))
            dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
            dark_palette.setColor(QPalette.HighlightedText, QColor(240, 240, 240))
            
            # Отключенные элементы
            dark_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(150, 150, 150))
            dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(150, 150, 150))
            
            app.setPalette(dark_palette)
            
            # Стили для виджетов (смягченные)
            dark_stylesheet = """
            QMainWindow {
                background-color: #3C3F41;
            }
            QTreeWidget {
                background-color: #2B2B2B;
                color: #DCDCDC;
                alternate-background-color: #323232;
                border: 1px solid #555;
            }
            QTreeWidget::item:selected {
                background-color: #2A82DA;
                color: #F0F0F0;
            }
            QTreeWidget::item:hover {
                background-color: #3A3A3A;
            }
            QGroupBox {
                color: #DCDCDC;
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #3C3F41;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #DCDCDC;
                background-color: #3C3F41;
            }
            QPushButton {
                background-color: #5A5D5F;
                color: #DCDCDC;
                border: 1px solid #666;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #6A6D6F;
                border: 1px solid #777;
            }
            QPushButton:pressed {
                background-color: #4A4D4F;
            }
            QPushButton:disabled {
                background-color: #3A3D3F;
                color: #888;
            }
            QLineEdit, QComboBox {
                background-color: #2B2B2B;
                color: #DCDCDC;
                border: 1px solid #555;
                padding: 3px;
                border-radius: 3px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #2B2B2B;
                color: #DCDCDC;
                selection-background-color: #2A82DA;
            }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 3px;
                text-align: center;
                color: #DCDCDC;
                background-color: #2B2B2B;
            }
            QProgressBar::chunk {
                background-color: #2A82DA;
                border-radius: 3px;
            }
            QMenuBar {
                background-color: #3C3F41;
                color: #DCDCDC;
            }
            QMenuBar::item:selected {
                background-color: #4C4F51;
            }
            QMenu {
                background-color: #3C3F41;
                color: #DCDCDC;
                border: 1px solid #555;
            }
            QMenu::item:selected {
                background-color: #2A82DA;
                color: #F0F0F0;
            }
            QCheckBox {
                color: #DCDCDC;
            }
            QCheckBox::indicator {
                width: 13px;
                height: 13px;
            }
            QLabel {
                color: #DCDCDC;
            }
            QToolBar {
                background-color: #414446;
                border: none;
                spacing: 3px;
                padding: 2px;
            }
            QStatusBar {
                background-color: #414446;
                color: #DCDCDC;
            }
            QScrollBar:vertical {
                background-color: #2B2B2B;
                width: 15px;
                margin: 15px 0 15px 0;
            }
            QScrollBar::handle:vertical {
                background-color: #5A5D5F;
                min-height: 20px;
                border-radius: 7px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #6A6D6F;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                background-color: #2B2B2B;
                height: 15px;
                margin: 0 15px 0 15px;
            }
            QScrollBar::handle:horizontal {
                background-color: #5A5D5F;
                min-width: 20px;
                border-radius: 7px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #6A6D6F;
            }
            """
            app.setStyleSheet(dark_stylesheet)
        else:
            # Светлая тема (смягченная)
            light_palette = QPalette()
            
            # Базовые цвета (смягченные)
            light_palette.setColor(QPalette.Window, QColor(240, 240, 240))
            light_palette.setColor(QPalette.WindowText, Qt.black)
            light_palette.setColor(QPalette.Base, Qt.white)
            light_palette.setColor(QPalette.AlternateBase, QColor(248, 248, 248))
            light_palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 220))
            light_palette.setColor(QPalette.ToolTipText, Qt.black)
            light_palette.setColor(QPalette.Text, Qt.black)
            light_palette.setColor(QPalette.Button, QColor(240, 240, 240))
            light_palette.setColor(QPalette.ButtonText, Qt.black)
            light_palette.setColor(QPalette.BrightText, Qt.red)
            light_palette.setColor(QPalette.Link, QColor(0, 120, 215))
            light_palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
            light_palette.setColor(QPalette.HighlightedText, Qt.white)
            
            app.setPalette(light_palette)
            
            # Стили для виджетов (смягченные)
            light_stylesheet = """
            QMainWindow {
                background-color: #F0F0F0;
            }
            QTreeWidget {
                background-color: white;
                color: black;
                alternate-background-color: #F8F8F8;
                border: 1px solid #CCC;
            }
            QTreeWidget::item:selected {
                background-color: #0078D7;
                color: white;
            }
            QTreeWidget::item:hover {
                background-color: #E8E8E8;
            }
            QGroupBox {
                color: #333;
                border: 1px solid #CCC;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #333;
                background-color: white;
            }
            QPushButton {
                background-color: #F0F0F0;
                color: black;
                border: 1px solid #CCC;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #E0E0E0;
                border: 1px solid #BBB;
            }
            QPushButton:pressed {
                background-color: #D0D0D0;
            }
            QPushButton:disabled {
                background-color: #F5F5F5;
                color: #888;
            }
            QLineEdit, QComboBox {
                background-color: white;
                color: black;
                border: 1px solid #CCC;
                padding: 3px;
                border-radius: 3px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                color: black;
                selection-background-color: #0078D7;
                selection-color: white;
            }
            QProgressBar {
                border: 1px solid #CCC;
                border-radius: 3px;
                text-align: center;
                color: #333;
                background-color: white;
            }
            QProgressBar::chunk {
                background-color: #0078D7;
                border-radius: 3px;
            }
            QMenuBar {
                background-color: #F0F0F0;
                color: black;
            }
            QMenuBar::item:selected {
                background-color: #E0E0E0;
            }
            QMenu {
                background-color: white;
                color: black;
                border: 1px solid #CCC;
            }
            QMenu::item:selected {
                background-color: #0078D7;
                color: white;
            }
            QCheckBox {
                color: black;
            }
            QLabel {
                color: #333;
            }
            QToolBar {
                background-color: #F5F5F5;
                border: none;
                spacing: 3px;
                padding: 2px;
            }
            QStatusBar {
                background-color: #F5F5F5;
                color: #333;
            }
            QScrollBar:vertical {
                background-color: #F5F5F5;
                width: 15px;
                margin: 15px 0 15px 0;
            }
            QScrollBar::handle:vertical {
                background-color: #C0C0C0;
                min-height: 20px;
                border-radius: 7px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #A0A0A0;
            }
            QScrollBar:horizontal {
                background-color: #F5F5F5;
                height: 15px;
                margin: 0 15px 0 15px;
            }
            QScrollBar::handle:horizontal {
                background-color: #C0C0C0;
                min-width: 20px;
                border-radius: 7px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #A0A0A0;
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
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #AAA;
                border-radius: 3px;
                background-color: #F0F0F0;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(
                    spread:pad, x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4CAF50, stop:1 #8BC34A
                );
                border-radius: 3px;
            }
        """)
        self.file_count_label.setText("Сканирование...")
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
        self.file_count_label.setText(message)
    
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
        
        self.file_count_label.setText(f"Файлов: {len(all_files)}")
    
    def on_scan_error(self, error_msg):
        """Ошибка сканирования"""
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        QMessageBox.critical(self, "Ошибка сканирования", f"Не удалось выполнить сканирование:\n{error_msg}")
        self.file_count_label.setText("Ошибка сканирования")
    
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
        """Обновление дерева файлов с расширенным поиском"""
        self.files_tree.clear()
        
        search_criteria = self.advanced_search.get_search_criteria()
        criteria = self.advanced_search.parse_search_criteria(search_criteria)
        
        filtered_files = []
        for file_info in self.all_files:
            # Фильтр избранного
            if self.show_favorites_only and not file_info.get('is_favorite', False):
                continue
            
            # Фильтр по расширению
            if self.current_extension_filter and self.current_extension_filter != "Все расширения":
                file_ext = file_info.get('extension', '')
                if file_ext != self.current_extension_filter:
                    continue
            
            # Проверка всех критериев поиска
            if not self.check_file_against_criteria(file_info, criteria):
                continue
            
            # Скрытие дочерних файлов Blockbench
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
        
        self.file_count_label.setText(f"Файлов: {len(filtered_files)}")
    
    def check_file_against_criteria(self, file_info, criteria):
        """Проверить файл против всех критериев поиска"""
        for criteria_type, criteria_list in criteria.items():
            for criterion in criteria_list:
                if not self.check_single_criterion(file_info, criteria_type, criterion):
                    return False
        return True
    
    def check_single_criterion(self, file_info, criteria_type, criterion):
        """Проверить файл против одного критерия"""
        criterion = criterion.lower().strip()
        
        if criteria_type == 'текст':
            # Поиск по имени или содержимому
            if criterion in file_info['name'].lower():
                return True
            
            # Поиск по содержимому
            content = self.load_file_content(file_info).lower()
            if criterion in content:
                return True
            return False
        
        elif criteria_type == 'размер':
            return self.check_size_criterion(file_info['size'], criterion)
        
        elif criteria_type == 'дата':
            return self.check_date_criterion(file_info['modified'], criterion)
        
        return True
    
    def check_size_criterion(self, size_bytes, criterion):
        """Проверить критерий размера"""
        # Парсим критерий
        criterion = criterion.lower().replace(' ', '')
        
        # Определяем множитель
        multiplier = 1
        if 'kb' in criterion:
            multiplier = 1024
            criterion = criterion.replace('kb', '')
        elif 'mb' in criterion:
            multiplier = 1024 * 1024
            criterion = criterion.replace('mb', '')
        elif 'gb' in criterion:
            multiplier = 1024 * 1024 * 1024
            criterion = criterion.replace('gb', '')
        elif 'b' in criterion:
            criterion = criterion.replace('b', '')
        
        # Парсим оператор и значение
        if '>=' in criterion:
            value = float(criterion.replace('>=', '')) * multiplier
            return size_bytes >= value
        elif '<=' in criterion:
            value = float(criterion.replace('<=', '')) * multiplier
            return size_bytes <= value
        elif '>' in criterion:
            value = float(criterion.replace('>', '')) * multiplier
            return size_bytes > value
        elif '<' in criterion:
            value = float(criterion.replace('<', '')) * multiplier
            return size_bytes < value
        elif '=' in criterion or '-' in criterion:
            if '-' in criterion:
                # Диапазон
                parts = criterion.split('-')
                if len(parts) == 2:
                    min_val = float(parts[0]) * multiplier
                    max_val = float(parts[1]) * multiplier
                    return min_val <= size_bytes <= max_val
            else:
                # Точное значение
                value = float(criterion.replace('=', '')) * multiplier
                tolerance = 0.1 * multiplier  # 10% допуск
                return abs(size_bytes - value) <= tolerance
        
        return True
    
    def check_date_criterion(self, file_date, criterion):
        """Проверить критерий даты"""
        from datetime import datetime, timedelta
        
        criterion = criterion.lower()
        today = datetime.now().date()
        
        # Специальные ключевые слова
        if 'сегодня' in criterion:
            return file_date.date() == today
        elif 'вчера' in criterion:
            yesterday = today - timedelta(days=1)
            return file_date.date() == yesterday
        elif 'неделя' in criterion or 'недели' in criterion:
            week_ago = today - timedelta(days=7)
            return file_date.date() >= week_ago
        elif 'месяц' in criterion or 'месяца' in criterion:
            month_ago = today - timedelta(days=30)
            return file_date.date() >= month_ago
        elif 'год' in criterion:
            year_ago = today - timedelta(days=365)
            return file_date.date() >= year_ago
        
        # Парсим дату
        try:
            if '>=' in criterion:
                date_str = criterion.replace('>=', '').strip()
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return file_date.date() >= target_date
            elif '<=' in criterion:
                date_str = criterion.replace('<=', '').strip()
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return file_date.date() <= target_date
            elif '>' in criterion:
                date_str = criterion.replace('>', '').strip()
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return file_date.date() > target_date
            elif '<' in criterion:
                date_str = criterion.replace('<', '').strip()
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return file_date.date() < target_date
            elif '=' in criterion:
                date_str = criterion.replace('=', '').strip()
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return file_date.date() == target_date
        except ValueError:
            pass
        
        return True
    
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
                        content = f.read(100000)  # Ограничиваем чтение для производительности
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
            self.file_count_label.setText("Показаны только избранные файлы")
        else:
            self.file_count_label.setText(f"Файлов: {len(self.all_files)}")
    
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
            "date_asc": "Дата изменения ↑",
            "date_desc": "Дата изменения ↓",
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
            
            # Удалить
            delete_action = QAction("Удалить", self)
            delete_action.triggered.connect(self.delete_selected_files)
            delete_action.setToolTip("Удалить выбранные файлы")
            menu.addAction(delete_action)
            
            # Переименовать
            rename_action = QAction("Переименовать", self)
            rename_action.triggered.connect(lambda: self.rename_file(item))
            rename_action.setToolTip("Переименовать файл")
            menu.addAction(rename_action)
            
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
            
            # Добавление в виртуальные папки (через контекстное меню вместо DnD)
            add_to_folder_menu = QMenu("Добавить в виртуальную папку", self)
            
            # Создать новую папку
            create_folder_action = QAction("Создать новую папку...", self)
            create_folder_action.triggered.connect(self.create_virtual_folder_from_selection)
            add_to_folder_menu.addAction(create_folder_action)
            
            if self.virtual_folders:
                add_to_folder_menu.addSeparator()
                # Существующие папки
                for folder_name in sorted(self.virtual_folders.keys()):
                    folder_action = QAction(folder_name, self)
                    folder_action.triggered.connect(lambda checked, f=folder_name: self.add_selected_to_virtual_folder(f))
                    add_to_folder_menu.addAction(folder_action)
            
            menu.addMenu(add_to_folder_menu)
        
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
            self.file_count_label.setText(f"Открыта папка: {folder_path}")
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
            
            self.file_count_label.setText(f"Открытие файла: {os.path.basename(file_path)}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{str(e)}")
    
    def open_file_with_dialog_win11(self, file_path):
        """Открыть файл через диалог 'Открыть с помощью' для Windows 10/11"""
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Предупреждение", f"Файл не существует:\n{file_path}")
            return
        
        try:
            if sys.platform == "win32":
                # Для Windows 10/11 используем shell32 для вызова диалога "Открыть с помощью"
                import ctypes
                from ctypes import wintypes
                
                # Загружаем shell32
                shell32 = ctypes.windll.shell32
                
                # Подготовка параметров
                class SHELLEXECUTEINFO(ctypes.Structure):
                    _fields_ = [
                        ('cbSize', wintypes.DWORD),
                        ('fMask', ctypes.c_ulong),
                        ('hwnd', wintypes.HWND),
                        ('lpVerb', wintypes.LPCWSTR),
                        ('lpFile', wintypes.LPCWSTR),
                        ('lpParameters', wintypes.LPCWSTR),
                        ('lpDirectory', wintypes.LPCWSTR),
                        ('nShow', ctypes.c_int),
                        ('hInstApp', wintypes.HINSTANCE),
                        ('lpIDList', ctypes.c_void_p),
                        ('lpClass', wintypes.LPCWSTR),
                        ('hKeyClass', wintypes.HKEY),
                        ('dwHotKey', wintypes.DWORD),
                        ('hIcon', wintypes.HANDLE),
                        ('hProcess', wintypes.HANDLE)
                    ]
                
                # Константы
                SEE_MASK_INVOKEIDLIST = 0x0000000C
                SEE_MASK_NOCLOSEPROCESS = 0x00000040
                SW_SHOW = 5
                
                # Создаем структуру
                sei = SHELLEXECUTEINFO()
                sei.cbSize = ctypes.sizeof(sei)
                sei.fMask = SEE_MASK_INVOKEIDLIST
                sei.hwnd = 0
                sei.lpVerb = "openas"  # "Открыть с помощью"
                sei.lpFile = os.path.normpath(file_path)
                sei.lpParameters = None
                sei.lpDirectory = os.path.dirname(file_path) if os.path.dirname(file_path) else None
                sei.nShow = SW_SHOW
                sei.hInstApp = 0
                sei.lpIDList = None
                sei.lpClass = None
                sei.hKeyClass = 0
                sei.dwHotKey = 0
                sei.hIcon = 0
                sei.hProcess = 0
                
                # Вызываем ShellExecuteExW
                result = shell32.ShellExecuteExW(ctypes.byref(sei))
                
                if not result:
                    # Если не удалось, пробуем стандартный способ
                    os.startfile(os.path.normpath(file_path))
            elif sys.platform == "darwin":
                # Для macOS
                subprocess.run(["open", "-a", "Finder", file_path])
            else:
                # Для Linux
                subprocess.run(["xdg-open", file_path])
            
            self.file_count_label.setText(f"Открытие файла с помощью: {os.path.basename(file_path)}")
        except Exception as e:
            # В случае ошибки, пробуем стандартный способ
            try:
                self.open_file_with_default(file_path)
            except:
                QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{str(e)}")
    
    def delete_selected_files(self):
        """Удалить выбранные файлы с историей для отмены"""
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            return
        
        reply = QMessageBox.question(self, "Подтверждение", 
                                    f"Удалить {len(selected_items)} выбранных файлов?",
                                    QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            files_to_delete = []
            
            for item in selected_items:
                item_type = item.text(4)
                if item_type == 'file':
                    file_path = item.text(3)
                    
                    if os.path.exists(file_path):
                        try:
                            # Читаем содержимое файла для возможного восстановления
                            with open(file_path, 'rb') as f:
                                content = f.read()
                            
                            # Создаем временный файл с содержимым для восстановления
                            temp_dir = self.settings.get("temp_folder", tempfile.gettempdir())
                            os.makedirs(temp_dir, exist_ok=True)
                            temp_file = tempfile.NamedTemporaryFile(
                                delete=False, 
                                dir=temp_dir,
                                prefix='sofila_undo_',
                                suffix='.tmp'
                            )
                            temp_file.write(content)
                            temp_file.close()
                            
                            files_to_delete.append({
                                'path': file_path,
                                'content': content,
                                'temp_path': temp_file.name,
                                'name': os.path.basename(file_path),
                                'size': len(content)
                            })
                        except Exception as e:
                            QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать файл {file_path}: {str(e)}")
                            continue
            
            if files_to_delete:
                # Добавляем в историю действий
                self.add_to_action_history('file_delete', {
                    'files': files_to_delete
                })
                
                # Удаляем файлы
                deleted_count = 0
                for file_info in files_to_delete:
                    try:
                        os.remove(file_info['path'])
                        deleted_count += 1
                    except Exception as e:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось удалить файл {file_info['path']}: {str(e)}")
                
                # Обновляем списки
                for file_info in files_to_delete:
                    self.all_files = [f for f in self.all_files if f['path'] != file_info['path']]
                
                self.refresh_files_tree()
                self.file_count_label.setText(f"Удалено файлов: {deleted_count}")
    
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
                    'new_path': new_path,
                    'old_name': old_name,
                    'new_name': new_name
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
                self.file_count_label.setText(f"Файл переименован: '{old_name}' -> '{new_name}'")
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
            message = f"Файл убран из избранного"
        else:
            favorites.append(file_path)
            message = f"Файл добавлен в избранное"
        
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
        self.file_count_label.setText(message)
    
    def toggle_virtual_folder_favorite(self, folder_name):
        """Добавить/убрать виртуальную папку из избранного"""
        favorites = self.settings.get("favorites", [])
        
        was_favorite = folder_name in favorites
        
        if folder_name in favorites:
            favorites.remove(folder_name)
            message = f"Папка '{folder_name}' убрана из избранного"
        else:
            favorites.append(folder_name)
            message = f"Папка '{folder_name}' добавлена в избранное"
        
        # Добавляем в историю действий
        self.add_to_action_history('virtual_folder_favorite', {
            'folder_name': folder_name,
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
            
            # Добавляем в историю действий
            self.add_to_action_history('virtual_folder_rename', {
                'old_name': folder_name,
                'new_name': new_name,
                'files': old_files
            })
            
            self.save_settings()
            self.refresh_files_tree()
            self.file_count_label.setText(f"Папка переименована: '{folder_name}' -> '{new_name}'")
    
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
                
                # Добавляем в историю действий
                self.add_to_action_history('virtual_folder_delete', {
                    'folder_name': folder_name,
                    'files': old_files
                })
                
                del self.virtual_folders[folder_name]
                
                self.save_settings()
                self.refresh_files_tree()
                self.file_count_label.setText(f"Папка '{folder_name}' удалена")
    
    def create_virtual_folder_from_selection(self):
        """Создать виртуальную папку из выделенных файлов"""
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Предупреждение", "Выберите файлы для объединения в папку")
            return
        
        # Собираем информацию о файлах
        files_to_add = []
        for item in selected_items:
            item_type = item.text(4)
            if item_type == 'file':
                file_path = item.text(3)
                
                # Находим полную информацию о файле
                file_info = None
                for f in self.all_files:
                    if f['path'] == file_path:
                        file_info = f.copy()
                        break
                
                if file_info:
                    files_to_add.append(file_info)
        
        if not files_to_add:
            QMessageBox.warning(self, "Предупреждение", "Выберите файлы для объединения в папку")
            return
        
        # Проверяем на дубликаты
        file_names = [f['name'] for f in files_to_add]
        duplicates = [name for name in file_names if file_names.count(name) > 1]
        if duplicates:
            reply = QMessageBox.question(self, "Предупреждение", 
                                        f"Некоторые файлы имеют одинаковые имена:\n{', '.join(set(duplicates))}\n\nПродолжить?",
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
        
        folder_name, ok = QInputDialog.getText(self, "Создать папку", "Введите название папки:")
        if ok and folder_name:
            if folder_name in self.virtual_folders:
                reply = QMessageBox.question(self, "Предупреждение", 
                                            f"Папка с именем '{folder_name}' уже существует.\nЗаменить?",
                                            QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.No:
                    return
            
            # Добавляем в историю действий
            old_files = self.virtual_folders.get(folder_name, []) if folder_name in self.virtual_folders else []
            self.add_to_action_history('virtual_folder_create', {
                'folder_name': folder_name,
                'files': files_to_add.copy(),
                'old_files': old_files
            })
            
            self.virtual_folders[folder_name] = files_to_add
            self.save_settings()
            self.refresh_files_tree()
            self.file_count_label.setText(f"Создана новая папка '{folder_name}' с {len(files_to_add)} файлами")
    
    def add_selected_to_virtual_folder(self, folder_name):
        """Добавить выбранные файлы в существующую виртуальную папку"""
        selected_items = self.files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Предупреждение", "Выберите файлы для добавления в папку")
            return
        
        # Собираем информацию о файлах
        files_to_add = []
        for item in selected_items:
            item_type = item.text(4)
            if item_type == 'file':
                file_path = item.text(3)
                
                # Находим полную информацию о файле
                file_info = None
                for f in self.all_files:
                    if f['path'] == file_path:
                        file_info = f.copy()
                        break
                
                if file_info:
                    files_to_add.append(file_info)
        
        if not files_to_add:
            return
        
        # Проверяем, нет ли уже таких файлов в папке
        existing_files = []
        if folder_name in self.virtual_folders:
            for f in self.virtual_folders[folder_name]:
                if isinstance(f, dict) and 'path' in f:
                    existing_files.append(f['path'])
                else:
                    existing_files.append(f)
        
        # Проверяем на дубликаты в добавляемых файлах
        file_names = [f['name'] for f in files_to_add]
        duplicates = [name for name in file_names if file_names.count(name) > 1]
        if duplicates:
            reply = QMessageBox.question(self, "Предупреждение", 
                                        f"Некоторые добавляемые файлы имеют одинаковые имена:\n{', '.join(set(duplicates))}\n\nПродолжить?",
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
        
        # Проверяем на дубликаты с существующими файлами
        duplicate_with_existing = []
        for file_info in files_to_add:
            if file_info['path'] in existing_files:
                duplicate_with_existing.append(file_info['name'])
        
        if duplicate_with_existing:
            reply = QMessageBox.question(self, "Предупреждение", 
                                        f"Некоторые файлы уже есть в папке:\n{', '.join(duplicate_with_existing)}\n\nПропустить их?",
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
        
        # Добавляем файлы в папку
        old_files = self.virtual_folders.get(folder_name, []).copy()
        
        added_count = 0
        if folder_name not in self.virtual_folders:
            self.virtual_folders[folder_name] = []
        
        for file_info in files_to_add:
            if file_info['path'] not in existing_files:
                self.virtual_folders[folder_name].append(file_info)
                added_count += 1
        
        # Добавляем в историю действий
        self.add_to_action_history('virtual_folder_add_files', {
            'folder_name': folder_name,
            'files_added': files_to_add.copy(),
            'old_files': old_files
        })
        
        self.save_settings()
        self.refresh_files_tree()
        self.file_count_label.setText(f"Добавлено {added_count} файлов в папку '{folder_name}'")
    
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
            
            try:
                if action['type'] == 'file_rename':
                    old_path = action['data']['old_path']
                    new_path = action['data']['new_path']
                    
                    if os.path.exists(new_path) and not os.path.exists(old_path):
                        os.rename(new_path, old_path)
                        
                        # Обновляем информацию
                        for file_info in self.all_files:
                            if file_info['path'] == new_path:
                                file_info['path'] = old_path
                                file_info['name'] = action['data']['old_name']
                                break
                        
                        # Обновляем виртуальные папки
                        for folder_name, files in self.virtual_folders.items():
                            for i, file_info in enumerate(files):
                                if isinstance(file_info, dict) and file_info.get('path') == new_path:
                                    file_info['path'] = old_path
                                    file_info['name'] = action['data']['old_name']
                                elif file_info == new_path:
                                    files[i] = old_path
                        
                        # Обновляем избранное
                        if new_path in self.settings.get("favorites", []):
                            favorites = self.settings["favorites"]
                            favorites.remove(new_path)
                            favorites.append(old_path)
                            self.settings["favorites"] = favorites
                        
                        self.file_count_label.setText(f"Отменено переименование: '{action['data']['new_name']}' -> '{action['data']['old_name']}'")
                
                elif action['type'] == 'file_delete':
                    restored_count = 0
                    for file_info in action['data']['files']:
                        try:
                            if os.path.exists(file_info['temp_path']):
                                shutil.copy(file_info['temp_path'], file_info['path'])
                                os.remove(file_info['temp_path'])
                            else:
                                with open(file_info['path'], 'wb') as f:
                                    f.write(file_info['content'])
                            
                            # Восстанавливаем информацию о файле
                            restored_file = {
                                'name': file_info['name'],
                                'path': file_info['path'],
                                'relative_path': file_info['path'],
                                'size': file_info['size'],
                                'modified': datetime.now(),
                                'is_favorite': file_info['path'] in self.settings.get("favorites", []),
                                'extension': os.path.splitext(file_info['name'])[1].lower() or "(без расширения)",
                                'has_parent': False
                            }
                            self.all_files.append(restored_file)
                            restored_count += 1
                        except Exception as e:
                            print(f"Ошибка восстановления файла: {e}")
                    
                    self.file_count_label.setText(f"Отменено удаление: восстановлено {restored_count} файлов")
                
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
                    
                    # Обновляем состояние файлов
                    for file_info in self.all_files:
                        if file_info['path'] in file_paths:
                            file_info['is_favorite'] = file_info['path'] in favorites
                    
                    self.file_count_label.setText("Отменено изменение избранного")
                
                elif action['type'] == 'virtual_folder_create':
                    folder_name = action['data']['folder_name']
                    if folder_name in self.virtual_folders:
                        # Если были старые файлы, восстанавливаем их
                        if 'old_files' in action['data'] and action['data']['old_files']:
                            self.virtual_folders[folder_name] = action['data']['old_files']
                        else:
                            del self.virtual_folders[folder_name]
                        self.file_count_label.setText(f"Отменено создание папки: {folder_name}")
                
                elif action['type'] == 'virtual_folder_delete':
                    folder_name = action['data']['folder_name']
                    files = action['data']['files']
                    self.virtual_folders[folder_name] = files
                    self.file_count_label.setText(f"Отменено удаление папки: {folder_name}")
                
                elif action['type'] == 'virtual_folder_rename':
                    old_name = action['data']['old_name']
                    new_name = action['data']['new_name']
                    
                    if new_name in self.virtual_folders:
                        self.virtual_folders[old_name] = self.virtual_folders.pop(new_name)
                        
                        # Восстанавливаем состояние раскрытия
                        if new_name in self.virtual_folders_expanded:
                            self.virtual_folders_expanded[old_name] = self.virtual_folders_expanded.pop(new_name)
                        
                        # Восстанавливаем избранное
                        if new_name in self.settings.get("favorites", []):
                            favorites = self.settings["favorites"]
                            favorites.remove(new_name)
                            favorites.append(old_name)
                            self.settings["favorites"] = favorites
                        
                        self.file_count_label.setText(f"Отменено переименование папки: '{new_name}' -> '{old_name}'")
                
                elif action['type'] == 'virtual_folder_add_files':
                    folder_name = action['data']['folder_name']
                    old_files = action['data']['old_files']
                    self.virtual_folders[folder_name] = old_files
                    self.file_count_label.setText(f"Отменено добавление файлов в папку '{folder_name}'")
                
                self.save_settings()
                self.refresh_files_tree()
                
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось отменить действие: {str(e)}")
            
            self.current_action_index -= 1
            self.is_undo_redo_in_progress = False
            self.update_undo_redo_buttons()
    
    def redo_action(self):
        """Повторить отмененное действие"""
        if self.current_action_index < len(self.action_history) - 1:
            self.is_undo_redo_in_progress = True
            self.current_action_index += 1
            action = self.action_history[self.current_action_index]
            
            try:
                if action['type'] == 'file_rename':
                    old_path = action['data']['old_path']
                    new_path = action['data']['new_path']
                    
                    if os.path.exists(old_path) and not os.path.exists(new_path):
                        os.rename(old_path, new_path)
                        
                        # Обновляем информацию
                        for file_info in self.all_files:
                            if file_info['path'] == old_path:
                                file_info['path'] = new_path
                                file_info['name'] = action['data']['new_name']
                                break
                        
                        # Обновляем виртуальные папки
                        for folder_name, files in self.virtual_folders.items():
                            for i, file_info in enumerate(files):
                                if isinstance(file_info, dict) and file_info.get('path') == old_path:
                                    file_info['path'] = new_path
                                    file_info['name'] = action['data']['new_name']
                                elif file_info == old_path:
                                    files[i] = new_path
                        
                        # Обновляем избранное
                        if old_path in self.settings.get("favorites", []):
                            favorites = self.settings["favorites"]
                            favorites.remove(old_path)
                            favorites.append(new_path)
                            self.settings["favorites"] = favorites
                        
                        self.file_count_label.setText(f"Повторено переименование: '{action['data']['old_name']}' -> '{action['data']['new_name']}'")
                
                elif action['type'] == 'file_delete':
                    deleted_count = 0
                    for file_info in action['data']['files']:
                        try:
                            if os.path.exists(file_info['path']):
                                os.remove(file_info['path'])
                                self.all_files = [f for f in self.all_files if f['path'] != file_info['path']]
                                deleted_count += 1
                        except Exception as e:
                            print(f"Ошибка удаления файла: {e}")
                    
                    self.file_count_label.setText(f"Повторено удаление: удалено {deleted_count} файлов")
                
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
                    
                    # Обновляем состояние файлов
                    for file_info in self.all_files:
                        if file_info['path'] in file_paths:
                            file_info['is_favorite'] = file_info['path'] in favorites
                    
                    self.file_count_label.setText("Повторено изменение избранного")
                
                elif action['type'] == 'virtual_folder_create':
                    folder_name = action['data']['folder_name']
                    files = action['data']['files']
                    self.virtual_folders[folder_name] = files
                    self.file_count_label.setText(f"Повторено создание папки: {folder_name}")
                
                elif action['type'] == 'virtual_folder_delete':
                    folder_name = action['data']['folder_name']
                    if folder_name in self.virtual_folders:
                        del self.virtual_folders[folder_name]
                        self.file_count_label.setText(f"Повторено удаление папки: {folder_name}")
                
                elif action['type'] == 'virtual_folder_rename':
                    old_name = action['data']['old_name']
                    new_name = action['data']['new_name']
                    
                    if old_name in self.virtual_folders:
                        self.virtual_folders[new_name] = self.virtual_folders.pop(old_name)
                        
                        # Восстанавливаем состояние раскрытия
                        if old_name in self.virtual_folders_expanded:
                            self.virtual_folders_expanded[new_name] = self.virtual_folders_expanded.pop(old_name)
                        
                        # Восстанавливаем избранное
                        if old_name in self.settings.get("favorites", []):
                            favorites = self.settings["favorites"]
                            favorites.remove(old_name)
                            favorites.append(new_name)
                            self.settings["favorites"] = favorites
                        
                        self.file_count_label.setText(f"Повторено переименование папки: '{old_name}' -> '{new_name}'")
                
                elif action['type'] == 'virtual_folder_add_files':
                    folder_name = action['data']['folder_name']
                    files_added = action['data']['files_added']
                    
                    if folder_name not in self.virtual_folders:
                        self.virtual_folders[folder_name] = []
                    
                    for file_info in files_added:
                        self.virtual_folders[folder_name].append(file_info)
                    
                    self.file_count_label.setText(f"Повторено добавление файлов в папку '{folder_name}'")
                
                self.save_settings()
                self.refresh_files_tree()
                
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось повторить действие: {str(e)}")
            
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
Enter — Открыть файл
Ctrl+ЛКМ — Добавить/убрать из выделения
Shift+ЛКМ — Выделить диапазон
ЛКМ с движением — Выделить область мышью

Поиск:
Используйте разделитель "; " для нескольких критериев:
- По имени: 'report.txt'
- По размеру: '>1MB', '<100KB', '500B-2MB'
- По дате: '>2023-01-01', 'сегодня', 'неделя'

Пример: 'report.txt; >1MB; >2023-01-01'"""
        
        QMessageBox.information(self, "Сочетания клавиш", hotkeys_text)
    
    def show_about(self):
        """Показать информацию о программе"""
        about_text = """Sofil - Сканер папок
Версия: 6.7
Создатель: Akami_bl
Обратная связь: akami.bl@gmail.com

Основное:
📁 Сканирует папки и архивы (ZIP)
🗂️ Создает виртуальные папки
🔍 Расширенный поиск по имени, содержимому, размеру и дате
⭐ Добавляет файлы в избранное

Новые возможности:
🎯 Выделение файлов мышью с зажатой ЛКМ
🔍 Поиск по нескольким критериям одновременно
↩️ Полная поддержка отмены/повтора действий
🎨 Смягченные светлая и тёмная темы
📊 Улучшенный прогресс-бар

Фишки:
📊 Показывает дубликаты файлов
🔄 Отмена действий и повтор
⚠️ Предупреждения при дубликатах"""
        
        QMessageBox.information(self, "О программе", about_text)
    
    def closeEvent(self, event):
        """Обработка закрытия окна"""
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.stop()
            self.scan_thread.wait()
        
        self.save_settings()
        
        # Очищаем временные файлы отмены
        temp_dir = self.settings.get("temp_folder", tempfile.gettempdir())
        if os.path.exists(temp_dir):
            for file in os.listdir(temp_dir):
                if file.startswith('sofila_undo_') and file.endswith('.tmp'):
                    try:
                        os.remove(os.path.join(temp_dir, file))
                    except:
                        pass
        
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