# -*- coding: utf-8 -*-
"""
Приложение для генерации табличных отчётов в форматах .docx и .xlsx.
Реализовано на чистом Python 3 + tkinter (без сторонних библиотек).
"""

import io
import os
import random
import re
import zipfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from xml.sax.saxutils import escape


# =============================================================================
# КОНСТАНТЫ ОФОРМЛЕНИЯ (СВЕТЛАЯ FLAT-ТЕМА)
# =============================================================================

COLOR_BG            = "#F4F6F9"
COLOR_CARD          = "#FFFFFF"
COLOR_FG            = "#202124"
COLOR_FG_MUTED      = "#5F6368"
COLOR_ACCENT        = "#1A73E8"
COLOR_ACCENT_HOVER  = "#4285F4"
COLOR_ACCENT_PRESS  = "#1558C0"
COLOR_ENTRY_BG      = "#FFFFFF"
COLOR_ENTRY_BORDER  = "#DADCE0"
COLOR_ERROR_BORDER  = "#C5221F"
COLOR_BORDER        = "#E0E3E7"
COLOR_SUCCESS       = "#188038"
COLOR_ERROR         = "#C5221F"

FONT_FAMILY         = "Segoe UI"
FONT_TITLE          = (FONT_FAMILY, 15, "bold")
FONT_SUBTITLE       = (FONT_FAMILY, 10)
FONT_LABEL          = (FONT_FAMILY, 10)
FONT_LABEL_BOLD     = (FONT_FAMILY, 10, "bold")
FONT_ENTRY          = (FONT_FAMILY, 10)
FONT_BUTTON         = (FONT_FAMILY, 12, "bold")   # FIX: было 11 — кнопка чуть крупнее
FONT_STATUS         = (FONT_FAMILY, 10)
FONT_HINT           = (FONT_FAMILY, 9)

# FIX: регулярка для корректной проверки целого числа
INT_RE = re.compile(r"^-?\d+$")


# =============================================================================
# КЛАСС ПРИЛОЖЕНИЯ
# =============================================================================

