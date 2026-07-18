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
        self.root.geometry("1600x800")
        
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
            "favorites": [],
            "last_search": "",
            "last_extension": "",
            "hide_blockbench_children": True
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
            "models": [".json", ".bbmodel", ".model"],
            "textures": [".png", ".jpg", ".jpeg", ".tga"],
            "sounds": [".ogg", ".wav", ".mp3"],
            "scripts": [".js", ".py", ".txt", ".mcfunction"],
            "other": []
        }
        
        # Дочерние файлы Blockbench (будут скрыты если включена настройка)
        self.blockbench_child_files = [
            ".bbmodel", 
            ".png", 
            ".jpg", 
            ".jpeg", 
            "_texture.json",
            ".mcproject"
        ]
        
        # Переменные для хранения данных
        self.folder_data = defaultdict(list)
        self.virtual_folders = {}
        self.archive_data = {}
        self.available_extensions = set()
        self.duplicate_files = set()
        self.files_without_textures = set()
        self.all_files = []
        self.extension_data = defaultdict(list)
        self.all_folders = set()  # Для хранения всех папок
        
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
        # Ctrl+B - переключить скрытие дочерних файлов Blockbench
        self.root.bind('<Control-b>', lambda e: self.toggle_hide_blockbench_children())
    
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
                    # Сохраняем текущую папку данных если она есть
                    current_data_folder = self.settings.get("data_folder", "")
                    self.settings.update(loaded_settings)
                    # Восстанавливаем папку данных если она была установлена
                    if current_data_folder:
                        self.settings["data_folder"] = current_data_folder
                    
                    # Восстанавливаем последний поисковый запрос
                    if "last_search" in loaded_settings:
                        self.search_var.set(loaded_settings["last_search"])
                    
                    # Восстанавливаем последнее расширение
                    if "last_extension" in loaded_settings:
                        self.current_extension_filter = loaded_settings["last_extension"]
                    
                    # Восстанавливаем историю сканирования
                    if "scan_history" in loaded_settings:
                        self.settings["scan_history"] = loaded_settings["scan_history"]
                    
                    # Восстанавливаем избранное
                    if "favorites" in loaded_settings:
                        self.settings["favorites"] = loaded_settings["favorites"]
                    
                    print("Настройки загружены успешно")
            else:
                print("Файл настроек не найден, используются настройки по умолчанию")
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
                
            # Дублируем настройки в папку данных если она указана
            data_folder = self.settings.get("data_folder")
            if data_folder and os.path.exists(data_folder):
                data_settings_path = os.path.join(data_folder, "folder_scanner_settings.json")
                with open(data_settings_path, 'w', encoding='utf-8') as f:
                    json.dump(self.settings, f, indent=2, ensure_ascii=False)
                    
            print("Настройки сохранены успешно")
            
        except Exception as e:
            print(f"Ошибка сохранения настроек: {str(e)}")
            messagebox.showerror("Ошибка сохранения настроек", f"Не удалось сохранить настройки: {str(e)}")
    
    def add_to_scan_history(self, folder_path):
        """Добавить папку в истории сканирования"""
        if not folder_path:
            return
            
        scan_history = self.settings.get("scan_history", [])
        
        if folder_path in scan_history:
            scan_history.remove(folder_path)
        
        scan_history.insert(0, folder_path)
        # Ограничиваем историю 10 элементами
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
        
        # Кнопка скрытия дочерних файлов Blockbench
        self.hide_bb_children_var = tk.BooleanVar(value=self.settings.get("hide_blockbench_children", True))
        self.hide_bb_children_btn = ttk.Checkbutton(toolbar, text="Скрыть дочерние BB", 
                                                   variable=self.hide_bb_children_var,
                                                   command=self.toggle_hide_blockbench_children)
        self.hide_bb_children_btn.pack(side=tk.LEFT, padx=(0, 10))
        
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
        
        # Убираем привязки для перетаскивания
        self.tree.bind('<ButtonPress-1>', self.on_drag_start)
        self.tree.bind('<B1-Motion>', self.on_drag_motion)
        self.tree.bind('<ButtonRelease-1>', self.on_drag_release)
        
        # Добавляем контекстное меню для дерева файлов
        self.tree_menu = tk.Menu(self.tree, tearoff=0)
        self.tree_menu.add_command(label="Открыть расположение файла", command=self.open_file_location)
        self.tree_menu.add_command(label="Открыть с помощью...", command=self.open_file_with)
        self.tree_menu.add_command(label="Переименовать", command=self.rename_file)
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
    
    def on_folder_selected(self, event):
        """Обработка выбора папки из истории"""
        selected_folder = self.folder_var.get()
        if selected_folder and os.path.exists(selected_folder):
            self.folder_var.set(selected_folder)
    
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
    
    def open_file_with(self):
        """Открыть файл с помощью выбранного приложения"""
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
                if archive_path:
                    temp_dir = self.settings.get("temp_folder") or tempfile.gettempdir()
                    os.makedirs(temp_dir, exist_ok=True)
                    
                    temp_file = os.path.join(temp_dir, os.path.basename(file_path))
                    
                    if archive_path.lower().endswith('.zip'):
                        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                            zip_ref.extract(file_path, temp_dir)
                            extracted_path = os.path.join(temp_dir, file_path)
                            if os.path.exists(extracted_path):
                                shutil.move(extracted_path, temp_file)
                    
                    elif archive_path.lower().endswith('.rar'):
                        try:
                            import rarfile
                            rarfile.UNRAR_TOOL = self.settings.get("unrar_path")
                            with rarfile.RarFile(archive_path) as rar_ref:
                                rar_ref.extract(file_path, temp_dir)
                                extracted_path = os.path.join(temp_dir, file_path)
                                if os.path.exists(extracted_path):
                                    shutil.move(extracted_path, temp_file)
                        except ImportError:
                            messagebox.showerror("Ошибка", "Для работы с RAR архивами установите библиотеку rarfile")
                            return
                    
                    file_to_open = temp_file
                else:
                    file_to_open = file_path
                
                # Используем стандартный диалог Windows "Открыть с помощью"
                if os.name == 'nt':  # Windows
                    os.system(f'rundll32.exe shell32.dll,OpenAs_RunDLL "{file_to_open}"')
                else:  # Linux, macOS - альтернативный вариант
                    subprocess.run(['xdg-open', file_to_open])
                
                self.status_var.set(f"Открытие файла с помощью: {os.path.basename(file_path)}")
                
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{str(e)}")
    
    def rename_file(self):
        """Переименовать выбранный файл"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        item = selected_items[0]
        item_values = self.tree.item(item, 'values')
        
        if len(item_values) >= 1:
            old_file_path = item_values[0]
            archive_path = item_values[1] if len(item_values) > 1 else None
            
            # Если файл находится в архиве, нельзя его переименовать
            if archive_path:
                messagebox.showwarning("Предупреждение", "Нельзя переименовать файлы внутри архивов")
                return
            
            if not os.path.exists(old_file_path):
                messagebox.showwarning("Предупреждение", "Файл не существует или путь недоступен")
                return
            
            old_filename = os.path.basename(old_file_path)
            old_dir = os.path.dirname(old_file_path)
            
            # Запрашиваем новое имя файла
            new_filename = simpledialog.askstring(
                "Переименовать файл", 
                "Введите новое имя файла:",
                initialvalue=old_filename
            )
            
            if not new_filename:
                return  # Пользователь отменил операцию
            
            if new_filename == old_filename:
                return  # Имя не изменилось
            
            new_file_path = os.path.join(old_dir, new_filename)
            
            # Проверяем, не существует ли уже файл с таким именем
            if os.path.exists(new_file_path):
                messagebox.showerror("Ошибка", f"Файл с именем '{new_filename}' уже существует")
                return
            
            try:
                # Переименовываем файл
                os.rename(old_file_path, new_file_path)
                
                # Обновляем информацию в дереве
                self.tree.item(item, text=new_filename, values=(new_file_path,) + item_values[1:])
                
                # Обновляем информацию в all_files
                for file_info in self.all_files:
                    if file_info['path'] == old_file_path:
                        file_info['path'] = new_file_path
                        file_info['name'] = new_filename
                        break
                
                # Обновляем избранное если файл был в избранном
                favorites = self.settings.get("favorites", [])
                if old_file_path in favorites:
                    favorites.remove(old_file_path)
                    favorites.append(new_file_path)
                    self.settings["favorites"] = favorites
                    self.save_settings()
                
                self.status_var.set(f"Файл переименован: {old_filename} -> {new_filename}")
                
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось переименовать файл:\n{str(e)}")
    
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
        
        # Скрытие дочерних файлов Blockbench
        if self.settings.get("hide_blockbench_children", True):
            filtered_files = [f for f in filtered_files if not self.is_blockbench_child_file(f)]
        
        # Сортировка
        if self.settings.get("sort_alphabetically", True):
            filtered_files.sort(key=lambda x: x['name'].lower())
        else:
            filtered_files.sort(key=lambda x: x['name'].lower(), reverse=True)
        
        # Показываем отфильтрованные файлы
        self.show_files_in_tree(filtered_files)
        self.status_var.set(f"Показано файлов: {len(filtered_files)}")
    
    def is_blockbench_child_file(self, file_info):
        """Проверить, является ли файл дочерним файлом Blockbench"""
        filename = file_info.get('name', '').lower()
        filepath = file_info.get('path', '').lower()
        
        # Проверяем расширения файлов
        for ext in self.blockbench_child_files:
            if filename.endswith(ext):
                return True
        
        # Проверяем специальные имена файлов
        if '_texture.json' in filename:
            return True
        
        # Проверяем пути, содержащие специфичные для Blockbench папки
        blockbench_folders = ['textures', 'models', 'blockbench']
        for folder in blockbench_folders:
            if f'/{folder}/' in filepath.replace('\\', '/'):
                return True
        
        return False
    
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
    
    def toggle_hide_blockbench_children(self):
        """Переключить режим скрытия дочерних файлов Blockbench"""
        self.settings["hide_blockbench_children"] = self.hide_bb_children_var.get()
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
        selected_items = self.tree.selection()
        if selected_items:
            item = selected_items[0]
            item_values = self.tree.item(item, 'values')
            if item_values:
                file_path = item_values[0]
                self.status_var.set(f"Выбран: {file_path}")
    
    def on_tree_double_click(self, event):
        """Обработка двойного клика по элементу дерева"""
        item = self.tree.identify_row(event.y)
        if item:
            item_values = self.tree.item(item, 'values')
            if item_values and len(item_values) > 0:
                file_path = item_values[0]
                archive_path = item_values[1] if len(item_values) > 1 else None
                
                # Проверяем, является ли элемент папкой
                if self.tree.item(item, 'text').endswith('/'):
                    # Это папка - раскрываем/скрываем
                    if self.tree.get_children(item):
                        if self.tree.item(item, 'open'):
                            self.tree.item(item, open=False)
                        else:
                            self.tree.item(item, open=True)
                else:
                    # Это файл - открываем
                    self.open_file(file_path, archive_path)
    
    def open_file(self, file_path, archive_path=None):
        """Открыть файл в ассоциированном приложении"""
        try:
            if archive_path:
                # Файл в архиве - извлекаем во временную папку
                temp_dir = self.settings.get("temp_folder") or tempfile.gettempdir()
                os.makedirs(temp_dir, exist_ok=True)
                
                temp_file = os.path.join(temp_dir, os.path.basename(file_path))
                
                if archive_path.lower().endswith('.zip'):
                    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                        zip_ref.extract(file_path, temp_dir)
                        extracted_path = os.path.join(temp_dir, file_path)
                        if os.path.exists(extracted_path):
                            shutil.move(extracted_path, temp_file)
                
                elif archive_path.lower().endswith('.rar'):
                    try:
                        import rarfile
                        rarfile.UNRAR_TOOL = self.settings.get("unrar_path")
                        with rarfile.RarFile(archive_path) as rar_ref:
                            rar_ref.extract(file_path, temp_dir)
                            extracted_path = os.path.join(temp_dir, file_path)
                            if os.path.exists(extracted_path):
                                shutil.move(extracted_path, temp_file)
                    except ImportError:
                        messagebox.showerror("Ошибка", "Для работы с RAR архивами установите библиотеку rarfile")
                        return
                
                file_to_open = temp_file
            else:
                file_to_open = file_path
            
            # Открываем файл в ассоциированном приложении
            if os.name == 'nt':  # Windows
                os.startfile(file_to_open)
            elif os.name == 'posix':  # Linux, macOS
                subprocess.run(['xdg-open', file_to_open])
            
            self.status_var.set(f"Открыт файл: {os.path.basename(file_path)}")
            
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
        """Перемещение при перетаскивании"""
        pass  # Отключаем функционал перетаскивания
    
    def on_drag_release(self, event):
        """Завершение перетаскивания"""
        self.drag_data["item"] = None
        self.drag_data["x"] = 0
        self.drag_data["y"] = 0
    
    def create_menu(self):
        """Создание меню приложения"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # Меню Файл
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Файл", menu=file_menu)
        file_menu.add_command(label="Открыть папку...", command=self.browse_folder, accelerator="Ctrl+O")
        file_menu.add_command(label="Открыть архив...", command=self.browse_archive, accelerator="Ctrl+Shift+O")
        file_menu.add_separator()
        file_menu.add_command(label="Сканировать", command=self.scan_selected, accelerator="Ctrl+S")
        file_menu.add_command(label="Обновить", command=self.refresh_tree, accelerator="F5")
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.root.quit)
        
        # Меню Настройки
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Настройки", menu=settings_menu)
        settings_menu.add_command(label="Настройки приложения...", command=self.show_settings)
        settings_menu.add_command(label="Настройки Blockbench...", command=self.show_blockbench_settings)
        settings_menu.add_command(label="Настройки UnRAR...", command=self.show_unrar_settings)
        
        # Меню Вид
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Вид", menu=view_menu)
        view_menu.add_checkbutton(label="Сортировка A-Z", variable=tk.BooleanVar(value=self.settings.get("sort_alphabetically", True)), command=self.toggle_sorting)
        view_menu.add_checkbutton(label="Скрыть дубликаты", variable=self.hide_duplicates_var, command=self.toggle_hide_duplicates)
        view_menu.add_checkbutton(label="Скрыть дочерние файлы Blockbench", variable=self.hide_bb_children_var, command=self.toggle_hide_blockbench_children)
        view_menu.add_separator()
        view_menu.add_command(label="Очистить историю сканирования", command=self.clear_scan_history)
        
        # Меню Помощь
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Помощь", menu=help_menu)
        help_menu.add_command(label="О программе", command=self.show_about)
    
    def browse_folder(self):
        """Выбор папки для сканирования"""
        folder_path = filedialog.askdirectory(title="Выберите папку для сканирования")
        if folder_path:
            self.folder_var.set(folder_path)
            self.add_to_scan_history(folder_path)
            self.scan_selected()
    
    def browse_archive(self):
        """Выбор архива для сканирования"""
        file_types = [
            ("Архивы", "*.zip *.rar *.7z"),
            ("ZIP архивы", "*.zip"),
            ("RAR архивы", "*.rar"),
            ("7z архивы", "*.7z"),
            ("Все файлы", "*.*")
        ]
        
        archive_path = filedialog.askopenfilename(
            title="Выберите архив для сканирования",
            filetypes=file_types
        )
        
        if archive_path:
            self.folder_var.set(archive_path)
            self.add_to_scan_history(archive_path)
            self.scan_selected()
    
    def scan_selected(self):
        """Сканирование выбранной папки или архива"""
        selected_path = self.folder_var.get()
        if not selected_path:
            messagebox.showwarning("Предупреждение", "Выберите папку или архив для сканирования")
            return
        
        if not os.path.exists(selected_path):
            messagebox.showerror("Ошибка", "Выбранный путь не существует")
            return
        
        # Показываем прогресс
        self.progress.start()
        self.status_var.set("Сканирование...")
        self.root.update()
        
        # Запускаем сканирование в отдельном потоке
        threading.Thread(target=self.perform_scan, args=(selected_path,), daemon=True).start()
    
    def perform_scan(self, scan_path):
        """Выполнить сканирование папки или архива"""
        try:
            self.folder_data = defaultdict(list)
            self.virtual_folders = {}
            self.archive_data = {}
            self.available_extensions = set()
            self.duplicate_files = set()
            self.files_without_textures = set()
            self.all_files = []
            self.extension_data = defaultdict(list)
            self.all_folders = set()
            
            if os.path.isdir(scan_path):
                # Сканирование папки
                self.scan_folder(scan_path)
            elif zipfile.is_zipfile(scan_path):
                # Сканирование ZIP архива
                self.scan_zip_archive(scan_path)
            elif scan_path.lower().endswith('.rar'):
                # Сканирование RAR архива
                self.scan_rar_archive(scan_path)
            elif scan_path.lower().endswith('.7z'):
                # Сканирование 7z архива
                self.scan_7z_archive(scan_path)
            else:
                self.root.after(0, lambda: messagebox.showerror("Ошибка", "Неподдерживаемый формат файла"))
                return
            
            # Обновляем интерфейс в основном потоке
            self.root.after(0, self.on_scan_complete)
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Ошибка", f"Ошибка сканирования: {str(e)}"))
            self.root.after(0, self.on_scan_error)
    
    def scan_folder(self, folder_path):
        """Сканирование обычной папки"""
        for root, dirs, files in os.walk(folder_path):
            # Добавляем папки в список всех папок
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                self.all_folders.add(dir_path)
            
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, folder_path)
                
                # Получаем информацию о файле
                try:
                    stat_info = os.stat(file_path)
                    file_size = stat_info.st_size
                    modified = stat_info.st_mtime
                except:
                    file_size = 0
                    modified = 0
                
                file_info = {
                    'name': file,
                    'path': file_path,
                    'relative_path': relative_path,
                    'size': file_size,
                    'modified': modified,
                    'extension': os.path.splitext(file)[1].lower(),
                    'type': 'file',
                    'archive_path': None
                }
                
                self.all_files.append(file_info)
                self.available_extensions.add(file_info['extension'])
                self.extension_data[file_info['extension']].append(file_info)
        
        # Создаем виртуальные папки
        self.create_virtual_folders()
    
    def scan_zip_archive(self, archive_path):
        """Сканирование ZIP архива"""
        try:
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                for file_info in zip_ref.infolist():
                    if not file_info.is_dir():
                        file_name = os.path.basename(file_info.filename)
                        file_path = file_info.filename
                        
                        file_data = {
                            'name': file_name,
                            'path': file_path,
                            'relative_path': file_path,
                            'size': file_info.file_size,
                            'modified': self.get_zip_timestamp(file_info),
                            'extension': os.path.splitext(file_name)[1].lower(),
                            'type': 'file',
                            'archive_path': archive_path
                        }
                        
                        self.all_files.append(file_data)
                        self.available_extensions.add(file_data['extension'])
                        self.extension_data[file_data['extension']].append(file_data)
                
                # Создаем виртуальные папки
                self.create_virtual_folders()
                
        except Exception as e:
            raise Exception(f"Ошибка чтения ZIP архива: {str(e)}")
    
    def get_zip_timestamp(self, zip_info):
        """Получить временную метку из ZIP информации"""
        # Пытаемся получить дату из разных полей
        date_time = zip_info.date_time
        if date_time:
            try:
                # Формат: (год, месяц, день, час, минута, секунда)
                dt = datetime(*date_time)
                return dt.timestamp()
            except:
                pass
        
        return 0
    
    def scan_rar_archive(self, archive_path):
        """Сканирование RAR архива"""
        try:
            import rarfile
            
            # Устанавливаем путь к unrar если указан
            if self.settings.get("unrar_path"):
                rarfile.UNRAR_TOOL = self.settings["unrar_path"]
            
            with rarfile.RarFile(archive_path) as rar_ref:
                for file_info in rar_ref.infolist():
                    if not file_info.isdir():
                        file_name = os.path.basename(file_info.filename)
                        file_path = file_info.filename
                        
                        file_data = {
                            'name': file_name,
                            'path': file_path,
                            'relative_path': file_path,
                            'size': file_info.file_size,
                            'modified': self.get_rar_timestamp(file_info),
                            'extension': os.path.splitext(file_name)[1].lower(),
                            'type': 'file',
                            'archive_path': archive_path
                        }
                        
                        self.all_files.append(file_data)
                        self.available_extensions.add(file_data['extension'])
                        self.extension_data[file_data['extension']].append(file_data)
                
                # Создаем виртуальные папки
                self.create_virtual_folders()
                
        except ImportError:
            raise Exception("Для работы с RAR архивами установите библиотеку rarfile: pip install rarfile")
        except Exception as e:
            raise Exception(f"Ошибка чтения RAR архива: {str(e)}")
    
    def get_rar_timestamp(self, rar_info):
        """Получить временную метку из RAR информации"""
        try:
            return rar_info.mtime.timestamp()
        except:
            return 0
    
    def scan_7z_archive(self, archive_path):
        """Сканирование 7z архива"""
        try:
            import py7zr
            
            with py7zr.SevenZipFile(archive_path, mode='r') as seven_zip_ref:
                for file_info in seven_zip_ref.list():
                    if not file_info.is_directory:
                        file_name = os.path.basename(file_info.filename)
                        file_path = file_info.filename
                        
                        file_data = {
                            'name': file_name,
                            'path': file_path,
                            'relative_path': file_path,
                            'size': file_info.uncompressed,
                            'modified': self.get_7z_timestamp(file_info),
                            'extension': os.path.splitext(file_name)[1].lower(),
                            'type': 'file',
                            'archive_path': archive_path
                        }
                        
                        self.all_files.append(file_data)
                        self.available_extensions.add(file_data['extension'])
                        self.extension_data[file_data['extension']].append(file_data)
                
                # Создаем виртуальные папки
                self.create_virtual_folders()
                
        except ImportError:
            raise Exception("Для работы с 7z архивами установите библиотеку py7zr: pip install py7zr")
        except Exception as e:
            raise Exception(f"Ошибка чтения 7z архива: {str(e)}")
    
    def get_7z_timestamp(self, seven_zip_info):
        """Получить временную метку из 7z информации"""
        try:
            if hasattr(seven_zip_info, 'lastwritetime'):
                return seven_zip_info.lastwritetime.timestamp()
        except:
            pass
        return 0
    
    def create_virtual_folders(self):
        """Создание виртуальных папок на основе структуры файлов"""
        # В этой версии не используем виртуальные папки для категорий
        # Вместо этого группируем только по расширениям
        pass
    
    def on_scan_complete(self):
        """Завершение сканирования"""
        self.progress.stop()
        
        # Обновляем дерево расширений
        self.update_extension_tree()
        
        # Применяем фильтры для показа файлов
        self.apply_filters()
        
        # Активируем кнопку обновления
        self.refresh_btn.config(state=tk.NORMAL)
        
        self.status_var.set(f"Сканирование завершено. Найдено файлов: {len(self.all_files)}")
    
    def on_scan_error(self):
        """Обработка ошибки сканирования"""
        self.progress.stop()
        self.status_var.set("Ошибка сканирования")
    
    def update_extension_tree(self):
        """Обновление дерева расширений"""
        self.extension_tree.delete(*self.extension_tree.get_children())
        
        # Сортируем расширения по количеству файлов
        sorted_extensions = sorted(self.extension_data.items(), 
                                 key=lambda x: len(x[1]), 
                                 reverse=True)
        
        for extension, files in sorted_extensions:
            count = len(files)
            if extension == "":
                display_name = "Без расширения"
            else:
                display_name = extension
            
            self.extension_tree.insert('', 'end', text=display_name, values=(count,))
    
    def refresh_tree(self):
        """Обновление дерева файлов"""
        if self.folder_var.get():
            self.scan_selected()
        else:
            messagebox.showwarning("Предупреждение", "Не выбрана папка для сканирования")
    
    def update_folder_history(self):
        """Обновление истории папок в комбобоксе"""
        scan_history = self.settings.get("scan_history", [])
        self.folder_combo['values'] = scan_history
    
    def clear_scan_history(self):
        """Очистка истории сканирования"""
        if messagebox.askyesno("Подтверждение", "Очистить историю сканирования?"):
            self.settings["scan_history"] = []
            self.save_settings()
            self.update_folder_history()
            self.folder_var.set("")
    
    def check_settings(self):
        """Проверка и настройка параметров приложения"""
        # Создаем временную папку если не существует
        temp_folder = self.settings.get("temp_folder")
        if not temp_folder:
            temp_folder = os.path.join(tempfile.gettempdir(), "folder_scanner")
            self.settings["temp_folder"] = temp_folder
        
        if not os.path.exists(temp_folder):
            os.makedirs(temp_folder)
        
        # Создаем папку данных если не существует
        data_folder = self.settings.get("data_folder")
        if not data_folder:
            data_folder = os.path.join(os.path.expanduser("~"), "folder_scanner_data")
            self.settings["data_folder"] = data_folder
        
        if not os.path.exists(data_folder):
            os.makedirs(data_folder)
        
        self.save_settings()
    
    def show_settings(self):
        """Показать настройки приложения"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Настройки приложения")
        settings_window.geometry("500x400")
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        main_frame = ttk.Frame(settings_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Папка данных
        ttk.Label(main_frame, text="Папка данных:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        data_frame = ttk.Frame(main_frame)
        data_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        data_var = tk.StringVar(value=self.settings.get("data_folder", ""))
        data_entry = ttk.Entry(data_frame, textvariable=data_var, width=50)
        data_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_data_folder():
            folder = filedialog.askdirectory(title="Выберите папку для данных")
            if folder:
                data_var.set(folder)
        
        ttk.Button(data_frame, text="Обзор...", command=browse_data_folder).pack(side=tk.RIGHT)
        
        # Временная папка
        ttk.Label(main_frame, text="Временная папка:").grid(row=2, column=0, sticky=tk.W, pady=(0, 5))
        temp_frame = ttk.Frame(main_frame)
        temp_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        temp_var = tk.StringVar(value=self.settings.get("temp_folder", ""))
        temp_entry = ttk.Entry(temp_frame, textvariable=temp_var, width=50)
        temp_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_temp_folder():
            folder = filedialog.askdirectory(title="Выберите временную папку")
            if folder:
                temp_var.set(folder)
        
        ttk.Button(temp_frame, text="Обзор...", command=browse_temp_folder).pack(side=tk.RIGHT)
        
        # Автозагрузка текстур
        auto_load_var = tk.BooleanVar(value=self.settings.get("auto_load_textures", True))
        ttk.Checkbutton(main_frame, text="Автозагрузка текстур для моделей", 
                       variable=auto_load_var).grid(row=4, column=0, sticky=tk.W, pady=(0, 10))
        
        # Кнопки сохранения/отмены
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=10, column=0, columnspan=2, pady=(20, 0))
        
        def save_settings():
            self.settings["data_folder"] = data_var.get()
            self.settings["temp_folder"] = temp_var.get()
            self.settings["auto_load_textures"] = auto_load_var.get()
            self.save_settings()
            settings_window.destroy()
            messagebox.showinfo("Настройки", "Настройки сохранены успешно")
        
        ttk.Button(button_frame, text="Сохранить", command=save_settings).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Отмена", command=settings_window.destroy).pack(side=tk.LEFT)
    
    def show_blockbench_settings(self):
        """Показать настройки Blockbench"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Настройки Blockbench")
        settings_window.geometry("400x200")
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        main_frame = ttk.Frame(settings_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text="Путь к Blockbench:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        bb_frame = ttk.Frame(main_frame)
        bb_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        bb_var = tk.StringVar(value=self.settings.get("blockbench_path", ""))
        bb_entry = ttk.Entry(bb_frame, textvariable=bb_var, width=50)
        bb_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_blockbench():
            file_path = filedialog.askopenfilename(
                title="Выберите исполняемый файл Blockbench",
                filetypes=[("Исполняемые файлы", "*.exe"), ("Все файлы", "*.*")]
            )
            if file_path:
                bb_var.set(file_path)
        
        ttk.Button(bb_frame, text="Обзор...", command=browse_blockbench).pack(side=tk.RIGHT)
        
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=10, column=0, columnspan=2, pady=(20, 0))
        
        def save_settings():
            self.settings["blockbench_path"] = bb_var.get()
            self.save_settings()
            settings_window.destroy()
            messagebox.showinfo("Настройки", "Настройки Blockbench сохранены")
        
        ttk.Button(button_frame, text="Сохранить", command=save_settings).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Отмена", command=settings_window.destroy).pack(side=tk.LEFT)
    
    def show_unrar_settings(self):
        """Показать настройки UnRAR"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Настройки UnRAR")
        settings_window.geometry("400x200")
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        main_frame = ttk.Frame(settings_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text="Путь к UnRAR:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        unrar_frame = ttk.Frame(main_frame)
        unrar_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        unrar_var = tk.StringVar(value=self.settings.get("unrar_path", ""))
        unrar_entry = ttk.Entry(unrar_frame, textvariable=unrar_var, width=50)
        unrar_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_unrar():
            file_path = filedialog.askopenfilename(
                title="Выберите исполняемый файл UnRAR",
                filetypes=[("Исполняемые файлы", "*.exe"), ("Все файлы", "*.*")]
            )
            if file_path:
                unrar_var.set(file_path)
        
        ttk.Button(unrar_frame, text="Обзор...", command=browse_unrar).pack(side=tk.RIGHT)
        
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=10, column=0, columnspan=2, pady=(20, 0))
        
        def save_settings():
            self.settings["unrar_path"] = unrar_var.get()
            self.save_settings()
            settings_window.destroy()
            messagebox.showinfo("Настройки", "Настройки UnRAR сохранены")
        
        ttk.Button(button_frame, text="Сохранить", command=save_settings).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Отмена", command=settings_window.destroy).pack(side=tk.LEFT)
    
    def show_about(self):
        """Показать информацию о программе"""
        about_text = """Сканер папок с виртуальными каталогами

