"""Журнал: история всех изменений, сделанных программой, и папка отчётов."""

from __future__ import annotations

import customtkinter as ctk

from winopt.history import clear_history, history_path, read_history
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import DataTable, PageHeader, ask, button
from winopt.winutil import data_dir, open_path, reports_dir


class JournalPage(Page):
    def build(self) -> None:
        header = PageHeader(self, "Журнал действий", "Всё, что WinOpt изменил на компьютере: когда, что и с каким результатом.", "journal")
        header.pack(fill="x", pady=(0, 14))
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 10))
        button(bar, "↻  Обновить", self.refresh).pack(side="left")
        button(bar, "Папка отчётов", lambda: open_path(reports_dir())).pack(side="left", padx=8)
        button(bar, "Папка данных", lambda: open_path(data_dir())).pack(side="left")
        button(bar, "Очистить журнал…", self.clear, kind="ghost").pack(side="right")
        self.info = ctk.CTkLabel(self, text="", text_color=T.DIM, font=T.font(12), anchor="w")
        self.info.pack(fill="x", pady=(0, 6))
        self.table = DataTable(self, [("time", "Время", 160, "w", False), ("cat", "Раздел", 130, "w", False), ("action", "Действие", 360, "w", True),
                                      ("details", "Подробности", 420, "w", True), ("ok", "Итог", 80, "center", False)], height=18)
        self.table.pack(fill="both", expand=True)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        entries = read_history()
        rows = [{"iid": f"h{n}", "values": [e.time, e.category, e.action, e.details, "✓" if e.ok else "ошибка"],
                 "sort": [e.time, e.category, e.action, e.details, e.ok], "tags": [] if e.ok else ["danger"]} for n, e in enumerate(entries)]
        self.table.set_rows(rows, "Журнал пуст — программа ещё ничего не меняла")
        self.info.configure(text=f"Записей: {len(entries)} · файл: {history_path()}")

    def clear(self) -> None:
        if ask(self, "Очистить журнал?", "Удалить историю действий? Сами изменения на компьютере не откатываются.", confirm="Очистить", danger=True):
            clear_history()
            self.refresh()