class ReportGeneratorApp:
    """Главный класс: UI, валидация, генерация данных, экспорт .docx/.xlsx."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Генератор табличных отчётов")
        self.root.geometry("820x780")
        self.root.minsize(780, 720)
        self.root.configure(bg=COLOR_BG)

        # --- Модель ---
        self.var_count    = tk.StringVar(value="10")
        self.var_mode     = tk.StringVar(value="Автоматически")
        self.var_format   = tk.StringVar(value="xlsx")
        self.var_save_dir = tk.StringVar(value=os.path.expanduser("~"))
        self.var_filename = tk.StringVar(value="Отчёт_измерений")
        self.var_status   = tk.StringVar(value="Готово к работе")

        self.var_ext_hint = tk.StringVar(value=".xlsx")

        self.var_count_err  = tk.StringVar(value="")
        self.var_manual_err = tk.StringVar(value="")

        self.entry_count:  ttk.Entry | None = None
        self.txt_manual:   tk.Text    | None = None
        self.frame_manual: tk.Frame   | None = None
        self.lbl_count_err:  tk.Label | None = None
        self.lbl_manual_err: tk.Label | None = None
        self.entry_filename: ttk.Entry | None = None
        self.entry_dir:      ttk.Entry | None = None
        self.status_label: tk.Label   | None = None
        self.status_icon:  tk.Label   | None = None
        self.lbl_save_path_value: tk.Label | None = None
        self.lbl_ext_hint: tk.Label | None = None  # FIX: явное объявление

        self._setup_styles()
        self._build_ui()

        # Трейсы
        self.var_mode.trace_add("write", lambda *_: self._on_mode_changed())
        self.var_count.trace_add("write", lambda *_: self._validate_count_live())
        self.var_format.trace_add("write", lambda *_: self._update_extension_hint())
        self.var_save_dir.trace_add("write", lambda *_: self._update_path_label())

        self._on_mode_changed()
        self._update_extension_hint()
        self._update_path_label()

    # -------------------------------------------------------------------------
    # СТИЛИ
    # -------------------------------------------------------------------------

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=COLOR_BG,
                        foreground=COLOR_FG, font=FONT_LABEL)

        style.configure("Card.TFrame", background=COLOR_CARD,
                        relief="flat", borderwidth=1)

        style.configure("Title.TLabel", background=COLOR_BG,
                        foreground=COLOR_FG, font=FONT_TITLE)
        style.configure("Subtitle.TLabel", background=COLOR_BG,
                        foreground=COLOR_FG_MUTED, font=FONT_SUBTITLE)

        style.configure("TLabel", background=COLOR_CARD,
                        foreground=COLOR_FG, font=FONT_LABEL)
        style.configure("Bold.TLabel", background=COLOR_CARD,
                        foreground=COLOR_FG, font=FONT_LABEL_BOLD)
        style.configure("Muted.TLabel", background=COLOR_CARD,
                        foreground=COLOR_FG_MUTED, font=FONT_LABEL)
        style.configure("Hint.TLabel", background=COLOR_CARD,
                        foreground=COLOR_FG_MUTED, font=FONT_HINT)
        style.configure("Error.TLabel", background=COLOR_CARD,
                        foreground=COLOR_ERROR, font=FONT_HINT)

        style.configure("Flat.TEntry",
                        fieldbackground=COLOR_ENTRY_BG,
                        foreground=COLOR_FG,
                        bordercolor=COLOR_ENTRY_BORDER,
                        lightcolor=COLOR_ENTRY_BORDER,
                        darkcolor=COLOR_ENTRY_BORDER,
                        padding=6, font=FONT_ENTRY)
        style.map("Flat.TEntry",
                  bordercolor=[("focus", COLOR_ACCENT),
                               ("invalid", COLOR_ERROR_BORDER)],
                  lightcolor=[("focus", COLOR_ACCENT)],
                  darkcolor=[("focus", COLOR_ACCENT)])

        style.configure("Error.TEntry",
                        fieldbackground=COLOR_ENTRY_BG,
                        foreground=COLOR_FG,
                        bordercolor=COLOR_ERROR_BORDER,
                        lightcolor=COLOR_ERROR_BORDER,
                        darkcolor=COLOR_ERROR_BORDER,
                        padding=6, font=FONT_ENTRY)
        # FIX: добавляем map, чтобы при фокусе рамка тоже оставалась красной
        style.map("Error.TEntry",
                  bordercolor=[("focus", COLOR_ERROR_BORDER)],
                  lightcolor=[("focus", COLOR_ERROR_BORDER)],
                  darkcolor=[("focus", COLOR_ERROR_BORDER)])

        style.configure("Flat.TRadiobutton", background=COLOR_CARD,
                        foreground=COLOR_FG, font=FONT_LABEL)
        style.map("Flat.TRadiobutton",
                  background=[("active", COLOR_CARD)],
                  foreground=[("active", COLOR_FG)])

        # FIX: кнопка стала крупнее (шрифт 12, отступы 28×12)
        style.configure("Accent.TButton",
                        background=COLOR_ACCENT, foreground="#FFFFFF",
                        font=FONT_BUTTON, borderwidth=0,
                        focusthickness=0, padding=(28, 12))
        style.map("Accent.TButton",
                  background=[("active", COLOR_ACCENT_HOVER),
                              ("pressed", COLOR_ACCENT_PRESS)],
                  foreground=[("disabled", "#B0B6BC")])

        style.configure("Secondary.TButton",
                        background=COLOR_CARD, foreground=COLOR_FG_MUTED,
                        font=FONT_LABEL, borderwidth=0, padding=(4, 4))
        style.map("Secondary.TButton",
                  background=[("active", "#F1F3F4"),
                              ("pressed", "#E8EAED")])

    # -------------------------------------------------------------------------
    # ПОСТРОЕНИЕ UI
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_status_bar()

        outer = tk.Frame(self.root, bg=COLOR_BG)
        outer.pack(fill="both", expand=True, padx=20, pady=(16, 0))

        header = tk.Frame(outer, bg=COLOR_BG)
        header.pack(fill="x", pady=(0, 12))
        tk.Label(header, text="Генератор табличных отчётов",
                 bg=COLOR_BG, fg=COLOR_FG, font=FONT_TITLE).pack(anchor="w")
        tk.Label(header, text="Создание таблицы измерений в Word и Excel",
                 bg=COLOR_BG, fg=COLOR_FG_MUTED, font=FONT_SUBTITLE
                 ).pack(anchor="w", pady=(2, 0))

        self._build_params_card(outer)
        self._build_mode_card(outer)
        self._build_format_card(outer)
        self._build_save_card(outer)

        btn_frame = tk.Frame(outer, bg=COLOR_BG)
        btn_frame.pack(fill="x", pady=(16, 12))
        self.btn_generate = ttk.Button(
            btn_frame, text="Сгенерировать и сохранить",
            style="Accent.TButton", command=self.on_generate)
        self.btn_generate.pack(anchor="center")  # FIX: было anchor="w"

    def _build_status_bar(self) -> None:
        self.status_frame = tk.Frame(self.root, bg="#E8EAED", height=36)
        self.status_frame.pack(fill="x", side="bottom")
        self.status_frame.pack_propagate(False)

        self.status_icon = tk.Label(self.status_frame, text="●",
                                    bg="#E8EAED", fg=COLOR_FG_MUTED,
                                    font=(FONT_FAMILY, 11))
        self.status_icon.pack(side="left", padx=(16, 6))

        self.status_label = tk.Label(
            self.status_frame, textvariable=self.var_status,
            bg="#E8EAED", fg=COLOR_FG_MUTED,
            font=FONT_STATUS, anchor="w", justify="left")
        self.status_label.pack(side="left", fill="x", expand=True, pady=8)

    # -------------------------------------------------------------------------
    # Карточки
    # -------------------------------------------------------------------------

    def _build_params_card(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg=COLOR_CARD, bd=0,
                        highlightthickness=1,
                        highlightbackground=COLOR_BORDER)
        card.pack(fill="x", pady=(0, 10))

        inner = tk.Frame(card, bg=COLOR_CARD, padx=16, pady=12)
        inner.pack(fill="x")

        tk.Label(inner, text="Объём выборки (N)",
                 bg=COLOR_CARD, fg=COLOR_FG, font=FONT_LABEL_BOLD
                 ).grid(row=0, column=0, sticky="w")

        self.entry_count = ttk.Entry(inner, textvariable=self.var_count,
                                     style="Flat.TEntry", width=28)
        self.entry_count.grid(row=0, column=1, sticky="w", padx=(12, 0))

        self.lbl_count_err = tk.Label(
            inner, text="Количество строк таблицы (от 1 до 10000)",
            bg=COLOR_CARD, fg=COLOR_FG_MUTED, font=FONT_HINT)
        self.lbl_count_err.grid(row=1, column=0, columnspan=2,
                                sticky="w", pady=(6, 0))

        inner.grid_columnconfigure(2, weight=1)

    def _build_mode_card(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg=COLOR_CARD, bd=0,
                        highlightthickness=1,
                        highlightbackground=COLOR_BORDER)
        card.pack(fill="x", pady=(0, 10))

        inner = tk.Frame(card, bg=COLOR_CARD, padx=16, pady=12)
        inner.pack(fill="x")

        tk.Label(inner, text="Способ заполнения",
                 bg=COLOR_CARD, fg=COLOR_FG, font=FONT_LABEL_BOLD
                 ).pack(anchor="w", pady=(0, 6))

        ttk.Radiobutton(inner, text="Автоматически (случайные числа 0–100)",
                        variable=self.var_mode, value="Автоматически",
                        style="Flat.TRadiobutton").pack(anchor="w", pady=(0, 4))

        ttk.Radiobutton(inner, text="Вручную",
                        variable=self.var_mode, value="Вручную",
                        style="Flat.TRadiobutton").pack(anchor="w")

        self.frame_manual = tk.Frame(inner, bg=COLOR_CARD)

        hint = ("Введите N чисел через запятую, пробел или с новой строки.\n"
                "Например: 15, 42, 87, 3, 100. Каждое число — целое, 0–100.")
        tk.Label(self.frame_manual, text=hint, bg=COLOR_CARD,
                 fg=COLOR_FG_MUTED, font=FONT_HINT,
                 justify="left").pack(anchor="w", pady=(6, 4))

        self.txt_manual = tk.Text(
            self.frame_manual, height=3, wrap="word",
            bg=COLOR_ENTRY_BG, fg=COLOR_FG,
            insertbackground=COLOR_FG,
            relief="flat", bd=0,
            highlightthickness=1,
            highlightbackground=COLOR_ENTRY_BORDER,
            highlightcolor=COLOR_ACCENT,
            font=FONT_ENTRY, padx=8, pady=6)
        self.txt_manual.pack(fill="x")
        self.txt_manual.bind("<KeyRelease>",
                             lambda _e: self._validate_manual_live())

        self.lbl_manual_err = tk.Label(
            self.frame_manual, text="", bg=COLOR_CARD, fg=COLOR_ERROR,
            font=FONT_HINT, justify="left")
        self.lbl_manual_err.pack(anchor="w", pady=(4, 0))

    def _build_format_card(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg=COLOR_CARD, bd=0,
                        highlightthickness=1,
                        highlightbackground=COLOR_BORDER)
        card.pack(fill="x", pady=(0, 10))

        inner = tk.Frame(card, bg=COLOR_CARD, padx=16, pady=12)
        inner.pack(fill="x")

        tk.Label(inner, text="Формат сохранения",
                 bg=COLOR_CARD, fg=COLOR_FG, font=FONT_LABEL_BOLD
                 ).pack(anchor="w", pady=(0, 6))

        ttk.Radiobutton(inner, text="Microsoft Word (.docx)",
                        variable=self.var_format, value="docx",
                        style="Flat.TRadiobutton").pack(anchor="w", pady=(0, 4))
        ttk.Radiobutton(inner, text="Microsoft Excel (.xlsx)",
                        variable=self.var_format, value="xlsx",
                        style="Flat.TRadiobutton").pack(anchor="w", pady=(0, 4))
        ttk.Radiobutton(inner, text="Оба формата (Word и Excel)",
                        variable=self.var_format, value="both",
                        style="Flat.TRadiobutton").pack(anchor="w")

    def _build_save_card(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg=COLOR_CARD, bd=0,
                        highlightthickness=1,
                        highlightbackground=COLOR_BORDER)
        card.pack(fill="x", pady=(0, 4))

        inner = tk.Frame(card, bg=COLOR_CARD, padx=16, pady=12)
        inner.pack(fill="x")

        tk.Label(inner, text="Куда сохранить",
                 bg=COLOR_CARD, fg=COLOR_FG, font=FONT_LABEL_BOLD
                 ).grid(row=0, column=0, columnspan=4, sticky="w",
                        pady=(0, 8))

        tk.Label(inner, text="Имя файла",
                 bg=COLOR_CARD, fg=COLOR_FG, font=FONT_LABEL
                 ).grid(row=1, column=0, sticky="w")

        self.entry_filename = ttk.Entry(inner, textvariable=self.var_filename,
                                        style="Flat.TEntry", width=28)
        self.entry_filename.grid(row=1, column=1, sticky="w", padx=(12, 0))

        self.lbl_ext_hint = tk.Label(inner, textvariable=self.var_ext_hint,
                                     bg=COLOR_CARD, fg=COLOR_FG_MUTED,
                                     font=FONT_ENTRY)
        self.lbl_ext_hint.grid(row=1, column=2, sticky="w", padx=(6, 0))

        tk.Label(inner, text="Папка",
                 bg=COLOR_CARD, fg=COLOR_FG, font=FONT_LABEL
                 ).grid(row=2, column=0, sticky="w", pady=(12, 0))

        self.entry_dir = ttk.Entry(inner, textvariable=self.var_save_dir,
                                   style="Flat.TEntry", width=28)
        self.entry_dir.grid(row=2, column=1, sticky="w", padx=(12, 0), pady=(12, 0))

        btn_browse = ttk.Button(inner, text="📁",
                                style="Secondary.TButton",
                                width=3,
                                command=self._on_browse_dir)
        btn_browse.grid(row=2, column=2, sticky="w", padx=(6, 0), pady=(12, 0))

        path_frame = tk.Frame(inner, bg=COLOR_CARD)
        path_frame.grid(row=3, column=0, columnspan=4, sticky="w", pady=(12, 0))

        tk.Label(path_frame, text="Файлы будут сохранены в: ",
                 bg=COLOR_CARD, fg=COLOR_FG_MUTED, font=FONT_LABEL
                 ).pack(side="left")

        self.lbl_save_path_value = tk.Label(path_frame, text="",
                                            bg=COLOR_CARD, fg=COLOR_FG,
                                            font=FONT_LABEL_BOLD)
        self.lbl_save_path_value.pack(side="left")

        inner.grid_columnconfigure(3, weight=1)

    # -------------------------------------------------------------------------
    # ОБРАБОТЧИКИ
    # -------------------------------------------------------------------------

    def _update_extension_hint(self) -> None:
        fmt = self.var_format.get()
        if fmt == "docx":
            self.var_ext_hint.set(".docx")
        elif fmt == "xlsx":
            self.var_ext_hint.set(".xlsx")
        else:
            self.var_ext_hint.set(".*")

    def _update_path_label(self) -> None:
        if self.lbl_save_path_value is not None:
            path = self.var_save_dir.get() or "Не выбрано"
            self.lbl_save_path_value.configure(text=path)

    def _on_browse_dir(self) -> None:
        d = filedialog.askdirectory(
            title="Выберите папку для сохранения",
            initialdir=self.var_save_dir.get() or os.path.expanduser("~"))
        if d:
            self.var_save_dir.set(d)

    def _on_mode_changed(self) -> None:
        if self.var_mode.get() == "Автоматически":
            if self.frame_manual is not None:
                self.frame_manual.pack_forget()
            self.var_manual_err.set("")
        else:
            if self.frame_manual is not None:
                self.frame_manual.pack(fill="x", expand=True)
            self._validate_manual_live()

    def _validate_count_live(self) -> None:
        raw = self.var_count.get().strip()
        ok = bool(INT_RE.match(raw)) and 1 <= int(raw) <= 10_000
        if not raw:
            ok = False
        if self.entry_count is not None:
            self.entry_count.configure(
                style="Flat.TEntry" if ok else "Error.TEntry")
        if self.lbl_count_err is not None:
            if not raw:
                self.lbl_count_err.configure(
                    text="Введите объём выборки (от 1 до 10000)",
                    fg=COLOR_ERROR)
            elif not INT_RE.match(raw):
                self.lbl_count_err.configure(
                    text="Допустимы только целые числа",
                    fg=COLOR_ERROR)
            elif int(raw) < 1:
                self.lbl_count_err.configure(
                    text="Значение должно быть ≥ 1",
                    fg=COLOR_ERROR)
            elif int(raw) > 10_000:
                self.lbl_count_err.configure(
                    text="Значение должно быть ≤ 10000",
                    fg=COLOR_ERROR)
            else:
                self.lbl_count_err.configure(
                    text="Количество строк таблицы (от 1 до 10000)",
                    fg=COLOR_FG_MUTED)

    def _validate_manual_live(self) -> None:
        if self.var_mode.get() != "Вручную":
            return
        if self.txt_manual is None or self.lbl_manual_err is None:
            return
        raw = self.txt_manual.get("1.0", "end").strip()
        if not raw:
            self.lbl_manual_err.configure(text="")
            self.txt_manual.configure(highlightbackground=COLOR_ENTRY_BORDER)
            return

        try:
            n = int(self.var_count.get())
        except ValueError:
            n = 0
        normalized = raw.replace(",", " ").replace(";", " ").replace("\n", " ")
        tokens = [t for t in normalized.split() if t]

        if n and len(tokens) != n:
            self.lbl_manual_err.configure(
                text=f"Введено {len(tokens)} из {n} ожидаемых значений",
                fg=COLOR_ERROR)
            self.txt_manual.configure(highlightbackground=COLOR_ERROR_BORDER)
            return
        for t in tokens:
            # FIX: корректная проверка целого числа (не пропускает "--5")
            if not INT_RE.match(t):
                self.lbl_manual_err.configure(
                    text=f"«{t}» — не целое число", fg=COLOR_ERROR)
                self.txt_manual.configure(highlightbackground=COLOR_ERROR_BORDER)
                return
            v = int(t)
            if v < 0 or v > 100:
                self.lbl_manual_err.configure(
                    text=f"Значение {v} вне диапазона 0–100",
                    fg=COLOR_ERROR)
                self.txt_manual.configure(highlightbackground=COLOR_ERROR_BORDER)
                return

        self.lbl_manual_err.configure(
            text=f"Значений: {len(tokens)} — всё корректно",
            fg=COLOR_SUCCESS)
        self.txt_manual.configure(highlightbackground=COLOR_SUCCESS)

    def set_status(self, text: str, kind: str = "info") -> None:
        self.var_status.set(text)
        if self.status_label is None or self.status_icon is None:
            return
        if kind == "success":
            self.status_icon.configure(text="✓", fg=COLOR_SUCCESS)
            self.status_label.configure(fg=COLOR_SUCCESS,
                                        font=(FONT_FAMILY, 10, "bold"))
        elif kind == "error":
            self.status_icon.configure(text="✗", fg=COLOR_ERROR)
            self.status_label.configure(fg=COLOR_ERROR,
                                        font=(FONT_FAMILY, 10, "bold"))
        else:
            self.status_icon.configure(text="●", fg=COLOR_FG_MUTED)
            self.status_label.configure(fg=COLOR_FG_MUTED, font=FONT_STATUS)

    # -------------------------------------------------------------------------
    # ВАЛИДАЦИЯ (перед сохранением)
    # -------------------------------------------------------------------------

    def _parse_count(self) -> int | None:
        raw = self.var_count.get().strip()
        if not raw or not INT_RE.match(raw):
            self.set_status("Ошибка: N должно быть целым положительным числом",
                            "error")
            return None
        n = int(raw)
        if n <= 0 or n > 10_000:
            self.set_status("Ошибка: N должно быть от 1 до 10000", "error")
            return None
        return n

    def _parse_manual_values(self, n: int) -> list[int] | None:
        raw = self.txt_manual.get("1.0", "end").strip()
        if not raw:
            self.set_status("Ошибка: поле ручного ввода пусто", "error")
            return None
        normalized = raw.replace(",", " ").replace(";", " ").replace("\n", " ")
        tokens = [t for t in normalized.split() if t]
        if len(tokens) != n:
            self.set_status(
                f"Ошибка: введено {len(tokens)} значений, ожидается {n}",
                "error")
            return None
        values: list[int] = []
        for t in tokens:
            # FIX: корректная проверка (не падаем на "--5")
            if not INT_RE.match(t):
                self.set_status(f"Ошибка: «{t}» не целое число", "error")
                return None
            v = int(t)
            if v < 0 or v > 100:
                self.set_status(f"Ошибка: {v} вне диапазона 0–100", "error")
                return None
            values.append(v)
        return values

    def generate_data(self, n: int) -> list[int] | None:
        if self.var_mode.get() == "Автоматически":
            return [random.randint(0, 100) for _ in range(n)]
        return self._parse_manual_values(n)

    # -------------------------------------------------------------------------
    # ГЕНЕРАЦИЯ .DOCX
    # -------------------------------------------------------------------------

    @staticmethod
    def _docx_cell(text: str, bold: bool = False,
                   shade: str | None = None) -> str:
        # FIX: заливка ячейки должна быть в <w:tcPr>, а не в <w:pPr>
        rpr = "<w:rPr>"
        if bold:
            rpr += "<w:b/>"
        rpr += '<w:sz w:val="22"/></w:rPr>'
        tc_pr = ""
        if shade:
            tc_pr = (f'<w:tcPr><w:shd w:val="clear" w:color="auto" '
                     f'w:fill="{shade}"/></w:tcPr>')
        return (
            f'{tc_pr}'
            '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
            f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
            '</w:p>'
        )

    def _build_docx_bytes(self, values: list[int]) -> bytes:
        header_cells = (
            "<w:tr>"
            + f"<w:tc>{self._docx_cell('Номер измерения', bold=True, shade='E8EEF7')}</w:tc>"
            + f"<w:tc>{self._docx_cell('Результат', bold=True, shade='E8EEF7')}</w:tc>"
            + "</w:tr>"
        )
        data_rows = []
        for i, v in enumerate(values, start=1):
            data_rows.append(
                "<w:tr>"
                f"<w:tc>{self._docx_cell(str(i))}</w:tc>"
                f"<w:tc>{self._docx_cell(str(v))}</w:tc>"
                "</w:tr>"
            )
        rows_xml = header_cells + "".join(data_rows)

        tbl_pr = (
            "<w:tblPr>"
            '<w:tblW w:w="5000" w:type="pct"/>'
            '<w:tblBorders>'
            '<w:top    w:val="single" w:sz="6" w:space="0" w:color="444444"/>'
            '<w:left   w:val="single" w:sz="6" w:space="0" w:color="444444"/>'
            '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="444444"/>'
            '<w:right  w:val="single" w:sz="6" w:space="0" w:color="444444"/>'
            '<w:insideH w:val="single" w:sz="6" w:space="0" w:color="444444"/>'
            '<w:insideV w:val="single" w:sz="6" w:space="0" w:color="444444"/>'
            '</w:tblBorders>'
            '<w:jc w:val="center"/>'
            "</w:tblPr>"
        )
        tbl_grid = ('<w:tblGrid>'
                    '<w:gridCol w:w="4500"/>'
                    '<w:gridCol w:w="4500"/>'
                    '</w:tblGrid>')
        table_xml = f"<w:tbl>{tbl_pr}{tbl_grid}{rows_xml}</w:tbl>"

        doc_body = (
            '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
            '<w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr>'
            '<w:t xml:space="preserve">Отчёт измерений</w:t></w:r></w:p>'
            + table_xml
            + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
              '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/>'
              '</w:sectPr>'
        )

        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{doc_body}</w:body></w:document>'
        )

        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml"  ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>'
        )
        rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            '</Relationships>'
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/document.xml", document_xml)
        return buf.getvalue()

    # -------------------------------------------------------------------------
    # ГЕНЕРАЦИЯ .XLSX
    # -------------------------------------------------------------------------

    def _build_xlsx_bytes(self, values: list[int]) -> bytes:
        strings: list[str] = []
        index: dict[str, int] = {}

        def sid(text: str) -> int:
            if text not in index:
                index[text] = len(strings)
                strings.append(text)
            return index[text]

        h1 = sid("Номер измерения")
        h2 = sid("Результат")

        rows_xml = []
        rows_xml.append(
            '<row r="1">'
            f'<c r="A1" s="1" t="s"><v>{h1}</v></c>'
            f'<c r="B1" s="1" t="s"><v>{h2}</v></c>'
            '</row>'
        )
        for i, v in enumerate(values, start=2):
            rows_xml.append(
                f'<row r="{i}">'
                f'<c r="A{i}" s="2"><v>{i - 1}</v></c>'
                f'<c r="B{i}" s="2"><v>{v}</v></c>'
                '</row>'
            )

        sheet_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<cols>'
            '<col min="1" max="1" width="22" customWidth="1"/>'
            '<col min="2" max="2" width="16" customWidth="1"/>'
            '</cols>'
            '<sheetData>'
            + "".join(rows_xml) +
            '</sheetData>'
            '</worksheet>'
        )

        sst_items = "".join(
            f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings
        )
        # FIX: count — общее число ссылок на строки в ячейках (2 заголовка),
        # uniqueCount — число уникальных строк
        shared_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'count="2" uniqueCount="{len(strings)}">'
            f'{sst_items}</sst>'
        )

        styles_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2">'
            '<font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/></font>'
            '<font><b/><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/></font>'
            '</fonts>'
            '<fills count="3">'
            '<fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid">'
            '<fgColor rgb="FFE8EEF7"/><bgColor indexed="64"/></patternFill></fill>'
            '</fills>'
            '<borders count="2">'
            '<border><left/><right/><top/><bottom/><diagonal/></border>'
            '<border>'
            '<left style="thin"><color rgb="FF444444"/></left>'
            '<right style="thin"><color rgb="FF444444"/></right>'
            '<top style="thin"><color rgb="FF444444"/></top>'
            '<bottom style="thin"><color rgb="FF444444"/></bottom>'
            '<diagonal/>'
            '</border>'
            '</borders>'
            '<cellStyleXfs count="1">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
            '</cellStyleXfs>'
            '<cellXfs count="3">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" '
            'applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/></xf>'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" '
            'applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/></xf>'
            '</cellXfs>'
            '<cellStyles count="1">'
            '<cellStyle name="Normal" xfId="0" builtinId="0"/>'
            '</cellStyles>'
            '</styleSheet>'
        )

        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<bookViews><workbookView/></bookViews>'
            '<sheets><sheet name="Измерения" sheetId="1" r:id="rId1"/></sheets>'
            '</workbook>'
        )

        wb_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>'
            '<Relationship Id="rId3" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
            'Target="sharedStrings.xml"/>'
            '</Relationships>'
        )
        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            '</Relationships>'
        )
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml"  ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>'
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("_rels/.rels", root_rels)
            z.writestr("xl/workbook.xml", workbook_xml)
            z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
            z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
            z.writestr("xl/sharedStrings.xml", shared_xml)
            z.writestr("xl/styles.xml", styles_xml)
        return buf.getvalue()

    # -------------------------------------------------------------------------
    # ОСНОВНОЙ ОБРАБОТЧИК
    # -------------------------------------------------------------------------

    def on_generate(self) -> None:
        n = self._parse_count()
        if n is None:
            return

        fmt = self.var_format.get()
        want_docx = fmt in ("docx", "both")
        want_xlsx = fmt in ("xlsx", "both")

        values = self.generate_data(n)
        if values is None:
            return

        directory = self.var_save_dir.get().strip()
        base_name = self.var_filename.get().strip()
        if not directory or not os.path.isdir(directory):
            self.set_status(
                "Ошибка: укажите существующую папку для сохранения", "error")
            return
        if not base_name:
            self.set_status("Ошибка: введите имя файла", "error")
            return

        # FIX: убираем расширение, только если оно совпадает с ожидаемым
        root_name, ext = os.path.splitext(base_name)
        if ext.lower() in (".docx", ".xlsx", ".doc", ".xls"):
            base_name = root_name

        payload: list[tuple[str, bytes]] = []
        try:
            if want_docx:
                payload.append((os.path.join(directory, base_name + ".docx"),
                                self._build_docx_bytes(values)))
            if want_xlsx:
                payload.append((os.path.join(directory, base_name + ".xlsx"),
                                self._build_xlsx_bytes(values)))
        except Exception as exc:
            self.set_status(f"Ошибка генерации: {exc}", "error")
            return

        try:
            for path, data in payload:
                with open(path, "wb") as f:
                    f.write(data)
        except OSError as exc:
            self.set_status(f"Ошибка записи: {exc}", "error")
            messagebox.showerror("Ошибка",
                                 f"Не удалось сохранить файлы:\n{exc}")
            return

        paths_str = " | ".join(os.path.basename(p) for p, _ in payload)
        self.set_status(f"Успешно сохранено: {paths_str}", "success")
        messagebox.showinfo(
            "Готово",
            "Файлы успешно созданы:\n\n" +
            "\n".join(f"• {p}" for p, _ in payload))


# =============================================================================
# ТОЧКА ВХОДА
# =============================================================================

def main() -> None:
    root = tk.Tk()
    ReportGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()