Версия 3.2

Функции:
- Сканирование папок и архивов (ZIP, RAR, 7z)
- Группировка файлов по расширениям
- Поиск и фильтрация файлов
- Открытие файлов в ассоциированных приложениях
- Работа с избранными файлами
- Поддержка Blockbench моделей

Горячие клавиши:
Ctrl+O - открыть папку
Ctrl+Shift+O - открыть архив
Ctrl+S - сканировать
F5 - обновить
Ctrl+F - добавить в избранное
Delete - удалить выделенное"""
        
        messagebox.showinfo("О программе", about_text)
    
    def toggle_favorite(self):
        """Добавить/удалить файл из избранного"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        item = selected_items[0]
        item_values = self.tree.item(item, 'values')
        
        if len(item_values) >= 1:
            file_path = item_values[0]
            favorites = self.settings.get("favorites", [])
            
            if file_path in favorites:
                favorites.remove(file_path)
                self.tree.item(item, tags=('file',))
                self.status_var.set("Удалено из избранного")
            else:
                favorites.append(file_path)
                self.tree.item(item, tags=('file', 'favorite'))
                self.status_var.set("Добавлено в избранное")
            
            self.settings["favorites"] = favorites
            self.save_settings()
            
            # Обновляем отображение если активен фильтр избранного
            if self.show_favorites_only:
                self.apply_filters()

def main():
    root = tk.Tk()
    app = FolderScannerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()