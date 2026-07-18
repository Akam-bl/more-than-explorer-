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
        self.duplicate_files = defaultdict(list)  # Изменено на словарь для группировки
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
        
        # История действий для отмены/повтора
        self.action_history = deque(maxlen=50)  # Ограничиваем историю 50 действиями
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
        # Ctrl+Z - отменить действие
        self.root.bind('<Control-z>', lambda e: self.undo_action())
        # Ctrl+Y - повторить действие
        self.root.bind('<Control-y>', lambda e: self.redo_action())
        # Кнопка 4 мыши - отменить действие
        self.root.bind('<Button-4>', lambda e: self.undo_action())
        # Кнопка 5 мыши - повторить действие
        self.root.bind('<Button-5>', lambda e: self.redo_action())
    
    def add_to_action_history(self, action_type, data):
        """Добавить действие в историю"""
        if self.is_undo_redo_in_progress:
            return
            
        # Удаляем все действия после текущего индекса
        if self.current_action_index < len(self.action_history) - 1:
            for i in range(len(self.action_history) - 1, self.current_action_index, -1):
                self.action_history.pop()
        
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
            self.current_action_index -= 1
            
            if action['type'] == 'folder_selection':
                # Восстанавливаем предыдущую папку
                if self.current_action_index >= 0:
                    prev_action = self.action_history[self.current_action_index]
                    if prev_action['type'] == 'folder_selection':
                        self.folder_var.set(prev_action['data']['folder_path'])
                        if prev_action['data'].get('scan_after_change', False):
                            self.scan_selected()
            
            elif action['type'] == 'file_rename':
                # Восстанавливаем старое имя файла
                old_path = action['data']['old_path']
                new_path = action['data']['new_path']
                
                if os.path.exists(new_path) and not os.path.exists(old_path):
                    try:
                        os.rename(new_path, old_path)
                        self.refresh_tree()
                        self.status_var.set(f"Отменено переименование: {os.path.basename(new_path)} -> {os.path.basename(old_path)}")
                    except Exception as e:
                        messagebox.showerror("Ошибка", f"Не удалось отменить переименование: {str(e)}")
            
            elif action['type'] == 'file_delete':
                # Восстанавливаем удаленный файл из корзины (если возможно)
                # В реальном приложении здесь должна быть логика восстановления файлов
                self.status_var.set("Отмена удаления файлов (функция в разработке)")
            
            self.is_undo_redo_in_progress = False
            self.update_undo_redo_buttons()
    
    def redo_action(self):
        """Повторить отмененное действие"""
        if self.current_action_index < len(self.action_history) - 1:
            self.is_undo_redo_in_progress = True
            self.current_action_index += 1
            action = self.action_history[self.current_action_index]
            
            if action['type'] == 'folder_selection':
                # Восстанавливаем следующую папку
                self.folder_var.set(action['data']['folder_path'])
                if action['data'].get('scan_after_change', False):
                    self.scan_selected()
            
            elif action['type'] == 'file_rename':
                # Повторяем переименование
                old_path = action['data']['old_path']
                new_path = action['data']['new_path']
                
                if os.path.exists(old_path) and not os.path.exists(new_path):
                    try:
                        os.rename(old_path, new_path)
                        self.refresh_tree()
                        self.status_var.set(f"Повторено переименование: {os.path.basename(old_path)} -> {os.path.basename(new_path)}")
                    except Exception as e:
                        messagebox.showerror("Ошибка", f"Не удалось повторить переименование: {str(e)}")
            
            self.is_undo_redo_in_progress = False
            self.update_undo_redo_buttons()
    
    def update_undo_redo_buttons(self):
        """Обновить состояние кнопок отмены/повтора"""
        has_undo = self.current_action_index >= 0
        has_redo = self.current_action_index < len(self.action_history) - 1
        
        # Обновляем состояние кнопок в тулбаре если они существуют
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
            # Сохраняем информацию для возможной отмены
            deleted_items = []
            for item in selected_items:
                item_values = self.tree.item(item, 'values')
                if item_values and len(item_values) > 0:
                    file_path = item_values[0]
                    deleted_items.append({
                        'path': file_path,
                        'name': self.tree.item(item, 'text')
                    })
            
            # Добавляем в историю действий
            if deleted_items:
                self.add_to_action_history('file_delete', {'items': deleted_items})
            
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
            
            # Сохраняем текущую папку сканирования
            current_folder = self.folder_var.get()
            if current_folder and os.path.exists(current_folder):
                self.settings["main_folder"] = current_folder
            
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
        
        # Кнопки отмены/повтора
        self.undo_btn = ttk.Button(toolbar, text="↶", command=self.undo_action, width=3, state=tk.DISABLED)
        self.undo_btn.pack(side=tk.LEFT, padx=(10, 5))
        
        self.redo_btn = ttk.Button(toolbar, text="↷", command=self.redo_action, width=3, state=tk.DISABLED)
        self.redo_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Поле поиска
        ttk.Label(toolbar, text="Поиск:").pack(side=tk.LEFT, padx=(10, 5))
        self.search_var = tk.StringVar(value=self.settings.get("last_search", ""))
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=(0, 10))
        self.search_entry.bind('<KeyRelease>', self.on_search_changed)
        
        self.sort_btn = ttk.Button(toolbar, text="A→Z", command=self.toggle_sorting)
        self.sort_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.update_sort_button_text()
        
        # Кнопка группировки дубликатов
        self.hide_duplicates_var = tk.BooleanVar(value=self.settings.get("hide_duplicates", False))
        self.hide_duplicates_btn = ttk.Checkbutton(toolbar, text="Группировать дубликаты", 
                                                  variable=self.hide_duplicates_var,
                                                  command=self.on_hide_duplicates_changed)
        self.hide_duplicates_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Кнопка показа избранного
        self.favorites_btn = ttk.Button(toolbar, text="⭐", command=self.toggle_favorites_filter, width=3)
        self.favorites_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Кнопка скрытия дочерних файлов Blockbench
        self.hide_bb_children_var = tk.BooleanVar(value=self.settings.get("hide_blockbench_children", True))
        self.hide_bb_children_btn = ttk.Checkbutton(toolbar, text="Скрыть дочерние BB", 
                                                   variable=self.hide_bb_children_var,
                                                   command=self.on_hide_bb_children_changed)
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
        
        # Контекстное меню будет создаваться динамически
        self.tree_menu = None
        
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
        
        # Восстанавливаем последнюю папку сканирования
        if self.settings.get("main_folder") and os.path.exists(self.settings["main_folder"]):
            self.folder_var.set(self.settings["main_folder"])
    
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
            # Добавляем в историю действий
            self.add_to_action_history('folder_selection', {
                'folder_path': selected_folder,
                'scan_after_change': True
            })
    
    def show_tree_context_menu(self, event):
        """Показать контекстное меню для дерева файлов"""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            
            # Создаем контекстное меню динамически
            self.tree_menu = tk.Menu(self.tree, tearoff=0)
            
            # Добавляем стандартные пункты
            self.tree_menu.add_command(label="Открыть расположение файла", command=self.open_file_location)
            self.tree_menu.add_command(label="Открыть с помощью...", command=self.open_file_with)
            self.tree_menu.add_command(label="Переименовать", command=self.rename_file)
            
            # Проверяем, находится ли файл в избранном
            item_values = self.tree.item(item, 'values')
            if item_values and len(item_values) >= 1:
                file_path = item_values[0]
                favorites = self.settings.get("favorites", [])
                
                if file_path in favorites:
                    self.tree_menu.add_command(label="Убрать из избранного", command=lambda: self.toggle_favorite(update_immediately=True))
                else:
                    self.tree_menu.add_command(label="Добавить в избранное", command=lambda: self.toggle_favorite(update_immediately=True))
            
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
                            # Получаем правильный путь к файлу внутри архива
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
                                # Ищем файл в архиве
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
                    
                    file_to_open = temp_file
                else:
                    file_to_open = file_path
                
                # Открываем файл с помощью диалога "Открыть с помощью"
                if os.name == 'nt':  # Windows
                    # Используем start для открытия файла с ассоциацией по умолчанию
                    os.startfile(file_to_open)
                else:  # Linux, macOS
                    subprocess.run(['xdg-open', file_to_open])
                
                self.status_var.set(f"Открытие файла: {os.path.basename(file_path)}")
                
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
                # Сохраняем информацию для отмены
                self.add_to_action_history('file_rename', {
                    'old_path': old_file_path,
                    'new_path': new_file_path
                })
                
                # Переименовываем файл
                os.rename(old_file_path, new_file_path)
                
                # Обновляем дерево
                self.refresh_tree()
                
                self.status_var.set(f"Файл переименован: {old_filename} -> {new_filename}")
                
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось переименовать файл:\n{str(e)}")
    
    def toggle_favorite(self, update_immediately=False):
        """Добавить/удалить файл из избранного"""
        selected_items = self.tree.selection()
        if not selected_items:
            return
        
        item = selected_items[0]
        item_values = self.tree.item(item, 'values')
        
        if len(item_values) >= 1:
            file_path = item_values[0]
            favorites = self.settings.get("favorites", [])
            
            was_favorite = file_path in favorites
            
            if was_favorite:
                favorites.remove(file_path)
                self.status_var.set(f"Удалено из избранного: {os.path.basename(file_path)}")
            else:
                favorites.append(file_path)
                self.status_var.set(f"Добавлено в избранное: {os.path.basename(file_path)}")
            
            self.settings["favorites"] = favorites
            self.save_settings()
            
            # Немедленно обновляем отображение
            if update_immediately:
                if was_favorite:
                    # Убираем подсветку
                    self.tree.item(item, tags=())
                    # Если включен фильтр избранного, удаляем элемент через 0.1 секунду
                    if self.show_favorites_only:
                        self.root.after(100, lambda: self.remove_item_if_not_favorite(item, file_path))
                else:
                    # Добавляем подсветку
                    self.tree.item(item, tags=('favorite',))
            
            # Если не требуется немедленное обновление, обновляем все дерево
            if not update_immediately:
                self.refresh_tree()
    
    def remove_item_if_not_favorite(self, item, file_path):
        """Удалить элемент из дерева если он больше не в избранном"""
        if file_path not in self.settings.get("favorites", []):
            try:
                self.tree.delete(item)
            except:
                pass  # Элемент уже удален
    
    def toggle_favorites_filter(self):
        """Переключить фильтр избранного"""
        self.show_favorites_only = not self.show_favorites_only
        if self.show_favorites_only:
            self.favorites_btn.config(text="★")
            self.status_var.set("Показаны только избранные файлы")
        else:
            self.favorites_btn.config(text="⭐")
            self.status_var.set("Показаны все файлы")
        self.refresh_tree()
    
    def toggle_hide_blockbench_children(self):
        """Переключить скрытие дочерних файлов Blockbench"""
        self.settings["hide_blockbench_children"] = self.hide_bb_children_var.get()
        self.save_settings()
        self.refresh_tree()
    
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
            # Вычисляем смещение
            dx = abs(event.x - self.drag_data["x"])
            dy = abs(event.y - self.drag_data["y"])
            
            # Если смещение достаточно большое, начинаем перетаскивание
            if dx > 5 or dy > 5:
                self.tree.selection_set(self.drag_data["item"])
    
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
        settings_menu.add_command(label="Путь к Blockbench...", command=self.set_blockbench_path)
        settings_menu.add_command(label="Папка для данных...", command=self.set_data_folder)
        settings_menu.add_command(label="Временная папка...", command=self.set_temp_folder)
        settings_menu.add_command(label="Путь к UnRAR...", command=self.set_unrar_path)
        settings_menu.add_separator()
        settings_menu.add_command(label="Сохранить настройки", command=self.save_settings)
        
        # Меню Вид
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Вид", menu=view_menu)
        view_menu.add_checkbutton(label="Автозагрузка текстур", 
                                 variable=tk.BooleanVar(value=self.settings.get("auto_load_textures", True)),
                                 command=self.toggle_auto_load_textures)
        view_menu.add_checkbutton(label="Сортировка по алфавиту", 
                                 variable=tk.BooleanVar(value=self.settings.get("sort_alphabetically", True)),
                                 command=self.toggle_sorting)
        view_menu.add_checkbutton(label="Группировать дубликаты", 
                                 variable=self.hide_duplicates_var,
                                 command=self.on_hide_duplicates_changed)
        view_menu.add_checkbutton(label="Скрыть дочерние файлы Blockbench", 
                                 variable=self.hide_bb_children_var,
                                 command=self.on_hide_bb_children_changed)
        
        # Меню Помощь
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Помощь", menu=help_menu)
        help_menu.add_command(label="О программе", command=self.show_about)
    
    def show_about(self):
        """Показать информацию о программе"""
        about_text = """Сканер папок с виртуальными каталогами
Версия: 3.7
Создатель: Akami_bl
Обратная связь: akami.bl@gmail.com

Функции:
- Сканирование папок и архивов
- Виртуальные каталоги по типам файлов
- Поиск и фильтрация
- Открытие файлов в Blockbench
- Группировка дубликатов
- История сканирования

Горячие клавиши:
Ctrl+O - Открыть папку
Ctrl+Shift+O - Открыть архив
Ctrl+S - Сканировать
F5 - Обновить
Ctrl+Z - Отменить
Ctrl+Y - Повторить
Кнопка 4 мыши - Отменить
Кнопка 5 мыши - Повторить"""
        
        messagebox.showinfo("О программе", about_text)
    
    def toggle_auto_load_textures(self):
        """Переключить автозагрузку текстур"""
        self.settings["auto_load_textures"] = not self.settings.get("auto_load_textures", True)
        self.save_settings()
    
    def set_blockbench_path(self):
        """Установить путь к Blockbench"""
        path = filedialog.askopenfilename(
            title="Выберите исполняемый файл Blockbench",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")]
        )
        if path:
            self.settings["blockbench_path"] = path
            self.save_settings()
            messagebox.showinfo("Успех", f"Путь к Blockbench установлен:\n{path}")
    
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
            # Добавляем в историю действий
            self.add_to_action_history('folder_selection', {
                'folder_path': folder_path,
                'scan_after_change': True
            })
    
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
            # Добавляем в историю действий
            self.add_to_action_history('folder_selection', {
                'folder_path': file_path,
                'scan_after_change': True
            })
    
    def scan_selected(self):
        """Сканирование выбранной папки или архива"""
        folder_path = self.folder_var.get()
        if not folder_path:
            messagebox.showwarning("Предупреждение", "Выберите папку или архив для сканирования")
            return
        
        if not os.path.exists(folder_path):
            messagebox.showerror("Ошибка", "Указанный путь не существует")
            return
        
        # Добавляем в историю сканирования
        self.add_to_scan_history(folder_path)
        
        # Запускаем сканирование в отдельном потоке
        self.progress.start()
        self.status_var.set("Сканирование...")
        self.scan_btn.config(state=tk.DISABLED)
        
        thread = threading.Thread(target=self.scan_folder_thread, args=(folder_path,))
        thread.daemon = True
        thread.start()
    
    def scan_folder_thread(self, folder_path):
        """Поток для сканирования папки"""
        try:
            self.folder_data = defaultdict(list)
            self.virtual_folders = {}
            self.archive_data = {}
            self.available_extensions = set()
            self.duplicate_files = defaultdict(list)  # Сбрасываем дубликаты
            self.files_without_textures = set()
            self.all_files = []
            self.extension_data = defaultdict(list)
            self.all_folders = set()
            
            # Определяем тип сканирования (папка или архив)
            if os.path.isfile(folder_path):
                # Сканирование архива
                self.scan_archive(folder_path)
            else:
                # Сканирование папки
                self.scan_real_folder(folder_path)
            
            # Находим дубликаты
            self.find_duplicates()
            
            # Обновляем интерфейс в основном потоке
            self.root.after(0, self.on_scan_complete)
            
        except Exception as e:
            self.root.after(0, lambda: self.on_scan_error(str(e)))
    
    def scan_real_folder(self, folder_path):
        """Сканирование реальной папки"""
        for root, dirs, files in os.walk(folder_path):
            # Добавляем папки в список всех папок
            for dir_name in dirs:
                full_dir_path = os.path.join(root, dir_name)
                self.all_folders.add(full_dir_path)
            
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, folder_path)
                
                # Получаем информацию о файле
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
                    'has_parent': False  # По умолчанию
                }
                
                # Проверяем, является ли файл дочерним (содержит "parent")
                if file_info['extension'] in ['.json', '.bbmodel']:
                    file_info['has_parent'] = self.check_file_has_parent(file_path)
                
                # Добавляем файл в общий список
                self.all_files.append(file_info)
                
                # Добавляем расширение в список доступных
                ext = file_info['extension']
                if ext:
                    self.available_extensions.add(ext)
                    self.extension_data[ext].append(file_info)
    
    def check_file_has_parent(self, file_path):
        """Проверить, содержит ли файл поле 'parent'"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Ищем паттерн "parent": "какое-то-значение"
                return '"parent":' in content
        except:
            return False
    
    def scan_archive(self, archive_path):
        """Сканирование архива"""
        self.archive_data = {
            'path': archive_path,
            'files': []
        }
        
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
                        
                        # Для JSON файлов в архиве проверяем наличие parent
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
                            
                            # Для JSON файлов в архиве проверяем наличие parent
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
        
        # Группируем файлы по имени и расширению
        file_groups = defaultdict(list)
        for file_info in self.all_files:
            key = file_info['name']  # Используем полное имя файла с расширением
            file_groups[key].append(file_info)
        
        # Находим группы с дубликатами (больше 1 файла)
        for filename, files in file_groups.items():
            if len(files) > 1:
                self.duplicate_files[filename] = files
    
    def on_scan_complete(self):
        """Завершение сканирования"""
        self.progress.stop()
        self.scan_btn.config(state=tk.NORMAL)
        self.refresh_btn.config(state=tk.NORMAL)
        
        # Обновляем дерево расширений
        self.update_extension_tree()
        
        # Обновляем дерево файлов
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
        # Очищаем дерево
        for item in self.extension_tree.get_children():
            self.extension_tree.delete(item)
        
        # Добавляем расширения
        for ext in sorted(self.available_extensions):
            count = len(self.extension_data[ext])
            self.extension_tree.insert("", "end", text=ext, values=(count,))
    
    def on_extension_select(self, event):
        """Обработка выбора расширения"""
        selected_items = self.extension_tree.selection()
        if not selected_items:
            self.current_extension_filter = ""
        else:
            item = selected_items[0]
            self.current_extension_filter = self.extension_tree.item(item, "text")
        
        self.refresh_tree()
    
    def on_search_changed(self, event):
        """Обработка изменения поискового запроса"""
        self.refresh_tree()
    
    def refresh_tree(self):
        """Обновление дерева файлов"""
        if not hasattr(self, 'tree') or not self.tree.winfo_exists():
            return
        
        # Очищаем дерево
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Получаем поисковый запрос
        search_query = self.search_var.get().lower()
        
        # Фильтруем файлы
        filtered_files = []
        for file_info in self.all_files:
            # Применяем фильтр избранного
            if self.show_favorites_only and not file_info.get('is_favorite', False):
                continue
            
            # Применяем фильтр расширения
            if self.current_extension_filter:
                file_ext = file_info.get('extension', '')
                if file_ext != self.current_extension_filter:
                    continue
            
            # Применяем поисковый запрос
            if search_query:
                filename = file_info['name'].lower()
                if search_query not in filename:
                    continue
            
            # Применяем фильтр дочерних файлов Blockbench
            if self.settings.get("hide_blockbench_children", True):
                if file_info.get('has_parent', False):
                    continue
            
            filtered_files.append(file_info)
        
        # Сортируем файлы
        if self.settings.get("sort_alphabetically", True):
            filtered_files.sort(key=lambda x: x['name'].lower())
        else:
            filtered_files.sort(key=lambda x: x['modified'], reverse=True)
        
        # Добавляем файлы в дерево
        if self.settings.get("hide_duplicates", False):
            # Режим группировки дубликатов
            self.add_files_with_duplicates_grouping(filtered_files)
        else:
            # Обычный режим
            self.add_files_normal(filtered_files)
        
        # Настраиваем теги для избранных файлов
        self.tree.tag_configure('favorite', background='light yellow')
        self.tree.tag_configure('duplicate_folder', background='light blue')
        
        self.status_var.set(f"Показано файлов: {len(filtered_files)}")
    
    def add_files_normal(self, files):
        """Добавить файлы в обычном режиме"""
        for file_info in files:
            # Определяем теги
            tags = ()
            if file_info.get('is_favorite', False):
                tags = ('favorite',)
            
            # Форматируем размер файла
            size_str = self.format_file_size(file_info['size'])
            
            # Форматируем дату изменения
            modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
            
            # Добавляем файл в дерево
            self.tree.insert(
                "", "end", 
                text=file_info['name'],
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
        """Добавить файлы с группировкой дубликатов - негруппируемые файлы вверху"""
        # Создаем словарь для группировки файлов по имени
        file_groups = defaultdict(list)
        single_files = []  # Файлы без дубликатов
        duplicate_groups = []  # Группы дубликатов
        
        for file_info in files:
            file_groups[file_info['name']].append(file_info)
        
        # Разделяем на одиночные файлы и группы дубликатов
        for filename, file_list in file_groups.items():
            if len(file_list) == 1:
                single_files.append(file_list[0])
            else:
                duplicate_groups.append((filename, file_list))
        
        # Сначала добавляем одиночные файлы (в самом верху)
        for file_info in single_files:
            tags = ()
            if file_info.get('is_favorite', False):
                tags = ('favorite',)
            
            size_str = self.format_file_size(file_info['size'])
            modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
            
            self.tree.insert(
                "", "end", 
                text=file_info['name'],
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
        
        # Затем добавляем группы дубликатов (после одиночных файлов)
        for filename, file_list in duplicate_groups:
            # Создаем папку для дубликатов
            folder_id = self.tree.insert(
                "", "end", 
                text=f"📁 {filename} ({len(file_list)} файлов)",
                values=('', '', 'folder', '', '', False),
                tags=('duplicate_folder',)
            )
            
            # Добавляем файлы в папку
            for file_info in file_list:
                tags = ()
                if file_info.get('is_favorite', False):
                    tags = ('favorite',)
                
                size_str = self.format_file_size(file_info['size'])
                modified_str = file_info['modified'].strftime("%Y-%m-%d %H:%M")
                
                self.tree.insert(
                    folder_id, "end", 
                    text=file_info['name'],
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
    
    def on_tree_double_click(self, event):
        """Обработка двойного клика по элементу дерева"""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        
        item_values = self.tree.item(item, 'values')
        
        if len(item_values) >= 1:
            file_path = item_values[0]
            archive_path = item_values[1] if len(item_values) > 1 else None
            
            # Открываем файл в ассоциированной программе
            self.open_file(file_path, archive_path)
    
    def open_file(self, file_path, archive_path=None):
        """Открытие файла"""
        try:
            # Если файл находится в архиве, извлекаем его во временную папку
            if archive_path:
                temp_dir = self.settings.get("temp_folder") or tempfile.gettempdir()
                os.makedirs(temp_dir, exist_ok=True)
                
                temp_file = os.path.join(temp_dir, os.path.basename(file_path))
                
                if archive_path.lower().endswith('.zip'):
                    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                        # Получаем правильный путь к файлу внутри архива
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
                            # Ищем файл в архиве
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
                
                file_to_open = temp_file
            else:
                file_to_open = file_path
            
            # Проверяем расширение файла
            file_ext = os.path.splitext(file_path)[1].lower()
            
            # Для моделей Blockbench открываем в Blockbench
            if file_ext in ['.bbmodel', '.json'] and self.settings.get("blockbench_path"):
                blockbench_path = self.settings["blockbench_path"]
                if os.path.exists(blockbench_path):
                    subprocess.Popen([blockbench_path, file_to_open])
                    self.status_var.set(f"Открытие в Blockbench: {os.path.basename(file_path)}")
                    return
            
            # Для других файлов используем системную ассоциацию
            if os.name == 'nt':  # Windows
                os.startfile(file_to_open)
            else:  # Linux, macOS
                subprocess.run(['xdg-open', file_to_open])
            
            self.status_var.set(f"Открытие файла: {os.path.basename(file_path)}")
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{str(e)}")
    
    def update_folder_history(self):
        """Обновление истории папок"""
        history = self.settings.get("scan_history", [])
        self.folder_combo['values'] = history
    
    def toggle_sorting(self):
        """Переключение сортировки"""
        self.settings["sort_alphabetically"] = not self.settings.get("sort_alphabetically", True)
        self.save_settings()
        self.update_sort_button_text()
        self.refresh_tree()
    
    def update_sort_button_text(self):
        """Обновление текста кнопки сортировки"""
        if self.settings.get("sort_alphabetically", True):
            self.sort_btn.config(text="A→Z")
        else:
            self.sort_btn.config(text="Дата")
    
    def check_settings(self):
        """Проверка и настройка необходимых параметров"""
        # Проверяем временную папку
        if not self.settings.get("temp_folder"):
            self.settings["temp_folder"] = tempfile.gettempdir()
        
        # Проверяем папку для данных
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