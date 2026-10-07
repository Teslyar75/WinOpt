"""Очистка: временные файлы, кэши браузеров, дампы, корзина — с предпросмотром размера."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from winopt.cleanup import clean_categories, scan_categories
from winopt.disk import list_drives
from winopt.history import log_action
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import Card, HBar, PageHeader, ask, button, inform
from winopt.winutil import format_size, launch

GROUP_TITLES = {"system": "Система", "browser": "Браузеры", "other": "Прочее"}


class CleanupPage(Page):
    def build(self) -> None:
        self.scans = []
        self.vars: dict[str, tk.BooleanVar] = {}
        header = PageHeader(self, "Очистка", "Перед удалением показывается, сколько места освободится. Занятые файлы и файлы младше суток не трогаются.", "cleanup")
        header.pack(fill="x", pady=(0, 14))

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        total_card = Card(top)
        total_card.pack(side="left", fill="both", expand=True, padx=(0, 12))
        ctk.CTkLabel(total_card.body, text="ВЫБРАНО К ОЧИСТКЕ", font=T.font(11, "bold"), text_color=T.MUTED, anchor="w").pack(anchor="w")
        self.total_lbl = ctk.CTkLabel(total_card.body, text="—", font=T.font(34, "bold"), text_color=T.ACCENT, anchor="w")
        self.total_lbl.pack(anchor="w")
        self.found_lbl = ctk.CTkLabel(total_card.body, text="Нажмите «Сканировать»", font=T.font(12), text_color=T.MUTED, anchor="w")
        self.found_lbl.pack(anchor="w")

        disk_card = Card(top)
        disk_card.pack(side="left", fill="both", expand=True, padx=(0, 12))
        ctk.CTkLabel(disk_card.body, text="СИСТЕМНЫЙ ДИСК", font=T.font(11, "bold"), text_color=T.MUTED, anchor="w").pack(anchor="w")
        self.disk_lbl = ctk.CTkLabel(disk_card.body, text="—", font=T.font(20, "bold"), text_color=T.TEXT, anchor="w")
        self.disk_lbl.pack(anchor="w", pady=(4, 6))
        self.disk_bar = HBar(disk_card.body, height=10, color=T.BLUE)
        self.disk_bar.pack(fill="x")
        self.disk_after = ctk.CTkLabel(disk_card.body, text="", font=T.font(12), text_color=T.MUTED, anchor="w")
        self.disk_after.pack(anchor="w", pady=(4, 0))

        actions = Card(top)
        actions.pack(side="left", fill="both")
        button(actions.body, "↻  Сканировать", self.scan, width=220).pack(fill="x", pady=(0, 6))
        button(actions.body, "Очистить выбранное…", self.clean, kind="primary", width=220, height=40).pack(fill="x", pady=(0, 6))
        tools = ctk.CTkFrame(actions.body, fg_color="transparent")
        tools.pack(fill="x")
        button(tools, "Очистка диска", lambda: launch("cleanmgr.exe"), kind="ghost", height=28).pack(side="left", expand=True, fill="x")
        button(tools, "Контроль памяти", lambda: launch("ms-settings:storagesense"), kind="ghost", height=28).pack(side="left", expand=True, fill="x")

        self.list_card = Card(self, "Категории")
        self.list_card.pack(fill="both", expand=True)
        self.rows_host = ctk.CTkScrollableFrame(self.list_card.body, fg_color="transparent", scrollbar_button_color=T.BORDER)
        self.rows_host.pack(fill="both", expand=True)
        self.app.on_analysis(self._from_analysis)

    def _from_analysis(self, analysis) -> None:
        if analysis.get("cleanup_scans") and not self.scans:
            self._render(analysis["cleanup_scans"])

    def on_show(self) -> None:
        self._update_disk()
        cached = self.app.analysis.get("cleanup_scans")
        if cached and not self.scans:
            self._render(cached)
        elif not self.scans:
            self.scan()

    def _update_disk(self, freed: int = 0) -> None:
        drives = list_drives()
        if not drives:
            return
        d = drives[0]
        free_pct = 100 - d.used_percent
        color = T.RED if free_pct < 10 else (T.AMBER if free_pct < 20 else T.BLUE)
        self.disk_lbl.configure(text=f"{d.drive}  свободно {format_size(d.free_bytes)} из {format_size(d.total_bytes)}", text_color=color)
        self.disk_bar.set(d.used_percent / 100, color)
        self._disk = d

    def scan(self) -> None:
        self.found_lbl.configure(text="Сканирую…")
        self.app.run_task("cleanup-scan", lambda ctx: scan_categories(progress=ctx.progress), self._render, busy="Сканирую временные файлы…")

    def _render(self, scans) -> None:
        self.scans = scans
        for child in self.rows_host.winfo_children():
            child.destroy()
        self.vars.clear()
        peak = max([s.size_bytes for s in scans] + [1])
        group = None
        for scan in scans:
            if scan.group != group:
                group = scan.group
                ctk.CTkLabel(self.rows_host, text=GROUP_TITLES.get(group, group).upper(), font=T.font(11, "bold"), text_color=T.DIM, anchor="w").pack(fill="x", pady=(10, 2), padx=4)
            blocked = bool(scan.blocked_reason)
            empty = scan.size_bytes == 0
            var = tk.BooleanVar(value=scan.default_selected and not blocked and not empty)
            self.vars[scan.category_id] = var
            row = ctk.CTkFrame(self.rows_host, fg_color=T.CARD_HI, corner_radius=12)
            row.pack(fill="x", pady=3, padx=(0, 6))
            cb = ctk.CTkCheckBox(row, text="", variable=var, width=24, command=self._update_total, fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER, border_color=T.DIM, checkmark_color="#04131A")
            cb.pack(side="left", padx=(14, 6), pady=10)
            if blocked or empty:
                cb.configure(state="disabled")
            mid = ctk.CTkFrame(row, fg_color="transparent")
            mid.pack(side="left", fill="x", expand=True, pady=8)
            danger = scan.category_id == "recycle_bin"
            ctk.CTkLabel(mid, text=scan.label, font=T.font(14, "bold"), text_color=T.TEXT if not (blocked or empty) else T.DIM, anchor="w").pack(fill="x")
            desc = scan.blocked_reason or scan.description
            ctk.CTkLabel(mid, text=desc, font=T.font(12), text_color=T.AMBER if (blocked or danger) else T.MUTED, anchor="w", justify="left", wraplength=640).pack(fill="x")
            bar = HBar(mid, height=5, bg=T.CARD_HI, color=T.RED if danger else T.ACCENT)
            bar.pack(fill="x", pady=(4, 0))
            bar.set(scan.size_bytes / peak)
            right = ctk.CTkFrame(row, fg_color="transparent")
            right.pack(side="right", padx=16)
            ctk.CTkLabel(right, text=format_size(scan.size_bytes), font=T.font(15, "bold"), text_color=T.ACCENT if not empty else T.DIM, anchor="e").pack(anchor="e")
            noun = "объектов" if danger else "файлов"
            ctk.CTkLabel(right, text=f"{scan.file_count} {noun}", font=T.font(11), text_color=T.DIM, anchor="e").pack(anchor="e")
        total = sum(s.size_bytes for s in scans)
        self.found_lbl.configure(text=f"Найдено всего: {format_size(total)}")
        self._update_total()

    def _selected(self) -> list[str]:
        return [cid for cid, var in self.vars.items() if var.get()]

    def _update_total(self) -> None:
        sizes = {s.category_id: s.size_bytes for s in self.scans}
        total = sum(sizes.get(c, 0) for c in self._selected())
        self.total_lbl.configure(text=format_size(total))
        if hasattr(self, "_disk"):
            self.disk_after.configure(text=f"После очистки будет свободно ≈ {format_size(self._disk.free_bytes + total)}")

    def clean(self) -> None:
        ids = self._selected()
        if not ids:
            inform(self, "Ничего не выбрано", "Отметьте категории для очистки (сначала нажмите «Сканировать»).", level="info")
            return
        by_id = {s.category_id: s for s in self.scans}
        items = [f"{by_id[c].label}: {format_size(by_id[c].size_bytes)}" for c in ids if c in by_id]
        recycle = "recycle_bin" in ids
        note = "Корзина будет очищена окончательно — восстановить файлы из неё будет нельзя." if recycle else "Пароли, история браузеров и ваши документы не затрагиваются."
        if not ask(self, "Очистить?", "Будут удалены:", items, confirm="Очистить", danger=recycle, note=note):
            return

        def work(ctx):
            return clean_categories(ids, progress=ctx.progress)

        def finish(result) -> None:
            log_action("Очистка", "Очистка временных файлов", f"{len(ids)} категорий, освобождено {format_size(result.freed_bytes)}, файлов {result.deleted_files}")
            lines = [f"Удалено файлов: {result.deleted_files}", f"Пропущено (заняты): {result.skipped_files}"]
            lines += [f"Пропущено: {c}" for c in result.skipped_categories]
            inform(self, "Очистка завершена", f"Освобождено {format_size(result.freed_bytes)}", lines, level="ok")
            self._update_disk()
            self.scan()

        self.app.run_task("cleanup-run", work, finish, busy="Удаляю временные файлы…")
