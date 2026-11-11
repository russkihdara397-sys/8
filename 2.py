"""
Приложение для генерации текстовых файлов (ASCII-таблиц данных)
для осциллографа Electronics Workbench (EWB).

Среда разработки: Python 3 + стандартная библиотека tkinter/ttk.
Сторонние библиотеки не используются.

ТЕМА: Светлая минималистичная (Nord Light / Snow Storm).
Сохранены все исправления предыдущего ревью:
  • Высококонтрастный тёмный текст на светлом фоне.
  • Чёткие видимые рамки полей ввода, ограниченная ширина.
  • Главная кнопка стандартного размера по центру.
  • Увеличенные переключатели, условное скрытие полей.
  • Стилизованный Combobox без белой рамки из старой темы.
  • Компактный лог с моноширинным шрифтом.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import random


# ============================================================================
# ЦВЕТОВАЯ ПАЛИТРА И ШРИФТЫ (светлая тема, Snow Storm / Frost)
# ============================================================================
COLOR_BG        = "#ECEFF4"   # основной светлый фон окна
COLOR_PANEL     = "#FFFFFF"   # белые карточки-панели
COLOR_FIELD     = "#F8F9FB"   # очень светлая подложка полей ввода
COLOR_BORDER    = "#C2C8D4"   # видимая граница полей (серо-голубая)
COLOR_TEXT      = "#1E2430"   # почти чёрный основной текст
COLOR_TEXT_SOFT = "#2E3440"   # мягкий тёмный для подписей
COLOR_TEXT_DIM  = "#5E6A7A"   # приглушённый, но контрастный
COLOR_ACCENT    = "#3B82C4"   # акцентный синий (кнопка, фокус)
COLOR_ACCENT_HL = "#4E96D8"   # акцент при наведении
COLOR_ACCENT_FG = "#FFFFFF"   # текст на акцентной кнопке
COLOR_ERROR     = "#C0392B"   # тёмно-красный для ошибок (читаем на белом)
COLOR_SUCCESS   = "#2E7D32"   # тёмно-зелёный для успеха
COLOR_DISABLED  = "#E2E5EA"   # фон disabled-полей
COLOR_HEADER_BG = "#E3E8EF"   # фон заголовочной зоны (мягкий контраст)

FONT_MAIN   = ("Segoe UI", 10)
FONT_BOLD   = ("Segoe UI", 10, "bold")
FONT_TITLE  = ("Segoe UI", 16, "bold")
FONT_SMALL  = ("Segoe UI", 9)
FONT_LOG    = ("Consolas", 10)
FONT_RADIO  = ("Segoe UI", 11)


# ============================================================================
# ГЛАВНЫЙ КЛАСС ПРИЛОЖЕНИЯ
# ============================================================================
class EWBGeneratorApp(tk.Tk):
    """
    Главное окно приложения (светлая тема).
    Отвечает за построение интерфейса, валидацию, генерацию данных
    и сохранение файла в формате Electronics Workbench.
    """

    def __init__(self):
        """Конструктор: настраивает окно, стили и строит виджеты."""
        super().__init__()

        self.title("EWB Oscilloscope Data Generator")
        self.geometry("620x700")
        self.minsize(600, 660)
        self.configure(bg=COLOR_BG)

        # --- Переменные состояния ---
        self.var_delta_t    = tk.StringVar(value="0.001")
        self.var_total_t    = tk.StringVar(value="0.1")
        self.var_mode       = tk.StringVar(value="manual")
        self.var_bitstring  = tk.StringVar(value="10101100")
        self.var_bitcount   = tk.StringVar(value="16")
        self.var_decimals   = tk.StringVar(value="6")
        self.var_v_low      = tk.StringVar(value="0")
        self.var_v_high     = tk.StringVar(value="5")

        self._setup_styles()
        self._build_ui()
        self._on_mode_change()

    # ------------------------------------------------------------------
    # СТИЛИ
    # ------------------------------------------------------------------
    def _setup_styles(self):
        """
        Настраивает стили ttk для светлой плоской темы.
        Ключевые моменты: белые карточки, тёмный текст,
        видимые серо-голубые рамки полей, синий акцент.
        """
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Общий фон
        style.configure(".", background=COLOR_BG,
                        foreground=COLOR_TEXT, font=FONT_MAIN)

        # Фреймы-панели (карточки на светлом фоне)
        style.configure("Panel.TFrame", background=COLOR_PANEL, relief="flat")
        style.configure("Card.TFrame",  background=COLOR_PANEL, relief="flat")
        # Фрейм заголовка — слегка тонированный
        style.configure("Header.TFrame", background=COLOR_HEADER_BG, relief="flat")

        # Метки
        style.configure("TLabel", background=COLOR_PANEL,
                        foreground=COLOR_TEXT_SOFT, font=FONT_MAIN)
        style.configure("Title.TLabel", background=COLOR_HEADER_BG,
                        foreground=COLOR_TEXT, font=FONT_TITLE)
        style.configure("Sub.TLabel", background=COLOR_HEADER_BG,
                        foreground=COLOR_TEXT_DIM, font=FONT_SMALL)
        style.configure("FieldLabel.TLabel", background=COLOR_PANEL,
                        foreground=COLOR_TEXT, font=FONT_MAIN)
        style.configure("Hint.TLabel", background=COLOR_PANEL,
                        foreground=COLOR_TEXT_DIM, font=FONT_SMALL)

        # Поля ввода: светлая подложка + чёткая серо-голубая рамка
        style.configure("TEntry",
                        fieldbackground=COLOR_FIELD,
                        foreground=COLOR_TEXT,
                        background=COLOR_FIELD,
                        bordercolor=COLOR_BORDER,
                        lightcolor=COLOR_BORDER,
                        darkcolor=COLOR_BORDER,
                        insertcolor=COLOR_TEXT,
                        padding=6,
                        relief="solid",
                        borderwidth=1)
        style.map("TEntry",
                  bordercolor=[("focus", COLOR_ACCENT)],
                  lightcolor=[("focus", COLOR_ACCENT)],
                  darkcolor=[("focus", COLOR_ACCENT)],
                  fieldbackground=[("disabled", COLOR_DISABLED)],
                  foreground=[("disabled", COLOR_TEXT_DIM)])

        # Переключатели
        style.configure("TRadiobutton",
                        background=COLOR_PANEL,
                        foreground=COLOR_TEXT,
                        font=FONT_RADIO,
                        indicatorcolor=COLOR_FIELD,
                        padding=6)
        style.map("TRadiobutton",
                  background=[("active", COLOR_PANEL)],
                  foreground=[("active", COLOR_ACCENT)],
                  indicatorcolor=[("selected", COLOR_ACCENT)])

        # Combobox под светлую тему (без белой рамки из старой темы)
        style.configure("TCombobox",
                        fieldbackground=COLOR_FIELD,
                        background=COLOR_FIELD,
                        foreground=COLOR_TEXT,
                        arrowcolor=COLOR_ACCENT,
                        bordercolor=COLOR_BORDER,
                        lightcolor=COLOR_BORDER,
                        darkcolor=COLOR_BORDER,
                        padding=6,
                        relief="solid",
                        borderwidth=1)
        style.map("TCombobox",
                  fieldbackground=[("readonly", COLOR_FIELD), ("disabled", COLOR_DISABLED)],
                  foreground=[("readonly", COLOR_TEXT)],
                  bordercolor=[("focus", COLOR_ACCENT)],
                  lightcolor=[("focus", COLOR_ACCENT)],
                  darkcolor=[("focus", COLOR_ACCENT)])

        # Выпадающий список Combobox
        self.option_add("*TCombobox*Listbox.background", COLOR_PANEL)
        self.option_add("*TCombobox*Listbox.foreground", COLOR_TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", COLOR_ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", COLOR_ACCENT_FG)
        self.option_add("*TCombobox*Listbox.font", FONT_MAIN)

        # Главная кнопка (синий акцент, белый текст)
        style.configure("Accent.TButton",
                        background=COLOR_ACCENT,
                        foreground=COLOR_ACCENT_FG,
                        font=FONT_BOLD,
                        padding=(20, 10),
                        relief="flat",
                        borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", COLOR_ACCENT_HL), ("pressed", COLOR_ACCENT)],
                  foreground=[("active", COLOR_ACCENT_FG)])

        # Разделитель
        style.configure("TSeparator", background=COLOR_BORDER)

    # ------------------------------------------------------------------
    # ПОСТРОЕНИЕ ИНТЕРФЕЙСА
    # ------------------------------------------------------------------
    def _build_ui(self):
        """Создаёт и размещает все виджеты окна (светлая тема)."""
        # ----- Заголовочная зона с мягким тонированным фоном -----
        header = ttk.Frame(self, style="Header.TFrame", padding=(24, 20))
        header.pack(fill="x")

        ttk.Label(header, text="Генератор данных для осциллографа EWB",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(header,
                  text="Создание ASCII-таблиц Time\\tV1 для Electronics Workbench",
                  style="Sub.TLabel").pack(anchor="w", pady=(2, 0))

        # ----- Карточка параметров сигнала -----
        params = ttk.Frame(self, style="Card.TFrame", padding=20)
        params.pack(fill="x", padx=24, pady=(16, 8))
        # Тонкая рамка-контур карточки через отдельный TFrame не делаем —
        # на светлом фоне белая карточка и так отделена от #ECEFF4.

        ttk.Label(params, text="Параметры сигнала",
                  style="TLabel", font=FONT_BOLD).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))

        # Поля с ограниченной шириной
        self._make_labeled_entry(
            params, row=1, col=0, label="Шаг по времени (Delta T), с:",
            var=self.var_delta_t, width=14)
        self._make_labeled_entry(
            params, row=1, col=1, label="Длительность передачи (Total Time), с:",
            var=self.var_total_t, width=14)
        self._make_labeled_entry(
            params, row=2, col=0, label="Уровень лог. 0, В:",
            var=self.var_v_low, width=14)
        self._make_labeled_entry(
            params, row=2, col=1, label="Уровень лог. 1, В:",
            var=self.var_v_high, width=14)

        params.columnconfigure(0, weight=1)
        params.columnconfigure(1, weight=1)
        params.columnconfigure(2, weight=1)

        # ----- Карточка режима формирования последовательности -----
        mode_card = ttk.Frame(self, style="Card.TFrame", padding=20)
        mode_card.pack(fill="x", padx=24, pady=8)

        ttk.Label(mode_card, text="Формирование последовательности бит",
                  style="TLabel", font=FONT_BOLD).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        # Переключатели (увеличенные)
        ttk.Radiobutton(mode_card, text="Вручную",
                        variable=self.var_mode, value="manual",
                        command=self._on_mode_change).grid(
            row=1, column=0, sticky="w", padx=(0, 30), pady=(0, 8))
        ttk.Radiobutton(mode_card, text="Случайно",
                        variable=self.var_mode, value="random",
                        command=self._on_mode_change).grid(
            row=1, column=1, sticky="w", pady=(0, 8))

        # ---- Поле битовой строки (скрываемое в режиме "Случайно") ----
        self.frame_bitstring = ttk.Frame(mode_card, style="Card.TFrame")
        self.frame_bitstring.grid(row=2, column=0, columnspan=3, sticky="ew",
                                  pady=(10, 0))
        ttk.Label(self.frame_bitstring, text="Битовая строка (только 0 и 1):",
                  style="FieldLabel.TLabel").pack(anchor="w", pady=(0, 4))
        self.entry_bitstring = ttk.Entry(self.frame_bitstring,
                                         textvariable=self.var_bitstring,
                                         width=24)
        self.entry_bitstring.pack(anchor="w")

        # ---- Поле количества бит (скрываемое в режиме "Вручную") ----
        self.frame_bitcount = ttk.Frame(mode_card, style="Card.TFrame")
        self.frame_bitcount.grid(row=2, column=0, columnspan=3, sticky="ew",
                                 pady=(10, 0))
        ttk.Label(self.frame_bitcount, text="Количество бит:",
                  style="FieldLabel.TLabel").pack(anchor="w", pady=(0, 4))
        self.entry_bitcount = ttk.Entry(self.frame_bitcount,
                                        textvariable=self.var_bitcount,
                                        width=14)
        self.entry_bitcount.pack(anchor="w")

        # ---- Комбобокс знаков после запятой ----
        dec_frame = ttk.Frame(mode_card, style="Card.TFrame")
        dec_frame.grid(row=3, column=0, columnspan=3, sticky="w", pady=(14, 0))
        ttk.Label(dec_frame, text="Знаков после запятой у времени:",
                  style="FieldLabel.TLabel").pack(anchor="w", pady=(0, 4))
        self.combo_decimals = ttk.Combobox(
            dec_frame, textvariable=self.var_decimals,
            values=("4", "6", "8"), state="readonly", width=8)
        self.combo_decimals.pack(anchor="w")

        # Подсказка
        ttk.Label(mode_card,
                  text="Примечание: длительность одного бита = Total Time / Кол-во бит.",
                  style="Hint.TLabel").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(14, 0))

        mode_card.columnconfigure(0, weight=1)
        mode_card.columnconfigure(1, weight=1)
        mode_card.columnconfigure(2, weight=1)

        # ----- Кнопка генерации: стандартный размер, по центру -----
        btn_frame = ttk.Frame(self, style="TFrame")
        btn_frame.pack(fill="x", padx=24, pady=(16, 4))
        self.btn_generate = ttk.Button(btn_frame, text="Сгенерировать и сохранить",
                                       style="Accent.TButton",
                                       command=self._on_generate)
        self.btn_generate.pack(side="top")

        # ----- Лог / статус-бар: компактный, контрастный -----
        log_frame = ttk.Frame(self, style="Card.TFrame", padding=12)
        log_frame.pack(fill="x", padx=24, pady=(8, 20))

        ttk.Label(log_frame, text="Лог / статус:",
                  style="TLabel", font=FONT_BOLD).pack(anchor="w", pady=(0, 6))

        log_inner = ttk.Frame(log_frame, style="Card.TFrame")
        log_inner.pack(fill="x", expand=False)

        self.log_text = tk.Text(
            log_inner, height=4, wrap="word",
            bg=COLOR_FIELD, fg=COLOR_TEXT,
            insertbackground=COLOR_TEXT,
            font=FONT_LOG, relief="solid", borderwidth=1,
            highlightthickness=0,
            padx=10, pady=8)
        self.log_text.pack(fill="x", side="left", expand=True)

        scroll = ttk.Scrollbar(log_inner, orient="vertical",
                               command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.configure(state="disabled")

    def _make_labeled_entry(self, parent, row, col, label, var, width=14):
        """
        Создаёт подпись + поле ввода фиксированной ширины.
        """
        ttk.Label(parent, text=label, style="FieldLabel.TLabel").grid(
            row=row * 2 - 1, column=col, sticky="w", pady=(10, 4), padx=(0, 10))
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.grid(row=row * 2, column=col, sticky="w", padx=(0, 10))
        return entry

    # ------------------------------------------------------------------
    # ЛОГИКА ИНТЕРФЕЙСА
    # ------------------------------------------------------------------
    def _on_mode_change(self):
        """
        Смена режима: скрываем ненужное поле через grid_remove().
        """
        if self.var_mode.get() == "manual":
            self.frame_bitcount.grid_remove()
            self.frame_bitstring.grid()
        else:
            self.frame_bitstring.grid_remove()
            self.frame_bitcount.grid()

    def _log(self, message, kind="info"):
        """Добавляет сообщение в лог с цветовой индикацией."""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        tag = f"tag_{kind}"
        self.log_text.tag_add(tag, "end-2l", "end-1l")
        color = COLOR_TEXT
        if kind == "error":
            color = COLOR_ERROR
        elif kind == "success":
            color = COLOR_SUCCESS
        self.log_text.tag_config(tag, foreground=color)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # ВАЛИДАЦИЯ
    # ------------------------------------------------------------------
    def _parse_float(self, value, field_name):
        """Парсит положительное число с плавающей точкой."""
        try:
            num = float(value.replace(",", ".").strip())
        except (ValueError, AttributeError):
            raise ValueError(f"Поле «{field_name}» должно содержать число.")
        if num <= 0:
            raise ValueError(f"Поле «{field_name}» должно быть больше нуля.")
        return num

    def _parse_int(self, value, field_name):
        """Парсит положительное целое число."""
        try:
            num = int(str(value).strip())
        except (ValueError, AttributeError):
            raise ValueError(f"Поле «{field_name}» должно содержать целое число.")
        if num <= 0:
            raise ValueError(f"Поле «{field_name}» должно быть больше нуля.")
        return num

    def _validate_bitstring(self, s):
        """Проверяет, что строка состоит только из '0' и '1'."""
        s = s.strip()
        if not s:
            raise ValueError("Битовая строка не должна быть пустой.")
        if any(ch not in ("0", "1") for ch in s):
            raise ValueError("Битовая строка может содержать только '0' и '1'.")
        return s

    def _validate_all(self):
        """Полная валидация всех полей."""
        delta_t = self._parse_float(self.var_delta_t.get(), "Шаг по времени")
        total_t = self._parse_float(self.var_total_t.get(), "Длительность передачи")
        v_low   = float(self.var_v_low.get().replace(",", ".").strip())
        v_high  = float(self.var_v_high.get().replace(",", ".").strip())

        try:
            decimals = int(self.var_decimals.get())
        except ValueError:
            raise ValueError("Некорректное число знаков после запятой.")
        if decimals < 0 or decimals > 12:
            raise ValueError("Число знаков после запятой должно быть от 0 до 12.")

        if self.var_mode.get() == "manual":
            bits = self._validate_bitstring(self.var_bitstring.get())
        else:
            n = self._parse_int(self.var_bitcount.get(), "Количество бит")
            bits = "".join(random.choice("01") for _ in range(n))

        if total_t <= 0:
            raise ValueError("Длительность передачи должна быть больше нуля.")
        bit_duration = total_t / len(bits)
        if bit_duration <= 0:
            raise ValueError("Длительность одного бита должна быть больше нуля.")
        if delta_t > total_t:
            raise ValueError("Шаг по времени не должен превышать длительность передачи.")

        return delta_t, total_t, bits, decimals, v_low, v_high

    # ------------------------------------------------------------------
    # ГЕНЕРАЦИЯ ДАННЫХ
    # ------------------------------------------------------------------
    def _generate_data(self, delta_t, total_t, bits, decimals, v_low, v_high):
        """Формирует список строк '<время>\\t<напряжение>'."""
        bit_duration = total_t / len(bits)
        time_fmt = f"{{:.{decimals}f}}"

        def fmt_level(v):
            if float(v).is_integer():
                return str(int(v))
            return f"{v:g}"

        v_low_str  = fmt_level(v_low)
        v_high_str = fmt_level(v_high)

        lines = []
        n_points = int(round(total_t / delta_t)) + 1
        for i in range(n_points):
            t = i * delta_t
            if t > total_t + 1e-12:
                break
            bit_index = int(t / bit_duration)
            if bit_index >= len(bits):
                bit_index = len(bits) - 1
            level = v_high_str if bits[bit_index] == "1" else v_low_str
            lines.append(f"{time_fmt.format(t)}\t{level}")
        return lines

    # ------------------------------------------------------------------
    # СОХРАНЕНИЕ
    # ------------------------------------------------------------------
    def _save_file(self, lines):
        """Открывает диалог сохранения и пишет файл формата EWB."""
        path = filedialog.asksaveasfilename(
            title="Сохранить файл данных EWB",
            defaultextension=".txt",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
            initialfile="ewb_data.txt")
        if not path:
            self._log("Сохранение отменено пользователем.", "info")
            return

        header = [
            "ASCII output data for Electronics Workbench circuit untitled",
            "Time\tV1",
        ]
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(header) + "\n")
                f.write("\n".join(lines) + "\n")
        except OSError as e:
            self._log(f"Ошибка записи файла: {e}", "error")
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{e}")
            return

        self._log(f"Файл успешно сохранён: {path} "
                  f"(строк данных: {len(lines)})", "success")
        messagebox.showinfo("Готово", "Файл успешно сохранён.")

    # ------------------------------------------------------------------
    # ГЛАВНЫЙ ОБРАБОТЧИК КНОПКИ
    # ------------------------------------------------------------------
    def _on_generate(self):
        """Валидация → генерация → сохранение."""
        try:
            params = self._validate_all()
        except ValueError as e:
            self._log(f"Ошибка: {e}", "error")
            messagebox.showerror("Ошибка валидации", str(e))
            return

        try:
            lines = self._generate_data(*params)
        except Exception as e:
            self._log(f"Ошибка генерации: {e}", "error")
            messagebox.showerror("Ошибка", f"Не удалось сгенерировать данные:\n{e}")
            return

        self._log(f"Сгенерировано точек: {len(lines)}. "
                  f"Открывается диалог сохранения...", "info")
        self._save_file(lines)


# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================
if __name__ == "__main__":
    app = EWBGeneratorApp()
    app.mainloop()