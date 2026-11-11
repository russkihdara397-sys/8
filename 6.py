# -*- coding: utf-8 -*-
"""
=============================================================================
 ВИРТУАЛЬНАЯ ЛАБОРАТОРНАЯ РАБОТА
 «Определение ускорения свободного падения с помощью математического маятника»
=============================================================================
 Версия 4.3 — весь текст в рамках окон, адаптивный layout.
=============================================================================
"""

import os
import csv
import time
import base64
import tempfile
import webbrowser
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk


# =============================================================================
#  1. ДИЗАЙН-ТОКЕНЫ (компактные)
# =============================================================================
C = {
    "bg":        "#f4f6f9",
    "card":      "#ffffff",
    "soft":      "#f8fafc",
    "primary":   "#3b82f6",
    "primary_d": "#2563eb",
    "success":   "#10b981",
    "success_d": "#059669",
    "warning":   "#f59e0b",
    "danger":    "#ef4444",
    "danger_d":  "#dc2626",
    "text":      "#111827",
    "muted":     "#6b7280",
    "border":    "#e5e7eb",
    "ink":       "#334155",
}

# Шрифты (уменьшены для компактности)
F_UI      = ("Segoe UI", 10)
F_UI_B    = ("Segoe UI", 10, "bold")
F_SMALL   = ("Segoe UI", 9)
F_TINY    = ("Segoe UI", 8)
F_H1      = ("Segoe UI", 14, "bold")
F_H2      = ("Segoe UI", 11, "bold")
F_MONO    = ("Consolas", 9)
F_MONO_L  = ("Consolas", 16, "bold")
F_MONO_M  = ("Consolas", 12)


# =============================================================================
#  2. ФИЗИЧЕСКИЕ КОНСТАНТЫ И СТАТИСТИКА
# =============================================================================
G_TABLE = 9.81
G_MIN, G_MAX = 5.0, 15.0

_STUDENT = {
    0.90: [6.314, 2.920, 2.353, 2.132, 2.015, 1.943, 1.895, 1.860, 1.833, 1.812,
           1.796, 1.782, 1.771, 1.761, 1.753, 1.746, 1.740, 1.734, 1.729, 1.725],
    0.95: [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
           2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086],
    0.99: [63.657, 9.925, 5.841, 4.604, 4.032, 3.707, 3.499, 3.355, 3.250, 3.169,
           3.106, 3.055, 3.012, 2.977, 2.947, 2.921, 2.898, 2.878, 2.861, 2.845],
}
_Z = {0.90: 1.645, 0.95: 1.960, 0.99: 2.576}


def student_t(P: float, df: int) -> float:
    if df < 1:
        df = 1
    table = _STUDENT.get(P, _STUDENT[0.95])
    if df <= len(table):
        return table[df - 1]
    return _Z.get(P, 1.960)


def fmt_pm(x: float, err: float, sig: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    if err is None or not np.isfinite(err) or err <= 0:
        return f"{x:.4f}"
    exp = int(np.floor(np.log10(abs(err))))
    dec = max(0, -exp + sig - 1)
    e = round(err, dec)
    v = round(x, dec)
    if e > 0 and int(np.floor(np.log10(abs(e)))) > exp:
        dec = max(0, dec - 1)
        e = round(err, dec)
        v = round(x, dec)
    return f"{v:.{dec}f} ± {e:.{dec}f}"


def g_is_adequate(g: float) -> bool:
    return g is not None and np.isfinite(g) and G_MIN <= g <= G_MAX


# =============================================================================
#  3. ФИЗИЧЕСКАЯ МОДЕЛЬ
# =============================================================================
class PendulumModel:
    def __init__(self, L=1.0, g=G_TABLE, gamma=0.002, theta0=np.deg2rad(10)):
        self.L = float(L)
        self.g = float(g)
        self.gamma = float(gamma)
        self.theta0 = float(theta0)
        self.state = np.array([self.theta0, 0.0], dtype=float)
        self.t = 0.0

    def _f(self, y):
        theta, omega = y
        return np.array([omega, -(self.g / self.L) * np.sin(theta) - self.gamma * omega])

    def step_rk4(self, dt: float):
        t_prev = self.t
        th_prev = self.state[0]
        y = self.state
        k1 = self._f(y)
        k2 = self._f(y + 0.5 * dt * k1)
        k3 = self._f(y + 0.5 * dt * k2)
        k4 = self._f(y + dt * k3)
        self.state = y + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        self.t += dt
        th_new = self.state[0]
        if (th_prev > 0.0 and th_new <= 0.0) or (th_prev < 0.0 and th_new >= 0.0):
            denom = (th_prev - th_new)
            frac = th_prev / denom if denom != 0 else 0.0
            return t_prev + frac * dt
        return None

    def reset(self, theta0=None):
        if theta0 is not None:
            self.theta0 = float(theta0)
        self.state = np.array([self.theta0, 0.0], dtype=float)
        self.t = 0.0

    @property
    def theta(self):
        return float(self.state[0])

    @property
    def omega(self):
        return float(self.state[1])


# =============================================================================
#  4. СИСТЕМА ИЗМЕРЕНИЙ
# =============================================================================
class MeasurementSystem:
    SIGMA_REACTION   = 0.20
    SIGMA_RULER      = 0.0005
    SIGMA_PROTRACTOR = np.deg2rad(1.0)

    RULER_RANGE   = (0.20, 1.50)
    RULER_DIV     = 0.001
    ANGLE_RANGE   = (2.0, 30.0)
    ANGLE_DIV     = 1.0
    WATCH_DIV     = 0.001

    @staticmethod
    def reaction_offset() -> float:
        return float(np.random.normal(0.0, MeasurementSystem.SIGMA_REACTION))

    @staticmethod
    def measure_length(L_true: float) -> float:
        return float(L_true + np.random.normal(0.0, MeasurementSystem.SIGMA_RULER))

    @staticmethod
    def measure_angle(theta_true: float) -> float:
        return float(theta_true + np.random.normal(0.0, MeasurementSystem.SIGMA_PROTRACTOR))


# =============================================================================
#  5. СТИЛИ ttk
# =============================================================================
def apply_styles(root):
    st = ttk.Style(root)
    st.theme_use("clam")

    st.configure(".", background=C["bg"], foreground=C["text"],
                 borderwidth=0, focusthickness=0)
    st.configure("TFrame", background=C["bg"])
    st.configure("Card.TFrame", background=C["card"])

    def button(name, bg, hover, fg="white"):
        st.configure(name, background=bg, foreground=fg, padding=(10, 5),
                     font=F_UI_B, borderwidth=0, relief="flat")
        st.map(name,
               background=[("disabled", C["border"]), ("pressed", hover), ("active", hover)],
               foreground=[("disabled", "#9ca3af")])

    button("Primary.TButton", C["primary"], C["primary_d"])
    button("Success.TButton", C["success"], C["success_d"])
    button("Danger.TButton",  C["danger"],  C["danger_d"])
    button("Ghost.TButton",   "#eef2f7",    "#e2e8f0", fg=C["ink"])

    st.configure("Card.TLabel",     background=C["card"], foreground=C["text"], font=F_UI)
    st.configure("CardMuted.TLabel", background=C["card"], foreground=C["muted"], font=F_SMALL)
    st.configure("CardBold.TLabel", background=C["card"], foreground=C["text"], font=F_UI_B)
    st.configure("Bg.TLabel",       background=C["bg"],   foreground=C["text"], font=F_UI)

    st.configure("TEntry", padding=4, font=F_UI, fieldbackground="white")
    st.configure("TSpinbox", padding=4, font=F_UI, fieldbackground="white", arrowsize=12)
    st.configure("TCombobox", padding=4, font=F_UI, fieldbackground="white")
    st.configure("TCheckbutton", background=C["bg"], font=F_SMALL)
    st.map("TCheckbutton", background=[("active", C["bg"])])

    st.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(4, 4, 4, 0))
    st.configure("TNotebook.Tab", background="#e9edf3", foreground=C["muted"],
                 padding=(12, 6), font=F_UI_B, borderwidth=0)
    st.map("TNotebook.Tab",
           background=[("selected", C["card"]), ("disabled", "#f1f3f6")],
           foreground=[("selected", C["primary"]), ("disabled", "#b6bcc6")])

    st.configure("Treeview", background=C["card"], fieldbackground=C["card"],
                 foreground=C["text"], rowheight=22, font=("Segoe UI", 9), borderwidth=0)
    st.configure("Treeview.Heading", background="#eef2f7", foreground=C["ink"],
                 font=F_UI_B, padding=(4, 4), relief="flat")
    st.map("Treeview", background=[("selected", C["primary"])], foreground=[("selected", "white")])
    st.map("Treeview.Heading", background=[("active", "#e2e8f0")])

    st.configure("Horizontal.TScale", background=C["card"], troughcolor="#e5e7eb")
    st.configure("TPanedwindow", background=C["border"])


