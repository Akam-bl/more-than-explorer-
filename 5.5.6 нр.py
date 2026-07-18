[file name]: 5.5.py
[file content begin]
import os
import json
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
from collections import defaultdict, deque
import zipfile
import tempfile
import shutil
import threading
import math
import sys
from datetime import datetime
import ctypes

class FolderScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Sofil")
        self.root.geometry("1600x800")
        
        # Настройки по умолчанию
        self.settings = {
            "main_folder": "",
            "data_folder": "",
            "temp_folder": "",
            "scan_history": [],
            "unrar_path": "",
            "sort_mode": "name_asc",
            "archive_extensions": [".zip", ".rar", ".7z"],
            "hide_duplicates": False,
            "favorites": [],
            "last_search": "",
            "last_extension": "",
            "hide_blockbench_children": True,
            "virtual_folders": {},
            "search_mode": "name"  # "name" или "content"
        }
        
        # Переменные для хранения данных
        self.virtual_folders = self.settings.get("virtual_folders", {})
        self.available_extensions = set()
        self.duplicate_files = defaultdict(list)
        self.all_files = []
        self.extension_data = defaultdict(list)
        self.all_folders = set()
        self.file_content_cache = {}  # Кэш содержимого файлов для поиска
        
        # Переменные для перетаскивания
        self.drag_data = {"item": None, "x": 0, "y": 0}
        self.drag_start_item = None
        self.drag_start_index = None
        self.is_dragging = False
        
        # Переменная для фильтра избранного
        self.show_favorites_only = False
        
        # Текущий фильтр расширения
        self.current_extension_filter = ""
        
        # История действий для отмены/повтора
        self.action_history = deque(maxlen=50)
        self.current_action_index = -1
        self.is_undo_redo_in_progress = False
        
        # Загружаем настройки
        self.load_settings()
        
        # Создание интерфейса
        self.create_widgets()
        self.create_menu()
        
        # Настройка горячих клавиш
        self.setup_hotkeys()
        
        # Проверка настроек
        self.check_settings()
        
        # Отложенная инициализация привязок дерева
        self.root.after(100, self.initialize_tree_bindings)
    
    def initialize_tree_bindings(self):
        """Инициализировать привязки событий дерева после полной загрузки"""
        if hasattr(self, 'tree') and self.tree.winfo_exists():
            self.tree.bind('<<TreeviewSelect>>', self.on_tree_select)
            self.tree.bind('<Button-1>', self.on_tree_click)
    
    def on_tree_click(self, event):
        """Обработка клика по дереву для сброса выделения"""
        item = self.tree.identify_row(event.y)
        region = self.tree.identify_region(event.x, event.y)
        
        # Сбрасываем выделение при клике на пустое место
        if not item and region == "nothing":
            self.tree.selection_remove(self.tree.selection())
            self.is_dragging = False
    
    def setup_hotkeys(self):
        """Настройка горячих клавиш"""
        # Ctrl+O - открыть папку
        self.root.bind('<Control-o>', lambda e: self.browse_folder())
        # Ctrl+Shift+O - открыть архив
        self.root.bind('<Control-Shift-O>', lambda e: self.browse_archive())
        # Ctrl+S - сканировать
        self.root.bind('<Control-s>', lambda e: self.scan_selected())
        # Delete - удалить выделенное
        self.root.bind('<Delete>', lambda e: self.delete_selected())
        # Ctrl+F - добавить в избранное
        self.root.bind('<Control-f>', lambda e: self.toggle_favorite())
        # Ctrl+B - переключить скрытие дочерних файлов Blockbench
        self.root.bind('<Control-b>', lambda e: self.toggle_hide_blockbench_children())
        # Ctrl+Z - отменить действие
        self.root.bind('<Control-z>', lambda e: self.undo_action())
        # Ctrl+Y - повторить действие
        self.root.bind('<Control-y>', lambda e: self.redo_action())
        # Ctrl+J - создать виртуальную папку из выделенного
        self.root.bind('<Control-j>', lambda e: self.create_virtual_folder_from_selection())
        # Ctrl+O - переключить виртуальные папки
        self.root.bind('<Control-o>', lambda e: self.toggle_virtual_folders())
    
    def add_to_action_history(self, action_type, data):
        """Добавить действие в историю"""
        if self.is_undo_redo_in_progress:
            return
            
        # Обрезаем историю после текущей позиции
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
                        self.refresh_tree()
                        self.status_var.set(f"Отменено переименование: {os.path.basename(new_path)} -> {os.path.basename(old_path)}")
                    except Exception as e:
                        messagebox.showerror("Ошибка", f"Не удалось отменить переименование: {str(e)}")
            
            elif action['type'] == 'virtual_folder_create':
                folder_name = action['data']['folder_name']
                if folder_name in self.virtual_folders:
                    del self.virtual_folders[folder_name]
                    self.save_settings()
                    self.refresh_tree()
                    self.status_var.set(f"Отменено создание папки: {folder_name}")
            
            elif action['type'] == 'virtual_folder_delete':
                folder_name = action['data']['folder_name']
                files = action['data']['files']
                self.virtual_folders[folder_name] = files
                self.save_settings()
                self.refresh_tree()
                self.status_var.set(f"Отменено удаление папки: {folder_name}")
            
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
                self.refresh_tree()
                self.status_var.set("Отменено изменение избранного")
            
            elif action['type'] == 'file_move':
                self.undo_move_action(action['data'])
            
            elif action['type'] == 'file_delete':
                self.undo_delete_action(action['data'])
            
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
                        self.refresh_tree()
                        self.status_var.set(f"Повторено переименование: {os.path.basename(old_path)} -> {os.path.basename(new_path)}")
                    except Exception as e:
                        messagebox.showerror("Ошибка", f"Не удалось повторить переименование: {str(e)}")
            
            elif action['type'] == 'virtual_folder_create':
                folder_name = action['data']['folder_name']
                files = action['data']['files']
                self.virtual_folders[folder_name] = files
                self.save_settings()
                self.refresh_tree()
                self.status_var.set(f"Повторено создание папки: {folder_name}")
            
            elif action['type'] == 'virtual_folder_delete':
                folder_name = action['data']['folder_name']
                if folder_name in self.virtual_folders:
                    del self.virtual_folders[folder_name]
                    self.save_settings()
                    self.refresh_tree()
                    self.status_var.set(f"Повторено удаление папки: {folder_name}")
            
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
                self.refresh_tree()
                self.status_var.set("Повторено изменение избранного")
            
            elif action['type'] == 'file_move':
                self.redo_move_action(action['data'])
            
            elif action['type'] == 'file_delete':
                self.redo_delete_action(action['data'])
            
            self.is_undo_redo_in_progress = False
            self.update_undo_redo_buttons()
    
    def update_undo_redo_buttons(self):
        """Обновить состояние кнопок отмены/повтора"""
        has_undo = self.current_action_index >= 0
        has_redo = self.current_action_index < len(self.action_history) - 1
        
        if hasattr(self, 'undo_btn'):
            self.undo_btn.config(state=tk.NORMAL if has_undo else tk.DISABLED)
        if hasattr(self, 'redo_btn'):
            self.redo_btn.config(state=tk.NORMAL if has_redo else tk.DISABLED)
    
    def delete_selected(self):
        """Удалить выбранные элементы"""
        if not hasattr(self, 'tree') or not self.tree.winfo_exists():
            return
            
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        if messagebox.askyesno("Подтверждение", "Удалить выбранные элементы?"):
            for item in selected_items:
                self.tree.delete(item)
    
    def get_settings_path(self):
        """Получить путь к файлу настроек"""
        home_settings = os.path.join(os.path.expanduser("~"), "folder_scanner_settings.json")
        
        if os.path.exists(home_settings):
            return home_settings
        
        data_folder = self.settings.get("data_folder")
        if data_folder and os.path.exists(data_folder):
            return os.path.join(data_folder, "folder_scanner_settings.json")
        else:
            return home_settings
    
    def load_settings(self):
        """Загрузка настроек из файла"""
        try:
            settings_path = self.get_settings_path()
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                    current_data_folder = self.settings.get("data_folder", "")
                    self.settings.update(loaded_settings)
                    if current_data_folder:
                        self.settings["data_folder"] = current_data_folder
                    
                    if "virtual_folders" in loaded_settings:
                        self.virtual_folders = loaded_settings["virtual_folders"]
                    
                    if "last_search" in loaded_settings:
                        self.search_var.set(loaded_settings["last_search"])
                    
                    if "last_extension" in loaded_settings:
                        self.current_extension_filter = loaded_settings["last_extension"]
                    
                    if "scan_history" in loaded_settings:
                        self.settings["scan_history"] = loaded_settings["scan_history"]
                    
                    if "favorites" in loaded_settings:
                        self.settings["favorites"] = loaded_settings["favorites"]
                    
                    if "search_mode" in loaded_settings:
                        self.settings["search_mode"] = loaded_settings["search_mode"]
                    else:
                        self.settings["search_mode"] = "name"
                        
        except Exception as e:
            print(f"Не удалось загрузить настройки: {str(e)}")
    
    def save_settings(self):
        """Сохранение настроек в файл"""
        try:
            settings_path = self.get_settings_path()
            os.makedirs(os.path.dirname(settings_path), exist_ok=True)
            
            self.settings["last_search"] = self.search_var.get()
            self.settings["last_extension"] = self.current_extension_filter
            self.settings["virtual_folders"] = self.virtual_folders
            
            current_folder = self.folder_var.get()
            if current_folder and os.path.exists(current_folder):
                self.settings["main_folder"] = current_folder
            
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
                
            data_folder = self.settings.get("data_folder")
            if data_folder and os.path.exists(data_folder):
                data_settings_path = os.path.join(data_folder, "folder_scanner_settings.json")
                with open(data_settings_path, 'w', encoding='utf-8') as f:
                    json.dump(self.settings, f, indent=2, ensure_ascii=False)
                    
        except Exception as e:
            print(f"Ошибка сохранения настроек: {str(e)}")
    
    def add_to_scan_history(self, folder_path):
        """Добавить папку в истории сканирования"""
        if not folder_path:
            return
            
        scan_history = self.settings.get("scan_history", [])
        
        if folder_path in scan_history:
            scan_history.remove(folder_path)
        
        scan_history.insert(0, folder_path)
        scan_history = scan_history[:10]
        
        self.settings["scan_history"] = scan_history
        self.save_settings()
        self.update_folder_history()
    
    def create_widgets(self):
        """Создание виджетов интерфейса"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Панель инструментов
        toolbar = ttk.Frame(main_frame)
        toolbar.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(toolbar, text="Папка:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.folder_var = tk.StringVar()
        self.folder_combo = ttk.Combobox(toolbar, textvariable=self.folder_var, width=50)
        self.folder_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.folder_combo.bind('<<ComboboxSelected>>', self.on_folder_selected)
        
        self.browse_btn = ttk.Button(toolbar, text="Обзор папки...", command=self.browse_folder)
        self.browse_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.browse_archive_btn = ttk.Button(toolbar, text="Обзор архива...", command=self.browse_archive)
        self.browse_archive_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.undo_btn = ttk.Button(toolbar, text="↶", command=self.undo_action, width=3, state=tk.DISABLED)
        self.undo_btn.pack(side=tk.LEFT, padx=(10, 5))
        
        self.redo_btn = ttk.Button(toolbar, text="↷", command=self.redo_action, width=3, state=tk.DISABLED)
        self.redo_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Label(toolbar, text="Поиск:").pack(side=tk.LEFT, padx=(10, 5))
        
        # Фрейм для поиска с кнопкой переключения режима
        search_frame = ttk.Frame(toolbar)
        search_frame.pack(side=tk.LEFT, padx=(0, 10))
        
        self.search_var = tk.StringVar(value=self.settings.get("last_search", ""))
        self.search_entry = tk.Text(search_frame, height=1, width=30, wrap=tk.WORD)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Вставляем начальный текст если есть
        initial_text = self.settings.get("last_search", "")
        if initial_text:
            self.search_entry.insert("1.0", initial_text)
        
        self.search_entry.bind('<KeyRelease>', self.on_search_changed)
        
        # Кнопка переключения режима поиска
        self.search_mode_var = tk.StringVar(value=self.settings.get("search_mode", "name"))
        self.search_mode_btn = ttk.Button(
            search_frame, 
            text="Имя", 
            width=5,
            command=self.toggle_search_mode
        )
        self.search_mode_btn.pack(side=tk.LEFT, padx=(5, 0))
        self.update_search_mode_button()
        
        self.sort_btn = ttk.Button(toolbar, text=self.get_sort_button_text(), command=self.toggle_sorting)
        self.sort_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.hide_duplicates_var = tk.BooleanVar(value=self.settings.get("hide_duplicates", False))
        self.hide_duplicates_btn = ttk.Checkbutton(toolbar, text="Группировать дубликаты", 
                                                  variable=self.hide_duplicates_var,
                                                  command=self.on_hide_duplicates_changed)
        self.hide_duplicates_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.favorites_btn = ttk.Button(toolbar, text="⭐", command=self.toggle_favorites_filter, width=3)
        self.favorites_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.scan_btn = ttk.Button(toolbar, text="Сканировать", command=self.scan_selected)
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.progress = ttk.Progressbar(toolbar, mode='indeterminate')
        self.progress.pack(side=tk.RIGHT, padx=(10, 0))
        
        # Панель с деревьями
        paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Левая панель - расширения
        left_frame = ttk.Frame(paned_window)
        paned_window.add(left_frame, weight=1)
        
        extension_frame = ttk.LabelFrame(left_frame, text="Расширения файлов", padding="5")
        extension_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        
        self.extension_tree = ttk.Treeview(extension_frame, columns=("count",), show="tree headings", height=25)
        self.extension_tree.heading("#0", text="Расширение")
        self.extension_tree.heading("count", text="Файлов")
        self.extension_tree.column("count", width=80, anchor=tk.CENTER)
        
        extension_scroll = ttk.Scrollbar(extension_frame, orient=tk.VERTICAL, command=self.extension_tree.yview)
        self.extension_tree.configure(yscrollcommand=extension_scroll.set)
        
        self.extension_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        extension_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # Правая панель - файлы
        right_frame = ttk.Frame(paned_window)
        paned_window.add(right_frame, weight=2)
        
        tree_frame = ttk.Frame(right_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        y_scrollbar = ttk.Scrollbar(tree_frame)
        y_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        x_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        x_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.tree = ttk.Treeview(
            tree_frame, 
            yscrollcommand=y_scrollbar.set,
            xscrollcommand=x_scrollbar.set,
            columns=('full_path', 'archive_path', 'item_type', 'size', 'modified', 'is_favorite'), 
            displaycolumns=('size', 'modified'),
            height=25
        )
        
        self.tree.heading('#0', text='Имя')
        self.tree.heading('size', text='Размер')
        self.tree.heading('modified', text='Изменен')
        self.tree.column('size', width=100, anchor=tk.E)
        self.tree.column('modified', width=120)
        
        self.tree.pack(fill=tk.BOTH, expand=True)
        
        y_scrollbar.config(command=self.tree.yview)
        x_scrollbar.config(command=self.tree.xview)
        
        self.tree.bind('<Double-1>', self.on_tree_double_click)
        
        # Привязки для выделения через зажатие ЛКМ
        self.tree.bind('<ButtonPress-1>', self.on_drag_start)
        self.tree.bind('<B1-Motion>', self.on_drag_motion)
        self.tree.bind('<ButtonRelease-1>', self.on_drag_release)
        self.tree.bind('<Shift-Button-1>', self.on_shift_click)
        
        self.tree_menu = None
        self.tree.bind("<Button-3>", self.show_tree_context_menu)
        
        self.extension_tree.bind('<<TreeviewSelect>>', self.on_extension_select)
        
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)
        extension_frame.columnconfigure(0, weight=1)
        extension_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        
        self.status_var = tk.StringVar()
        self.status_var.set("Готов к работе")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, pady=(10, 0))
        
        self.update_folder_history()
        
        if self.settings.get("main_folder") and os.path.exists(self.settings["main_folder"]):
            self.folder_var.set(self.settings["main_folder"])
    
    def toggle_search_mode(self):
        """Переключить режим поиска между именем и содержимым"""
        current_mode = self.settings.get("search_mode", "name")
        new_mode = "content" if current_mode == "name" else "name"
        self.settings["search_mode"] = new_mode
        self.save_settings()
        self.update_search_mode_button()
        self.refresh_tree()
    
    def update_search_mode_button(self):
        """Обновить текст кнопки режима поиска"""
        current_mode = self.settings.get("search_mode", "name")
        if current_mode == "name":
            self.search_mode_btn.config(text="Имя")
            self.search_entry.config(height=1)
        else:
            self.search_mode_btn.config(text="Текст")
            # Автоматически настраиваем высоту в зависимости от содержимого
            self.adjust_search_height()
    
    def adjust_search_height(self):
        """Автоматически настроить высоту поля поиска в зависимости от содержимого"""
        content = self.search_entry.get("1.0", tk.END).strip()
        if not content:
            self.search_entry.config(height=1)
            return
        
        # Подсчитываем количество строк в тексте
        lines = content.split('\n')
        line_count = len(lines)
        
        # Ограничиваем максимальную высоту
        max_height = 10
        new_height = min(line_count, max_height)
        
        # Устанавливаем новую высоту
        self.search_entry.config(height=new_height)
    
    def on_search_changed(self, event):
        """Обработка изменения поискового запроса"""
        # Сохраняем текст из Text виджета в переменную
        search_text = self.search_entry.get("1.0", tk.END).strip()
        self.search_var.set(search_text)
        
        # Автоматически настраиваем высоту для режима поиска по содержимому
        if self.settings.get("search_mode") == "content":
            self.adjust_search_height()
        
        self.refresh_tree()
    
    def get_search_query(self):
        """Получить поисковый запрос из виджета"""
        return self.search_entry.get("1.0", tk.END).strip()
    
    def on_hide_duplicates_changed(self):
        """Обработка изменения настройки группировки дубликатов"""
        self.settings["hide_duplicates"] = self.hide_duplicates_var.get()
        self.save_settings()
        self.refresh_tree()
    
    def on_hide_bb_children_changed(self):
        """Обработка изменения настройки скрытия дочерних файлов Blockbench"""
        self.settings["hide_blockbench_children"] = self.hide_bb_children_var.get()
        self.save_settings()
        self.refresh_tree()
    
    def on_folder_selected(self, event):
        """Обработка выбора папки из истории"""
        selected_folder = self.folder_var.get()
        if selected_folder and os.path.exists(selected_folder):
            self.folder_var.set(selected_folder)
            self.scan_selected()
    
    def show_tree_context_menu(self, event):
        """Показать контекстное меню для дерева файлов"""
        item = self.tree.identify_row(event.y)
        if item:
            # Сохраняем текущее выделение при ПКМ
            current_selection = self.tree.selection()
            if item not in current_selection:
                self.tree.selection_set(item)
            
            self.tree_menu = tk.Menu(self.tree, tearoff=0)
            item_values = self.tree.item(item, 'values')
            
            if item_values and len(item_values) >= 3:
                item_type = item_values[2]
                
                if item_type == 'file':
                    self.tree_menu.add_command(label="Открыть расположение файла", command=self.open_file_location)
                    self.tree_menu.add_command(label="Открыть с помощью...", command=self.open_file_with)
                    self.tree_menu.add_command(label="Переименовать", command=self.rename_file)
                    self.tree_menu.add_command(label="Переместить в папку...", command=self.move_file_to_folder_dialog)
                    self.tree_menu.add_command(label="Удалить файл", command=self.delete_file_dialog)
                    
                    file_path = item_values[0]
                    favorites = self.settings.get("favorites", [])
                    
                    if file_path in favorites:
                        self.tree_menu.add_command(label="Убрать из избранного", command=lambda: self.toggle_favorite(update_immediately=True))
                    else:
                        self.tree_menu.add_command(label="Добавить в избранное", command=lambda: self.toggle_favorite(update_immediately=True))
                    
                    self.tree_menu.add_separator()
                    
                    # Добавляем подменю для добавления в папку
                    add_to_folder_menu = tk.Menu(self.tree_menu, tearoff=0)
                    self.tree_menu.add_cascade(label="Добавить в папку", menu=add_to_folder_menu)
                    add_to_folder_menu.add_command(label="Создать новую", command=self.create_new_virtual_folder_from_context)
                    
                    if self.virtual_folders:
                        add_to_folder_menu.add_separator()
                        for folder_name in self.virtual_folders.keys():
                            add_to_folder_menu.add_command(label=folder_name, 
                                                         command=lambda f=folder_name: self.add_selected_to_virtual_folder(f))
                    
                    # Проверяем, находится ли файл в виртуальных папках
                    in_virtual_folders = []
                    for folder_name, files in self.virtual_folders.items():
                        for file_info in files:
                            file_path_in_folder = file_info['path'] if isinstance(file_info, dict) else file_info
                            if file_path_in_folder == file_path:
                                in_virtual_folders.append(folder_name)
                    
                    if in_virtual_folders:
                        self.tree_menu.add_separator()
                        # Если файл находится только в одной папке, убираем его сразу
                        if len(in_virtual_folders) == 1:
                            self.tree_menu.add_command(label="Убрать из папки", 
                                                     command=lambda: self.remove_file_from_virtual_folder(in_virtual_folders[0], file_path))
                        else:
                            # Если в нескольких, показываем подменю
                            remove_menu = tk.Menu(self.tree_menu, tearoff=0)
                            self.tree_menu.add_cascade(label="Убрать из папки", menu=remove_menu)
                            for folder_name in in_virtual_folders:
                                remove_menu.add_command(label=folder_name, 
                                                      command=lambda f=folder_name, p=file_path: self.remove_file_from_virtual_folder(f, p))
                    
                elif item_type == 'virtual_folder':
                    folder_name = self.tree.item(item, 'text').replace('📁 ', '').replace('⭐ ', '')
                    
                    # Правильное отображение пунктов меню для избранного
                    if folder_name in self.settings.get("favorites", []):
                        self.tree_menu.add_command(label="Убрать из избранного", 
                                                 command=lambda: self.toggle_virtual_folder_favorite(folder_name))
                    else:
                        self.tree_menu.add_command(label="Добавить в избранное", 
                                                 command=lambda: self.toggle_virtual_folder_favorite(folder_name))
                    
                    self.tree_menu.add_command(label="Переименовать папку", 
                                             command=lambda: self.rename_virtual_folder(folder_name))
                    self.tree_menu.add_command(label="Удалить папку", 
                                             command=lambda: self.delete_virtual_folder(folder_name))
                    self.tree_menu.add_separator()
                    
                    # Показываем "Развернуть" или "Свернуть" в зависимости от состояния
                    if self.tree.item(item, 'open'):
                        self.tree_menu.add_command(label="Свернуть папку", 
                                                 command=lambda: self.tree.item(item, open=False))
                    else:
                        self.tree_menu.add_command(label="Развернуть папку", 
                                                 command=lambda: self.tree.item(item, open=True))
                    
                elif item_type == 'folder':
                    # Показываем "Развернуть" или "Свернуть" в зависимости от состояния
                    if self.tree.item(item, 'open'):
                        self.tree_menu.add_command(label="Свернуть все", command=lambda: self.collapse_folder(item))
                    else:
                        self.tree_menu.add_command(label="Развернуть все", command=lambda: self.expand_folder(item))
            
            self.tree_menu.post(event.x_root, event.y_root)
    
    def move_file_to_folder_dialog(self):
        """Открыть диалог для перемещения файла в папку"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        item = selected_items[0]
        item_values = self.tree.item(item, 'values')
        
        if len(item_values) >= 1:
            file_path = item_values[0]
            
            if not os.path.exists(file_path):
                messagebox.showwarning("Предупреждение", "Файл не существует")
                return
            
            # Открываем диалог выбора папки
            target_folder = filedialog.askdirectory(
                title="Выберите папку для перемещения файла",
                initialdir=os.path.dirname(file_path)
            )
            
            if target_folder:
                self.move_file_to_folder(file_path, target_folder)
    
    def delete_file_dialog(self):
        """Открыть диалог для удаления файла"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        item = selected_items[0]
        item_values = self.tree.item(item, 'values')
        
        if len(item_values) >= 1:
            file_path = item_values[0]
            
            if not os.path.exists(file_path):
                messagebox.showwarning("Предупреждение", "Файл не существует")
                return
            
            if messagebox.askyesno("Подтверждение", 
                                 f"Вы уверены, что хотите удалить файл?\n\n{os.path.basename(file_path)}\n\n"
                                 "Файл будет удален безвозвратно!"):
                self.delete_file_permanent(file_path)
    
    def expand_folder(self, item):
        """Развернуть папку и все подпапки"""
        self.tree.item(item, open=True)
        for child in self.tree.get_children(item):
            if self.tree.item(child, 'values')[2] == 'folder':
                self.expand_folder(child)
    
    def collapse_folder(self, item):
        """Свернуть папку и все подпапки"""
        self.tree.item(item, open=False)
        for child in self.tree.get_children(item):
            if self.tree.item(child, 'values')[2] == 'folder':
                self.collapse_folder(child)
    
    def remove_file_from_virtual_folder(self, folder_name, file_path):
        """Убрать файл из виртуальной папки"""
        if folder_name in self.virtual_folders:
            # Сохраняем состояние для истории
            old_files = self.virtual_folders[folder_name].copy()
            
            # Удаляем файл из папки
            self.virtual_folders[folder_name] = [
                file_info for file_info in self.virtual_folders[folder_name]
                if (isinstance(file_info, dict) and file_info.get('path') != file_path) or file_info != file_path
            ]
            
            # Если папка пустая, удаляем ее
            if not self.virtual_folders[folder_name]:
                del self.virtual_folders[folder_name]
                # Убираем папку из избранного если она там была
                if folder_name in self.settings.get("favorites", []):
                    self.settings["favorites"].remove(folder_name)
                self.status_var.set(f"Папка '{folder_name}' удалена, так как в ней не осталось файлов")
            else:
                self.status_var.set(f"Файл убран из папки '{folder_name}'")
            
            # Добавляем в историю действий
            self.add_to_action_history('virtual_folder_remove_file', {
                'folder_name': folder_name,
                'file_path': file_path,
                'old_files': old_files
            })
            
            self.save_settings()
            self.refresh_tree()
    
    def create_new_virtual_folder_from_context(self):
        """Создать новую виртуальную папку из контекстного меню"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        files_to_add = []
        for item in selected_items:
            item_values = self.tree.item(item, 'values')
            if item_values and len(item_values) >= 3 and item_values[2] == 'file':
                files_to_add.append({
                    'path': item_values[0],
                    'name': self.tree.item(item, 'text').replace('⭐ ', '')
                })
        
        if not files_to_add:
            messagebox.showwarning("Предупреждение", "Выберите файлы для добавления в папку")
            return
        
        folder_name = simpledialog.askstring("Создать папку", "Введите название папки:")
        if folder_name:
            if folder_name in self.virtual_folders:
                messagebox.showwarning("Предупреждение", "Папка с таким именем уже существует")
                return
            
            self.virtual_folders[folder_name] = files_to_add
            
            # Добавляем в историю действий
            self.add_to_action_history('virtual_folder_create', {
                'folder_name': folder_name,
                'files': files_to_add
            })
            
            self.save_settings()
            self.refresh_tree()
            self.status_var.set(f"Создана новая папка '{folder_name}' с {len(files_to_add)} файлами")
    
    def add_selected_to_virtual_folder(self, folder_name):
        """Добавить выбранные файлы в существующую виртуальную папку"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        files_to_add = []
        for item in selected_items:
            item_values = self.tree.item(item, 'values')
            if item_values and len(item_values) >= 3 and item_values[2] == 'file':
                files_to_add.append({
                    'path': item_values[0],
                    'name': self.tree.item(item, 'text').replace('⭐ ', '')
                })
        
        if not files_to_add:
            return
        
        self.add_files_to_virtual_folder(folder_name, files_to_add)
    
    def create_virtual_folder_from_selection(self):
        """Создать виртуальную папку из выделенных файлов"""
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Предупреждение", "Выберите файлы для объединения в папку")
            return
        
        files_to_add = []
        for item in selected_items:
            item_values = self.tree.item(item, 'values')
            if item_values and len(item_values) >= 3 and item_values[2] == 'file':
                files_to_add.append({
                    'path': item_values[0],
                    'name': self.tree.item(item, 'text').replace('⭐ ', '')
                })
        
        if not files_to_add:
            messagebox.showwarning("Предупреждение", "Выберите файлы для объединения в папку")
            return
        
        folder_name = simpledialog.askstring("Создать папку", "Введите название папки:")
        if folder_name:
            if folder_name in self.virtual_folders:
                messagebox.showwarning("Предупреждение", "Папка с таким именем уже существует")
                return
            
            self.virtual_folders[folder_name] = files_to_add
            
            # Добавляем в историю действий
            self.add_to_action_history('virtual_folder_create', {
                'folder_name': folder_name,
                'files': files_to_add
            })
            
            self.save_settings()
            self.refresh_tree()
            self.status_var.set(f"Создана новая папка '{folder_name}' с {len(files_to_add)} файлами")
    
    def toggle_virtual_folders(self):
        """Переключить состояние всех виртуальных папки (развернуть/свернуть)"""
        all_items = self.tree.get_children()
        has_closed_folders = False
        
        for item in all_items:
            item_values = self.tree.item(item, 'values')
            if item_values and len(item_values) >= 3 and item_values[2] == 'virtual_folder':
                if not self.tree.item(item, 'open'):
                    has_closed_folders = True
                    break
        
        # Если есть закрытые папки - открываем все, иначе закрываем все
        for item in all_items:
            item_values = self.tree.item(item, 'values')
            if item_values and len(item_values) >= 3 and item_values[2] == 'virtual_folder':
                self.tree.item(item, open=has_closed_folders)
    
    def add_files_to_virtual_folder(self, folder_name, files_to_add):
        """Добавить файлы в виртуальную папку"""
        if folder_name not in self.virtual_folders:
            self.virtual_folders[folder_name] = []
        
        # Сохраняем состояние для истории
        old_files = self.virtual_folders[folder_name].copy()
        
        # Исправление ошибки: проверяем тип данных в виртуальной папке
        existing_files = []
        for item in self.virtual_folders[folder_name]:
            if isinstance(item, dict) and 'path' in item:
                existing_files.append(item['path'])
            elif isinstance(item, str):
                existing_files.append(item)
        
        added_count = 0
        for file_info in files_to_add:
            if file_info['path'] not in existing_files:
                self.virtual_folders[folder_name].append(file_info)
                added_count += 1
                
                # Если папка в избранном, добавляем файлы в избранное
                if folder_name in self.settings.get("favorites", []):
                    if file_info['path'] not in self.settings["favorites"]:
                        self.settings["favorites"].append(file_info['path'])
        
        # Добавляем в историю действий
        self.add_to_action_history('virtual_folder_add_files', {
            'folder_name': folder_name,
            'files_added': files_to_add,
            'old_files': old_files
        })
        
        self.save_settings()
        self.refresh_tree()
        self.status_var.set(f"Добавлено {added_count} файлов в папку '{folder_name}'")
    
    def toggle_virtual_folder_favorite(self, folder_name):
        """Добавить/убрать виртуальную папку из избранного"""
        favorites = self.settings.get("favorites", [])
        
        if folder_name in favorites:
            # Убираем папку из избранного
            favorites.remove(folder_name)
            self.status_var.set(f"Папка '{folder_name}' убрана из избранного")
        else:
            # Добавляем папку в избранное
            favorites.append(folder_name)
            self.status_var.set(f"Папка '{folder_name}' добавлена в избранное")
            
            # Добавляем все файлы из папки в избранное
            if folder_name in self.virtual_folders:
                for file_info in self.virtual_folders[folder_name]:
                    file_path = file_info['path'] if isinstance(file_info, dict) else file_info
                    if file_path not in favorites:
                        favorites.append(file_path)
        
        self.settings["favorites"] = favorites
        self.save_settings()
        self.refresh_tree()
    
    def rename_virtual_folder(self, folder_name):
        """Переименовать виртуальную папку"""
        new_name = simpledialog.askstring("Переименовать папку", "Введите новое название папки:", initialvalue=folder_name)
        if new_name and new_name != folder_name:
            if new_name in self.virtual_folders:
                messagebox.showwarning("Предупреждение", "Папка с таким именем уже существует")
                return
            
            old_files = self.virtual_folders[folder_name].copy()
            self.virtual_folders[new_name] = self.virtual_folders.pop(folder_name)
            
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
            self.refresh_tree()
            self.status_var.set(f"Папка переименована: '{folder_name}' -> '{new_name}'")
    
    def delete_virtual_folder(self, folder_name):
        """Удалить виртуальную папку"""
        if messagebox.askyesno("Подтверждение", f"Вы уверены, что хотите удалить папку '{folder_name}'?"):
            if folder_name in self.virtual_folders:
                # Сохраняем данные для истории
                old_files = self.virtual_folders[folder_name].copy()
                
                # Убираем папку из избранного если она там была
                favorites = self.settings.get("favorites", [])
                if folder_name in favorites:
                    favorites.remove(folder_name)
                    self.settings["favorites"] = favorites
                
                del self.virtual_folders[folder_name]
                
                # Добавляем в историю действий
                self.add_to_action_history('virtual_folder_delete', {
                    'folder_name': folder_name,
                    'files': old_files
                })
                
                self.save_settings()
                self.refresh_tree()
                self.status_var.set(f"Папка '{folder_name}' удалена")
    
    def on_drag_start(self, event):
        """Начало перетаскивания"""
        item = self.tree.identify_row(event.y)
        if item:
            self.drag_start_item = item
            self.drag_data["item"] = item
            self.drag_data["x"] = event.x
            self.drag_data["y"] = event.y
            
            # Получаем индекс начального элемента
            all_items = list(self.tree.get_children())
            try:
                self.drag_start_index = all_items.index(item)
            except ValueError:
                self.drag_start_index = None
            
            self.is_dragging = True
            
            # Начинаем выделение с одного элемента
            if item not in self.tree.selection():
                self.tree.selection_set(item)
    
    def on_shift_click(self, event):
        """Обработка Shift+клик для выделения диапазона"""
        item = self.tree.identify_row(event.y)
        if item and self.drag_start_index is not None:
            all_items = list(self.tree.get_children())
            try:
                current_index = all_items.index(item)
                
                start_idx = min(self.drag_start_index, current_index)
                end_idx = max(self.drag_start_index, current_index)
                
                # Очищаем выделение и выделяем все элементы в диапазоне
                self.tree.selection_remove(self.tree.selection())
                
                for i in range(start_idx, end_idx + 1):
                    self.tree.selection_add(all_items[i])
            except ValueError:
                pass
    
    def on_drag_motion(self, event):
        """Перетаскивание с выделением области"""
        if self.is_dragging and self.drag_start_index is not None:
            item = self.tree.identify_row(event.y)
            if item:
                all_items = list(self.tree.get_children())
                try:
                    current_index = all_items.index(item)
                    
                    start_idx = min(self.drag_start_index, current_index)
                    end_idx = max(self.drag_start_index, current_index)
                    
                    # Очищаем выделение и выделяем все элементы в диапазоне
                    self.tree.selection_remove(self.tree.selection())
                    
                    for i in range(start_idx, end_idx + 1):
                        self.tree.selection_add(all_items[i])
                except ValueError:
                    pass
    
    def on_drag_release(self, event):
        """Завершение перетаскивания"""
        self.drag_start_item = None
        self.drag_start_index = None
        self.is_dragging = False
        self.drag_data = {"item": None, "x": 0, "y": 0}
    
    def on_tree_double_click(self, event):
        """Обработка двойного клика по дереву"""
        item = self.tree.identify_row(event.y)
        if item:
            item_values = self.tree.item(item, 'values')
            if item_values and len(item_values) >= 3:
                item_type = item_values[2]
                
                if item_type == 'virtual_folder':
                    # Разворачиваем/сворачиваем виртуальную папку
                    current_state = self.tree.item(item, 'open')
                    self.tree.item(item, open=not current_state)
                    return
                
                elif item_type == 'file':
                    file_path = item_values[0]
                    # Открываем через стандартный диалог
                    self.open_file_with()
                
                elif item_type == 'folder':
                    # Переключаем состояние развертывания обычной папки
                    current_state = self.tree.item(item, 'open')
                    self.tree.item(item, open=not current_state)
    
    def open_file(self, file_path):
        """Открыть файл через стандартный диалог Windows"""
        # Проверяем, является ли путь архивным
        archive_path = None
        actual_file_path = file_path
        
        # Если файл находится в архиве, извлекаем его
        if not os.path.exists(file_path) and hasattr(self, 'archive_data'):
            # Ищем файл в текущем архиве
            for file_info in self.all_files:
                if file_info['path'] == file_path and file_info.get('archive_path'):
                    archive_path = file_info['archive_path']
                    break
        
        temp_file_path = None
        if archive_path and os.path.exists(archive_path):
            try:
                # Создаем временную папку для извлечения
                temp_dir = tempfile.mkdtemp()
                file_name = os.path.basename(file_path)
                temp_file_path = os.path.join(temp_dir, file_name)
                
                if archive_path.lower().endswith('.zip'):
                    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                        # Ищем файл в архиве
                        for zip_info in zip_ref.infolist():
                            if zip_info.filename == file_path or zip_info.filename.endswith(file_path):
                                with zip_ref.open(zip_info) as source, open(temp_file_path, 'wb') as target:
                                    shutil.copyfileobj(source, target)
                                actual_file_path = temp_file_path
                                break
                
                elif archive_path.lower().endswith('.rar'):
                    try:
                        import rarfile
                        rarfile.UNRAR_TOOL = self.settings.get("unrar_path")
                        with rarfile.RarFile(archive_path) as rar_ref:
                            # Ищем файл в архиве
                            for rar_info in rar_ref.infolist():
                                if rar_info.filename == file_path or rar_info.filename.endswith(file_path):
                                    with rar_ref.open(rar_info) as source, open(temp_file_path, 'wb') as target:
                                        shutil.copyfileobj(source, target)
                                    actual_file_path = temp_file_path
                                    break
                    except ImportError:
                        messagebox.showerror("Ошибка", "Для работы с RAR архивами установите библиотеку rarfile")
                        return
                
                if not os.path.exists(actual_file_path):
                    messagebox.showerror("Ошибка", f"Не удалось извлечь файл из архива: {file_path}")
                    return
                    
            except Exception as e:
                messagebox.showerror("Ошибка", f"Ошибка при извлечении файла из архива: {str(e)}")
                return
        
        if not os.path.exists(actual_file_path):
            messagebox.showerror("Ошибка", f"Файл не найден: {actual_file_path}")
            return
        
        try:
            # Всегда открываем через стандартный диалог
            if os.name == 'nt':  # Windows
                # Используем ShellExecute с параметром "openas" для вызова диалога "Открыть с помощью"
                ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "openas",
                    actual_file_path,
                    None,
                    None,
                    1  # SW_SHOWNORMAL
                )
            else:  # macOS, Linux
                subprocess.run(['xdg-open', actual_file_path])
            
            self.status_var.set(f"Открытие файла: {os.path.basename(file_path)}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл: {str(e)}")
        finally:
            # Очищаем временный файл после использования
            if temp_file_path and os.path.exists(temp_file_path):
                def cleanup_temp_file():
                    try:
                        os.remove(temp_file_path)
                        temp_dir = os.path.dirname(temp_file_path)
                        if os.path.exists(temp_dir):
                            os.rmdir(temp_dir)
                    except:
                        pass
                
                self.root.after(30000, cleanup_temp_file)
    
    def open_file_with(self):
        """Открыть файл с помощью выбранной программы через диалог Windows"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        item = selected_items[0]
        item_values = self.tree.item(item, 'values')
        
        if len(item_values) >= 1:
            file_path = item_values[0]
            archive_path = item_values[1] if len(item_values) > 1 else None
            
            if not os.path.exists(file_path) and not archive_path:
                messagebox.showwarning("Предупреждение", "Файл не существует или путь недоступен")
                return
            
            try:
                # Если файл находится в архиве, извлекаем его во временную папку
                temp_file = None
                if archive_path:
                    temp_dir = self.settings.get("temp_folder") or tempfile.gettempdir()
                    os.makedirs(temp_dir, exist_ok=True)
                    
                    temp_file = os.path.join(temp_dir, os.path.basename(file_path))
                    
                    if archive_path.lower().endswith('.zip'):
                        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                            file_in_archive = None
                            for zip_file in zip_ref.namelist():
                                if zip_file.endswith(file_path) or os.path.basename(zip_file) == os.path.basename(file_path):
                                    file_in_archive = zip_file
                                    break
                            
                            if file_in_archive:
                                with zip_ref.open(file_in_archive) as source, open(temp_file, 'wb') as target:
                                    shutil.copyfileobj(source, target)
                    
                    elif archive_path.lower().endswith('.rar'):
                        try:
                            import rarfile
                            rarfile.UNRAR_TOOL = self.settings.get("unrar_path")
                            with rarfile.RarFile(archive_path) as rar_ref:
                                file_in_archive = None
                                for rar_file in rar_ref.namelist():
                                    if rar_file.endswith(file_path) or os.path.basename(rar_file) == os.path.basename(file_path):
                                        file_in_archive = rar_file
                                        break
                                
                                if file_in_archive:
                                    with rar_ref.open(file_in_archive) as source, open(temp_file, 'wb') as target:
                                        shutil.copyfileobj(source, target)
                        except ImportError:
                            messagebox.showerror("Ошибка", "Для работы с RAR архивами установите библиотеку rarfile")
                            return
                
                # Используем стандартный диалог Windows "Открыть с помощью"
                file_to_open = temp_file if temp_file else file_path
                
                if os.name == 'nt':  # Windows
                    # Используем ShellExecute с параметром "openas" для вызова диалога "Открыть с помощью"
                    ctypes.windll.shell32.ShellExecuteW(
                        None,
                        "openas",
                        file_to_open,
                        None,
                        None,
                        1  # SW_SHOWNORMAL
                    )
                else:  # Linux, macOS
                    subprocess.run(['xdg-open', file_to_open])
                
                self.status_var.set(f"Открытие файла с выбором программы: {os.path.basename(file_path)}")
                
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{str(e)}")
    
    def open_file_location(self):
        """Открыть расположение файла в проводнике с выделением файла"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        item = selected_items[0]
        item_values = self.tree.item(item, 'values')
        
        if len(item_values) >= 1:
            file_path = item_values[0]
            
            if os.path.exists(file_path):
                try:
                    if os.name == 'nt':  # Windows
                        # Используем команду explorer с параметром /select для выделения файла
                        subprocess.run(f'explorer /select,"{file_path}"', shell=True, check=False)
                        self.status_var.set(f"Открыта папка с выделением файла: {os.path.basename(file_path)}")
                    elif os.name == 'posix':  # Linux, macOS
                        folder_path = os.path.dirname(file_path)
                        if sys.platform == 'darwin':  # macOS
                            subprocess.run(['open', '-R', file_path])
                        else:  # Linux
                            subprocess.run(['xdg-open', folder_path])
                        self.status_var.set(f"Открыта папка: {folder_path}")
                        
                except Exception as e:
                    # Резервный способ без выделения
                    try:
                        folder_path = os.path.dirname(file_path)
                        if os.name == 'nt':
                            os.startfile(folder_path)
                        else:
                            subprocess.run(['xdg-open', folder_path])
                        self.status_var.set(f"Открыта папка: {folder_path}")
                    except Exception as e2:
                        messagebox.showerror("Ошибка", f"Не удалось открыть папку: {str(e2)}")
            else:
                messagebox.showwarning("Предупреждение", "Файл не существует или путь недоступен")
    
    def rename_file(self):
        """Переименовать файл"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        item = selected_items[0]
        item_values = self.tree.item(item, 'values')
        if not item_values or len(item_values) < 1:
            return
        
        old_path = item_values[0]
        old_name = os.path.basename(old_path)
        
        if not os.path.exists(old_path):
            messagebox.showerror("Ошибка", f"Файл не найден: {old_path}")
            return
        
        new_name = simpledialog.askstring("Переименовать файл", "Введите новое имя файла:", initialvalue=old_name)
        
        if new_name and new_name != old_name:
            new_path = os.path.join(os.path.dirname(old_path), new_name)
            
            if os.path.exists(new_path):
                messagebox.showerror("Ошибка", f"Файл с именем '{new_name}' уже существует")
                return
            
            try:
                # Добавляем в историю перед переименованием
                self.add_to_action_history('file_rename', {
                    'old_path': old_path,
                    'new_path': new_path
                })
                
                os.rename(old_path, new_path)
                
                # Обновляем данные файла
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
                self.refresh_tree()
                self.status_var.set(f"Файл переименован: '{old_name}' -> '{new_name}'")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось переименовать файл: {str(e)}")
    
    def move_file_to_folder(self, source_file, target_folder):
        """Переместить файл в папку"""
        try:
            if not os.path.exists(source_file):
                raise FileNotFoundError(f"Файл не найден: {source_file}")
            
            if not os.path.exists(target_folder):
                os.makedirs(target_folder, exist_ok=True)
            
            new_path = os.path.join(target_folder, os.path.basename(source_file))
            
            # Добавляем в историю перед перемещением
            self.add_to_action_history('file_move', {
                'old_path': source_file,
                'new_path': new_path,
                'old_folder': os.path.dirname(source_file),
                'new_folder': target_folder
            })
            
            shutil.move(source_file, new_path)
            self.status_var.set(f"Файл перемещен: {os.path.basename(source_file)}")
            
            # Обновляем данные
            for file_info in self.all_files:
                if file_info['path'] == source_file:
                    file_info['path'] = new_path
                    break
            
            self.refresh_tree()
            return True
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось переместить файл: {str(e)}")
            return False
    
    def undo_move_action(self, action_data):
        """Отменить перемещение файла"""
        old_path = action_data['old_path']
        new_path = action_data['new_path']
        
        if os.path.exists(new_path) and not os.path.exists(old_path):
            try:
                # Создаем старую папку если не существует
                old_dir = os.path.dirname(old_path)
                if not os.path.exists(old_dir):
                    os.makedirs(old_dir, exist_ok=True)
                
                shutil.move(new_path, old_path)
                
                # Обновляем данные
                for file_info in self.all_files:
                    if file_info['path'] == new_path:
                        file_info['path'] = old_path
                        break
                
                self.refresh_tree()
                self.status_var.set(f"Отменено перемещение: {os.path.basename(new_path)}")
                return True
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось отменить перемещение: {str(e)}")
                return False
        return False
    
    def redo_move_action(self, action_data):
        """Повторить перемещение файла"""
        old_path = action_data['old_path']
        new_path = action_data['new_path']
        
        if os.path.exists(old_path) and not os.path.exists(new_path):
            try:
                # Создаем новую папку если не существует
                new_dir = os.path.dirname(new_path)
                if not os.path.exists(new_dir):
                    os.makedirs(new_dir, exist_ok=True)
                
                shutil.move(old_path, new_path)
                
                # Обновляем данные
                for file_info in self.all_files:
                    if file_info['path'] == old_path:
                        file_info['path'] = new_path
                        break
                
                self.refresh_tree()
                self.status_var.set(f"Повторено перемещение: {os.path.basename(old_path)}")
                return True
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось повторить перемещение: {str(e)}")
                return False
        return False
    
    def delete_file_permanent(self, file_path):
        """Удалить файл безвозвратно"""
        try:
            # Находим информацию о файле перед удалением
            file_info = None
            for f in self.all_files:
                if f['path'] == file_path:
                    file_info = f.copy()
                    break
            
            if not file_info:
                messagebox.showerror("Ошибка", "Информация о файле не найдена")
                return False
            
            # Читаем содержимое файла если это текстовый файл
            file_content = None
            if os.path.exists(file_path):
                try:
                    # Проверяем, является ли файл текстовым по расширению
                    text_extensions = ['.txt', '.json', '.js', '.py', '.html', '.css', '.xml', '.md', '.csv', '.log']
                    file_ext = os.path.splitext(file_path)[1].lower()
                    if file_ext in text_extensions:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            file_content = f.read()
                except:
                    pass
            
            # Добавляем в историю перед удалением
            self.add_to_action_history('file_delete', {
                'path': file_path,
                'file_info': file_info,
                'file_content': file_content,
                'in_favorites': file_path in self.settings.get("favorites", []),
                'in_virtual_folders': self.get_file_virtual_folders(file_path)
            })
            
            # Удаляем файл
            if os.path.exists(file_path):
                os.remove(file_path)
            
            # Удаляем из избранного
            if file_path in self.settings.get("favorites", []):
                self.settings["favorites"].remove(file_path)
            
            # Удаляем из виртуальных папок
            for folder_name, files in self.virtual_folders.items():
                self.virtual_folders[folder_name] = [
                    f for f in files 
                    if (isinstance(f, dict) and f.get('path') != file_path) or f != file_path
                ]
            
            # Удаляем из списка файлов
            self.all_files = [f for f in self.all_files if f['path'] != file_path]
            
            self.save_settings()
            self.refresh_tree()
            self.status_var.set(f"Файл удален: {os.path.basename(file_path)}")
            return True
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось удалить файл: {str(e)}")
            return False
    
    def redo_delete_action(self, action_data):
        """Повторить удаление файла"""
        file_path = action_data['path']
        
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                
                # Удаляем из избранного
                if file_path in self.settings.get("favorites", []):
                    self.settings["favorites"].remove(file_path)
                
                # Удаляем из виртуальных папок
                for folder_name, files in self.virtual_folders.items():
                    self.virtual_folders[folder_name] = [
                        f for f in files 
                        if (isinstance(f, dict) and f.get('path') != file_path) or f != file_path
                    ]
                
                # Удаляем из списка файлов
                self.all_files = [f for f in self.all_files if f['path'] != file_path]
                
                self.save_settings()
                self.refresh_tree()
                self.status_var.set(f"Повторено удаление: {os.path.basename(file_path)}")
                return True
                
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось повторить удаление: {str(e)}")
                return False
        return False
    
    def undo_delete_action(self, action_data):
        """Отменить удаление файла"""
        file_path = action_data['path']
        file_info = action_data.get('file_info')
        file_content = action_data.get('file_content')
        
        if not os.path.exists(file_path) and file_info:
            try:
                # Создаем папку если не существует
                file_dir = os.path.dirname(file_path)
                if not os.path.exists(file_dir):
                    os.makedirs(file_dir, exist_ok=True)
                
                # Восстанавливаем содержимое файла
                if file_content:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(file_content)
                else:
                    # Создаем пустой файл
                    with open(file_path, 'w') as f:
                        pass
                
                # Восстанавливаем в избранное
                if action_data.get('in_favorites'):
                    favorites = self.settings.get("favorites", [])
                    if file_path not in favorites:
                        favorites.append(file_path)
                    self.settings["favorites"] = favorites
                
                # Восстанавливаем в виртуальные папки
                virtual_folders = action_data.get('in_virtual_folders', [])
                for folder_name in virtual_folders:
                    if folder_name in self.virtual_folders:
                        self.virtual_folders[folder_name].append(file_info)
                
                # Восстанавливаем в список файлов
                self.all_files.append(file_info)
                
                self.save_settings()
                self.refresh_tree()
                self.status_var.set(f"Отменено удаление: {os.path.basename(file_path)}")
                return True
                
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось отменить удаление: {str(e)}")
                return False
        return False
    
    def get_file_virtual_folders(self, file_path):
        """Получить список виртуальных папок, содержащих файл"""
        folders = []
        for folder_name, files in self.virtual_folders.items():
            for file_info in files:
                file_path_in_folder = file_info['path'] if isinstance(file_info, dict) else file_info
                if file_path_in_folder == file_path:
                    folders.append(folder_name)
                    break
        return folders
    
    def toggle_favorite(self, update_immediately=False):
        """Добавить/убрать файл из избранного"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        favorites = self.settings.get("favorites", [])
        changed = False
        file_paths = []
        was_favorite = False
        
        for item in selected_items:
            item_values = self.tree.item(item, 'values')
            if item_values and len(item_values) >= 1:
                file_path = item_values[0]
                file_paths.append(file_path)
                
                if file_path in favorites:
                    was_favorite = True
                    favorites.remove(file_path)
                    changed = True
                else:
                    was_favorite = False
                    favorites.append(file_path)
                    changed = True
        
        if changed:
            # Добавляем в историю действий
            self.add_to_action_history('favorite_toggle', {
                'file_paths': file_paths,
                'was_favorite': was_favorite
            })
            
            self.settings["favorites"] = favorites
            self.save_settings()
            
            # Обновляем данные файлов
            for file_info in self.all_files:
                file_info['is_favorite'] = file_info['path'] in favorites
            
            if update_immediately:
                self.refresh_tree()
                self.status_var.set("Избранное обновлено")
    
    def toggle_favorites_filter(self):
        """Переключить фильтр избранного"""
        self.show_favorites_only = not self.show_favorites_only
        
        if self.show_favorites_only:
            self.status_var.set("Показаны только избранные файлы")
        else:
            self.status_var.set("Показаны все файлы")
        
        self.refresh_tree()
    
    def toggle_hide_blockbench_children(self):
        """Переключить скрытие дочерних файлов Blockbench"""
        self.settings["hide_blockbench_children"] = not self.settings.get("hide_blockbench_children", True)
        self.save_settings()
        self.refresh_tree()
    
    def update_folder_history(self):
        """Обновление истории папок"""
        history = self.settings.get("scan_history", [])
        self.folder_combo['values'] = history
    
    def get_sort_button_text(self):
        """Получить текст кнопки сортировки"""
        sort_mode = self.settings.get("sort_mode", "name_asc")
        texts = {
            "name_asc": "A-Z ↑",
            "name_desc": "Z-A ↓", 
            "date_asc": "Дата ↑",
            "date_desc": "Дата ↓",
            "size_asc": "Размер ↑",
            "size_desc": "Размер ↓"
        }
        return texts.get(sort_mode, "A-Z ↑")
    
    def toggle_sorting(self, event=None):
        """Переключение сортировки"""
        current_mode = self.settings.get("sort_mode", "name_asc")
        shift_pressed = event and event.state & 0x0001  # Проверяем зажат ли Shift
        
        # Порядок сортировки: name_asc -> name_desc -> date_asc -> date_desc -> size_asc -> size_desc
        modes_forward = ["name_asc", "name_desc", "date_asc", "date_desc", "size_asc", "size_desc"]
        modes_reverse = list(reversed(modes_forward))
        
        if shift_pressed:
            # Обратный порядок при зажатом Shift
            current_index = modes_reverse.index(current_mode)
            next_index = (current_index + 1) % len(modes_reverse)
            new_mode = modes_reverse[next_index]
        else:
            # Прямой порядок
            current_index = modes_forward.index(current_mode)
            next_index = (current_index + 1) % len(modes_forward)
            new_mode = modes_forward[next_index]
        
        self.settings["sort_mode"] = new_mode
        self.save_settings()
        self.sort_btn.config(text=self.get_sort_button_text())
        self.refresh_tree()
    
    def load_file_content(self, file_info):
        """Загрузить содержимое файла для поиска"""
        file_path = file_info['path']
        
        # Проверяем кэш
        if file_path in self.file_content_cache:
            return self.file_content_cache[file_path]
        
        content = ""
        try:
            # Проверяем, является ли файл текстовым по расширению
            text_extensions = ['.txt', '.json', '.js', '.py', '.html', '.css', '.xml', '.md', '.csv', '.log']
            file_ext = file_info.get('extension', '').lower()
            
            if file_ext in text_extensions or file_info.get('archive_path'):
                # Для архивных файлов
                if file_info.get('archive_path'):
                    archive_path = file_info['archive_path']
                    if archive_path.lower().endswith('.zip'):
                        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                            # Ищем файл в архиве
                            for zip_info in zip_ref.infolist():
                                if zip_info.filename == file_path or zip_info.filename.endswith(file_path):
                                    with zip_ref.open(zip_info) as f:
                                        content = f.read().decode('utf-8', errors='ignore')
                                    break
                    elif archive_path.lower().endswith('.rar'):
                        try:
                            import rarfile
                            rarfile.UNRAR_TOOL = self.settings.get("unrar_path")
                            with rarfile.RarFile(archive_path) as rar_ref:
                                for rar_info in rar_ref.infolist():
                                    if rar_info.filename == file_path or rar_info.filename.endswith(file_path):
                                        with rar_ref.open(rar_info) as f:
                                            content = f.read().decode('utf-8', errors='ignore')
                                        break
                        except ImportError:
                            pass
                # Для обычных файлов
                elif os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
        except Exception:
            content = ""
        
        # Сохраняем в кэш
        self.file_content_cache[file_path] = content
        return content
    
    def clear_search_cache(self):
        """Очистить кэш поиска по содержимому"""
        self.file_content_cache.clear()
        messagebox.showinfo("Информация", "Кэш поиска очищен")
    
    def refresh_tree(self):
        """Обновление дерева файлов"""
        if not hasattr(self, 'tree') or not self.tree.winfo_exists():
            return
        
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        search_query = self.get_search_query().lower()
        search_mode = self.settings.get("search_mode", "name")
        
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
                    # Поиск по имени файла
                    filename = file_info['name'].lower()
                    if search_query not in filename:
                        continue
                else:
                    # Поиск по содержимому файла
                    content = self.load_file_content(file_info).lower()
                    if search_query not in content:
                        continue
            
            if self.settings.get("hide_blockbench_children", True):
                if file_info.get('has_parent', False):
                    continue
            
            filtered_files.append(file_info)
        
        # Применяем сортировку
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
        
        # Добавляем виртуальные папки с учетом фильтра расширений
        self.add_virtual_folders_to_tree(filtered_files)
        
        # Добавляем файлы
        if self.settings.get("hide_duplicates", False):
            self.add_files_with_duplicates_grouping(filtered_files)
        else:
            self.add_files_normal(filtered_files)
        
        self.tree.tag_configure('favorite', background='light yellow')
        self.tree.tag_configure('duplicate_folder', background='light blue')
        self.tree.tag_configure('virtual_folder', background='light green')
        
        self.status_var.set(f"Показано файлов: {len(filtered_files)} (режим поиска: {'по содержимому' if search_mode == 'content' else 'по имени'})")
    
    def add_virtual_folders_to_tree(self, filtered_files):
        """Добавить виртуальные папки в дерево с учетом фильтра расширений"""
        if not self.virtual_folders:
            return
        
        for folder_name, files in self.virtual_folders.items():
            # Проверяем, есть ли файлы из этой папки в отсканированных файлах
            has_files_in_scan = False
            for file_info in files:
                file_path = file_info['path'] if isinstance(file_info, dict) else file_info
                for scanned_file in self.all_files:
                    if scanned_file['path'] == file_path:
                        has_files_in_scan = True
                        break
                if has_files_in_scan:
                    break
            
            if not has_files_in_scan:
                continue
            
            # Проверяем фильтр избранного
            if self.show_favorites_only:
                if folder_name not in self.settings.get("favorites", []):
                    continue
            
            # Проверяем фильтр расширений для виртуальных папок
            if self.current_extension_filter and self.current_extension_filter != "Все расширения":
                # Проверяем, содержит ли папка файлы с нужным расширением
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
            folder_icon = "⭐ " if is_favorite else "📁 "
            
            folder_item = self.tree.insert(
                "", "end", 
                text=folder_icon + folder_name,
                values=('', '', 'virtual_folder', '', '', is_favorite),
                tags=('virtual_folder',)
            )
            
            # Добавляем файлы в папку
            for file_info in files:
                if isinstance(file_info, dict) and 'path' in file_info:
                    file_path = file_info['path']
                    file_name = file_info.get('name', os.path.basename(file_path))
                    
                    # Проверяем, проходит ли файл фильтры
                    file_passes_filters = False
                    for filtered_file in filtered_files:
                        if filtered_file['path'] == file_path:
                            file_passes_filters = True
                            full_file_info = filtered_file
                            break
                    
                    if not file_passes_filters and not self.show_favorites_only:
                        continue
                    
                    if not file_passes_filters:
                        # Если файл не прошел фильтры, но мы в режиме избранного, ищем его в all_files
                        for f in self.all_files:
                            if f['path'] == file_path:
                                full_file_info = f
                                break
                        else:
                            continue
                    
                    is_file_favorite = full_file_info.get('is_favorite', False)
                    file_icon = "⭐ " if is_file_favorite else ""
                    
                    size_str = self.format_file_size(full_file_info['size'])
                    modified_str = full_file_info['modified'].strftime("%Y-%m-%d %H:%M")
                    
                    self.tree.insert(
                        folder_item, "end", 
                        text=file_icon + file_name,
                        values=(
                            file_path,
                            full_file_info.get('archive_path', ''),
                            'file',
                            size_str,
                            modified_str,
                            is_file_favorite
                        ),
                        tags=('favorite',) if is_file_favorite else ()
                    )
    
    def add_files_normal(self, files):
        """Добавить файлы в обычном режиме"""
        for file_info in files:
            # Пропускаем файлы, которые уже в виртуальных папках
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
            
            tags = ()
            if file_info.get('is_favorite', False):
                tags = ('favorite',)
                display_name = "⭐ " + file_info['name']
            else:
                display_name = file_info['name']
            
            size_str = self.format_file_size(file_info['size'])
            modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
            
            self.tree.insert(
                "", "end", 
                text=display_name,
                values=(
                    file_info['path'],
                    file_info.get('archive_path', ''),
                    'file',
                    size_str,
                    modified_str,
                    file_info.get('is_favorite', False)
                ),
                tags=tags
            )
    
    def add_files_with_duplicates_grouping(self, files):
        """Добавить файлы с группировкой дубликатов"""
        file_groups = defaultdict(list)
        single_files = []
        duplicate_groups = []
        
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
                file_groups[file_info['name']].append(file_info)
        
        for filename, file_list in file_groups.items():
            if len(file_list) == 1:
                single_files.append(file_list[0])
            else:
                duplicate_groups.append((filename, file_list))
        
        for file_info in single_files:
            tags = ()
            if file_info.get('is_favorite', False):
                tags = ('favorite',)
                display_name = "⭐ " + file_info['name']
            else:
                display_name = file_info['name']
            
            size_str = self.format_file_size(file_info['size'])
            modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
            
            self.tree.insert(
                "", "end", 
                text=display_name,
                values=(
                    file_info['path'],
                    file_info.get('archive_path', ''),
                    'file',
                    size_str,
                    modified_str,
                    file_info.get('is_favorite', False)
                ),
                tags=tags
            )
        
        for filename, file_list in duplicate_groups:
            folder_id = self.tree.insert(
                "", "end", 
                text=f"📁 {filename} ({len(file_list)} файлов)",
                values=('', '', 'folder', '', '', False),
                tags=('duplicate_folder',)
            )
            
            for file_info in file_list:
                tags = ()
                if file_info.get('is_favorite', False):
                    tags = ('favorite',)
                    display_name = "⭐ " + file_info['name']
                else:
                    display_name = file_info['name']
                
                size_str = self.format_file_size(file_info['size'])
                modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
                
                self.tree.insert(
                    folder_id, "end", 
                    text=display_name,
                    values=(
                        file_info['path'],
                        file_info.get('archive_path', ''),
                        'file',
                        size_str,
                        modified_str,
                        file_info.get('is_favorite', False)
                    ),
                    tags=tags
                )
    
    def format_file_size(self, size_bytes):
        """Форматирование размера файла"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB"]
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        
        return f"{s} {size_names[i]}"
    
    def on_tree_select(self, event):
        """Обработка выбора элемента в дереве"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        item = selected_items[0]
        item_values = self.tree.item(item, 'values')
        
        if len(item_values) >= 1:
            file_path = item_values[0]
            self.status_var.set(f"Выбран: {file_path}")
    
    def on_extension_select(self, event):
        """Обработка выбора расширения"""
        selected_items = self.extension_tree.selection()
        if not selected_items:
            self.current_extension_filter = ""
        else:
            item = selected_items[0]
            item_text = self.extension_tree.item(item, "text")
            if item_text == "Все расширения":
                self.current_extension_filter = ""
            else:
                self.current_extension_filter = item_text
        
        self.refresh_tree()
    
    def scan_selected(self):
        """Сканирование выбранной папки или архива"""
        folder_path = self.folder_var.get()
        if not folder_path:
            messagebox.showwarning("Предупреждение", "Выберите папку или архив для сканирования")
            return
        
        if not os.path.exists(folder_path):
            messagebox.showerror("Ошибка", "Указанный путь не существует")
            return
        
        self.add_to_scan_history(folder_path)
        
        self.progress.start()
        self.status_var.set("Сканирование...")
        self.scan_btn.config(state=tk.DISABLED)
        
        thread = threading.Thread(target=self.scan_folder_thread, args=(folder_path,))
        thread.daemon = True
        thread.start()
    
    def scan_folder_thread(self, folder_path):
        """Поток для сканирования папки"""
        try:
            self.available_extensions = set()
            self.duplicate_files = defaultdict(list)
            self.all_files = []
            self.extension_data = defaultdict(list)
            self.all_folders = set()
            self.file_content_cache = {}  # Очищаем кэш при новом сканировании
            
            if os.path.isfile(folder_path):
                self.scan_archive(folder_path)
            else:
                self.scan_real_folder(folder_path)
            
            self.find_duplicates()
            
            self.root.after(0, self.on_scan_complete)
            
        except Exception as e:
            self.root.after(0, lambda: self.on_scan_error(str(e)))
    
    def scan_real_folder(self, folder_path):
        """Сканирование реальной папки"""
        for root, dirs, files in os.walk(folder_path):
            for dir_name in dirs:
                full_dir_path = os.path.join(root, dir_name)
                self.all_folders.add(full_dir_path)
            
            for file in files:
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
                    'extension': os.path.splitext(file)[1].lower(),
                    'has_parent': False
                }
                
                # Добавляем файлы без расширения в отдельную категорию
                if not file_info['extension']:
                    file_info['extension'] = "(без расширения)"
                
                if file_info['extension'] in ['.json', '.bbmodel']:
                    file_info['has_parent'] = self.check_file_has_parent(file_path)
                
                self.all_files.append(file_info)
                
                ext = file_info['extension']
                if ext:
                    self.available_extensions.add(ext)
                    self.extension_data[ext].append(file_info)
    
    def check_file_has_parent(self, file_path):
        """Проверить, содержит ли файл поле 'parent'"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return '"parent":' in content
        except:
            return False
    
    def scan_archive(self, archive_path):
        """Сканирование архива"""
        if archive_path.lower().endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                for file_info in zip_ref.infolist():
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
                            'extension': os.path.splitext(file_name)[1].lower(),
                            'has_parent': False
                        }
                        
                        # Добавляем файлы без расширения в отдельную категорию
                        if not file_data['extension']:
                            file_data['extension'] = "(без расширения)"
                        
                        if file_data['extension'] in ['.json', '.bbmodel']:
                            try:
                                with zip_ref.open(file_info.filename) as f:
                                    content = f.read().decode('utf-8')
                                    file_data['has_parent'] = '"parent":' in content
                            except:
                                pass
                        
                        self.all_files.append(file_data)
                        
                        ext = file_data['extension']
                        if ext:
                            self.available_extensions.add(ext)
                            self.extension_data[ext].append(file_data)
        
        elif archive_path.lower().endswith('.rar'):
            try:
                import rarfile
                rarfile.UNRAR_TOOL = self.settings.get("unrar_path")
                with rarfile.RarFile(archive_path) as rar_ref:
                    for file_info in rar_ref.infolist():
                        if not file_info.isdir:
                            file_name = os.path.basename(file_info.filename)
                            file_path = file_info.filename
                            
                            file_data = {
                                'name': file_name,
                                'path': file_path,
                                'relative_path': file_path,
                                'archive_path': archive_path,
                                'size': file_info.file_size,
                                'modified': datetime.fromtimestamp(file_info.mtime),
                                'is_favorite': False,
                                'extension': os.path.splitext(file_name)[1].lower(),
                                'has_parent': False
                            }
                            
                            # Добавляем файлы без расширения в отдельную категорию
                            if not file_data['extension']:
                                file_data['extension'] = "(без расширения)"
                            
                            if file_data['extension'] in ['.json', '.bbmodel']:
                                try:
                                    with rar_ref.open(file_info.filename) as f:
                                        content = f.read().decode('utf-8')
                                        file_data['has_parent'] = '"parent":' in content
                                except:
                                    pass
                            
                            self.all_files.append(file_data)
                            
                            ext = file_data['extension']
                            if ext:
                                self.available_extensions.add(ext)
                                self.extension_data[ext].append(file_data)
            except ImportError:
                raise Exception("Для работы с RAR архивами установите библиотеку rarfile")
    
    def find_duplicates(self):
        """Найти дубликаты файлов и сгруппировать их"""
        self.duplicate_files.clear()
        
        file_groups = defaultdict(list)
        for file_info in self.all_files:
            key = file_info['name']
            file_groups[key].append(file_info)
        
        for filename, files in file_groups.items():
            if len(files) > 1:
                self.duplicate_files[filename] = files
    
    def on_scan_complete(self):
        """Завершение сканирования"""
        self.progress.stop()
        self.scan_btn.config(state=tk.NORMAL)
        
        self.update_extension_tree()
        self.refresh_tree()
        
        self.status_var.set(f"Сканирование завершено. Найдено файлов: {len(self.all_files)}")
    
    def on_scan_error(self, error_msg):
        """Ошибка сканирования"""
        self.progress.stop()
        self.scan_btn.config(state=tk.NORMAL)
        messagebox.showerror("Ошибка сканирования", f"Не удалось выполнить сканирование:\n{error_msg}")
        self.status_var.set("Ошибка сканирования")
    
    def update_extension_tree(self):
        """Обновление дерева расширений"""
        for item in self.extension_tree.get_children():
            self.extension_tree.delete(item)
        
        all_count = len(self.all_files)
        self.extension_tree.insert("", "end", text="Все расширения", values=(all_count,))
        
        # Добавляем файлы без расширения
        no_extension_count = len(self.extension_data.get("(без расширения)", []))
        if no_extension_count > 0:
            self.extension_tree.insert("", "end", text="(без расширения)", values=(no_extension_count,))
        
        for ext in sorted(self.available_extensions):
            if ext != "(без расширения)":
                count = len(self.extension_data[ext])
                self.extension_tree.insert("", "end", text=ext, values=(count,))
    
    def create_menu(self):
        """Создание меню приложения"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Файл", menu=file_menu)
        file_menu.add_command(label="Открыть папку...", command=self.browse_folder, accelerator="Ctrl+O")
        file_menu.add_command(label="Открыть архив...", command=self.browse_archive, accelerator="Ctrl+Shift+O")
        file_menu.add_separator()
        file_menu.add_command(label="Сканировать", command=self.scan_selected, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.root.quit)
        
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Настройки", menu=settings_menu)
        settings_menu.add_command(label="Папка для данных...", command=self.set_data_folder)
        settings_menu.add_command(label="Временная папка...", command=self.set_temp_folder)
        settings_menu.add_command(label="Путь к UnRAR...", command=self.set_unrar_path)
        settings_menu.add_separator()
        settings_menu.add_command(label="Сохранить настройки", command=self.save_settings)
        
        # Новая вкладка "Спец настройки"
        special_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Спец настройки", menu=special_menu)
        
        # Переменная для чекбокса "Скрыть дочерние файлы Blockbench"
        self.hide_bb_children_var = tk.BooleanVar(value=self.settings.get("hide_blockbench_children", True))
        
        special_menu.add_checkbutton(label="Скрыть дочерние файлы Blockbench", 
                                   variable=self.hide_bb_children_var,
                                   command=self.on_hide_bb_children_changed)
        special_menu.add_checkbutton(label="Группировать дубликаты", 
                                   variable=self.hide_duplicates_var,
                                   command=self.on_hide_duplicates_changed)
        special_menu.add_separator()
        special_menu.add_command(label="Очистить кэш поиска", command=self.clear_search_cache)
        
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Вид", menu=view_menu)
        view_menu.add_command(label="Сортировка", command=lambda: self.toggle_sorting(None))
        view_menu.add_command(label="Показать только избранное", command=self.toggle_favorites_filter)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Помощь", menu=help_menu)
        help_menu.add_command(label="О программе", command=self.show_about)
    
    def show_about(self):
        """Показать информацию о программе"""
        about_text = """Сканер папок
