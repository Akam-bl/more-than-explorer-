import os
import json
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
from collections import defaultdict
import zipfile
import tempfile
import shutil
import stat
import fnmatch
import threading
import re
import math
import shutil
from datetime import datetime

class FolderScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Сканер папок с виртуальными каталогами")
        self.root.geometry("1200x800")
        
        # Настройки по умолчанию
        self.settings = {
            "main_folder": "",
            "blockbench_path": "",
            "data_folder": "",
            "temp_folder": "",
            "scan_history": [],
            "unrar_path": "",
            "auto_load_textures": True,
            "sort_alphabetically": True,
            "archive_extensions": [".zip", ".rar", ".7z"],
            "hide_duplicates": False,
            "favorites": [],  # Добавляем список избранного
            "last_search": "",  # Сохраняем последний поисковый запрос
            "last_extension": ""  # Сохраняем последнее выбранное расширение
        }
        
        # Словарь переводов
        self.translations = {
            "models": "Модели",
            "textures": "Текстуры",
            "sounds": "Звуки",
            "lang": "Языки",
            "scripts": "Скрипты",
            "shaders": "Шейдеры",
            "structures": "Структуры",
            "worldgen": "Генерация мира",
            "functions": "Функции",
            "loot_tables": "Таблицы добычи",
            "predicates": "Предикаты",
            "item_modifiers": "Модификаторы предметов",
            "recipes": "Рецепты",
            "advancements": "Достижения",
            "tags": "Теги",
            "dimension": "Измерения",
            "dimension_type": "Типы измерений",
            "biome": "Биомы",
            "configured_carver": "Карверы",
            "configured_feature": "Особенности",
            "placed_feature": "Размещенные особенности",
            "configured_structure_feature": "Структурные особенности",
            "processor_list": "Списки обработчиков",
            "template_pool": "Пулы шаблонов",
            "noise_settings": "Настройки шума",
            "pack": "Пак",
            "data": "Данные",
            "assets": "Активы",
            "minecraft": "Minecraft",
            "custom": "Пользовательский",
            "blockstates": "Состояния блоков",
            "block_models": "Модели блоков",
            "item_models": "Модели предметов",
            "atlases": "Атласы",
            "font": "Шрифты",
            "gl_state": "Состояния GL",
            "post_effect": "Пост-эффекты",
            "particles": "Частицы",
            "animation_controllers": "Контроллеры анимации",
            "animations": "Анимации",
            "render_controllers": "Контроллеры отрисовки",
            "attachables": "Присоединяемые",
            "entity": "Сущности",
            "geometry": "Геометрия",
            "material": "Материалы",
            "fog": "Туман",
            "particle_effect": "Эффекты частиств",
            "animation": "Анимация",
            "render_controllers": "Контроллеры отрисовки",
            "texture_set": "Наборы текстур",
            "definition": "Определения",
            "client_entity": "Клиентские сущности",
            "server_entity": "Серверные сущности",
            "tick": "Тики",
            "load": "Загрузка",
            "criteria": "Критерии",
            "display": "Отображение",
            "parent": "Родитель",
            "elements": "Элементы",
            "textures": "Текстуры",
            "overrides": "Переопределения",
            "gui": "Интерфейс",
            "items": "Предметы",
            "blocks": "Блоки",
            "entities": "Сущности",
            "armor": "Броня",
            "elytra": "Элитры",
            "handheld": "В руках",
            "head": "Голова",
            "fixed": "Фиксированный",
            "ground": "На земле",
            "thirdperson_righthand": "От третьего лица в правой руке",
            "thirdperson_lefthand": "От третьего лица в левой руке",
            "firstperson_righthand": "От первого лица в правой руке",
            "firstperson_lefthand": "От первого лица в левой руке",
            "gui_light": "Свет интерфейса",
            "ambient": "Окружающий",
            "front": "Передний",
            "side": "Боковой"
        }
        
        # Категории файлов
        self.file_categories = {
            "models": [".json", ".bbmodel", ".model"],  # Добавляем .model
            "textures": [".png", ".jpg", ".jpeg", ".tga"],
            "sounds": [".ogg", ".wav", ".mp3"],
            "scripts": [".js", ".py", ".txt", ".mcfunction"],
            "other": []  # Все остальные файлы
        }
        
        # Переменные для хранения данных
        self.folder_data = defaultdict(list)
        self.virtual_folders = {}
        self.archive_data = {}  # Для хранения содержимого архивов
        self.available_extensions = set()  # Для хранения доступных расширений в текущем архиве
        self.duplicate_files = set()  # Для хранения имен дублирующихся файлов
        self.files_without_textures = set()  # Для хранения файлов без текстур
        self.all_files = []  # Все файлы для поиска
        self.extension_data = defaultdict(list)  # Файлы по расширениям
        
        # Переменные для перетаскивания
        self.drag_data = {"item": None, "x": 0, "y": 0}
        
        # Переменная для отслеживания инициализации дерева
        self.tree_initialized = False
        
        # Переменная для фильтра избранного
        self.show_favorites_only = False
        
        # Текущий фильтр расширения
        self.current_extension_filter = ""
        
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
            self.tree_initialized = True
    
    def setup_hotkeys(self):
        """Настройка горячих клавиш"""
        # Ctrl+O - открыть папку
        self.root.bind('<Control-o>', lambda e: self.browse_folder())
        # Ctrl+Shift+O - открыть архив
        self.root.bind('<Control-Shift-O>', lambda e: self.browse_archive())
        # Ctrl+R - обновить
        self.root.bind('<Control-r>', lambda e: self.refresh_tree())
        # Ctrl+S - сканировать
        self.root.bind('<Control-s>', lambda e: self.scan_selected())
        # F5 - обновить дерево
        self.root.bind('<F5>', lambda e: self.refresh_tree())
        # Delete - удалить выделенное
        self.root.bind('<Delete>', lambda e: self.delete_selected())
        # Ctrl+F - добавить в избранное
        self.root.bind('<Control-f>', lambda e: self.toggle_favorite())
    
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
                    
                    # Восстанавливаем последний поисковый запрос
                    if "last_search" in self.settings:
                        self.search_var.set(self.settings["last_search"])
                    
                    # Восстанавливаем последнее расширение
                    if "last_extension" in self.settings:
                        self.current_extension_filter = self.settings["last_extension"]
        except Exception as e:
            print(f"Не удалось загрузить настройки: {str(e)}")
    
    def save_settings(self):
        """Сохранение настроек в файл"""
        try:
            settings_path = self.get_settings_path()
            os.makedirs(os.path.dirname(settings_path), exist_ok=True)
            
            # Сохраняем текущий поисковый запрос и расширение
            self.settings["last_search"] = self.search_var.get()
            self.settings["last_extension"] = self.current_extension_filter
            
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
                
            data_folder = self.settings.get("data_folder")
            if data_folder and os.path.exists(data_folder):
                data_settings_path = os.path.join(data_folder, "folder_scanner_settings.json")
                with open(data_settings_path, 'w', encoding='utf-8') as f:
                    json.dump(self.settings, f, indent=2, ensure_ascii=False)
                    
        except Exception as e:
            messagebox.showerror("Ошибка сохранения настроек", f"Не удалось сохранить настройки: {str(e)}")
    
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
        
        self.browse_btn = ttk.Button(toolbar, text="Обзор папки...", command=self.browse_folder)
        self.browse_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.browse_archive_btn = ttk.Button(toolbar, text="Обзор архива...", command=self.browse_archive)
        self.browse_archive_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Поле поиска
        ttk.Label(toolbar, text="Поиск:").pack(side=tk.LEFT, padx=(10, 5))
        self.search_var = tk.StringVar(value=self.settings.get("last_search", ""))
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=(0, 10))
        self.search_entry.bind('<KeyRelease>', self.on_search_changed)
        
        self.sort_btn = ttk.Button(toolbar, text="A→Z", command=self.toggle_sorting)
        self.sort_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.update_sort_button_text()
        
        # Кнопка скрытия дубликатов
        self.hide_duplicates_var = tk.BooleanVar(value=self.settings.get("hide_duplicates", False))
        self.hide_duplicates_btn = ttk.Checkbutton(toolbar, text="Скрыть дубликаты", 
                                                  variable=self.hide_duplicates_var,
                                                  command=self.toggle_hide_duplicates)
        self.hide_duplicates_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Кнопка показа избранного
        self.favorites_btn = ttk.Button(toolbar, text="⭐", command=self.toggle_favorites_filter, width=3)
        self.favorites_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.scan_btn = ttk.Button(toolbar, text="Сканировать", command=self.scan_selected)
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.refresh_btn = ttk.Button(toolbar, text="Обновить", command=self.refresh_tree, state=tk.DISABLED)
        self.refresh_btn.pack(side=tk.LEFT)
        
        self.progress = ttk.Progressbar(toolbar, mode='indeterminate')
        self.progress.pack(side=tk.RIGHT, padx=(10, 0))
        
        # Панель с деревьями
        paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Левая панель - только расширения (категории убраны)
        left_frame = ttk.Frame(paned_window)
        paned_window.add(left_frame, weight=1)
        
        # Дерево расширений
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
        self.tree.bind('<<TreeviewOpen>>', self.on_tree_open)
        
        # Убираем привязки для перетаскивания
        self.tree.bind('<ButtonPress-1>', self.on_drag_start)
        self.tree.bind('<B1-Motion>', self.on_drag_motion)
        self.tree.bind('<ButtonRelease-1>', self.on_drag_release)
        
        # Убираем все теги подсветки
        # self.tree.tag_configure('missing_texture', background='#ffcccc')
        # self.tree.tag_configure('has_texture', background='#ccffcc')
        # self.tree.tag_configure('duplicate', background='#ffcc99')
        # self.tree.tag_configure('problem', background='#ff6666')
        # self.tree.tag_configure('favorite', background='#ffffcc')
        
        # Добавляем контекстное меню для дерева файлов
        self.tree_menu = tk.Menu(self.tree, tearoff=0)
        self.tree_menu.add_command(label="Открыть расположение файла", command=self.open_file_location)
        self.tree_menu.add_command(label="Добавить в избранное", command=self.toggle_favorite)
        self.tree.bind("<Button-3>", self.show_tree_context_menu)
        
        # Бинды для дерева расширений
        self.extension_tree.bind('<<TreeviewSelect>>', self.on_extension_select)
        
        # Настройка весов для растягивания
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
    
    def show_tree_context_menu(self, event):
        """Показать контекстное меню для дерева файлов"""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.tree_menu.post(event.x_root, event.y_root)
    
    def open_file_location(self):
        """Открыть расположение файла в проводнике"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        item = selected_items[0]
        item_values = self.tree.item(item, 'values')
        
        if len(item_values) >= 1:
            file_path = item_values[0]
            
            if os.path.exists(file_path):
                # Открываем папку, содержащую файл
                folder_path = os.path.dirname(file_path)
                try:
                    if os.name == 'nt':  # Windows
                        os.startfile(folder_path)
                    elif os.name == 'posix':  # Linux, macOS
                        subprocess.run(['xdg-open', folder_path])
                    self.status_var.set(f"Открыта папка: {folder_path}")
                except Exception as e:
                    messagebox.showerror("Ошибка", f"Не удалось открыть папку: {str(e)}")
            else:
                messagebox.showwarning("Предупреждение", "Файл не существует или путь недоступен")
    
    def on_search_changed(self, event):
        """Обработка изменения поискового запроса"""
        # Сохраняем поисковый запрос
        self.settings["last_search"] = self.search_var.get()
        self.save_settings()
        
        # Обновляем дерево с учетом текущих фильтров
        self.apply_filters()
    
    def on_extension_select(self, event):
        """Обработка выбора расширения"""
        selected = self.extension_tree.selection()
        if not selected:
            self.current_extension_filter = ""
        else:
            item = self.extension_tree.item(selected[0])
            self.current_extension_filter = item['text']
        
        # Сохраняем выбранное расширение
        self.settings["last_extension"] = self.current_extension_filter
        self.save_settings()
        
        # Обновляем дерево с учетом текущих фильтров
        self.apply_filters()
    
    def apply_filters(self):
        """Применить все активные фильтры"""
        if not hasattr(self, 'all_files') or not self.all_files:
            return
        
        # Начинаем со всех файлов
        filtered_files = self.all_files.copy()
        
        # Фильтр по расширению
        if self.current_extension_filter:
            filtered_files = [f for f in filtered_files if f.get('extension', '') == self.current_extension_filter]
        
        # Фильтр по избранному
        if self.show_favorites_only:
            favorites = self.settings.get("favorites", [])
            filtered_files = [f for f in filtered_files if f['path'] in favorites]
        
        # Фильтр по поисковому запросу
        search_text = self.search_var.get().lower().strip()
        if search_text:
            search_words = search_text.split()
            filtered_files = [f for f in filtered_files if 
                            any(word in f.get('name', '').lower() for word in search_words) or
                            any(word in f.get('path', '').lower() for word in search_words)]
        
        # Скрытие дубликатов
        if self.settings.get("hide_duplicates", False):
            seen_names = set()
            unique_files = []
            for file_info in filtered_files:
                if file_info['name'] not in seen_names:
                    unique_files.append(file_info)
                    seen_names.add(file_info['name'])
            filtered_files = unique_files
        
        # Сортировка
        if self.settings.get("sort_alphabetically", True):
            filtered_files.sort(key=lambda x: x['name'].lower())
        else:
            filtered_files.sort(key=lambda x: x['name'].lower(), reverse=True)
        
        # Показываем отфильтрованные файлы
        self.show_files_in_tree(filtered_files)
        self.status_var.set(f"Показано файлов: {len(filtered_files)}")
    
    def show_files_in_tree(self, files):
        """Показать файлы в дереве"""
        self.tree.delete(*self.tree.get_children())
        
        for file_info in files:
            file_path = file_info.get('path', '')
            file_name = file_info.get('name', '')
            file_type = file_info.get('type', '')
            file_size = file_info.get('size', 0)
            modified = file_info.get('modified', 0)
            is_favorite = file_path in self.settings.get("favorites", [])
            
            size_str = self.format_size(file_size)
            modified_str = self.format_timestamp(modified) if modified else ""
            
            # Убираем все теги подсветки, оставляем только базовые
            tags = ('file',)
            
            if is_favorite:
                tags = tags + ('favorite',)
            
            self.tree.insert('', 'end', text=file_name,
                           values=(file_path, '', file_type, size_str, modified_str, is_favorite),
                           tags=tags)
    
    def format_size(self, size_bytes):
        """Форматирование размера файла"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        
        return f"{s} {size_names[i]}"
    
    def format_timestamp(self, timestamp):
        """Форматирование временной метки"""
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    
    def toggle_hide_duplicates(self):
        """Переключить режим скрытия дубликатов"""
        self.settings["hide_duplicates"] = self.hide_duplicates_var.get()
        self.save_settings()
        self.apply_filters()
    
    def toggle_favorites_filter(self):
        """Переключить фильтр избранного"""
        self.show_favorites_only = not self.show_favorites_only
        if self.show_favorites_only:
            self.favorites_btn.config(text="⭐", style="Accent.TButton")
        else:
            self.favorites_btn.config(text="⭐")
        self.apply_filters()
    
    def update_sort_button_text(self):
        """Обновить текст кнопки сортировки"""
        if self.settings.get("sort_alphabetically", True):
            self.sort_btn.config(text="A→Z")
        else:
            self.sort_btn.config(text="Z→A")
    
    def toggle_sorting(self):
        """Переключить режим сортировки"""
        self.settings["sort_alphabetically"] = not self.settings.get("sort_alphabetically", True)
        self.save_settings()
        self.update_sort_button_text()
        self.apply_filters()
    
    def on_tree_select(self, event):
        """Обработка выбора элемента в дереве"""
        # Убрана логика подсветки текстур
        pass
    
    def update_folder_history(self):
        """Обновить выпадающий список историей папки"""
        scan_history = self.settings.get("scan_history", [])
        self.folder_combo['values'] = scan_history
        
        current_folder = self.settings.get("main_folder", "")
        if current_folder:
            self.folder_var.set(current_folder)
    
    def browse_folder(self):
        """Обзор папки"""
        folder = filedialog.askdirectory()
        if folder:
            self.folder_var.set(folder)
    
    def browse_archive(self):
        """Обзор архива"""
        archive_extensions = self.settings.get("archive_extensions", [".zip", ".rar", ".7z"])
        file_types = []
        
        if archive_extensions:
            extensions_str = " ".join([f"*{ext}" for ext in archive_extensions])
            file_types.append(("Архивы", extensions_str))
        
        file_types.extend([
            ("ZIP архивы", "*.zip"),
            ("RAR архивы", "*.rar"),
            ("7z архивы", "*.7z"),
            ("Все файлы", "*.*")
        ])
        
        file_path = filedialog.askopenfilename(
            title="Выберите архив",
            filetypes=file_types
        )
        if file_path:
            self.folder_var.set(file_path)
    
    def create_menu(self):
        """Создание меню приложения"""
        menubar = tk.Menu(self.root)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Настройки", command=self.show_settings, accelerator="Ctrl+P")
        file_menu.add_separator()
        file_menu.add_command(label="Очистить историе", command=self.clear_history)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.root.quit, accelerator="Ctrl+Q")
        menubar.add_cascade(label="Файл", menu=file_menu)
        
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Сканировать папку", command=lambda: self.scan_selected(), accelerator="Ctrl+S")
        tools_menu.add_command(label="Сканировать архив", command=lambda: self.scan_archive(), accelerator="Ctrl+Shift+S")
        tools_menu.add_command(label="Обновить дерево", command=self.refresh_tree, accelerator="F5")
        menubar.add_cascade(label="Инструменты", menu=tools_menu)
        
        favorites_menu = tk.Menu(menubar, tearoff=0)
        favorites_menu.add_command(label="Добавить в избранное", command=self.toggle_favorite, accelerator="Ctrl+F")
        favorites_menu.add_command(label="Показать только избранное", command=self.toggle_favorites_filter)
        favorites_menu.add_command(label="Очистить избранное", command=self.clear_favorites)
        menubar.add_cascade(label="Избранное", menu=favorites_menu)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="О программе", command=self.show_about)
        menubar.add_cascade(label="Справка", menu=help_menu)
        
        self.root.config(menu=menubar)
    
    def clear_history(self):
        """Очистить историю сканирования"""
        if messagebox.askyesno("Подтверждение", "Очистить историе сканированных папок?"):
            self.settings["scan_history"] = []
            self.save_settings()
            self.update_folder_history()
            self.status_var.set("История очищена")
    
    def clear_favorites(self):
        """Очистить избранное"""
        if messagebox.askyesno("Подтверждение", "Очистить все избранные файлы?"):
            self.settings["favorites"] = []
            self.save_settings()
            self.apply_filters()
            self.status_var.set("Избранное очищено")
    
    def check_settings(self):
        """Проверка настроек при запуске"""
        if not self.settings.get("main_folder"):
            self.show_settings()
        elif not self.settings.get("blockbench_path"):
            self.show_settings()
    
    def show_settings(self):
        """Показать диалог настроек"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Настройки")
        settings_window.geometry("700x600")
        settings_window.resizable(False, False)
        
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        notebook = ttk.Notebook(settings_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        main_frame = ttk.Frame(notebook, padding="10")
        notebook.add(main_frame, text="Основные")
        
        ttk.Label(main_frame, text="Основная папка:").grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
        main_folder_var = tk.StringVar(value=self.settings.get("main_folder", ""))
        main_folder_entry = ttk.Entry(main_frame, textvariable=main_folder_var, width=50)
        main_folder_entry.grid(row=0, column=1, padx=10, pady=10, sticky=tk.EW)
        
        def browse_main_folder():
            folder = filedialog.askdirectory()
            if folder:
                main_folder_var.set(folder)
        
        ttk.Button(main_frame, text="Обзор...", command=browse_main_folder).grid(row=0, column=2, padx=10, pady=10)
        
        ttk.Label(main_frame, text="Путь к Blockbench:").grid(row=1, column=0, padx=10, pady=10, sticky=tk.W)
        blockbench_var = tk.StringVar(value=self.settings.get("blockbench_path", ""))
        blockbench_entry = ttk.Entry(main_frame, textvariable=blockbench_var, width=50)
        blockbench_entry.grid(row=1, column=1, padx=10, pady=10, sticky=tk.EW)
        
        def browse_blockbench():
            file_path = filedialog.askopenfilename(
                title="Выберите Blockbench.exe",
                filetypes=[("Blockbench", "Blockbench.exe"), ("Все файлы", "*.*")]
            )
            if file_path:
                blockbench_var.set(file_path)
        
        ttk.Button(main_frame, text="Обзор...", command=browse_blockbench).grid(row=1, column=2, padx=10, pady=10)
        
        ttk.Label(main_frame, text="Папка для данных:").grid(row=2, column=0, padx=10, pady=10, sticky=tk.W)
        data_folder_var = tk.StringVar(value=self.settings.get("data_folder", ""))
        data_folder_entry = ttk.Entry(main_frame, textvariable=data_folder_var, width=50)
        data_folder_entry.grid(row=2, column=1, padx=10, pady=10, sticky=tk.EW)
        
        def browse_data_folder():
            folder = filedialog.askdirectory()
            if folder:
                data_folder_var.set(folder)
        
        ttk.Button(main_frame, text="Обзор...", command=browse_data_folder).grid(row=2, column=2, padx=10, pady=10)
        
        ttk.Label(main_frame, text="Временная папка:").grid(row=3, column=0, padx=10, pady=10, sticky=tk.W)
        temp_folder_var = tk.StringVar(value=self.settings.get("temp_folder", ""))
        temp_folder_entry = ttk.Entry(main_frame, textvariable=temp_folder_var, width=50)
        temp_folder_entry.grid(row=3, column=1, padx=10, pady=10, sticky=tk.EW)
        
        def browse_temp_folder():
            folder = filedialog.askdirectory()
            if folder:
                temp_folder_var.set(folder)
        
        ttk.Button(main_frame, text="Обзор...", command=browse_temp_folder).grid(row=3, column=2, padx=10, pady=10)
        
        # Настройки RAR
        rar_frame = ttk.Frame(notebook, padding="10")
        notebook.add(rar_frame, text="RAR архивы")
        
        ttk.Label(rar_frame, text="Путь к unrar:").grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
        unrar_var = tk.StringVar(value=self.settings.get("unrar_path", ""))
        unrar_entry = ttk.Entry(rar_frame, textvariable=unrar_var, width=50)
        unrar_entry.grid(row=0, column=1, padx=10, pady=10, sticky=tk.EW)
        
        def browse_unrar():
            file_path = filedialog.askopenfilename(
                title="Выберите unrar.exe",
                filetypes=[("UnRAR", "unrar.exe"), ("Все файлы", "*.*")]
            )
            if file_path:
                unrar_var.set(file_path)
        
        ttk.Button(rar_frame, text="Обзор...", command=browse_unrar).grid(row=0, column=2, padx=10, pady=10)
        
        # Кнопка автоматического поиска unrar
        def find_unrar_auto():
            unrar_path = self.find_unrar_automatically()
            if unrar_path:
                unrar_var.set(unrar_path)
                messagebox.showinfo("Найден unrar", f"Unrar найден: {unrar_path}")
            else:
                messagebox.showwarning("Unrar не найден", 
                    "Unrar не найден автоматически. Пожалуйста, укажите путь вручную.")
        
        ttk.Button(rar_frame, text="Найти unrar архив", command=find_unrar_auto).grid(row=1, column=0, columnspan=3, padx=10, pady=10)
        
        ttk.Label(rar_frame, text="Примечание: unrar.exe необходим для работы с RAR архивами").grid(row=2, column=0, columnspan=3, padx=10, pady=5, sticky=tk.W)
        
        # Настройки отображения
        display_frame = ttk.Frame(notebook, padding="10")
        notebook.add(display_frame, text="Отображение")
        
        auto_load_var = tk.BooleanVar(value=self.settings.get("auto_load_textures", True))
        auto_load_cb = ttk.Checkbutton(display_frame, text="Автоматически загружать текстуры", variable=auto_load_var)
        auto_load_cb.grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
        
        sort_var = tk.BooleanVar(value=self.settings.get("sort_alphabetically", True))
        sort_cb = ttk.Checkbutton(display_frame, text="Сортировать по алфавиту", variable=sort_var)
        sort_cb.grid(row=1, column=0, padx=10, pady=10, sticky=tk.W)
        
        hide_duplicates_var = tk.BooleanVar(value=self.settings.get("hide_duplicates", False))
        hide_duplicates_cb = ttk.Checkbutton(display_frame, text="Скрывать дубликаты файлов", variable=hide_duplicates_var)
        hide_duplicates_cb.grid(row=2, column=0, padx=10, pady=10, sticky=tk.W)
        
        def save_settings():
            self.settings.update({
                "main_folder": main_folder_var.get(),
                "blockbench_path": blockbench_var.get(),
                "data_folder": data_folder_var.get(),
                "temp_folder": temp_folder_var.get(),
                "unrar_path": unrar_var.get(),
                "auto_load_textures": auto_load_var.get(),
                "sort_alphabetically": sort_var.get(),
                "hide_duplicates": hide_duplicates_var.get()
            })
            
            self.save_settings()
            settings_window.destroy()
            
            if hasattr(self, 'tree'):
                self.apply_filters()
        
        def cancel_settings():
            settings_window.destroy()
        
        button_frame = ttk.Frame(settings_window)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(button_frame, text="Сохранить", command=save_settings).pack(side=tk.RIGHT, padx=(10, 0))
        ttk.Button(button_frame, text="Отмена", command=cancel_settings).pack(side=tk.RIGHT)
        
        main_frame.columnconfigure(1, weight=1)
        rar_frame.columnconfigure(1, weight=1)
    
    def find_unrar_automatically(self):
        """Автоматически найти unrar.exe в системе"""
        possible_paths = []
        
        # Проверяем стандартные пути установки WinRAR
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        
        # Пути WinRAR
        winrar_paths = [
            os.path.join(program_files, "WinRAR", "unrar.exe"),
            os.path.join(program_files_x86, "WinRAR", "unrar.exe"),
            os.path.join(program_files, "WinRAR", "UnRAR.exe"),
            os.path.join(program_files_x86, "WinRAR", "UnRAR.exe"),
            "C:\\WinRAR\\unrar.exe",
            "C:\\WinRAR\\UnRAR.exe"
        ]
        
        # Проверяем пути в переменной PATH
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)
        for path_dir in path_dirs:
            possible_paths.append(os.path.join(path_dir, "unrar.exe"))
            possible_paths.append(os.path.join(path_dir, "UnRAR.exe"))
        
        # Добавляем пути WinRAR
        possible_paths.extend(winrar_paths)
        
        # Проверяем все возможные пути
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        # Если не нашли в стандартных местах, ищем в текущей директории
        current_dir = os.path.dirname(os.path.abspath(__file__))
        local_paths = [
            os.path.join(current_dir, "unrar.exe"),
            os.path.join(current_dir, "UnRAR.exe"),
            os.path.join(os.getcwd(), "unrar.exe"),
            os.path.join(os.getcwd(), "UnRAR.exe")
        ]
        
        for path in local_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def show_about(self):
        """Показать информацию о программе"""
        about_text = """Сканер папок с виртуальными каталогами