# =============================================================================
#  6. ДИАЛОГ РЕДАКТИРОВАНИЯ
# =============================================================================
class EditRowDialog(tk.Toplevel):
    def __init__(self, master, row: dict):
        super().__init__(master)
        self.title("Редактирование измерения")
        self.configure(bg=C["card"])
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = None

        body = tk.Frame(self, bg=C["card"], padx=16, pady=12)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(body, text="Проверьте и исправьте запись",
                 font=F_H2, bg=C["card"], fg=C["text"]).grid(row=0, column=0, columnspan=2,
                                                            sticky="w", pady=(0, 10))

        self.vars = {}
        fields = [
            ("L", "Длина L, м", f"{row['L']:.4f}", "0.20 … 1.50 м"),
            ("N", "Число колебаний N", str(row["N"]), "целое, 1 … 100"),
            ("t", "Время t, с", f"{row['t']:.3f}", "больше 0.05 с"),
        ]
        for i, (key, label, value, hint) in enumerate(fields, start=1):
            tk.Label(body, text=label, font=F_UI, bg=C["card"], fg=C["text"])\
                .grid(row=i, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=value)
            self.vars[key] = var
            ttk.Entry(body, textvariable=var, width=14).grid(row=i, column=1, padx=(10, 0), pady=4)
            tk.Label(body, text=hint, font=F_TINY, bg=C["card"], fg=C["muted"])\
                .grid(row=i + len(fields), column=0, columnspan=2, sticky="w")

        btns = tk.Frame(body, bg=C["card"])
        btns.grid(row=10, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Отмена", style="Ghost.TButton",
                   command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btns, text="Сохранить", style="Primary.TButton",
                   command=self._ok).pack(side=tk.RIGHT)

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + 150
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _ok(self):
        try:
            L = float(self.vars["L"].get().replace(",", "."))
            N = int(self.vars["N"].get())
            t = float(self.vars["t"].get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Некорректный ввод", "Проверьте числа: L и t — дробные, N — целое.",
                                 parent=self)
            return
        if not (MeasurementSystem.RULER_RANGE[0] <= L <= MeasurementSystem.RULER_RANGE[1]):
            messagebox.showerror("Диапазон", "L вне диапазона 0.20 … 1.50 м.", parent=self)
            return
        if not (1 <= N <= 100):
            messagebox.showerror("Диапазон", "N должно быть целым от 1 до 100.", parent=self)
            return
        if t <= 0.05:
            messagebox.showerror("Диапазон", "Время должно быть больше 0.05 с.", parent=self)
            return
        self.result = {"L": L, "N": N, "t": t}
        self.destroy()


