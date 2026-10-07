"""Точка входа графического интерфейса (сохранена для совместимости).

Сам интерфейс находится в пакете winopt.ui (CustomTkinter, тёмная тема).
"""

from __future__ import annotations


def run_gui(start_page: str = "dashboard") -> int:
    try:
        from winopt.ui.app import run_gui as _run
    except ImportError as exc:  # нет customtkinter
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "WinOpt",
            "Не установлена библиотека интерфейса.\n\n"
            "Выполните в папке проекта:\n  python -m pip install -r requirements.txt\n\n"
            f"Подробности: {exc}",
        )
        root.destroy()
        return 1
    return _run(start_page)
