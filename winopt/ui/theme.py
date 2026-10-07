"""Цвета, шрифты и стиль таблиц тёмной темы."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import customtkinter as ctk

# --- Палитра -----------------------------------------------------------------
BG = "#070B16"
SIDEBAR = "#0B1122"
CARD = "#0F1730"
CARD_HI = "#16213F"
CARD_HOVER = "#1B2850"
BORDER = "#1F2C4D"
GRID = "#18233F"
TEXT = "#E6EAF5"
MUTED = "#8A94B3"
DIM = "#56607F"
ACCENT = "#22D3EE"
ACCENT_HOVER = "#0EA5C6"
ACCENT_DARK = "#0B4F63"
VIOLET = "#A78BFA"
GREEN = "#34D399"
AMBER = "#FBBF24"
RED = "#F87171"
RED_DARK = "#7F1D1D"
BLUE = "#60A5FA"
PINK = "#F472B6"

LEVEL_COLORS = {"ok": GREEN, "info": BLUE, "warn": AMBER, "danger": RED}

FAMILY = "Segoe UI"
MONO = "Consolas"
ICON_FAMILY: str | None = None
SCALE = 1.0

# Значки сайдбара: Segoe Fluent Icons / Segoe MDL2 Assets (есть в Windows 10/11),
# запасной вариант — обычные символы Unicode.
ICONS = {
    "dashboard": ("\uE80F", "⌂"),
    "optimize": ("\uE945", "⚡"),
    "processes": ("\uE9D9", "≣"),
    "startup": ("\uE7E8", "⏻"),
    "cleanup": ("\uE74D", "✦"),
    "disk": ("\uEDA2", "◫"),
    "programs": ("\uE71D", "▦"),
    "services": ("\uE713", "⚙"),
    "network": ("\uE774", "◎"),
    "security": ("\uEA18", "⛨"),
    "health": ("\uE95E", "♥"),
    "journal": ("\uE81C", "☰"),
    "admin": ("\uE7EF", "★"),
    "refresh": ("\uE72C", "↻"),
}


def init_fonts(root: tk.Misc) -> None:
    """Выбрать доступные шрифты и коэффициент масштабирования."""
    global FAMILY, MONO, ICON_FAMILY, SCALE
    families = set(tkfont.families(root))
    for name in ("Segoe UI Variable Text", "Segoe UI", "Inter", "DejaVu Sans"):
        if name in families:
            FAMILY = name
            break
    for name in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono"):
        if name in families:
            MONO = name
            break
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in families:
            ICON_FAMILY = name
            break
    try:
        SCALE = ctk.ScalingTracker.get_widget_scaling(root)
    except Exception:
        SCALE = 1.0


def icon(name: str) -> str:
    glyph, fallback = ICONS.get(name, ("", "•"))
    return glyph if ICON_FAMILY else fallback


def icon_font(size: int = 16) -> ctk.CTkFont:
    return ctk.CTkFont(family=ICON_FAMILY or FAMILY, size=size)


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FAMILY, size=size, weight=weight)


def mono(size: int = 12) -> ctk.CTkFont:
    return ctk.CTkFont(family=MONO, size=size)


def px(value: float) -> int:
    return int(round(value * SCALE))


def tk_font(size: int = 12, weight: str = "normal", family: str | None = None) -> tuple:
    """Шрифт для обычных tk-виджетов (Canvas, Treeview) в пикселях с учётом DPI."""
    return (family or FAMILY, -px(size), weight)


def blend(color: str, background: str = CARD, alpha: float = 0.3) -> str:
    """Смешать цвет с фоном — даёт «полупрозрачный» оттенок."""
    c = _rgb(color)
    b = _rgb(background)
    mixed = tuple(int(b[i] + (c[i] - b[i]) * alpha) for i in range(3))
    return "#%02x%02x%02x" % mixed


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def level_color(score: float) -> str:
    if score >= 80:
        return GREEN
    if score >= 55:
        return AMBER
    return RED


def load_color(percent: float) -> str:
    if percent >= 85:
        return RED
    if percent >= 60:
        return AMBER
    return ACCENT


def setup_ttk(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "WinOpt.Treeview",
        background=CARD,
        fieldbackground=CARD,
        foreground=TEXT,
        bordercolor=CARD,
        lightcolor=CARD,
        darkcolor=CARD,
        borderwidth=0,
        rowheight=px(30),
        font=tk_font(13),
    )
    style.map(
        "WinOpt.Treeview",
        background=[("selected", ACCENT_DARK)],
        foreground=[("selected", "#FFFFFF")],
    )
    style.configure(
        "WinOpt.Treeview.Heading",
        background=CARD_HI,
        foreground=MUTED,
        relief="flat",
        borderwidth=0,
        font=tk_font(12, "bold"),
        padding=(px(8), px(6)),
    )
    style.map("WinOpt.Treeview.Heading", background=[("active", CARD_HOVER)], foreground=[("active", TEXT)])
    style.layout("WinOpt.Treeview", [("WinOpt.Treeview.treearea", {"sticky": "nswe"})])