# =============================================================================
#  7. ГЛАВНОЕ ПРИЛОЖЕНИЕ
# =============================================================================
class App(tk.Tk):

    TARGET_REPEATS = 5
    TARGET_SERIES  = 5
    MIN_POINTS     = 2
    MIN_ROWS       = 3

    def __init__(self):
        super().__init__()
        self.title("Виртуальная лабораторная — определение g")
        self.geometry("1280x800")
        self.minsize(1100, 700)
        self.configure(bg=C["bg"])
        apply_styles(self)

        self.model = PendulumModel(L=1.0, theta0=np.deg2rad(10))
        self.msr = MeasurementSystem()
        self.L_set = 1.0

        self.animation_running = False
        self.last_wall = time.perf_counter()
        self.flash_until = 0.0

        self.timer_state = "idle"
        self.zero_times = []
        self.t_start_true = None
        self.t_start_meas = None
        self.measured_t = None
        self.measured_N = None

        self.measurements = []
        self.res = None
        self.data_stale = True
        self.calc_time = None

        self._toast_win = None
        self._plot_pts = None
        self._annot = None
        self._saved_lims = None

        self._build_ui()
        self._update_progress()
        self._update_tab_states()
        self._update_report_buttons()
        self._animate()

    # =========================================================================
    #  7.1. КАРКАС ИНТЕРФЕЙСА
    # =========================================================================
    def _card(self, parent, title=None, pad=8):
        """Компактная карточка."""
        outer = tk.Frame(parent, bg=C["card"], highlightbackground=C["border"],
                         highlightthickness=1)
        inner = tk.Frame(outer, bg=C["card"], padx=pad, pady=pad)
        inner.pack(fill=tk.BOTH, expand=True)
        if title:
            tk.Label(inner, text=title, font=F_H2, bg=C["card"], fg=C["text"])\
                .pack(anchor="w", pady=(0, 6))
        return outer, inner

    def _wrap_label(self, parent, text, font=F_SMALL, color=C["muted"], wrap=600):
        """Label с автоматическим переносом."""
        return tk.Label(parent, text=text, font=font, bg=C["card"], fg=color,
                       justify=tk.LEFT, wraplength=wrap, anchor="w")

    def _build_ui(self):
        # Шапка (компактная)
        header = tk.Frame(self, bg=C["primary"], height=44)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="Виртуальная лабораторная работа",
                 font=("Segoe UI", 12, "bold"), bg=C["primary"], fg="white")\
            .pack(side=tk.LEFT, padx=14)
        tk.Label(header, text="Определение g · математический маятник",
                 font=F_SMALL, bg=C["primary"], fg="#dbeafe")\
            .pack(side=tk.LEFT, padx=4)
        self.hint_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self.hint_var, font=F_TINY,
                 bg=C["primary"], fg="#eff6ff", wraplength=400, justify=tk.RIGHT)\
            .pack(side=tk.RIGHT, padx=14)

        # Баннер (компактный)
        self.banner = tk.Frame(self, bg=C["warning"])
        self.banner_lbl = tk.Label(self.banner, text="", font=F_SMALL,
                                   bg=C["warning"], fg="white", pady=4,
                                   wraplength=1200, justify=tk.CENTER)
        self.banner_lbl.pack(fill=tk.X)

        # Вкладки
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 4))
        self.tabs = {}
        for key, label in [("setup", "1 · Установка"), ("measure", "2 · Измерения"),
                           ("process", "3 · Обработка"), ("plot", "4 · График"),
                           ("report", "5 · Отчёт")]:
            frame = tk.Frame(self.nb, bg=C["bg"])
            self.tabs[key] = frame
            self.nb.add(frame, text="  " + label + "  ")
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_change)

        # Статус-бар (компактный)
        bar = tk.Frame(self, bg=C["card"], highlightbackground=C["border"], highlightthickness=1)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="Готово. Задайте параметры и запустите маятник.")
        tk.Label(bar, textvariable=self.status_var, font=F_SMALL, bg=C["card"],
                 fg=C["ink"], anchor="w", padx=12, pady=5, wraplength=1200)\
            .pack(fill=tk.X)

        self._build_setup_tab(self.tabs["setup"])
        self._build_measure_tab(self.tabs["measure"])
        self._build_process_tab(self.tabs["process"])
        self._build_plot_tab(self.tabs["plot"])
        self._build_report_tab(self.tabs["report"])

        self.bind("<space>", self._on_space)

    # -------------------------- вкладка 1: установка -------------------------
    def _build_setup_tab(self, root):
        wrap = tk.Frame(root, bg=C["bg"])
        wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        left = tk.Frame(wrap, bg=C["bg"], width=320)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        left.pack_propagate(False)

        # Параметры
        card, box = self._card(left, "Параметры установки")
        card.pack(fill=tk.X, pady=(0, 6))

        tk.Label(box, text="Длина подвеса L, м", font=F_UI_B,
                 bg=C["card"], fg=C["text"]).pack(anchor="w")
        row = tk.Frame(box, bg=C["card"]); row.pack(fill=tk.X, pady=(2, 2))
        self.var_L = tk.DoubleVar(value=1.0)
        self.scale_L = ttk.Scale(row, from_=0.20, to=1.50, variable=self.var_L,
                                 orient=tk.HORIZONTAL, command=self._on_L_scale)
        self.scale_L.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.entry_L = ttk.Entry(row, width=7, font=F_UI)
        self.entry_L.insert(0, "1.000")
        self.entry_L.pack(side=tk.LEFT)
        self.entry_L.bind("<Return>", lambda e: self._on_L_entry())
        ttk.Button(row, text="OK", style="Ghost.TButton", width=3,
                   command=self._on_L_entry).pack(side=tk.LEFT, padx=(3, 0))
        self.lbl_L_info = self._wrap_label(box, "", wrap=300)
        self.lbl_L_info.pack(anchor="w", pady=(2, 0))

        ttk.Separator(box).pack(fill=tk.X, pady=6)

        tk.Label(box, text="Начальный угол θ₀, градусы", font=F_UI_B,
                 bg=C["card"], fg=C["text"]).pack(anchor="w")
        row2 = tk.Frame(box, bg=C["card"]); row2.pack(fill=tk.X, pady=(2, 2))
        self.var_theta = tk.DoubleVar(value=10.0)
        self.scale_theta = ttk.Scale(row2, from_=2.0, to=30.0, variable=self.var_theta,
                                     orient=tk.HORIZONTAL, command=self._on_theta_scale)
        self.scale_theta.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.entry_theta = ttk.Entry(row2, width=7, font=F_UI)
        self.entry_theta.insert(0, "10.0")
        self.entry_theta.pack(side=tk.LEFT)
        self.entry_theta.bind("<Return>", lambda e: self._on_theta_entry())
        ttk.Button(row2, text="OK", style="Ghost.TButton", width=3,
                   command=self._on_theta_entry).pack(side=tk.LEFT, padx=(3, 0))
        self.lbl_theta_info = self._wrap_label(box, "", wrap=300)
        self.lbl_theta_info.pack(anchor="w", pady=(2, 0))

        # Управление
        card2, box2 = self._card(left, "Управление маятником")
        card2.pack(fill=tk.X, pady=(0, 6))
        r = tk.Frame(box2, bg=C["card"]); r.pack(fill=tk.X)
        self.btn_run = ttk.Button(r, text="▶ Запустить", style="Success.TButton",
                                  command=self._start_pendulum)
        self.btn_run.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 3))
        self.btn_pause = ttk.Button(r, text="⏸ Пауза", style="Ghost.TButton",
                                    command=self._stop_pendulum)
        self.btn_pause.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 3))
        ttk.Button(r, text="↺ Сброс", style="Ghost.TButton",
                   command=self._reset_pendulum).pack(side=tk.LEFT, expand=True, fill=tk.X)

        tk.Label(box2, text="Быстрые пресеты длины:", font=F_SMALL,
                 bg=C["card"], fg=C["muted"]).pack(anchor="w", pady=(6, 3))
        pr = tk.Frame(box2, bg=C["card"]); pr.pack(fill=tk.X)
        for v in (0.30, 0.50, 0.70, 1.00, 1.30):
            ttk.Button(pr, text=f"{v:.2f}", style="Ghost.TButton", width=4,
                       command=lambda x=v: self._set_length(x)).pack(side=tk.LEFT, padx=(0, 3))

        # Методика (Text вместо Label — автоперенос)
        card3, box3 = self._card(left, "Методика и приборы")
        card3.pack(fill=tk.BOTH, expand=True)
        info = (
            "Модель:\n"
            "  θ'' = −(g/L)·sin θ − γ·θ',  γ = 0.002 с⁻¹\n"
            "  Интегрирование: RK4, шаг ≤ 5 мс\n\n"
            "Приборы (пределы / цена деления / СКО):\n"
            f"  Линейка: {self.msr.RULER_RANGE[0]:.2f}–{self.msr.RULER_RANGE[1]:.2f} м / "
            f"{self.msr.RULER_DIV*1000:.0f} мм / σ = {self.msr.SIGMA_RULER*1000:.1f} мм\n"
            f"  Транспортир: {self.msr.ANGLE_RANGE[0]:.0f}–{self.msr.ANGLE_RANGE[1]:.0f}° / "
            f"{self.msr.ANGLE_DIV:.0f}° / σ = {np.rad2deg(self.msr.SIGMA_PROTRACTOR):.0f}°\n"
            f"  Секундомер: реакция σ = {self.msr.SIGMA_REACTION:.2f} с (старт и стоп)\n\n"
            "Порядок работы:\n"
            "  1. Задать L и θ₀, запустить маятник\n"
            f"  2. Снять {self.TARGET_REPEATS} повторов на каждой из "
            f"{self.TARGET_SERIES} длин\n"
            "  3. Обработка → график → отчёт"
        )
        txt = tk.Text(box3, font=F_SMALL, bg=C["card"], fg=C["ink"],
                     relief=tk.FLAT, wrap=tk.WORD, height=12)
        txt.insert("1.0", info)
        txt.config(state=tk.DISABLED)
        txt.pack(fill=tk.BOTH, expand=True)

        # Визуализация
        right = tk.Frame(wrap, bg=C["bg"])
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        card4, box4 = self._card(right, "Установка (анимация)", pad=6)
        card4.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(box4, bg=C["soft"], highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw_pendulum())

        self._refresh_param_labels()

    # -------------------------- вкладка 2: измерения -------------------------
    def _build_measure_tab(self, root):
        wrap = tk.Frame(root, bg=C["bg"])
        wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Вертикальный PanedWindow
        vp = ttk.PanedWindow(wrap, orient=tk.VERTICAL)
        vp.pack(fill=tk.BOTH, expand=True)

        # Верх: серия + секундомер
        top_frame = tk.Frame(vp, bg=C["bg"])
        vp.add(top_frame, weight=0)

        # Серия
        card, box = self._card(top_frame, "Текущая серия", pad=8)
        card.pack(fill=tk.X, pady=(0, 4))
        row = tk.Frame(box, bg=C["card"]); row.pack(fill=tk.X)

        tk.Label(row, text="Длина L, м:", font=F_UI, bg=C["card"], fg=C["text"])\
            .pack(side=tk.LEFT)
        self.var_measure_L = tk.DoubleVar(value=1.0)
        sp = ttk.Spinbox(row, from_=0.20, to=1.50, increment=0.05, width=7,
                         textvariable=self.var_measure_L, format="%.3f")
        sp.pack(side=tk.LEFT, padx=4)
        sp.bind("<Return>", lambda e: self._apply_measure_L())
        ttk.Button(row, text="Применить", style="Ghost.TButton",
                   command=self._apply_measure_L).pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(row, text="Колебаний N:", font=F_UI, bg=C["card"], fg=C["text"])\
            .pack(side=tk.LEFT)
        self.var_N = tk.IntVar(value=15)
        ttk.Spinbox(row, from_=3, to=50, increment=1, width=5,
                    textvariable=self.var_N).pack(side=tk.LEFT, padx=4)

        self.var_auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Автоостановка после N колебаний",
                        variable=self.var_auto).pack(side=tk.LEFT, padx=(8, 0))

        self.progress_var = tk.StringVar(value="")
        tk.Label(box, textvariable=self.progress_var, font=F_UI_B,
                 bg=C["card"], fg=C["primary"], wraplength=800, justify=tk.LEFT)\
            .pack(anchor="w", pady=(6, 0))
        self.progress = ttk.Progressbar(box, maximum=self.TARGET_REPEATS, length=240)
        self.progress.pack(anchor="w", pady=(3, 0))

        # Секундомер
        card2, box2 = self._card(top_frame, "Секундомер", pad=8)
        card2.pack(fill=tk.X)

        self.timer_state_var = tk.StringVar(value="Готов к старту")
        self.timer_state_lbl = tk.Label(box2, textvariable=self.timer_state_var,
                                        font=F_UI_B, bg=C["card"], fg=C["muted"],
                                        wraplength=800, justify=tk.LEFT)
        self.timer_state_lbl.pack(anchor="w")

        tiles = tk.Frame(box2, bg=C["card"]); tiles.pack(fill=tk.X, pady=6)

        def tile(parent, caption, var, font, color):
            f = tk.Frame(parent, bg=C["soft"], highlightbackground=C["border"],
                         highlightthickness=1, padx=10, pady=6)
            tk.Label(f, text=caption, font=F_TINY, bg=C["soft"], fg=C["muted"]).pack(anchor="w")
            tk.Label(f, textvariable=var, font=font, bg=C["soft"], fg=color).pack(anchor="w")
            return f

        self.var_display_time = tk.StringVar(value="0.000 с")
        self.var_last_time = tk.StringVar(value="—")
        self.var_count = tk.StringVar(value="0 / 15")
        tile(tiles, "Текущий замер", self.var_display_time, F_MONO_L, C["success_d"])\
            .pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        tile(tiles, "Последний замер", self.var_last_time, F_MONO_M, C["text"])\
            .pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        tile(tiles, "Полных колебаний", self.var_count, F_MONO_M, C["primary"])\
            .pack(side=tk.LEFT, fill=tk.X, expand=True)

        btns = tk.Frame(box2, bg=C["card"]); btns.pack(fill=tk.X, pady=(4, 0))
        self.btn_start = ttk.Button(btns, text="▶ Старт · Пробел", style="Success.TButton",
                                    command=self._timer_start)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_stop = ttk.Button(btns, text="⏹ Стоп · Пробел", style="Danger.TButton",
                                   command=self._timer_stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_add = ttk.Button(btns, text="＋ Зафиксировать", style="Primary.TButton",
                                  command=self._add_measurement, state=tk.DISABLED)
        self.btn_add.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btns, text="Очистить таблицу", style="Ghost.TButton",
                   command=self._clear_table).pack(side=tk.RIGHT)

        self._wrap_label(box2, "Старт/стоп привязаны к прохождению нуля. N = фактически пройденные периоды.",
                        wrap=900).pack(anchor="w", pady=(4, 0))

        # Низ: таблицы
        bottom_frame = tk.Frame(vp, bg=C["bg"])
        vp.add(bottom_frame, weight=1)

        hp = ttk.PanedWindow(bottom_frame, orient=tk.HORIZONTAL)
        hp.pack(fill=tk.BOTH, expand=True)

        # Левая: таблица измерений
        left_frame = tk.Frame(hp, bg=C["bg"])
        hp.add(left_frame, weight=1)
        card3, box3 = self._card(left_frame, "Таблица измерений", pad=6)
        card3.pack(fill=tk.BOTH, expand=True)
        cols = ("idx", "Lset", "L", "N", "t", "T", "T2")
        heads = ("№", "L уст.", "L изм.", "N", "t, с", "T, с", "T², с²")
        widths = (35, 65, 65, 40, 70, 75, 75)
        self.tree = ttk.Treeview(box3, columns=cols, show="headings", height=8)
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="center")
        vsb = ttk.Scrollbar(box3, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.tag_configure("odd", background="#fbfcfe")

        menu = tk.Menu(self.tree, tearoff=0)
        menu.add_command(label="Редактировать строку", command=self._edit_selected)
        menu.add_command(label="Удалить строку", command=self._delete_selected)
        self.tree_menu = menu
        self.tree.bind("<Button-3>", self._show_tree_menu)
        self.tree.bind("<Double-1>", lambda e: self._edit_selected())
        self.tree.bind("<Delete>", lambda e: self._delete_selected())

        # Правая: сводная таблица
        right_frame = tk.Frame(hp, bg=C["bg"])
        hp.add(right_frame, weight=1)
        card_sum, box_sum = self._card(right_frame, "Сводная таблица отчётов (P = 0.95)", pad=6)
        card_sum.pack(fill=tk.BOTH, expand=True)

        cols_sum = ("L", "n", "T_mean", "S_T", "dT", "T2", "dT2")
        heads_sum = ("L, м", "n", "<T>, с", "S_T, с", "ΔT, с", "<T²>, с²", "Δ(T²), с²")
        widths_sum = (65, 35, 65, 65, 65, 75, 75)
        self.summary_tree = ttk.Treeview(box_sum, columns=cols_sum, show="headings", height=8)
        for c, h, w in zip(cols_sum, heads_sum, widths_sum):
            self.summary_tree.heading(c, text=h)
            self.summary_tree.column(c, width=w, anchor="center")
        vsb2 = ttk.Scrollbar(box_sum, orient="vertical", command=self.summary_tree.yview)
        self.summary_tree.configure(yscrollcommand=vsb2.set)
        self.summary_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.summary_tree.tag_configure("odd", background="#fbfcfe")

        self._wrap_label(box_sum, "Сводка обновляется автоматически. P = 0.95. Подробный протокол — на вкладке «3 · Обработка».",
                        wrap=500).pack(anchor="w", pady=(4, 0))

    # -------------------------- вкладка 3: обработка -------------------------
    def _build_process_tab(self, root):
        wrap = tk.Frame(root, bg=C["bg"])
        wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        head = tk.Frame(wrap, bg=C["bg"]); head.pack(fill=tk.X, pady=(0, 6))
        tk.Label(head, text="Обработка результатов", font=F_H1,
                 bg=C["bg"], fg=C["text"]).pack(side=tk.LEFT)
        pf = tk.Frame(head, bg=C["bg"]); pf.pack(side=tk.RIGHT)
        tk.Label(pf, text="P:", font=F_UI, bg=C["bg"], fg=C["text"])\
            .pack(side=tk.LEFT, padx=(0, 4))
        self.var_P = tk.DoubleVar(value=0.95)
        cb = ttk.Combobox(pf, textvariable=self.var_P, values=[0.90, 0.95, 0.99],
                          width=5, state="readonly")
        cb.pack(side=tk.LEFT)
        cb.bind("<<ComboboxSelected>>", lambda e: self._reprocess(force=True))
        ttk.Button(pf, text="Пересчитать", style="Ghost.TButton",
                   command=lambda: self._reprocess(force=True)).pack(side=tk.LEFT, padx=(6, 0))

        cards = tk.Frame(wrap, bg=C["bg"]); cards.pack(fill=tk.X, pady=(0, 6))
        self.card_g = tk.Label(cards, text="g = — м/с²", font=("Segoe UI", 14, "bold"),
                               bg=C["card"], fg=C["muted"], anchor="w",
                               highlightbackground=C["border"], highlightthickness=1,
                               padx=14, pady=12, wraplength=400, justify=tk.LEFT)
        self.card_g.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.card_check = tk.Label(cards, text="Ожидание данных", font=F_H2,
                                   bg=C["card"], fg=C["muted"], anchor="w",
                                   highlightbackground=C["border"], highlightthickness=1,
                                   padx=14, pady=12, wraplength=400, justify=tk.LEFT)
        self.card_check.pack(side=tk.LEFT, fill=tk.X, expand=True)

        card, box = self._card(wrap, "Протокол вычислений", pad=8)
        card.pack(fill=tk.BOTH, expand=True)
        self.txt_result = tk.Text(box, wrap=tk.WORD, font=F_MONO, bg=C["soft"],
                                  fg=C["text"], relief=tk.FLAT, padx=8, pady=8)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.txt_result.yview)
        self.txt_result.configure(yscrollcommand=sb.set)
        self.txt_result.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._set_text(self.txt_result,
                       "Здесь появится протокол обработки.\n\n"
                       f"Нужно не менее {self.MIN_ROWS} измерений минимум при "
                       f"{self.MIN_POINTS} разных длинах.")

        self.lbl_timestamp = tk.Label(wrap, text="", font=F_TINY, bg=C["bg"], fg=C["muted"])
        self.lbl_timestamp.pack(anchor="e", pady=(3, 0))

    # -------------------------- вкладка 4: график ----------------------------
    def _build_plot_tab(self, root):
        wrap = tk.Frame(root, bg=C["bg"])
        wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        head = tk.Frame(wrap, bg=C["bg"]); head.pack(fill=tk.X, pady=(0, 6))
        tk.Label(head, text="Зависимость T² от L", font=F_H1,
                 bg=C["bg"], fg=C["text"]).pack(side=tk.LEFT)
        opts = tk.Frame(head, bg=C["bg"]); opts.pack(side=tk.RIGHT)
        self.show_errors_var = tk.BooleanVar(value=True)
        self.show_fit_var = tk.BooleanVar(value=True)
        self.keep_scale_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Погрешности", variable=self.show_errors_var,
                        command=self._rebuild_plot).pack(side=tk.LEFT, padx=3)
        ttk.Checkbutton(opts, text="Аппроксимация", variable=self.show_fit_var,
                        command=self._rebuild_plot).pack(side=tk.LEFT, padx=3)
        ttk.Checkbutton(opts, text="Сохранять масштаб", variable=self.keep_scale_var,
                        command=self._remember_scale).pack(side=tk.LEFT, padx=3)

        card, box = self._card(wrap, pad=6)
        card.pack(fill=tk.BOTH, expand=True)
        self.fig = Figure(figsize=(8, 4.5), dpi=100, facecolor=C["card"])
        self.ax = self.fig.add_subplot(111)
        self.canvas_plot = FigureCanvasTkAgg(self.fig, master=box)
        self.canvas_plot.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        tb_frame = tk.Frame(box, bg=C["card"]); tb_frame.pack(fill=tk.X)
        self.toolbar = NavigationToolbar2Tk(self.canvas_plot, tb_frame)
        self.toolbar.update()
        self.canvas_plot.mpl_connect("motion_notify_event", self._on_plot_hover)

        self.lbl_fit = tk.Label(wrap, text="", font=F_MONO, bg=C["bg"], fg=C["text"],
                               wraplength=1100, justify=tk.LEFT)
        self.lbl_fit.pack(anchor="w", pady=(4, 0))
        self.plot_warning = tk.Label(wrap, text="", font=F_SMALL, bg=C["bg"], fg=C["warning"],
                                    wraplength=1100, justify=tk.LEFT)
        self.plot_warning.pack(anchor="w")

    # -------------------------- вкладка 5: отчёт -----------------------------
    def _build_report_tab(self, root):
        wrap = tk.Frame(root, bg=C["bg"])
        wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        tk.Label(wrap, text="Отчёт: просмотр, сохранение, печать", font=F_H1,
                 bg=C["bg"], fg=C["text"]).pack(anchor="w", pady=(0, 6))

        card, box = self._card(wrap, "Экспорт", pad=8)
        card.pack(fill=tk.X, pady=(0, 6))
        row = tk.Frame(box, bg=C["card"]); row.pack(fill=tk.X)
        self.btn_csv = ttk.Button(row, text="CSV", style="Ghost.TButton",
                                  command=self._save_csv, state=tk.DISABLED)
        self.btn_csv.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_txt = ttk.Button(row, text="TXT", style="Ghost.TButton",
                                  command=self._save_txt, state=tk.DISABLED)
        self.btn_txt.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_pdf = ttk.Button(row, text="PDF", style="Primary.TButton",
                                  command=self._save_pdf, state=tk.DISABLED)
        self.btn_pdf.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_png = ttk.Button(row, text="PNG", style="Ghost.TButton",
                                  command=self._save_png, state=tk.DISABLED)
        self.btn_png.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(row, text="Обновить предпросмотр", style="Ghost.TButton",
                   command=self._preview_report).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(row, text="Печать", style="Ghost.TButton",
                   command=self._print_report).pack(side=tk.LEFT)
        self.report_hint = self._wrap_label(box, "", wrap=900)
        self.report_hint.pack(anchor="w", pady=(6, 0))

        card2, box2 = self._card(wrap, "Предпросмотр отчёта", pad=8)
        card2.pack(fill=tk.BOTH, expand=True)
        self.txt_report = tk.Text(box2, wrap=tk.WORD, font=F_MONO, bg=C["soft"],
                                  fg=C["text"], relief=tk.FLAT, padx=8, pady=8)
        sb = ttk.Scrollbar(box2, orient="vertical", command=self.txt_report.yview)
        self.txt_report.configure(yscrollcommand=sb.set)
        self.txt_report.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._set_text(self.txt_report,
                       "Отчёт появится после расчёта на вкладке «3 · Обработка».\n"
                       "Пока данных недостаточно.")

    # =========================================================================
    #  7.2. СЕРВИСНЫЕ МЕХАНИЗМЫ UI
    # =========================================================================
    @staticmethod
    def _set_text(widget, text):
        state = widget.cget("state")
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state=state)

    def _status(self, text, toast=False, kind="info"):
        self.status_var.set(text)
        if toast:
            self._toast(text, kind)

    def _toast(self, text, kind="info"):
        colors = {"info": C["primary"], "ok": C["success_d"],
                  "warn": C["warning"], "err": C["danger_d"]}
        if self._toast_win is not None and self._toast_win.winfo_exists():
            self._toast_win.destroy()
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        bg = colors.get(kind, C["primary"])
        frame = tk.Frame(win, bg=bg, padx=10, pady=8)
        frame.pack()
        tk.Label(frame, text=text, font=F_UI_B, bg=bg, fg="white",
                 wraplength=320, justify=tk.LEFT).pack()
        win.update_idletasks()
        x = self.winfo_rootx() + self.winfo_width() - win.winfo_width() - 20
        y = self.winfo_rooty() + 60
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self._toast_win = win
        self.after(2200, lambda: win.destroy() if win.winfo_exists() else None)

    def _show_banner(self, text, color):
        self.banner.configure(bg=color)
        self.banner_lbl.configure(text=text, bg=color)
        self.banner.pack(fill=tk.X, before=self.nb, padx=10, pady=(6, 0))

    def _hide_banner(self):
        self.banner.pack_forget()

    def _ready_for_analysis(self):
        series = {round(m["L_set"], 3) for m in self.measurements}
        return len(self.measurements) >= self.MIN_ROWS and len(series) >= self.MIN_POINTS

    def _update_tab_states(self):
        n = len(self.measurements)
        series = {round(m["L_set"], 3) for m in self.measurements}
        ready = self._ready_for_analysis()
        valid = bool(self.res and self.res["valid"])

        marks = {
            "setup":   "✓" if self.animation_running or self.L_set else "·",
            "measure": "✓" if ready else (f"{n}" if n else "·"),
            "process": ("✓" if valid else "!") if ready else "🔒",
            "plot":    ("✓" if valid else "!") if ready else "🔒",
            "report":  ("✓" if valid else "!") if ready else "🔒",
        }
        names = {"setup": "1 · Установка", "measure": "2 · Измерения",
                 "process": "3 · Обработка", "plot": "4 · График", "report": "5 · Отчёт"}
        for i, key in enumerate(["setup", "measure", "process", "plot", "report"]):
            state = tk.NORMAL if (key in ("setup", "measure") or ready) else tk.DISABLED
            try:
                self.nb.tab(i, text=f"  {names[key]}  {marks[key]}  ", state=state)
            except tk.TclError:
                self.nb.tab(i, text=f"  {names[key]}  {marks[key]}  ")

        if not ready:
            need_rows = max(0, self.MIN_ROWS - n)
            need_len = max(0, self.MIN_POINTS - len(series))
            self.hint_var.set(f"Шаги 3–5 закрыты: нужно ещё {need_rows} изм. и {need_len} разн. длин")
        elif self.data_stale:
            self.hint_var.set("Данные изменились — откройте шаг 3 для пересчёта")
        else:
            self.hint_var.set(f"Измерений: {n} · серий: {len(series)} · расчёт актуален")

    def _mark_stale(self):
        self.data_stale = True
        if self.measurements:
            self._show_banner("Данные изменились — результаты требуют пересчёта (шаг 3).", C["warning"])
        self._update_tab_states()
        self._update_report_buttons()

    # =========================================================================
    #  7.3. ПАРАМЕТРЫ УСТАНОВКИ
    # =========================================================================
    def _refresh_param_labels(self):
        self.lbl_L_info.config(
            text=f"{self.L_set:.3f} м · пределы {self.msr.RULER_RANGE[0]:.2f}–{self.msr.RULER_RANGE[1]:.2f} м · "
                 f"цена деления {self.msr.RULER_DIV*1000:.0f} мм · σ = {self.msr.SIGMA_RULER*1000:.1f} мм")
        self.lbl_theta_info.config(
            text=f"{self.var_theta.get():.1f}° · пределы {self.msr.ANGLE_RANGE[0]:.0f}–{self.msr.ANGLE_RANGE[1]:.0f}° · "
                 f"цена деления {self.msr.ANGLE_DIV:.0f}°")

    def _on_L_scale(self, _=None):
        L = round(float(self.var_L.get()), 3)
        self._set_length(L, from_scale=True)

    def _on_L_entry(self, silent=False):
        try:
            L = float(self.entry_L.get().replace(",", "."))
        except ValueError:
            if not silent:
                messagebox.showerror("Ввод", "Длина должна быть числом.")
            self.entry_L.delete(0, tk.END); self.entry_L.insert(0, f"{self.L_set:.3f}")
            return
        lo, hi = self.msr.RULER_RANGE
        if not (lo <= L <= hi):
            if not silent:
                messagebox.showerror("Диапазон", f"L должен быть в пределах {lo:.2f}–{hi:.2f} м.")
            self.entry_L.delete(0, tk.END); self.entry_L.insert(0, f"{self.L_set:.3f}")
            return
        self._set_length(round(L, 3))

    def _set_length(self, L, from_scale=False):
        if abs(L - self.L_set) < 1e-9:
            return
        was_running = self.animation_running
        self.L_set = float(L)
        self.model.L = float(L)
        self.var_L.set(L)
        self.entry_L.delete(0, tk.END); self.entry_L.insert(0, f"{L:.3f}")
        self.var_measure_L.set(L)

        if self.timer_state in ("arming", "running"):
            self._cancel_timer("Измерение отменено: изменена длина подвеса.")
        if was_running:
            self._reset_pendulum(silent=True)
            self._status(f"Длина изменена на {L:.3f} м — маятник перезапущен вручную.",
                         toast=True, kind="warn")
        self._refresh_param_labels()
        self._update_progress()
        self._draw_pendulum()

    def _on_theta_scale(self, _=None):
        self.var_theta.set(round(float(self.var_theta.get()), 1))
        self._apply_theta()

    def _on_theta_entry(self):
        try:
            a = float(self.entry_theta.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Ввод", "Угол должен быть числом.")
            return
        lo, hi = self.msr.ANGLE_RANGE
        if not (lo <= a <= hi):
            messagebox.showerror("Диапазон", f"Угол должен быть в пределах {lo:.0f}–{hi:.0f}°.")
            return
        self.var_theta.set(round(a, 1))
        self._apply_theta()

    def _apply_theta(self):
        a = self.var_theta.get()
        self.entry_theta.delete(0, tk.END); self.entry_theta.insert(0, f"{a:.1f}")
        if not self.animation_running:
            self.model.reset(np.deg2rad(a))
        self._refresh_param_labels()
        self._draw_pendulum()

    def _apply_measure_L(self):
        try:
            L = float(self.var_measure_L.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("Ввод", "Длина должна быть числом.")
            return
        lo, hi = self.msr.RULER_RANGE
        if not (lo <= L <= hi):
            messagebox.showerror("Диапазон", f"L должен быть в пределах {lo:.2f}–{hi:.2f} м.")
            return
        self._set_length(round(L, 3))
        self._status(f"Длина установлена: {L:.3f} м", toast=True, kind="ok")

    def _start_pendulum(self):
        if self.animation_running:
            return
        theta0 = self.msr.measure_angle(np.deg2rad(self.var_theta.get()))
        self.model.L = self.L_set
        self.model.reset(theta0)
        self.animation_running = True
        self.last_wall = time.perf_counter()
        self._status(f"Маятник запущен: L = {self.L_set:.3f} м, θ₀ ≈ {self.var_theta.get():.1f}°. "
                     "Перейдите к шагу 2.", toast=True, kind="ok")
        self._update_tab_states()

    def _stop_pendulum(self):
        self.animation_running = False
        if self.timer_state in ("arming", "running"):
            self._cancel_timer("Измерение отменено: маятник остановлен.")
        self._status("Маятник на паузе.")

    def _reset_pendulum(self, silent=False):
        self.animation_running = False
        self.model.reset(np.deg2rad(self.var_theta.get()))
        self._cancel_timer()
        self.var_display_time.set("0.000 с")
        self.var_count.set(f"0 / {self.var_N.get()}")
        self._draw_pendulum()
        if not silent:
            self._status("Маятник сброшен в начальное положение.")

    # =========================================================================
    #  7.4. АНИМАЦИЯ
    # =========================================================================
    def _animate(self):
        now = time.perf_counter()
        dt = now - self.last_wall
        self.last_wall = now
        dt = min(dt, 0.05)

        if self.animation_running and dt > 0:
            h = 0.005
            steps = max(1, int(np.ceil(dt / h)))
            dt_step = dt / steps
            for _ in range(steps):
                t_cross = self.model.step_rk4(dt_step)
                if t_cross is not None:
                    self.flash_until = now + 0.12
                    self._on_zero_cross(t_cross)

        self._update_timer_ui()
        if self.nb.index(self.nb.select()) == 0:
            self._draw_pendulum()
        self.after(20, self._animate)

    def _draw_pendulum(self):
        cv = self.canvas
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 40 or h < 40:
            return

        px, py = w * 0.55, h * 0.13
        scale = (h * 0.68) / 1.5
        Lp = self.model.L * scale
        th = self.model.theta
        bx, by = px + Lp * np.sin(th), py + Lp * np.cos(th)

        cv.create_rectangle(0, py - 14, w, py - 6, fill="#cbd5e1", outline="")
        flashing = time.perf_counter() < self.flash_until
        cv.create_line(px, py, px, py + 1.5 * scale,
                       fill=C["success"] if flashing else "#cbd5e1",
                       width=2 if flashing else 1, dash=(4, 4))
        cv.create_text(px + 8, py + 1.5 * scale - 6, text="θ = 0 (метка отсчёта)",
                       anchor="w", font=F_TINY, fill=C["success_d"] if flashing else C["muted"])

        cv.create_line(px, py, bx, by, fill=C["ink"], width=2)
        cv.create_oval(px - 5, py - 5, px + 5, py + 5, fill="#475569", outline="")
        r = 14
        cv.create_oval(bx - r, by - r, bx + r, by + r,
                       fill=C["primary"], outline=C["primary_d"], width=2)
        cv.create_oval(bx - r + 4, by - r + 4, bx - r + 9, by - r + 9,
                       fill="#93c5fd", outline="")

        rx = 38
        cv.create_line(rx, py, rx, py + 1.5 * scale, fill="#94a3b8", width=2)
        for i in range(151):
            m = i * 0.01
            y = py + m * scale
            if i % 10 == 0:
                ln, wd = 11, 2
            elif i % 5 == 0:
                ln, wd = 7, 1
            else:
                ln, wd = 4, 1
            cv.create_line(rx - ln, y, rx + ln, y, fill="#94a3b8", width=wd)
            if i % 10 == 0:
                cv.create_text(rx + 16, y, text=f"{m:.2f}", anchor="w",
                               font=F_TINY, fill="#64748b")
        yL = py + self.model.L * scale
        cv.create_line(rx - 14, yL, rx + 14, yL, fill=C["danger"], width=3)
        cv.create_text(rx + 16, yL - 10, text=f"L = {self.model.L:.3f} м",
                       anchor="w", font=F_TINY, fill=C["danger"])

        ar = 70
        cv.create_arc(px - ar, py - ar, px + ar, py + ar, start=240, extent=60,
                      style=tk.ARC, outline="#cbd5e1")
        cv.create_line(px, py, px + ar * np.sin(th), py + ar * np.cos(th),
                       fill=C["warning"], width=1, dash=(3, 3))

        chip = (f"t: {self.model.t:6.2f} с   θ: {np.rad2deg(th):+6.2f}°   "
                f"{'качается' if self.animation_running else 'остановлен'}")
        cv.create_rectangle(10, 10, 10 + 7.5 * len(chip), 32, fill="#eef2f7", outline="")
        cv.create_text(16, 21, text=chip, anchor="w", font=F_TINY, fill=C["ink"])

    # =========================================================================
    #  7.5. СЕКУНДОМЕР
    # =========================================================================
    def _on_space(self, event):
        wclass = event.widget.winfo_class()
        if wclass in ("TEntry", "Entry", "TSpinbox", "Spinbox", "TCombobox", "Text"):
            return
        if self.timer_state in ("idle", "finished"):
            self._timer_start()
        elif self.timer_state in ("arming", "running"):
            self._timer_stop()
        return "break"

    def _timer_start(self):
        if self.timer_state not in ("idle", "finished"):
            return
        if not self.animation_running:
            messagebox.showwarning("Маятник остановлен",
                                   "Сначала запустите маятник на вкладке «1 · Установка».")
            return
        try:
            n = int(self.var_N.get())
            if not (1 <= n <= 50):
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showerror("N", "Число колебаний N — целое от 1 до 50.")
            return

        self.timer_state = "arming"
        self.zero_times = []
        self.t_start_true = None
        self.t_start_meas = None
        self.measured_t = None
        self.measured_N = None
        self.btn_add.config(state=tk.DISABLED)
        self._status("Секундомер взведён: отсчёт начнётся при ближайшем прохождении нуля.",
                     toast=True)

    def _on_zero_cross(self, t_cross):
        if self.timer_state == "arming":
            self.t_start_true = t_cross
            self.t_start_meas = t_cross + self.msr.reaction_offset()
            self.zero_times = []
            self.timer_state = "running"
            self._status("Отсчёт пошёл. Считайте полные колебания и нажмите «Стоп».",
                         toast=True, kind="ok")
        elif self.timer_state == "running":
            self.zero_times.append(t_cross)
            full = len(self.zero_times) // 2
            if self.var_auto.get() and full >= int(self.var_N.get()):
                self._finalize(int(self.var_N.get()))

    def _timer_stop(self):
        if self.timer_state == "arming":
            self._cancel_timer("Отсчёт отменён до старта.")
            return
        if self.timer_state != "running":
            return
        full = len(self.zero_times) // 2
        if full < 1:
            self._status("Пройдено меньше одного полного колебания — ждём дальше.",
                         toast=True, kind="warn")
            return
        self._finalize(full)

    def _finalize(self, n_full):
        t_end_true = self.zero_times[2 * n_full - 1]
        t_end_meas = t_end_true + self.msr.reaction_offset()
        t_meas = t_end_meas - self.t_start_meas
        t_meas = max(t_meas, 0.05)
        t_meas = round(t_meas, 3)

        self.measured_t = t_meas
        self.measured_N = n_full
        self.timer_state = "finished"
        self.btn_add.config(state=tk.NORMAL)
        self.var_last_time.set(f"{t_meas:.3f} с / {n_full} кол.")
        self._status(f"Замер: t = {t_meas:.3f} с за {n_full} полных колебаний "
                     f"(T ≈ {t_meas / n_full:.3f} с). Нажмите «Зафиксировать».",
                     toast=True, kind="ok")

    def _cancel_timer(self, msg=None):
        self.timer_state = "idle"
        self.zero_times = []
        self.t_start_true = self.t_start_meas = None
        self.measured_t = self.measured_N = None
        if hasattr(self, "btn_add"):
            self.btn_add.config(state=tk.DISABLED)
        if msg:
            self._status(msg, toast=True, kind="warn")

    def _update_timer_ui(self):
        st = self.timer_state
        try:
            n_target = int(self.var_N.get())
        except (ValueError, tk.TclError):
            n_target = 0

        if st == "arming":
            self.timer_state_var.set("Взведён · ожидание прохождения нуля…")
            self.timer_state_lbl.config(fg=C["warning"])
            self.var_display_time.set("ждём 0")
            self.var_count.set(f"0 / {n_target}")
            self.btn_start.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL, text="✕ Отмена · Пробел")
        elif st == "running":
            full = len(self.zero_times) // 2
            elapsed = self.model.t - (self.t_start_true or self.model.t)
            self.timer_state_var.set("ИДЁТ ИЗМЕРЕНИЕ · нажмите «Стоп» после нужного числа колебаний")
            self.timer_state_lbl.config(fg=C["danger"])
            self.var_display_time.set(f"{elapsed:.3f} с")
            self.var_count.set(f"{full} / {n_target}")
            self.btn_start.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL, text="⏹ Стоп · Пробел")
        elif st == "finished":
            self.timer_state_var.set("Замер завершён · зафиксируйте результат в таблице")
            self.timer_state_lbl.config(fg=C["success_d"])
            self.var_display_time.set(f"{self.measured_t:.3f} с")
            self.var_count.set(f"{self.measured_N} / {n_target}")
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED, text="⏹ Стоп · Пробел")
        else:
            self.timer_state_var.set("Готов к старту")
            self.timer_state_lbl.config(fg=C["muted"])
            self.var_count.set(f"0 / {n_target}")
            self.btn_start.config(state=tk.NORMAL if self.animation_running else tk.DISABLED)
            self.btn_stop.config(state=tk.DISABLED, text="⏹ Стоп · Пробел")

    # =========================================================================
    #  7.6. ТАБЛИЦА ИЗМЕРЕНИЙ
    # =========================================================================
    def _add_measurement(self):
        if self.measured_t is None or self.measured_N is None:
            return
        L_meas = self.msr.measure_length(self.L_set)
        N = int(self.measured_N)
        t = float(self.measured_t)
        T = t / N
        self.measurements.append({
            "idx": len(self.measurements) + 1,
            "L_set": round(self.L_set, 3),
            "L": L_meas, "N": N, "t": t, "T": T, "T2": T * T,
        })
        self._refresh_tree()
        self._cancel_timer()
        self.var_display_time.set("0.000 с")
        self._mark_stale()
        self._update_progress()
        self._status(f"Запись №{len(self.measurements)} добавлена: L = {L_meas:.4f} м, "
                     f"N = {N}, t = {t:.3f} с, T = {T:.4f} с.", toast=True, kind="ok")

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, m in enumerate(self.measurements):
            m["idx"] = i + 1
            self.tree.insert("", "end", iid=str(m["idx"]),
                             tags=("odd",) if i % 2 else (),
                             values=(m["idx"], f"{m['L_set']:.3f}", f"{m['L']:.4f}", m["N"],
                                     f"{m['t']:.3f}", f"{m['T']:.4f}", f"{m['T2']:.4f}"))
        self._refresh_summary_table()

    def _refresh_summary_table(self):
        self.summary_tree.delete(*self.summary_tree.get_children())
        if not self.measurements:
            return

        P = 0.95
        ms = self.msr

        groups = {}
        for m in self.measurements:
            groups.setdefault(round(m["L_set"], 3), []).append(m)

        row_idx = 0
        for key in sorted(groups):
            g = groups[key]
            n = len(g)
            T = np.array([m["T"] for m in g])
            Lm = np.array([m["L"] for m in g])
            T_mean = float(T.mean())
            S_T = float(T.std(ddof=1)) if n > 1 else 0.0
            d_rand = student_t(P, n - 1) * S_T / np.sqrt(n) if n > 1 else 0.0
            N_mean = float(np.mean([m["N"] for m in g]))
            d_instr = np.sqrt(2.0) * ms.SIGMA_REACTION / N_mean
            d_tot = float(np.hypot(d_rand, d_instr))
            L_mean = float(Lm.mean())
            T2_mean = T_mean ** 2
            d_T2 = 2.0 * T_mean * d_tot

            self.summary_tree.insert("", "end", iid=f"s{row_idx}",
                                     tags=("odd",) if row_idx % 2 else (),
                                     values=(
                                         f"{L_mean:.4f}",
                                         n,
                                         f"{T_mean:.4f}",
                                         f"{S_T:.4f}",
                                         f"{d_tot:.4f}",
                                         f"{T2_mean:.4f}",
                                         f"{d_T2:.4f}",
                                     ))
            row_idx += 1

    def _show_tree_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.tree_menu.post(event.x_root, event.y_root)

    def _selected_row(self):
        sel = self.tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        return next((m for m in self.measurements if m["idx"] == idx), None)

    def _delete_selected(self):
        m = self._selected_row()
        if m is None:
            return
        if not messagebox.askyesno("Удаление", f"Удалить измерение №{m['idx']}?"):
            return
        self.measurements = [x for x in self.measurements if x["idx"] != m["idx"]]
        self._refresh_tree()
        self._mark_stale()
        self._update_progress()
        self._status(f"Измерение №{m['idx']} удалено.", toast=True, kind="warn")
        if not self._ready_for_analysis():
            self.res = None
            self.nb.select(1)

    def _edit_selected(self):
        m = self._selected_row()
        if m is None:
            return
        dlg = EditRowDialog(self, m)
        self.wait_window(dlg)
        if dlg.result:
            m.update(dlg.result)
            m["L_set"] = round(m["L"], 3)
            m["T"] = m["t"] / m["N"]
            m["T2"] = m["T"] ** 2
            self._refresh_tree()
            self._mark_stale()
            self._update_progress()
            self._status(f"Измерение №{m['idx']} изменено.", toast=True, kind="ok")

    def _clear_table(self):
        if not self.measurements:
            return
        if not messagebox.askyesno("Очистка", "Удалить ВСЕ измерения?"):
            return
        self.measurements.clear()
        self.res = None
        self._refresh_tree()
        self._mark_stale()
        self._update_progress()
        self._set_text(self.txt_result, "Данных нет. Выполните измерения на шаге 2.")
        self._set_text(self.txt_report, "Отчёт появится после расчёта на вкладке «3 · Обработка».")
        self.ax.clear(); self.canvas_plot.draw()
        self.nb.select(1)
        self._status("Таблица очищена.", toast=True, kind="warn")

    def _update_progress(self):
        key = round(self.L_set, 3)
        cnt = sum(1 for m in self.measurements if round(m["L_set"], 3) == key)
        series = {round(m["L_set"], 3) for m in self.measurements}
        self.progress_var.set(
            f"Серия L = {key:.3f} м: {cnt} из {self.TARGET_REPEATS} повторов   ·   "
            f"разных длин: {len(series)} из {self.TARGET_SERIES}   ·   "
            f"всего записей: {len(self.measurements)}")
        self.progress.configure(value=min(cnt, self.TARGET_REPEATS))

    # =========================================================================
    #  7.7. ОБРАБОТКА РЕЗУЛЬТАТОВ
    # =========================================================================
    def _on_tab_change(self, _=None):
        idx = self.nb.index(self.nb.select())
        if idx == 1:
            self._update_progress()
        elif idx == 2:
            self._reprocess()
        elif idx == 3:
            if self._reprocess():
                self._rebuild_plot()
        elif idx == 4:
            if self._reprocess():
                self._preview_report()
            self._update_report_buttons()

    def _reprocess(self, force=False):
        if not self._ready_for_analysis():
            return False
        if self.data_stale or self.res is None or force:
            self._process_data()
        return bool(self.res)

    def _process_data(self):
        P = float(self.var_P.get())
        ms = self.msr
        lines = []
        add = lines.append

        add("=" * 70)
        add("  ОБРАБОТКА РЕЗУЛЬТАТОВ ИЗМЕРЕНИЙ")
        add(f"  Тема: определение g математическим маятником.  P = {P:.2f}")
        add(f"  Дата: {datetime.now():%Y-%m-%d %H:%M:%S}")
        add("=" * 70)
        add("")
        add("ПРИБОРЫ (пределы / цена деления / СКО):")
        add(f"  линейка      {ms.RULER_RANGE[0]:.2f}–{ms.RULER_RANGE[1]:.2f} м / "
            f"{ms.RULER_DIV*1000:.0f} мм / σ = {ms.SIGMA_RULER*1000:.2f} мм")
        add(f"  транспортир  {ms.ANGLE_RANGE[0]:.0f}–{ms.ANGLE_RANGE[1]:.0f}° / "
            f"{ms.ANGLE_DIV:.0f}° / σ = {np.rad2deg(ms.SIGMA_PROTRACTOR):.1f}°")
        add(f"  секундомер   реакция σ = {ms.SIGMA_REACTION:.2f} с на каждое нажатие")
        add("")
        add("ИСХОДНЫЕ ИЗМЕРЕНИЯ:")
        add("-" * 70)
        add(f"{'№':>3} | {'L уст., м':>10} | {'L изм., м':>10} | {'N':>3} | "
            f"{'t, с':>9} | {'T, с':>9} | {'T², с²':>9}")
        add("-" * 70)
        for m in self.measurements:
            add(f"{m['idx']:3d} | {m['L_set']:10.3f} | {m['L']:10.4f} | {m['N']:3d} | "
                f"{m['t']:9.3f} | {m['T']:9.4f} | {m['T2']:9.4f}")
        add("-" * 70)
        add("")

        groups = {}
        for m in self.measurements:
            groups.setdefault(round(m["L_set"], 3), []).append(m)

        add("СЕРИИ (среднее и погрешности периода):")
        add("-" * 70)
        add(f"{'L, м':>9} | {'n':>2} | {'<T>, с':>9} | {'S_T, с':>9} | "
            f"{'ΔT случ':>9} | {'ΔT приб':>9} | {'ΔT полн':>9}")
        add("-" * 70)

        L_pts, T_pts, T2_pts, T2_err, n_list = [], [], [], [], []
        for key in sorted(groups):
            g = groups[key]
            n = len(g)
            T = np.array([m["T"] for m in g])
            Lm = np.array([m["L"] for m in g])
            T_mean = float(T.mean())
            S_T = float(T.std(ddof=1)) if n > 1 else 0.0
            d_rand = student_t(P, n - 1) * S_T / np.sqrt(n) if n > 1 else 0.0
            N_mean = float(np.mean([m["N"] for m in g]))
            d_instr = np.sqrt(2.0) * ms.SIGMA_REACTION / N_mean
            d_tot = float(np.hypot(d_rand, d_instr))
            L_mean = float(Lm.mean())

            add(f"{L_mean:9.4f} | {n:2d} | {T_mean:9.4f} | {S_T:9.4f} | "
                f"{d_rand:9.4f} | {d_instr:9.4f} | {d_tot:9.4f}")

            L_pts.append(L_mean)
            T_pts.append(T_mean)
            T2_pts.append(T_mean ** 2)
            T2_err.append(2.0 * T_mean * d_tot)
            n_list.append(n)

        add("-" * 70)
        add("  ΔT случ = t(P, n−1)·S_T/√n;  ΔT приб = √2·σ_реакции/N;  ΔT полн = √(случ² + приб²)")
        add("")

        L_arr, T2_arr, e_arr = np.array(L_pts), np.array(T2_pts), np.array(T2_err)
        npts = len(L_arr)

        Lbar, T2bar = L_arr.mean(), T2_arr.mean()
        Sxx = float(np.sum((L_arr - Lbar) ** 2))
        if Sxx <= 0:
            self._process_failed("Все измерения при одной длине — регрессия невозможна.")
            return
        k = float(np.sum((L_arr - Lbar) * (T2_arr - T2bar)) / Sxx)
        b = float(T2bar - k * Lbar)
        resid = T2_arr - (k * L_arr + b)
        dof = max(1, npts - 2)
        s_res = float(np.sqrt(np.sum(resid ** 2) / dof)) if npts > 2 else float(np.max(np.abs(resid)))
        s_k = s_res / np.sqrt(Sxx)
        d_k = student_t(P, dof) * s_k
        s_k_instr = float(np.sqrt(np.sum(((L_arr - Lbar) * e_arr) ** 2)) / Sxx) if Sxx > 0 else 0.0
        d_k_total = float(np.hypot(d_k, s_k_instr))

        g_val = 4.0 * np.pi ** 2 / k if k > 0 else float("nan")
        d_g = abs(g_val) * (d_k_total / k) if (k > 0 and np.isfinite(g_val)) else float("nan")

        add("ЛИНЕЙНАЯ РЕГРЕССИЯ  T² = k·L + b:")
        add(f"  число точек n = {npts} (разных длин), степеней свободы = {dof}")
        add(f"  k = {fmt_pm(k, d_k_total, 3)} с²/м")
        add(f"  b = {b:+.5f} с²   (теоретически b = 0)")
        add(f"  S остатков = {s_res:.5f} с²")
        add("")
        add("ВЫЧИСЛЕНИЕ УСКОРЕНИЯ СВОБОДНОГО ПАДЕНИЯ:")
        add("  T² = (4π²/g)·L  ⇒  k = 4π²/g  ⇒  g = 4π²/k")
        add(f"  g = {fmt_pm(g_val, d_g)} м/с²   (P = {P:.2f})")
        if np.isfinite(g_val) and np.isfinite(d_g) and d_g > 0:
            add(f"  доверительный интервал: [{g_val - d_g:.3f}; {g_val + d_g:.3f}] м/с²")
        add("")

        adequate = g_is_adequate(g_val)
        rel = abs(g_val - G_TABLE) / G_TABLE * 100 if np.isfinite(g_val) else float("nan")
        add("СРАВНЕНИЕ С ТАБЛИЧНЫМ ЗНАЧЕНИЕМ:")
        add(f"  g_табл = {G_TABLE:.2f} м/с²")
        add(f"  относительное отклонение = {rel:.2f} %")
        inside = np.isfinite(d_g) and abs(g_val - G_TABLE) <= d_g
        if not adequate:
            add("  ⚠ РЕЗУЛЬТАТ НЕАДЕКВАТЕН (вне диапазона 5–15 м/с²).")
            add("    Проверьте: время t, число колебаний N, не сбита ли длина подвеса.")
        elif inside:
            add("  ✓ Табличное значение попадает в доверительный интервал.")
        else:
            add("  ✗ Табличное значение вне доверительного интервала.")
            add("    Возможные причины: конечная амплитуда (нелинейность sin θ),")
            add("    систематика длины (не учтён радиус шарика), мало повторов.")
        add("")
        add("ЗАМЕЧАНИЯ О МОДЕЛИ:")
        add("  Период нелинейного маятника растёт с амплитудой: T ≈ T₀(1 + θ₀²/16 + …),")
        add("  поэтому при θ₀ = 20–30° возможно систематическое занижение g на 1–2 %.")
        add("=" * 70)

        errors_exceed = bool(np.all(e_arr >= T2_arr)) or bool(np.any(T2_arr <= 0))
        valid = bool(adequate and np.isfinite(g_val) and k > 0 and not errors_exceed)

        self.res = {
            "P": P, "lines": lines, "g": g_val, "dg": d_g, "k": k, "dk": d_k_total,
            "b": b, "npts": npts, "L": L_arr, "T2": T2_arr, "err": e_arr,
            "n": n_list, "T": np.array(T_pts),
            "adequate": adequate, "inside": inside, "rel": rel,
            "errors_exceed": errors_exceed, "valid": valid,
        }
        self.data_stale = False
        self.calc_time = datetime.now()

        self._set_text(self.txt_result, "\n".join(lines))
        self.lbl_timestamp.config(text=f"Данные актуальны на {self.calc_time:%H:%M:%S}")

        if not adequate:
            self.card_g.config(text=f"g = {g_val:.1f} м/с² — неадекватно", bg=C["danger"], fg="white")
            self.card_check.config(text="Проверьте t и N!", bg=C["danger"], fg="white")
            self._show_banner("Результат неадекватен — проверьте время измерений и число колебаний N.",
                              C["danger"])
        elif errors_exceed:
            self.card_g.config(text=f"g = {fmt_pm(g_val, d_g)} м/с²", bg=C["warning"], fg="white")
            self.card_check.config(text="Погрешности превышают значения", bg=C["warning"], fg="white")
            self._show_banner("Погрешности превышают значения — результаты недостоверны.", C["warning"])
        elif inside:
            self.card_g.config(text=f"g = {fmt_pm(g_val, d_g)} м/с²", bg=C["success"], fg="white")
            self.card_check.config(text=f"Совпадает с {G_TABLE:.2f} м/с² (откл. {rel:.2f} %)",
                                   bg=C["success"], fg="white")
            self._hide_banner()
        else:
            self.card_g.config(text=f"g = {fmt_pm(g_val, d_g)} м/с²", bg=C["warning"], fg="white")
            self.card_check.config(text=f"Вне интервала · откл. {rel:.2f} %", bg=C["warning"], fg="white")
            self._show_banner("Табличное значение вне доверительного интервала — возможна систематика.",
                              C["warning"])

        self._update_tab_states()
        self._update_report_buttons()

    def _process_failed(self, msg):
        self.res = None
        self._set_text(self.txt_result, msg)
        self.card_g.config(text="g = — м/с²", bg=C["card"], fg=C["muted"])
        self.card_check.config(text=msg, bg=C["card"], fg=C["muted"])
        self._show_banner(msg, C["warning"])
        self._update_report_buttons()

    # =========================================================================
    #  7.8. ГРАФИК
    # =========================================================================
    def _remember_scale(self):
        if self.keep_scale_var.get():
            self._saved_lims = (self.ax.get_xlim(), self.ax.get_ylim())
        else:
            self._saved_lims = None

    def _render_figure(self, fig, ax, interactive=False):
        r = self.res
        ax.clear()
        ax.set_facecolor(C["card"])
        fig.patch.set_facecolor(C["card"])

        if self.show_errors_var.get():
            ax.errorbar(r["L"], r["T2"], yerr=r["err"], fmt="o", color=C["primary"],
                        ecolor="#93c5fd", markersize=7, capsize=4, elinewidth=1.4,
                        label="Измерения (средние по серии)")
        else:
            ax.plot(r["L"], r["T2"], "o", color=C["primary"], markersize=7,
                    label="Измерения (средние по серии)")

        if self.show_fit_var.get():
            x0, x1 = float(r["L"].min()), float(r["L"].max())
            pad = (x1 - x0) * 0.12 + 1e-6
            xs = np.linspace(x0 - pad, x1 + pad, 200)
            ax.plot(xs, r["k"] * xs + r["b"], "-", color=C["danger"], linewidth=2,
                    label=f"МНК: T² = {r['k']:.4f}·L {r['b']:+.4f}")

        ax.set_xlabel("Длина подвеса L, м", fontsize=10)
        ax.set_ylabel("Квадрат периода T², с²", fontsize=10)
        ax.set_title("T²(L): линейная регрессия, g = 4π²/k", fontsize=11, pad=10)
        ax.grid(True, linestyle="--", alpha=0.45)
        ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.set_ylim(bottom=0)
        ax.set_xlim(left=max(0.0, float(r["L"].min()) - 0.1))
        fig.tight_layout()

        if interactive:
            self._plot_pts = np.column_stack([r["L"], r["T2"]])
            self._annot = ax.annotate(
                "", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.4", fc="#111827", ec="none", alpha=0.92),
                color="white", fontsize=8,
            )
            self._annot.set_visible(False)

    def _rebuild_plot(self):
        if not self.res:
            return
        r = self.res
        if not r["adequate"]:
            self.ax.clear()
            self.ax.set_facecolor(C["card"])
            self.ax.text(0.5, 0.5, "Построение заблокировано:\ng вне диапазона 5–15 м/с².\n"
                                   "Проверьте время измерений и число колебаний N.",
                         ha="center", va="center", transform=self.ax.transAxes,
                         fontsize=11, color=C["danger"])
            self.ax.set_xticks([]); self.ax.set_yticks([])
            self.canvas_plot.draw()
            self.plot_warning.config(text="График недоступен до получения достоверных данных.",
                                     fg=C["danger"])
            self.lbl_fit.config(text="")
            return
        if r["errors_exceed"]:
            self.ax.clear()
            self.ax.set_facecolor(C["card"])
            self.ax.text(0.5, 0.5, "Погрешности превышают значения.\nРезультаты недостоверны.",
                         ha="center", va="center", transform=self.ax.transAxes,
                         fontsize=11, color=C["warning"])
            self.ax.set_xticks([]); self.ax.set_yticks([])
            self.canvas_plot.draw()
            self.plot_warning.config(text="Увеличьте N колебаний и число повторов.", fg=C["warning"])
            self.lbl_fit.config(text="")
            return

        self._render_figure(self.fig, self.ax, interactive=True)
        if self.keep_scale_var.get() and self._saved_lims:
            self.ax.set_xlim(self._saved_lims[0])
            self.ax.set_ylim(self._saved_lims[1])
        self.canvas_plot.draw()

        self.lbl_fit.config(
            text=f"k = {fmt_pm(r['k'], r['dk'], 3)} с²/м    ·    b = {r['b']:+.4f} с²    ·    "
                 f"g = {fmt_pm(r['g'], r['dg'])} м/с²    ·    откл. {r['rel']:.2f} %")
        if r["npts"] < 4:
            self.plot_warning.config(
                text=f"Точек: {r['npts']}. Добавьте минимум 4–5 разных длин для надёжной аппроксимации.",
                fg=C["warning"])
        else:
            self.plot_warning.config(text="Наведите курсор на точку, чтобы увидеть её значения.",
                                     fg=C["muted"])

    def _on_plot_hover(self, event):
        if self._annot is None or self._plot_pts is None or event.inaxes is not self.ax:
            if self._annot is not None and self._annot.get_visible():
                self._annot.set_visible(False)
                self.canvas_plot.draw_idle()
            return
        if event.x is None or event.y is None:
            return
        pts = self.ax.transData.transform(self._plot_pts)
        d = np.hypot(pts[:, 0] - event.x, pts[:, 1] - event.y)
        i = int(np.argmin(d))
        if d[i] < 14:
            r = self.res
            self._annot.xy = (self._plot_pts[i, 0], self._plot_pts[i, 1])
            self._annot.set_text(
                f"L = {r['L'][i]:.4f} м\nT = {r['T'][i]:.4f} с\n"
                f"T² = {r['T2'][i]:.4f} ± {r['err'][i]:.4f} с²\nповторов n = {r['n'][i]}")
            self._annot.set_visible(True)
        else:
            self._annot.set_visible(False)
        self.canvas_plot.draw_idle()

    # =========================================================================
    #  7.9. ОТЧЁТ
    # =========================================================================
    def _update_report_buttons(self):
        has_rows = len(self.measurements) > 0
        valid = bool(self.res and self.res["valid"])
        self.btn_csv.config(state=tk.NORMAL if has_rows else tk.DISABLED)
        for b in (self.btn_txt, self.btn_pdf, self.btn_png):
            b.config(state=tk.NORMAL if valid else tk.DISABLED)
        if not has_rows:
            self.report_hint.config(text="Недоступно: нет измерений.")
        elif not self.res:
            self.report_hint.config(text="Недоступно: выполните расчёт на шаге 3.")
        elif not self.res["valid"]:
            self.report_hint.config(text="Экспорт заблокирован: результат недостоверен "
                                         "(проверьте t, N и погрешности).")
        else:
            self.report_hint.config(text="Готово к экспорту. PDF содержит таблицу, расчёты и график.")

    def _report_header(self):
        return (
            "ОТЧЁТ ПО ЛАБОРАТОРНОЙ РАБОТЕ\n"
            "Тема: определение ускорения свободного падения математическим маятником\n"
            f"Дата: {datetime.now():%Y-%m-%d %H:%M}\n"
            f"Модель: θ'' = −(g/L)sinθ − γθ', γ = 0.002 с⁻¹, RK4\n"
            f"Доверительная вероятность P = {self.res['P']:.2f}\n\n"
        )

    def _preview_report(self):
        if not self.res:
            self._set_text(self.txt_report,
                           "Отчёт ещё не сформирован.\n\n"
                           f"Нужно ≥ {self.MIN_ROWS} измерений при ≥ {self.MIN_POINTS} разных длинах, "
                           "затем откройте вкладку «3 · Обработка».")
            return
        self._set_text(self.txt_report, self._report_header() + "\n".join(self.res["lines"]))

    def _save_csv(self):
        if not self.measurements:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")],
                                            initialfile="measurements.csv")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f, delimiter=";")
            wr.writerow(["№", "L установленная, м", "L измеренная, м", "N", "t, с", "T, с", "T^2, с^2"])
            for m in self.measurements:
                wr.writerow([m["idx"], f"{m['L_set']:.3f}", f"{m['L']:.4f}", m["N"],
                             f"{m['t']:.3f}", f"{m['T']:.4f}", f"{m['T2']:.4f}"])
        self._status(f"Таблица сохранена: {path}", toast=True, kind="ok")

    def _save_txt(self):
        if not (self.res and self.res["valid"]):
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=[("Текст", "*.txt")],
                                            initialfile="report.txt")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._report_header())
            f.write("\n".join(self.res["lines"]))
        self._status(f"Отчёт сохранён: {path}", toast=True, kind="ok")

    def _save_png(self):
        if not (self.res and self.res["valid"]):
            return
        path = filedialog.asksaveasfilename(defaultextension=".png",
                                            filetypes=[("PNG", "*.png")],
                                            initialfile="plot_T2_L.png")
        if not path:
            return
        fig = Figure(figsize=(8, 5), dpi=150, facecolor="white")
        ax = fig.add_subplot(111)
        self._render_figure(fig, ax)
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
        self._status(f"График сохранён: {path}", toast=True, kind="ok")

    def _save_pdf(self):
        if not (self.res and self.res["valid"]):
            return
        path = filedialog.asksaveasfilename(defaultextension=".pdf",
                                            filetypes=[("PDF", "*.pdf")],
                                            initialfile="report.pdf")
        if not path:
            return
        from matplotlib.backends.backend_pdf import PdfPages
        lines = self._report_header().splitlines() + self.res["lines"]
        per_page = 50
        chunks = [lines[i:i + per_page] for i in range(0, len(lines), per_page)] or [[""]]
        with PdfPages(path) as pdf:
            for page, chunk in enumerate(chunks, start=1):
                fig = Figure(figsize=(8.27, 11.69), dpi=100, facecolor="white")
                ax = fig.add_axes([0.07, 0.05, 0.88, 0.88]); ax.axis("off")
                ax.set_title(f"Отчёт по лабораторной работе — стр. {page}/{len(chunks)}",
                             fontsize=11, loc="left", pad=12)
                ax.text(0, 1, "\n".join(chunk), va="top", ha="left",
                        fontsize=7.2, family="monospace", transform=ax.transAxes)
                pdf.savefig(fig, facecolor="white")
            fig = Figure(figsize=(8.27, 5.5), dpi=100, facecolor="white")
            ax = fig.add_subplot(111)
            self._render_figure(fig, ax)
            pdf.savefig(fig, facecolor="white")
        self._status(f"PDF сохранён: {path}", toast=True, kind="ok")

    def _print_report(self):
        if not (self.res and self.res["valid"]):
            messagebox.showinfo("Печать", "Сначала получите достоверный результат на шаге 3.")
            return
        fig = Figure(figsize=(7.5, 4.2), dpi=110, facecolor="white")
        ax = fig.add_subplot(111)
        self._render_figure(fig, ax)
        tmp_png = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        fig.savefig(tmp_png.name, dpi=110, bbox_inches="tight", facecolor="white")
        with open(tmp_png.name, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        os.unlink(tmp_png.name)

        html = (
            "<html><head><meta charset='utf-8'><title>Отчёт</title>"
            "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#111827}"
            "pre{font-family:Consolas,monospace;font-size:11px;white-space:pre-wrap}"
            "h1{font-size:18px}img{max-width:100%;margin-top:14px}</style></head><body>"
            "<h1>Отчёт по лабораторной работе</h1><pre>"
            + self._report_header() + "\n".join(self.res["lines"])
            + f"</pre><img src='data:image/png;base64,{b64}'></body></html>"
        )
        tmp_html = tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w",
                                               encoding="utf-8")
        tmp_html.write(html)
        tmp_html.close()
        webbrowser.open("file://" + os.path.abspath(tmp_html.name))
        self._status("Отчёт открыт в браузере — нажмите Ctrl+P для печати.", toast=True)


# =============================================================================
#  8. ТОЧКА ВХОДА
# =============================================================================
def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
