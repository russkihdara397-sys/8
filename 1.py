# -*- coding: utf-8 -*-
"""
Два GUI-приложения на tkinter в одном файле:
  1. Генератор комплексного текстового файла (output.txt)
  2. Умный регистратор данных датчика (sensor_log.csv)

UI/UX:
  • Палитра: белые рабочие области, светло-серая подложка, синий акцент.
  • Плоские поля и кнопки без 3D-теней.
  • Кастомный горизонтальный таб-бар с подчёркиванием активной вкладки.
  • Журнал операций с текстом-заглушкой, только для чтения.
  • Прогресс-бар в статус-баре на время операций.
  • Пакетный режим — единый блок «поле + кнопка».
  • Иконки ▶ / ■ / 📁 / ✎.

Только стандартные библиотеки: tkinter, math, random, datetime, os, sys.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import math
import random
import datetime
import os
import sys


# =====================================================================
# ПАЛИТРА И СТИЛИ
# =====================================================================
COLOR_BG          = "#F3F4F6"   # подложка окна
COLOR_SURFACE     = "#FFFFFF"   # фон рабочих областей
COLOR_BORDER      = "#D1D5DB"   # тонкие рамки
COLOR_TEXT        = "#111827"   # основной текст
COLOR_MUTED       = "#6B7280"   # подписи
COLOR_ACCENT      = "#2563EB"   # акцент (синий)
COLOR_ACCENT_HOV  = "#1D4ED8"   # акцент hover
COLOR_SUCCESS     = "#059669"   # успех
COLOR_ERROR       = "#DC2626"   # ошибка
COLOR_START       = "#16A34A"   # кнопка «Старт»
COLOR_STOP        = "#DC2626"   # кнопка «Стоп»
COLOR_TAB_ACTIVE  = "#2563EB"
COLOR_TAB_INACT   = "#9CA3AF"

FONT_UI       = ("Segoe UI", 10)
FONT_LABEL    = ("Segoe UI", 10)
FONT_HEADER   = ("Segoe UI", 11, "bold")
FONT_LOG      = ("Consolas", 9)
FONT_TAB      = ("Segoe UI", 10, "bold")


# =====================================================================
# ГЕНЕРАЦИЯ СЛУЧАЙНОГО ТЕКСТА ДЛЯ БЛОКА 1
# =====================================================================

_RANDOM_SUBJECTS = [
    "Программа", "Система", "Модуль", "Алгоритм", "Скрипт",
    "Генератор", "Датчик", "Контроллер", "Поток данных", "Отчёт",
    "Пользователь", "Оператор", "Сервер", "Клиент", "Процесс",
]
_RANDOM_VERBS = [
    "обработал", "сформировал", "проанализировал", "записал",
    "вычислил", "проверил", "сгенерировал", "сохранил",
    "обнаружил", "подтвердил", "инициализировал", "завершил",
]
_RANDOM_OBJECTS = [
    "массив случайных значений", "результаты измерений",
    "таблицу координат", "журнал событий", "набор точек функции",
    "пакет входных данных", "файл отчёта", "промежуточные результаты",
    "последовательность чисел", "график зависимости",
]
_RANDOM_ADVERBIALS = [
    "за 0.42 секунды", "без критических ошибок",
    "согласно техническому заданию", "в штатном режиме",
    "при температуре +23 °C", "в условиях ограниченных ресурсов",
    "на тестовом стенде", "с использованием ГПСЧ",
    "по заданному расписанию", "в автоматическом режиме",
]
_RANDOM_NOTES = [
    "Контрольная сумма блока проверена.",
    "Резервное копирование выполнено успешно.",
    "Уровень заряда батареи: 87%.",
    "Свободное место на диске: достаточно.",
    "Количество итераций в пределах нормы.",
    "Буферизация выполнена без потерь.",
    "Целостность данных подтверждена.",
    "Сетевой интерфейс активен.",
    "Параметры конфигурации загружены из файла.",
    "Ошибок целостности не обнаружено.",
]


def build_random_sentence() -> str:
    """Собирает одно случайное осмысленное предложение."""
    subject = random.choice(_RANDOM_SUBJECTS)
    verb = random.choice(_RANDOM_VERBS)
    obj = random.choice(_RANDOM_OBJECTS)
    adv = random.choice(_RANDOM_ADVERBIALS)
    sentence = f"{subject} {verb} {obj} {adv}."
    return sentence[0].upper() + sentence[1:]


def build_random_block1() -> str:
    """Формирует Блок 1: 3 случайных предложения + заметка + дата."""
    today = datetime.date.today().strftime("%Y-%m-%d")
    lines = [
        "=== БЛОК 1: ПРОИЗВОЛЬНЫЙ ТЕКСТ ===",
        "Данный файл сгенерирован автоматически программным путем.",
        build_random_sentence(),
        build_random_sentence(),
        build_random_sentence(),
        random.choice(_RANDOM_NOTES),
        f"Дата создания: {today}",
    ]
    return "\n".join(lines) + "\n"


# =====================================================================
# ПРИЛОЖЕНИЕ 1
# =====================================================================

def generate_output_file(filename: str, n_random: int, n_steps: int,
                         custom_text: str = None) -> str:
    """Формирует текстовый файл из трёх блоков. Возвращает путь.

    Если custom_text задан (непустой), он используется как содержимое
    Блока 1 вместо автогенерируемого текста.
    """
    if n_random <= 0:
        raise ValueError("Количество случайных чисел должно быть > 0")
    if n_steps <= 0:
        raise ValueError("Количество шагов для функции должно быть > 0")

    if custom_text and custom_text.strip():
        today = datetime.date.today().strftime("%Y-%m-%d")
        block1 = (
            "=== БЛОК 1: ПОЛЬЗОВАТЕЛЬСКИЙ ТЕКСТ ===\n"
            f"{custom_text.rstrip()}\n"
            f"Дата создания: {today}\n"
        )
    else:
        block1 = build_random_block1()

    numbers = [random.randint(1, 100) for _ in range(n_random)]
    block2 = (
        "\n=== БЛОК 2: СЛУЧАЙНЫЕ ЧИСЛА ===\n"
        f"Количество элементов: {n_random}\n"
        "Выборка: " + ", ".join(str(x) for x in numbers) + "\n"
    )

    lines = ["\n=== БЛОК 3: ЗНАЧЕНИЯ ФУНКЦИИ Y = SIN(X) ==="]
    if n_steps == 1:
        xs = [0.0]
    else:
        step = (2.0 * math.pi) / (n_steps - 1)
        xs = [i * step for i in range(n_steps)]

    for x in xs:
        y = math.sin(x)
        lines.append(f"x = {x:.2f} -> y = {y:.4f}")
    block3 = "\n".join(lines) + "\n"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(block1)
        f.write(block2)
        f.write(block3)

    return filename


# =====================================================================
# ПРИЛОЖЕНИЕ 2
# =====================================================================

CSV_ENCODING = "utf-8-sig"


def classify_temperature(value: float) -> str:
    """Статус по значению температуры согласно порогам."""
    if -50.0 <= value <= -20.0:
        return "Заморозки"
    if -19.0 <= value <= 40.0:
        return "Норма"
    if 41.0 <= value <= 100.0:
        return "Перегрев"
    if 101.0 <= value <= 150.0:
        return "Пожар / Авария"
    return "Неизвестно"


def generate_sensor_reading(timestamp: datetime.datetime) -> str:
    """Одна строка CSV: Timestamp;Значение;Статус (значение — 2 знака)."""
    value = random.uniform(-50.0, 150.0)
    status = classify_temperature(value)
    ts = timestamp.strftime("%Y-%m-%d %H:%M:%S")
    return f"{ts};{value:.2f};{status}"


def ensure_csv_header(filename: str) -> None:
    """Создаёт файл с заголовком, если он не существует или пуст."""
    need_header = (not os.path.exists(filename)) or os.path.getsize(filename) == 0
    if need_header:
        with open(filename, "w", encoding=CSV_ENCODING, newline="") as f:
            f.write("Timestamp;Значение;Статус\n")


# =====================================================================
# КОРНЕВОЕ ОКНО
# =====================================================================
root = tk.Tk()
root.title("Практическая работа: файлы и данные")
root.geometry("900x780")
root.minsize(860, 720)
root.configure(bg=COLOR_BG)

style = ttk.Style()
try:
    style.theme_use("clam")
except tk.TclError:
    pass

# --- Стили ---
style.configure("TFrame", background=COLOR_BG)
style.configure("Surface.TFrame", background=COLOR_SURFACE)
style.configure("TLabel",
                background=COLOR_SURFACE,
                foreground=COLOR_TEXT,
                font=FONT_LABEL)
style.configure("Header.TLabel",
                background=COLOR_SURFACE,
                foreground=COLOR_TEXT,
                font=FONT_HEADER)
style.configure("Muted.TLabel",
                background=COLOR_SURFACE,
                foreground=COLOR_MUTED,
                font=("Segoe UI", 9))

# Плоские поля ввода — без 3D-теней
style.configure("Field.TEntry",
                fieldbackground=COLOR_SURFACE,
                foreground=COLOR_TEXT,
                bordercolor=COLOR_BORDER,
                lightcolor=COLOR_BORDER,
                darkcolor=COLOR_BORDER,
                borderwidth=1,
                relief="flat",
                padding=6)
style.map("Field.TEntry",
          bordercolor=[("focus", COLOR_ACCENT)],
          lightcolor=[("focus", COLOR_ACCENT)],
          darkcolor=[("focus", COLOR_ACCENT)])

# Акцентная кнопка (синяя)
style.configure("Accent.TButton",
                background=COLOR_ACCENT,
                foreground="white",
                bordercolor=COLOR_ACCENT,
                focuscolor=COLOR_ACCENT,
                font=("Segoe UI", 10, "bold"),
                padding=(14, 8),
                relief="flat")
style.map("Accent.TButton",
          background=[("active", COLOR_ACCENT_HOV),
                      ("pressed", COLOR_ACCENT_HOV)],
          foreground=[("disabled", "#E5E7EB")])

# Кнопка «Старт» (зелёная)
style.configure("Start.TButton",
                background=COLOR_START,
                foreground="white",
                bordercolor=COLOR_START,
                focuscolor=COLOR_START,
                font=("Segoe UI", 10, "bold"),
                padding=(14, 8),
                relief="flat")
style.map("Start.TButton",
          background=[("active", "#15803D"), ("pressed", "#15803D")],
          foreground=[("disabled", "#E5E7EB")])

# Кнопка «Стоп» (красная)
style.configure("Stop.TButton",
                background=COLOR_STOP,
                foreground="white",
                bordercolor=COLOR_STOP,
                focuscolor=COLOR_STOP,
                font=("Segoe UI", 10, "bold"),
                padding=(14, 8),
                relief="flat")
style.map("Stop.TButton",
          background=[("active", "#B91C1C"), ("pressed", "#B91C1C")],
          foreground=[("disabled", "#E5E7EB")])

# Вторичная кнопка (контурная)
style.configure("Secondary.TButton",
                background=COLOR_SURFACE,
                foreground=COLOR_TEXT,
                bordercolor=COLOR_BORDER,
                focuscolor=COLOR_BORDER,
                font=("Segoe UI", 10),
                padding=(10, 6),
                relief="flat")
style.map("Secondary.TButton",
          background=[("active", "#F3F4F6"), ("pressed", "#E5E7EB")])

# Прогресс-бар
style.configure("Green.Horizontal.TProgressbar",
                troughcolor="#E5E7EB",
                background=COLOR_SUCCESS,
                bordercolor=COLOR_BORDER,
                lightcolor=COLOR_SUCCESS,
                darkcolor=COLOR_SUCCESS)

# Разделитель
style.configure("TSeparator", background=COLOR_BORDER)


# =====================================================================
# СТАТУС-БАР С ПРОГРЕССОМ
# =====================================================================
status_frame = tk.Frame(root, bg=COLOR_BG, height=36)
status_frame.pack(side=tk.BOTTOM, fill=tk.X)
status_frame.pack_propagate(False)

status_dot = tk.Label(status_frame, text="●", fg=COLOR_MUTED,
                      bg=COLOR_BG, font=("Segoe UI", 12))
status_dot.pack(side=tk.LEFT, padx=(12, 4))

status_var = tk.StringVar(value="Готово")
status_label = tk.Label(status_frame, textvariable=status_var,
                        fg=COLOR_TEXT, bg=COLOR_BG,
                        font=("Segoe UI", 10), anchor="w")
status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

progress = ttk.Progressbar(status_frame, mode="indeterminate",
                           length=120, style="Green.Horizontal.TProgressbar")


def set_status(text: str, level: str = "info", show_progress: bool = False):
    """
    Обновляет статус-бар:
      level: info / success / error — цвет точки и текста;
      show_progress: запуск/остановка анимированного прогресс-бара.
    """
    colors = {"info": COLOR_MUTED, "success": COLOR_SUCCESS,
              "error": COLOR_ERROR}
    status_dot.config(fg=colors.get(level, COLOR_MUTED))
    status_label.config(fg=colors.get(level, COLOR_TEXT) if level != "info"
                        else COLOR_TEXT)
    status_var.set(text)
    if show_progress:
        progress.pack(side=tk.RIGHT, padx=(8, 12))
        progress.start(12)
    else:
        progress.stop()
        progress.pack_forget()


# =====================================================================
# ЖУРНАЛ ОПЕРАЦИЙ (с плейсхолдером)
# =====================================================================
PLACEHOLDER = "Здесь будет отображаться история операций…"


def create_log(parent: tk.Widget) -> tk.Text:
    """
    Создаёт журнал операций:
      • только для чтения (state='disabled');
      • в пустом состоянии показывает плейсхолдер серым;
      • плоская рамка.
    """
    txt = tk.Text(parent, height=8, wrap="word",
                  font=FONT_LOG, fg=COLOR_TEXT, bg=COLOR_SURFACE,
                  relief="solid", borderwidth=1,
                  highlightthickness=1, highlightbackground=COLOR_BORDER,
                  highlightcolor=COLOR_ACCENT,
                  state="normal", cursor="arrow",
                  padx=10, pady=8)
    txt.insert("1.0", PLACEHOLDER)
    txt.tag_configure("placeholder", foreground=COLOR_MUTED,
                      font=("Segoe UI", 9, "italic"))
    txt.tag_add("placeholder", "1.0", "end")
    txt.config(state="disabled")
    return txt


def log_message(log_widget: tk.Text, text: str) -> None:
    """
    Дописывает строку в журнал. Если ещё виден плейсхолдер — удаляет его.
    Виджет остаётся в state='disabled', кроме момента вставки.
    """
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    log_widget.config(state="normal")
    if log_widget.get("1.0", "end-1c") == PLACEHOLDER:
        log_widget.delete("1.0", "end")
    log_widget.insert("end", f"[{ts}] {text}\n")
    log_widget.see("end")
    log_widget.config(state="disabled")


# =====================================================================
# ДЕЙСТВИЯ ПРИЛОЖЕНИЯ 1
# =====================================================================

def run_app1_generate():
    """Генерация output.txt с прогресс-индикатором в статус-баре."""
    try:
        filename = app1_entry_file.get().strip()
        if not filename:
            raise ValueError("Укажите имя файла")

        n_random_str = app1_entry_n.get().strip()
        if not n_random_str:
            raise ValueError("Укажите количество случайных чисел")
        n_random = int(n_random_str)

        n_steps_str = app1_entry_steps.get().strip()
        if not n_steps_str:
            raise ValueError("Укажите количество шагов для функции")
        n_steps = int(n_steps_str)

        # --- Читаем пользовательский текст ---
        raw_custom = app1_custom_text.get("1.0", "end-1c").strip()
        if raw_custom == CUSTOM_TEXT_PLACEHOLDER.strip():
            raw_custom = ""
        custom_text = raw_custom if raw_custom else None

        set_status("Генерация файла…", "info", show_progress=True)
        root.update_idletasks()

        generate_output_file(filename, n_random, n_steps,
                             custom_text=custom_text)

        abs_path = os.path.abspath(filename)
        block1_info = "пользовательский" if custom_text else "автогенерируемый"
        set_status(f"✔ Файл сохранён: {abs_path}", "success")
        log_message(app1_log, f"✔ Файл сохранён: {abs_path}")
        log_message(app1_log,
                    f"   Блок 1: {block1_info} | "
                    f"чисел: {n_random} | точек: {n_steps}")
        messagebox.showinfo(
            "Готово",
            f"Файл успешно создан!\n\n"
            f"Путь: {abs_path}\n"
            f"Блок 1: {block1_info}\n"
            f"Случайных чисел: {n_random}\n"
            f"Точек функции: {n_steps}"
        )
    except ValueError as e:
        set_status(f"✖ Ошибка ввода: {e}", "error")
        log_message(app1_log, f"✖ Ошибка ввода: {e}")
        messagebox.showerror("Ошибка ввода", str(e))
    except OSError as e:
        set_status(f"✖ Ошибка файла: {e}", "error")
        log_message(app1_log, f"✖ Ошибка файла: {e}")
        messagebox.showerror("Ошибка файла", f"Не удалось записать файл:\n{e}")
    except Exception as e:
        set_status(f"✖ Неизвестная ошибка: {e}", "error")
        log_message(app1_log, f"✖ Неизвестная ошибка: {e}")
        messagebox.showerror("Неизвестная ошибка", str(e))


def browse_save_file():
    """Диалог выбора пути output.txt."""
    path = filedialog.asksaveasfilename(
        defaultextension=".txt",
        filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
        initialfile="output.txt"
    )
    if path:
        app1_entry_file.delete(0, tk.END)
        app1_entry_file.insert(0, path)


# =====================================================================
# ДЕЙСТВИЯ ПРИЛОЖЕНИЯ 2
# =====================================================================

def run_app2_batch():
    """Пакетный режим: N строк сразу дописываются в файл."""
    try:
        filename = app2_entry_file.get().strip()
        if not filename:
            raise ValueError("Укажите имя файла лога")

        n_str = app2_entry_n.get().strip()
        if not n_str:
            raise ValueError("Укажите количество строк")
        n = int(n_str)
        if n <= 0:
            raise ValueError("Количество строк должно быть > 0")

        set_status(f"Генерация {n} строк…", "info", show_progress=True)
        root.update_idletasks()

        ensure_csv_header(filename)

        now = datetime.datetime.now()
        lines = []
        for i in range(n):
            ts = now - datetime.timedelta(seconds=(n - 1 - i))
            lines.append(generate_sensor_reading(ts))

        with open(filename, "a", encoding=CSV_ENCODING, newline="") as f:
            f.write("\n".join(lines) + "\n")

        abs_path = os.path.abspath(filename)
        set_status(f"✔ Сгенерировано {n} строк. Файл: {abs_path}", "success")
        log_message(app2_log, f"✔ Пакет: {n} строк → {abs_path}")
        messagebox.showinfo(
            "Готово",
            f"Пакет успешно записан!\n\n"
            f"Путь: {abs_path}\n"
            f"Строк добавлено: {n}"
        )
    except ValueError as e:
        set_status(f"✖ Ошибка ввода: {e}", "error")
        log_message(app2_log, f"✖ Ошибка ввода: {e}")
        messagebox.showerror("Ошибка ввода", str(e))
    except OSError as e:
        set_status(f"✖ Ошибка файла: {e}", "error")
        log_message(app2_log, f"✖ Ошибка файла: {e}")
        messagebox.showerror("Ошибка файла", f"Не удалось записать файл:\n{e}")
    except Exception as e:
        set_status(f"✖ Неизвестная ошибка: {e}", "error")
        log_message(app2_log, f"✖ Неизвестная ошибка: {e}")
        messagebox.showerror("Неизвестная ошибка", str(e))


realtime_state = {
    "running": False, "after_id": None, "filename": None, "counter": 0,
}


def realtime_tick():
    """Один такт режима реального времени."""
    if not realtime_state["running"]:
        return
    try:
        line = generate_sensor_reading(datetime.datetime.now())
        with open(realtime_state["filename"], "a",
                  encoding=CSV_ENCODING, newline="") as f:
            f.write(line + "\n")

        realtime_state["counter"] += 1
        app2_label_counter.config(
            text=f"Записано строк: {realtime_state['counter']}"
        )
        set_status("● Идёт запись в реальном времени…", "info")

        realtime_state["after_id"] = root.after(1000, realtime_tick)
    except Exception as e:
        realtime_state["running"] = False
        set_status(f"✖ Ошибка лога: {e}", "error")
        log_message(app2_log, f"✖ Ошибка лога: {e}")
        messagebox.showerror("Ошибка лога", str(e))
        app2_btn_stop.config(state=tk.DISABLED)
        app2_btn_start.config(state=tk.NORMAL)


def run_app2_start_realtime():
    """Запуск режима реального времени."""
    if realtime_state["running"]:
        return
    try:
        filename = app2_entry_file.get().strip()
        if not filename:
            raise ValueError("Укажите имя файла лога")

        ensure_csv_header(filename)
        realtime_state["filename"] = filename
        realtime_state["running"] = True
        realtime_state["counter"] = 0

        app2_label_counter.config(text="Записано строк: 0")
        app2_btn_start.config(state=tk.DISABLED)
        app2_btn_stop.config(state=tk.NORMAL)

        set_status("● Режим реального времени запущен", "info")
        log_message(app2_log, f"● Старт реального времени → {os.path.abspath(filename)}")
        messagebox.showinfo(
            "Запущено",
            f"Режим реального времени активен.\n"
            f"Файл: {os.path.abspath(filename)}\n\n"
            f"Запись — 1 строка в секунду.\n"
            f"Для остановки нажмите «■ Стоп»."
        )
        realtime_state["after_id"] = root.after(0, realtime_tick)
    except ValueError as e:
        set_status(f"✖ Ошибка ввода: {e}", "error")
        log_message(app2_log, f"✖ Ошибка ввода: {e}")
        messagebox.showerror("Ошибка ввода", str(e))
    except OSError as e:
        set_status(f"✖ Ошибка файла: {e}", "error")
        log_message(app2_log, f"✖ Ошибка файла: {e}")
        messagebox.showerror("Ошибка файла", f"Не удалось открыть файл:\n{e}")
    except Exception as e:
        set_status(f"✖ Неизвестная ошибка: {e}", "error")
        log_message(app2_log, f"✖ Неизвестная ошибка: {e}")
        messagebox.showerror("Неизвестная ошибка", str(e))


def run_app2_stop_realtime():
    """Остановка режима реального времени."""
    realtime_state["running"] = False
    if realtime_state["after_id"] is not None:
        try:
            root.after_cancel(realtime_state["after_id"])
        except Exception:
            pass
        realtime_state["after_id"] = None
    app2_btn_start.config(state=tk.NORMAL)
    app2_btn_stop.config(state=tk.DISABLED)
    set_status(
        f"■ Остановлено. Записано строк за сессию: {realtime_state['counter']}",
        "info"
    )
    log_message(
        app2_log,
        f"■ Стоп. Записано строк за сессию: {realtime_state['counter']}"
    )
    messagebox.showinfo(
        "Остановлено",
        f"Запись остановлена.\n\n"
        f"Строк записано за сессию: {realtime_state['counter']}"
    )


def browse_log_file():
    """Диалог выбора пути CSV-лога."""
    path = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV файлы", "*.csv"), ("Все файлы", "*.*")],
        initialfile="sensor_log.csv"
    )
    if path:
        app2_entry_file.delete(0, tk.END)
        app2_entry_file.insert(0, path)


# =====================================================================
# КАСТОМНЫЙ ТАБ-БАР (плоские вкладки с подчёркиванием активной)
# =====================================================================
# Главный контейнер
main_frame = tk.Frame(root, bg=COLOR_BG)
main_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 4))

# Строка вкладок
tabs_bar = tk.Frame(main_frame, bg=COLOR_BG)
tabs_bar.pack(fill=tk.X, pady=(0, 12))

# Контейнер для страниц
pages_container = tk.Frame(main_frame, bg=COLOR_BG)
pages_container.pack(fill=tk.BOTH, expand=True)

# Список (label, page_frame, underline_widget)
tabs = []
current_tab = {"index": 0}


def select_tab(index: int):
    """
    Переключает активную вкладку: показывает нужную страницу,
    подсвечивает подпись и двигает подчёркивание.
    """
    current_tab["index"] = index
    for i, (btn, page, underline) in enumerate(tabs):
        if i == index:
            btn.config(fg=COLOR_TAB_ACTIVE)
            underline.config(bg=COLOR_TAB_ACTIVE)
            page.pack(fill=tk.BOTH, expand=True)
        else:
            btn.config(fg=COLOR_TAB_INACT)
            underline.config(bg=COLOR_BG)
            page.pack_forget()
    set_status("Готово", "info")


def make_tab(label_text: str) -> tuple:
    """Создаёт кнопку-вкладку с подчёркиванием под ней."""
    wrap = tk.Frame(tabs_bar, bg=COLOR_BG)
    wrap.pack(side=tk.LEFT, padx=(0, 8))

    btn = tk.Label(wrap, text=label_text, bg=COLOR_BG, fg=COLOR_TAB_INACT,
                   font=FONT_TAB, padx=10, pady=6, cursor="hand2")
    btn.pack()

    underline = tk.Frame(wrap, bg=COLOR_BG, height=3)
    underline.pack(fill=tk.X, pady=(2, 0))

    page = tk.Frame(pages_container, bg=COLOR_SURFACE,
                    highlightthickness=1, highlightbackground=COLOR_BORDER)
    return wrap, btn, underline, page


# ---------- Создание вкладок ----------
# Вкладка 1
wrap1, btn1, ul1, page1 = make_tab("Генератор файла")
tabs.append((btn1, page1, ul1))
btn1.bind("<Button-1>", lambda e: select_tab(0))

# Вкладка 2
wrap2, btn2, ul2, page2 = make_tab("Регистратор датчика")
tabs.append((btn2, page2, ul2))
btn2.bind("<Button-1>", lambda e: select_tab(1))

# Вкладка 3
wrap3, btn3, ul3, page3 = make_tab("Справка")
tabs.append((btn3, page3, ul3))
btn3.bind("<Button-1>", lambda e: select_tab(2))


# =====================================================================
# СТРАНИЦА 1 — ГЕНЕРАТОР ФАЙЛА
# =====================================================================
p1 = tk.Frame(page1, bg=COLOR_SURFACE, padx=24, pady=20)
p1.pack(fill=tk.BOTH, expand=True)

tk.Label(p1, text="Параметры файла", bg=COLOR_SURFACE,
         fg=COLOR_TEXT, font=FONT_HEADER).grid(
    row=0, column=0, columnspan=3, sticky="w", pady=(0, 16))

# Имя файла — растягивается
tk.Label(p1, text="Имя файла:", bg=COLOR_SURFACE,
         fg=COLOR_TEXT, font=FONT_LABEL).grid(
    row=1, column=0, sticky="e", padx=(0, 12), pady=8)
app1_entry_file = ttk.Entry(p1, style="Field.TEntry", font=FONT_UI)
app1_entry_file.insert(0, "output.txt")
app1_entry_file.grid(row=1, column=1, sticky="we", pady=8)
ttk.Button(p1, text="📁 Обзор…", style="Secondary.TButton",
           command=browse_save_file).grid(
    row=1, column=2, sticky="w", padx=(12, 0), pady=8)

# Числовые поля — компактные
tk.Label(p1, text="Случайных чисел (N):", bg=COLOR_SURFACE,
         fg=COLOR_TEXT, font=FONT_LABEL).grid(
    row=2, column=0, sticky="e", padx=(0, 12), pady=8)
app1_entry_n = ttk.Entry(p1, style="Field.TEntry", font=FONT_UI, width=12)
app1_entry_n.insert(0, "20")
app1_entry_n.grid(row=2, column=1, sticky="w", pady=8)

tk.Label(p1, text="Точек функции:", bg=COLOR_SURFACE,
         fg=COLOR_TEXT, font=FONT_LABEL).grid(
    row=3, column=0, sticky="e", padx=(0, 12), pady=8)
app1_entry_steps = ttk.Entry(p1, style="Field.TEntry", font=FONT_UI, width=12)
app1_entry_steps.insert(0, "20")
app1_entry_steps.grid(row=3, column=1, sticky="w", pady=8)

# --- Пользовательский текст для Блока 1 ---
custom_header = tk.Frame(p1, bg=COLOR_SURFACE)
custom_header.grid(row=4, column=0, columnspan=3, sticky="we", pady=(12, 4))

tk.Label(custom_header, text="Свой текст для Блока 1 (необязательно):",
         bg=COLOR_SURFACE, fg=COLOR_TEXT, font=FONT_LABEL).pack(side=tk.LEFT)

# Кнопки инструментов справа
def load_custom_from_file():
    path = filedialog.askopenfilename(
        filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")]
    )
    if not path:
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        _clear_custom_placeholder()
        app1_custom_text.delete("1.0", "end")
        app1_custom_text.insert("1.0", content)
        log_message(app1_log, f"📁 Загружен текст из {path}")
        set_status(f"✔ Текст загружен из {path}", "success")
    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось прочитать файл:\n{e}")
        log_message(app1_log, f"✖ Ошибка чтения файла: {e}")
        set_status(f"✖ Ошибка чтения файла: {e}", "error")


def clear_custom_text():
    app1_custom_text.delete("1.0", "end")


ttk.Button(custom_header, text="Очистить", style="Secondary.TButton",
           command=clear_custom_text).pack(side=tk.RIGHT)
ttk.Button(custom_header, text="📁 Загрузить из файла…",
           style="Secondary.TButton",
           command=load_custom_from_file).pack(side=tk.RIGHT, padx=(0, 8))

custom_text_frame = tk.Frame(p1, bg=COLOR_SURFACE)
custom_text_frame.grid(row=5, column=0, columnspan=3, sticky="nsew",
                       pady=(0, 8))

app1_custom_text = tk.Text(
    custom_text_frame, height=6, wrap="word",
    font=FONT_LOG, fg=COLOR_TEXT, bg=COLOR_SURFACE,
    relief="solid", borderwidth=1,
    highlightthickness=1, highlightbackground=COLOR_BORDER,
    highlightcolor=COLOR_ACCENT,
    padx=10, pady=8, undo=True
)
app1_custom_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

custom_scroll = tk.Scrollbar(custom_text_frame, orient="vertical",
                             command=app1_custom_text.yview)
custom_scroll.pack(side=tk.RIGHT, fill=tk.Y)
app1_custom_text.config(yscrollcommand=custom_scroll.set)

# Подсказка-плейсхолдер
CUSTOM_TEXT_PLACEHOLDER = (
    "Введите или вставьте свой текст (Ctrl+V)…\n"
    "Если оставить поле пустым — Блок 1 будет сгенерирован автоматически."
)


def _insert_custom_placeholder(event=None):
    if app1_custom_text.get("1.0", "end-1c").strip() == "":
        app1_custom_text.insert("1.0", CUSTOM_TEXT_PLACEHOLDER)
        app1_custom_text.tag_configure("ph", foreground=COLOR_MUTED,
                                       font=("Segoe UI", 9, "italic"))
        app1_custom_text.tag_add("ph", "1.0", "end")


def _clear_custom_placeholder(event=None):
    if app1_custom_text.get("1.0", "end-1c").strip() == \
            CUSTOM_TEXT_PLACEHOLDER.strip():
        app1_custom_text.delete("1.0", "end")


_insert_custom_placeholder()
app1_custom_text.bind("<FocusIn>", _clear_custom_placeholder)
app1_custom_text.bind("<FocusOut>", _insert_custom_placeholder)

# Главная кнопка
ttk.Button(p1, text="▶ Сгенерировать файл", style="Accent.TButton",
           command=run_app1_generate).grid(
    row=6, column=0, columnspan=3, sticky="we", pady=(20, 16))

# Разделитель + журнал
ttk.Separator(p1, orient="horizontal").grid(
    row=7, column=0, columnspan=3, sticky="we", pady=(0, 12))

tk.Label(p1, text="Журнал операций", bg=COLOR_SURFACE,
         fg=COLOR_TEXT, font=FONT_HEADER).grid(
    row=8, column=0, columnspan=3, sticky="w", pady=(0, 8))
app1_log = create_log(p1)
app1_log.grid(row=9, column=0, columnspan=3, sticky="nsew")

p1.columnconfigure(1, weight=1)
p1.rowconfigure(5, weight=1)
p1.rowconfigure(9, weight=1)


# =====================================================================
# СТРАНИЦА 2 — РЕГИСТРАТОР ДАТЧИКА
# =====================================================================
p2 = tk.Frame(page2, bg=COLOR_SURFACE, padx=24, pady=20)
p2.pack(fill=tk.BOTH, expand=True)

tk.Label(p2, text="Параметры лога", bg=COLOR_SURFACE,
         fg=COLOR_TEXT, font=FONT_HEADER).grid(
    row=0, column=0, columnspan=3, sticky="w", pady=(0, 16))

# Имя файла лога
tk.Label(p2, text="Файл лога:", bg=COLOR_SURFACE,
         fg=COLOR_TEXT, font=FONT_LABEL).grid(
    row=1, column=0, sticky="e", padx=(0, 12), pady=8)
app2_entry_file = ttk.Entry(p2, style="Field.TEntry", font=FONT_UI)
app2_entry_file.insert(0, "sensor_log.csv")
app2_entry_file.grid(row=1, column=1, sticky="we", pady=8)
ttk.Button(p2, text="📁 Обзор…", style="Secondary.TButton",
           command=browse_log_file).grid(
    row=1, column=2, sticky="w", padx=(12, 0), pady=8)

ttk.Separator(p2, orient="horizontal").grid(
    row=2, column=0, columnspan=3, sticky="we", pady=16)

# Пакетный режим — единый блок «поле + кнопка»
batch_frame = tk.Frame(p2, bg=COLOR_SURFACE)
batch_frame.grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 8))

tk.Label(batch_frame, text="Пакетный режим", bg=COLOR_SURFACE,
         fg=COLOR_TEXT, font=FONT_HEADER).pack(anchor="w", pady=(0, 8))

batch_row = tk.Frame(batch_frame, bg=COLOR_SURFACE)
batch_row.pack(anchor="w")

tk.Label(batch_row, text="Строк:", bg=COLOR_SURFACE,
         fg=COLOR_TEXT, font=FONT_LABEL).pack(side=tk.LEFT, padx=(0, 8))
app2_entry_n = ttk.Entry(batch_row, style="Field.TEntry",
                          font=FONT_UI, width=10)
app2_entry_n.insert(0, "1000")
app2_entry_n.pack(side=tk.LEFT, padx=(0, 12))
ttk.Button(batch_row, text="✎ Сгенерировать пакет", style="Accent.TButton",
           command=run_app2_batch).pack(side=tk.LEFT)

ttk.Separator(p2, orient="horizontal").grid(
    row=4, column=0, columnspan=3, sticky="we", pady=16)

# Режим реального времени
tk.Label(p2, text="Режим реального времени", bg=COLOR_SURFACE,
         fg=COLOR_TEXT, font=FONT_HEADER).grid(
    row=5, column=0, columnspan=3, sticky="w", pady=(0, 8))

rt_frame = tk.Frame(p2, bg=COLOR_SURFACE)
rt_frame.grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 8))

app2_btn_start = ttk.Button(rt_frame, text="▶ Старт", style="Start.TButton",
                             command=run_app2_start_realtime)
app2_btn_start.pack(side=tk.LEFT, padx=(0, 8))

app2_btn_stop = ttk.Button(rt_frame, text="■ Стоп", style="Stop.TButton",
                            command=run_app2_stop_realtime, state=tk.DISABLED)
app2_btn_stop.pack(side=tk.LEFT, padx=(0, 16))

app2_label_counter = tk.Label(rt_frame, text="Записано строк: 0",
                               bg=COLOR_SURFACE, fg=COLOR_MUTED,
                               font=FONT_LABEL)
app2_label_counter.pack(side=tk.LEFT)

ttk.Separator(p2, orient="horizontal").grid(
    row=7, column=0, columnspan=3, sticky="we", pady=16)

# Журнал
tk.Label(p2, text="Журнал операций", bg=COLOR_SURFACE,
         fg=COLOR_TEXT, font=FONT_HEADER).grid(
    row=8, column=0, columnspan=3, sticky="w", pady=(0, 8))
app2_log = create_log(p2)
app2_log.grid(row=9, column=0, columnspan=3, sticky="nsew")

p2.columnconfigure(1, weight=1)
p2.rowconfigure(9, weight=1)


# =====================================================================
# СТРАНИЦА 3 — СПРАВКА
# =====================================================================
p3 = tk.Frame(page3, bg=COLOR_SURFACE, padx=24, pady=20)
p3.pack(fill=tk.BOTH, expand=True)

help_text = tk.Text(p3, wrap="word", font=("Segoe UI", 10),
                    fg=COLOR_TEXT, bg=COLOR_SURFACE,
                    relief="flat", borderwidth=0, padx=0, pady=0,
                    highlightthickness=0)
help_text.pack(fill=tk.BOTH, expand=True)

help_text.insert(
    "1.0",
    "ПРИЛОЖЕНИЕ 1 — ГЕНЕРАТОР КОМПЛЕКСНОГО ФАЙЛА\n"
    "────────────────────────────────────────────\n"
    "Создаёт текстовый файл с тремя блоками:\n\n"
    "  Блок 1 — произвольный текст. По умолчанию генерируется заново\n"
    "            при каждом запуске. Если заполнить поле «Свой текст\n"
    "            для Блока 1» — в файл будет записан именно ваш текст\n"
    "            (с датой создания в конце). Текст можно ввести вручную,\n"
    "            вставить через Ctrl+V или загрузить из .txt-файла;\n"
    "  Блок 2 — N случайных целых чисел от 1 до 100;\n"
    "  Блок 3 — значения функции y = sin(x) на отрезке [0, 2π]\n"
    "            по заданному числу точек.\n\n"
    "Блоки разделены маркерами «===» для читаемости.\n\n\n"
    "ПРИЛОЖЕНИЕ 2 — УМНЫЙ РЕГИСТРАТОР ДАННЫХ\n"
    "────────────────────────────────────────────\n"
    "Эмулирует промышленный датчик температуры.\n\n"
    "Формат строки:   Timestamp;Значение;Статус\n"
    "Значение — число с двумя знаками после точки (Excel не спутает с датой).\n\n"
    "Пороговые статусы:\n"
    "    • от -50 до -20 °C   → Заморозки\n"
    "    • от -19 до +40 °C   → Норма\n"
    "    • от +41 до +100 °C  → Перегрев\n"
    "    • от +101 до +150 °C → Пожар / Авария\n\n"
    "Режимы работы:\n"
    "    • Пакетный — мгновенно генерирует N строк и дописывает в файл;\n"
    "    • Режим реального времени — по одной строке раз в секунду\n"
    "      до нажатия кнопки «Стоп».\n\n"
    "Файл сохраняется в кодировке UTF-8 с BOM, чтобы Microsoft Excel\n"
    "корректно отображал кириллицу.\n"
)
help_text.config(state="disabled")


# =====================================================================
# ЗАПУСК
# =====================================================================
if __name__ == "__main__":
    try:
        select_tab(0)
        set_status("Готово к работе", "info")
        root.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)