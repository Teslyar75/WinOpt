"""Быстрая оптимизация в один клик: анализ → подтверждение → очистка → отчёт."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from winopt.optimize import build_plan, run_plan
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import Card, HBar, PageHeader, RingGauge, ask, button
from winopt.winutil import format_size, open_path


class OptimizePage(Page):
    def build(self) -> None:
        self.plan = None
        self.vars: dict[str, tk.BooleanVar] = {}
        self.last_report = None

        header = PageHeader(
            self,
            "Быстрая оптимизация",
            "Безопасная очистка в один клик. Автозагрузка, службы и программы здесь не меняются — только советы.",
            "optimize",
        )
        header.pack(fill="x", pady=(0, 16))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        hero = Card(body, "Итог")
        hero.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.ring = RingGauge(hero.body, size=210, thickness=14, color=T.ACCENT)
        self.ring.pack(pady=(6, 10))
        self.ring.set(0, "—", "можно освободить")
        self.state_lbl = ctk.CTkLabel(hero.body, text="Нажмите «Анализировать»", font=T.font(15, "bold"), text_color=T.TEXT, wraplength=260)
        self.state_lbl.pack(pady=(0, 4))
        self.hint_lbl = ctk.CTkLabel(hero.body, text="", font=T.font(12), text_color=T.MUTED, wraplength=260, justify="center")
        self.hint_lbl.pack(pady=(0, 12))
        self.run_btn = button(hero.body, "⚡  Оптимизировать", self.run, kind="primary", height=46, width=240)
        self.run_btn.pack(pady=4)
        self.scan_btn = button(hero.body, "Анализировать заново", self.analyze, kind="secondary", height=34, width=240)
        self.scan_btn.pack(pady=4)
        self.report_btn = button(hero.body, "Открыть отчёт", self.open_report, kind="ghost", height=30, width=240)
        self.progress = ctk.CTkProgressBar(hero.body, width=240, height=6, progress_color=T.ACCENT, fg_color=T.GRID)
        self.progress.set(0)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        self.steps_card = Card(right, "Что будет очищено", "отметьте нужное — всё перечисленное безопасно")
        self.steps_card.pack(fill="both", expand=True)
        self.steps_host = ctk.CTkScrollableFrame(self.steps_card.body, fg_color="transparent", scrollbar_button_color=T.BORDER)
        self.steps_host.pack(fill="both", expand=True)

        self.advice_card = Card(right, "Советы (без автоматических изменений)")
        self.advice_card.pack(fill="x", pady=(14, 0))
        self.advice_host = self.advice_card.body

    def on_show(self) -> None:
        if self.plan is None and not self.app.is_running("optimize-plan"):
            self.analyze()

    def analyze(self) -> None:
        self.state_lbl.configure(text="Анализирую…")
        self.ring.set(0, "…", "анализ")

        def work(ctx):
            return build_plan(progress=ctx.progress)

        self.app.run_task("optimize-plan", work, self._show_plan, busy="Быстрая оптимизация: анализ…")

    def _show_plan(self, plan) -> None:
        self.plan = plan
        for child in self.steps_host.winfo_children():
            child.destroy()
        self.vars.clear()
        scans = plan.safe_scans
        peak = max([s.size_bytes for s in scans] + [1])
        if not scans:
            ctk.CTkLabel(self.steps_host, text="Чистить почти нечего — временных файлов мало.", text_color=T.GREEN, font=T.font(14)).pack(anchor="w", pady=8)
        for scan in scans:
            blocked = bool(scan.blocked_reason)
            var = tk.BooleanVar(value=not blocked)
            self.vars[scan.category_id] = var
            row = ctk.CTkFrame(self.steps_host, fg_color=T.CARD_HI, corner_radius=12)
            row.pack(fill="x", pady=4, padx=(0, 6))
            cb = ctk.CTkCheckBox(row, text="", variable=var, width=24, command=self._update_total, fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER, border_color=T.DIM, checkmark_color="#04131A")
            cb.pack(side="left", padx=(14, 6), pady=12)
            if blocked:
                cb.configure(state="disabled")
            mid = ctk.CTkFrame(row, fg_color="transparent")
            mid.pack(side="left", fill="x", expand=True, pady=8)
            ctk.CTkLabel(mid, text=scan.label, font=T.font(14, "bold"), text_color=T.TEXT if not blocked else T.DIM, anchor="w").pack(fill="x")
            ctk.CTkLabel(mid, text=scan.blocked_reason or scan.description, font=T.font(12), text_color=T.AMBER if blocked else T.MUTED, anchor="w", justify="left", wraplength=520).pack(fill="x")
            bar = HBar(mid, height=5, bg=T.CARD_HI, color=T.ACCENT if not blocked else T.DIM)
            bar.pack(fill="x", pady=(4, 0))
            bar.set(scan.size_bytes / peak)
            ctk.CTkLabel(row, text=format_size(scan.size_bytes), font=T.font(15, "bold"), text_color=T.ACCENT if not blocked else T.DIM, width=110, anchor="e").pack(side="right", padx=16)

        for child in self.advice_host.winfo_children():
            child.destroy()
        free = plan.system_free_bytes
        total = plan.system_total_bytes or 1
        pct = free / total * 100
        color = T.RED if pct < 10 else (T.AMBER if pct < 20 else T.GREEN)
        self._advice_row(f"Свободно на системном диске: {format_size(free)} ({pct:.0f}%)",
                         "Крупные папки и большие файлы можно найти на странице «Диски и файлы».", color, "disk")
        if plan.startup_recommended:
            names = ", ".join(plan.startup_recommended[:5]) + ("…" if len(plan.startup_recommended) > 5 else "")
            self._advice_row(f"Автозагрузка: можно отключить {len(plan.startup_recommended)}", names, T.AMBER, "startup")
        else:
            self._advice_row("Автозагрузка в порядке", "Лишних программ при старте не найдено.", T.GREEN, None)
        self._update_total()

    def _advice_row(self, title, text, color, page) -> None:
        row = ctk.CTkFrame(self.advice_host, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text="●", text_color=color, width=16).pack(side="left", padx=(0, 8))
        box = ctk.CTkFrame(row, fg_color="transparent")
        box.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(box, text=title, text_color=T.TEXT, font=T.font(13, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(box, text=text, text_color=T.MUTED, font=T.font(12), anchor="w", justify="left", wraplength=560).pack(fill="x")
        if page:
            button(row, "Открыть →", lambda: self.app.show(page), kind="ghost", width=100, height=28, text_color=color).pack(side="right")

    def _selected(self) -> list[str]:
        return [cid for cid, var in self.vars.items() if var.get()]

    def _update_total(self) -> None:
        if not self.plan:
            return
        sizes = {s.category_id: s.size_bytes for s in self.plan.safe_scans}
        total = sum(sizes.get(cid, 0) for cid in self._selected())
        total_all = max(self.plan.total_bytes, 1)
        self.ring.set(total / total_all * 100 if total else 0, format_size(total), "можно освободить", T.ACCENT)
        self.state_lbl.configure(text="Готово к оптимизации" if total else "Нечего очищать")
        self.hint_lbl.configure(text="Файлы младше 24 часов и занятые файлы не трогаются.")
        self.run_btn.configure(state="normal" if total else "disabled")

    def run(self) -> None:
        if not self.plan or self.app.is_running("optimize-run"):
            return
        ids = self._selected()
        if not ids:
            return
        scans = {s.category_id: s for s in self.plan.safe_scans}
        items = [f"{scans[c].label}: {format_size(scans[c].size_bytes)}" for c in ids if c in scans]
        if not ask(self, "Запустить оптимизацию?", "Будут удалены временные файлы и кэши:", items,
                   confirm="Оптимизировать", note="Пароли, история браузера, документы и программы не затрагиваются."):
            return
        self.run_btn.configure(state="disabled")
        self.progress.pack(pady=(10, 0))
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.state_lbl.configure(text="Оптимизирую…")

        def work(ctx):
            return run_plan(self.plan, ids, progress=ctx.progress)

        def done(res) -> None:
            result, report = res
            self.progress.stop()
            self.progress.pack_forget()
            self.last_report = report
            self.ring.set(100, format_size(result.freed_bytes), "освобождено", T.GREEN)
            self.state_lbl.configure(text="Готово!")
            extra = f"; пропущено: {', '.join(result.skipped_categories)}" if result.skipped_categories else ""
            self.hint_lbl.configure(text=f"Удалено файлов: {result.deleted_files}. Занятых пропущено: {result.skipped_files}{extra}.")
            self.report_btn.pack(pady=4)
            self.app.set_status(f"Оптимизация завершена: освобождено {format_size(result.freed_bytes)}")
            self.plan = None
            self.app.run_analysis()

        def fail(exc) -> None:
            self.progress.stop()
            self.progress.pack_forget()
            self.state_lbl.configure(text="Ошибка")
            self.hint_lbl.configure(text=str(exc))
            self.run_btn.configure(state="normal")

        self.app.run_task("optimize-run", work, done, fail, busy="Оптимизация…")

    def open_report(self) -> None:
        if self.last_report:
            open_path(self.last_report)