Версия 2.0
Разработано для работы с моделями и текстурами

Разроботчик Akami_bl
Помощь: akami.bl@gmail.com

Возможности:
• Сканирование папок и архивов
• Создание виртуальных каталогов
• Автоматическое сопоставление моделей и текстур
• Работа с Blockbench
• Поддержка ZIP, RAR, 7z архивов
• Поиск и фильтрация файлов
• Избранные файлы"""
        
        messagebox.showinfo("О программе", about_text)
    
    def scan_selected(self):
        """Сканировать выбранную папку или архив"""
        selected_path = self.folder_var.get().strip()
        if not selected_path:
            messagebox.showwarning("Предупреждение", "Выберите папку или архив для сканирования")
            return
        
        if os.path.isdir(selected_path):
            self.scan_folder(selected_path)
        elif os.path.isfile(selected_path):
            self.scan_archive(selected_path)
        else:
            messagebox.showerror("Ошибка", "Выбранный путь не существует")
    
    def scan_folder(self, folder_path):
        """Сканировать папку"""
        if not os.path.exists(folder_path):
            messagebox.showerror("Ошибка", "Папка не существует")
            return
        
        self.progress.start()
        self.status_var.set("Сканирование...")
        
        def scan_thread():
            try:
                self.folder_data = defaultdict(list)
                self.virtual_folders = {}
                self.all_files = []
                self.extension_data = defaultdict(list)
                
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        relative_path = os.path.relpath(file_path, folder_path)
                        
                        file_info = {
                            'name': file,
                            'path': file_path,
                            'relative_path': relative_path,
                            'extension': os.path.splitext(file)[1].lower(),
                            'size': os.path.getsize(file_path),
                            'modified': os.path.getmtime(file_path),
                            'type': self.get_file_type(file)
                        }
                        
                        self.folder_data[root].append(file_info)
                        self.all_files.append(file_info)
                        self.extension_data[file_info['extension']].append(file_info)
                
                self.add_to_scan_history(folder_path)
                
                self.root.after(0, self.on_scan_complete)
                
            except Exception as e:
                self.root.after(0, lambda: self.on_scan_error(str(e)))
        
        threading.Thread(target=scan_thread, daemon=True).start()
    
    def scan_archive(self, archive_path):
        """Сканировать архив"""
        if not os.path.exists(archive_path):
            messagebox.showerror("Ошибка", "Архив не существует")
            return
        
        self.progress.start()
        self.status_var.set("Сканирование архива...")
        
        def scan_thread():
            try:
                self.folder_data = defaultdict(list)
                self.virtual_folders = {}
                self.all_files = []
                self.extension_data = defaultdict(list)
                self.archive_data = {}
                
                archive_ext = os.path.splitext(archive_path)[1].lower()
                
                if archive_ext == '.zip':
                    self.scan_zip_archive(archive_path)
                elif archive_ext == '.rar':
                    self.scan_rar_archive(archive_path)
                elif archive_ext == '.7z':
                    self.scan_7z_archive(archive_path)
                else:
                    self.root.after(0, lambda: messagebox.showerror("Ошибка", "Неподдерживаемый формат архива"))
                    return
                
                self.add_to_scan_history(archive_path)
                self.root.after(0, self.on_scan_complete)
                
            except Exception as e:
                self.root.after(0, lambda: self.on_scan_error(str(e)))
        
        threading.Thread(target=scan_thread, daemon=True).start()
    
    def scan_zip_archive(self, archive_path):
        """Сканировать ZIP архив"""
        import zipfile
        
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                if not file_info.is_dir():
                    file_name = os.path.basename(file_info.filename)
                    file_ext = os.path.splitext(file_name)[1].lower()
                    
                    archive_file_info = {
                        'name': file_name,
                        'path': file_info.filename,
                        'archive_path': archive_path,
                        'extension': file_ext,
                        'size': file_info.file_size,
                        'modified': self.get_zip_timestamp(file_info),
                        'type': self.get_file_type(file_name)
                    }
                    
                    folder_path = os.path.dirname(file_info.filename)
                    self.folder_data[folder_path].append(archive_file_info)
                    self.all_files.append(archive_file_info)
                    self.extension_data[file_ext].append(archive_file_info)
                    self.archive_data[file_info.filename] = archive_file_info
    
    def scan_rar_archive(self, archive_path):
        """Сканировать RAR архив"""
        unrar_path = self.settings.get("unrar_path")
        if not unrar_path or not os.path.exists(unrar_path):
            self.root.after(0, lambda: messagebox.showerror("Ошибка", "Путь к unrar не настроен или неверен"))
            return
        
        try:
            import rarfile
            rarfile.UNRAR_TOOL = unrar_path
            
            with rarfile.RarFile(archive_path) as rar_ref:
                for file_info in rar_ref.infolist():
                    if not file_info.isdir():
                        file_name = os.path.basename(file_info.filename)
                        file_ext = os.path.splitext(file_name)[1].lower()
                        
                        archive_file_info = {
                            'name': file_name,
                            'path': file_info.filename,
                            'archive_path': archive_path,
                            'extension': file_ext,
                            'size': file_info.file_size,
                            'modified': self.get_rar_timestamp(file_info),
                            'type': self.get_file_type(file_name)
                        }
                        
                        folder_path = os.path.dirname(file_info.filename)
                        self.folder_data[folder_path].append(archive_file_info)
                        self.all_files.append(archive_file_info)
                        self.extension_data[file_ext].append(archive_file_info)
                        self.archive_data[file_info.filename] = archive_file_info
                        
        except Exception as e:
            raise Exception(f"Ошибка чтения RAR архива: {str(e)}")
    
    def scan_7z_archive(self, archive_path):
        """Сканировать 7z архив"""
        try:
            import py7zr
            
            with py7zr.SevenZipFile(archive_path, mode='r') as sevenz_ref:
                for file_info in sevenz_ref.list():
                    if not file_info.is_directory:
                        file_name = os.path.basename(file_info.filename)
                        file_ext = os.path.splitext(file_name)[1].lower()
                        
                        archive_file_info = {
                            'name': file_name,
                            'path': file_info.filename,
                            'archive_path': archive_path,
                            'extension': file_ext,
                            'size': file_info.uncompressed,
                            'modified': self.get_7z_timestamp(file_info),
                            'type': self.get_file_type(file_name)
                        }
                        
                        folder_path = os.path.dirname(file_info.filename)
                        self.folder_data[folder_path].append(archive_file_info)
                        self.all_files.append(archive_file_info)
                        self.extension_data[file_ext].append(archive_file_info)
                        self.archive_data[file_info.filename] = archive_file_info
                        
        except Exception as e:
            raise Exception(f"Ошибка чтения 7z архива: {str(e)}")
    
    def get_zip_timestamp(self, zip_info):
        """Получить временную метку из ZIP информации"""
        # Приоритет: дата изменения > дата создания > текущее время
        timestamp = zip_info.date_time
        if timestamp:
            try:
                dt = datetime(*timestamp)
                return dt.timestamp()
            except:
                pass
        return datetime.now().timestamp()
    
    def get_rar_timestamp(self, rar_info):
        """Получить временную метку из RAR информации"""
        # RAR файлы обычно имеют временные метки
        if hasattr(rar_info, 'mtime') and rar_info.mtime:
            return rar_info.mtime.timestamp()
        return datetime.now().timestamp()
    
    def get_7z_timestamp(self, sevenz_info):
        """Получить временную метку из 7z информации"""
        if hasattr(sevenz_info, 'lastwritetime') and sevenz_info.lastwritetime:
            return sevenz_info.lastwritetime.timestamp()
        return datetime.now().timestamp()
    
    def get_file_type(self, filename):
        """Определить тип файла по расширению"""
        ext = os.path.splitext(filename)[1].lower()
        
        if ext in ['.json', '.bbmodel', '.model']:  # Добавляем .model
            return 'models'
        elif ext in ['.png', '.jpg', '.jpeg', '.tga']:
            return 'textures'
        elif ext in ['.ogg', '.wav', '.mp3']:
            return 'sounds'
        elif ext in ['.js', '.py', '.mcfunction']:
            return 'scripts'
        else:
            return 'other'
    
    def on_scan_complete(self):
        """Обработка завершения сканирования"""
        self.progress.stop()
        self.status_var.set(f"Сканирование завершено. Найдено файлов: {len(self.all_files)}")
        self.refresh_btn.config(state=tk.NORMAL)
        self.update_extension_tree()
        self.apply_filters()
    
    def on_scan_error(self, error_msg):
        """Обработка ошибки сканирования"""
        self.progress.stop()
        self.status_var.set("Ошибка сканирования")
        messagebox.showerror("Ошибка сканирования", f"Произошла ошибка при сканировании:\n{error_msg}")
    
    def update_extension_tree(self):
        """Обновить дерево расширений"""
        if not hasattr(self, 'extension_tree') or not self.extension_tree.winfo_exists():
            return
            
        self.extension_tree.delete(*self.extension_tree.get_children())
        
        for ext, files in sorted(self.extension_data.items()):
            if files:  # Показываем только расширения с файлами
                count = len(files)
                self.extension_tree.insert('', 'end', text=ext, values=(count,))
    
    def refresh_tree(self):
        """Обновить дерево файлов"""
        if hasattr(self, 'all_files') and self.all_files:
            self.apply_filters()
            self.status_var.set(f"Дерево обновлено. Файлов: {len(self.all_files)}")
        else:
            self.status_var.set("Нет данных для отображения")
    
    def on_tree_double_click(self, event):
        """Обработка двойного клика по дереву"""
        item = self.tree.selection()[0]
        if not item:
            return
        
        item_tags = self.tree.item(item, 'tags')
        item_values = self.tree.item(item, 'values')
        
        if len(item_values) >= 3:
            item_path = item_values[0]
            archive_path = item_values[1]
            item_type = item_values[2]
        
        if 'file' in item_tags or 'archive_file' in item_tags:
            if item_type == 'models':
                self.open_in_blockbench(item_path, archive_path)
            elif item_type == 'textures':
                self.open_texture(item_path, archive_path)
            else:
                self.open_file(item_path, archive_path)
    
    def on_tree_open(self, event):
        """Обработка открытия узла дерева"""
        item = self.tree.focus()
        if not item:
            return
    
    def open_in_blockbench(self, file_path, archive_path=None):
        """Открыть файл в Blockbench"""
        blockbench_path = self.settings.get("blockbench_path")
        if not blockbench_path or not os.path.exists(blockbench_path):
            messagebox.showerror("Ошибка", "Путь к Blockbench не настроен или неверен")
            return
        
        try:
            if archive_path:
                # Для архивных файлов нужно сначала извлечь во временную папку
                temp_dir = self.settings.get("temp_folder") or tempfile.gettempdir()
                os.makedirs(temp_dir, exist_ok=True)
                
                temp_file = os.path.join(temp_dir, os.path.basename(file_path))
                
                if archive_path.lower().endswith('.zip'):
                    import zipfile
                    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                        zip_ref.extract(file_path, temp_dir)
                        extracted_path = os.path.join(temp_dir, file_path)
                        if os.path.exists(extracted_path):
                            shutil.move(extracted_path, temp_file)
                
                elif archive_path.lower().endswith('.rar'):
                    import rarfile
                    rarfile.UNRAR_TOOL = self.settings.get("unrar_path")
                    with rarfile.RarFile(archive_path) as rar_ref:
                        rar_ref.extract(file_path, temp_dir)
                        extracted_path = os.path.join(temp_dir, file_path)
                        if os.path.exists(extracted_path):
                            shutil.move(extracted_path, temp_file)
                
                file_to_open = temp_file
            else:
                file_to_open = file_path
            
            # Добавляем поддержку файлов .model для Blockbench
            file_ext = os.path.splitext(file_to_open)[1].lower()
            if file_ext == '.model':
                # Blockbench может открывать .model файлы как JSON
                subprocess.Popen([blockbench_path, file_to_open])
            else:
                subprocess.Popen([blockbench_path, file_to_open])
                
            self.status_var.set(f"Открытие в Blockbench: {os.path.basename(file_path)}")
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл в Blockbench:\n{str(e)}")
    
    def open_texture(self, file_path, archive_path=None):
        """Открыть текстуру"""
        try:
            if archive_path:
                # Для архивных файлов нужно сначала извлечь во временную папку
                temp_dir = self.settings.get("temp_folder") or tempfile.gettempdir()
                os.makedirs(temp_dir, exist_ok=True)
                
                temp_file = os.path.join(temp_dir, os.path.basename(file_path))
                
                if archive_path.lower().endswith('.zip'):
                    import zipfile
                    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                        zip_ref.extract(file_path, temp_dir)
                        extracted_path = os.path.join(temp_dir, file_path)
                        if os.path.exists(extracted_path):
                            shutil.move(extracted_path, temp_file)
                
                elif archive_path.lower().endswith('.rar'):
                    import rarfile
                    rarfile.UNRAR_TOOL = self.settings.get("unrar_path")
                    with rarfile.RarFile(archive_path) as rar_ref:
                        rar_ref.extract(file_path, temp_dir)
                        extracted_path = os.path.join(temp_dir, file_path)
                        if os.path.exists(extracted_path):
                            shutil.move(extracted_path, temp_file)
                
                file_to_open = temp_file
            else:
                file_to_open = file_path
            
            # Открываем файл с помощью стандартной программы
            os.startfile(file_to_open)
            self.status_var.set(f"Открытие текстуры: {os.path.basename(file_path)}")
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть текстуру:\n{str(e)}")
    
    def open_file(self, file_path, archive_path=None):
        """Открыть файл стандартной программой"""
        try:
            if archive_path:
                # Для архивных файлов нужно сначала извлечь во временную папку
                temp_dir = self.settings.get("temp_folder") or tempfile.gettempdir()
                os.makedirs(temp_dir, exist_ok=True)
                
                temp_file = os.path.join(temp_dir, os.path.basename(file_path))
                
                if archive_path.lower().endswith('.zip'):
                    import zipfile
                    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                        zip_ref.extract(file_path, temp_dir)
                        extracted_path = os.path.join(temp_dir, file_path)
                        if os.path.exists(extracted_path):
                            shutil.move(extracted_path, temp_file)
                
                elif archive_path.lower().endswith('.rar'):
                    import rarfile
                    rarfile.UNRAR_TOOL = self.settings.get("unrar_path")
                    with rarfile.RarFile(archive_path) as rar_ref:
                        rar_ref.extract(file_path, temp_dir)
                        extracted_path = os.path.join(temp_dir, file_path)
                        if os.path.exists(extracted_path):
                            shutil.move(extracted_path, temp_file)
                
                file_to_open = temp_file
            else:
                file_to_open = file_path
            
            os.startfile(file_to_open)
            self.status_var.set(f"Открытие файла: {os.path.basename(file_path)}")
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{str(e)}")
    
    def on_drag_start(self, event):
        """Начало перетаскивания"""
        item = self.tree.identify_row(event.y)
        if item:
            self.drag_data["item"] = item
            self.drag_data["x"] = event.x
            self.drag_data["y"] = event.y
    
    def on_drag_motion(self, event):
        """Перетаскивание"""
        if self.drag_data["item"]:
            pass
    
    def on_drag_release(self, event):
        """Завершение перетаскивания"""
        if self.drag_data["item"]:
            self.drag_data["item"] = None
    
    def toggle_favorite(self):
        """Добавить/удалить из избранного"""
        if not hasattr(self, 'tree') or not self.tree.winfo_exists():
            return
            
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        favorites = self.settings.get("favorites", [])
        
        for item in selected_items:
            item_values = self.tree.item(item, 'values')
            if len(item_values) >= 1:
                file_path = item_values[0]
                
                if file_path in favorites:
                    favorites.remove(file_path)
                else:
                    favorites.append(file_path)
        
        self.settings["favorites"] = favorites
        self.save_settings()
        self.apply_filters()

def main():
    root = tk.Tk()
    app = FolderScannerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()