Версия: 5.5
Создатель: Akami_bl
Обратная связь: akami.bl@gmail.com

Основное:

📁 Сканирует папки и архивы (ZIP/RAR)

🗂️ Создает виртуальные папки - группирует файлы как хочешь

🔍 Ищет и фильтрует файлы по названию и содержимому

⭐ Добавляет файлы в избранное

Фишки:

🎨 Открывает файлы через стандартный диалог Windows

📊 Показывает дубликаты файлов

↩️ Отмена действий (Ctrl+Z) и повтор (Ctrl+Y)

🖱️ Выделение файлов перетаскиванием мыши

🔍 Поиск по содержимому файлов (текстовые файлы, JSON и др.)

Удобства:

Горячие клавиши

История недавних папок

Контекстное меню по правой кнопке

Сохраняет все настройки"""
        
        messagebox.showinfo("О программе", about_text)
    
    def set_data_folder(self):
        """Установить папку для данных"""
        path = filedialog.askdirectory(title="Выберите папку для данных")
        if path:
            self.settings["data_folder"] = path
            self.save_settings()
            messagebox.showinfo("Успех", f"Папка для данных установлена:\n{path}")
    
    def set_temp_folder(self):
        """Установить временную папку"""
        path = filedialog.askdirectory(title="Выберите временную папку")
        if path:
            self.settings["temp_folder"] = path
            self.save_settings()
            messagebox.showinfo("Успех", f"Временная папка установлена:\n{path}")
    
    def set_unrar_path(self):
        """Установить путь к UnRAR"""
        path = filedialog.askopenfilename(
            title="Выберите исполняемый файл UnRAR",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")]
        )
        if path:
            self.settings["unrar_path"] = path
            self.save_settings()
            messagebox.showinfo("Успех", f"Путь к UnRAR установлен:\n{path}")
    
    def browse_folder(self):
        """Выбор папки для сканирования"""
        folder_path = filedialog.askdirectory(title="Выберите папку для сканирования")
        if folder_path:
            self.folder_var.set(folder_path)
            self.scan_selected()
    
    def browse_archive(self):
        """Выбор архива для сканирования"""
        file_path = filedialog.askopenfilename(
            title="Выберите архив",
            filetypes=[
                ("Archives", "*.zip *.rar *.7z"),
                ("ZIP files", "*.zip"),
                ("RAR files", "*.rar"), 
                ("7z files", "*.7z"),
                ("All files", "*.*")
            ]
        )
        if file_path:
            self.folder_var.set(file_path)
            self.scan_selected()
    
    def check_settings(self):
        """Проверка и настройка необходимых параметров"""
        if not self.settings.get("temp_folder"):
            self.settings["temp_folder"] = tempfile.gettempdir()
        
        if not self.settings.get("data_folder"):
            home_dir = os.path.expanduser("~")
            data_dir = os.path.join(home_dir, "folder_scanner_data")
            os.makedirs(data_dir, exist_ok=True)
            self.settings["data_folder"] = data_dir
        
        self.save_settings()

def main():
    root = tk.Tk()
    app = FolderScannerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
[file content end]