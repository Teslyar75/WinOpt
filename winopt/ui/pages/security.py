"""Безопасность: Защитник Windows, точка восстановления, проверка процессов."""

from __future__ import annotations

import customtkinter as ctk

from winopt.defender import get_defender_status, open_windows_security, start_quick_scan
from winopt.heuristics import score_level
from winopt.history import log_action
from winopt.processes import iter_processes
from winopt.restore import create_restore_point
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import Card, DataTable, PageHeader, Pill, ask, button, inform, short
from winopt.winutil import launch


class SecurityPage(Page):
    def build(self) -> None:
        self.procs = {}
        header = PageHeader(self, "Безопасность", "Состояние встроенной защиты и эвристическая проверка процессов. Это не антивирус.", "security")
        header.pack(fill="x", pady=(0, 14))

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        top.grid_columnconfigure((0, 1), weight=1, uniform="s")

        dcard = Card(top, "Защитник Windows")
        dcard.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.def_title = ctk.CTkLabel(dcard.body, text="Проверяю…", font=T.font(20, "bold"), text_color=T.TEXT, anchor="w")
        self.def_title.pack(anchor="w")
        pills = ctk.CTkFrame(dcard.body, fg_color="transparent")
        pills.pack(anchor="w", pady=8)
        self.p_av = Pill(pills, "Антивирус: —", T.MUTED)
        self.p_rt = Pill(pills, "Защита в реальном времени: —", T.MUTED)
        self.p_av.pack(side="left", padx=(0, 6))
        self.p_rt.pack(side="left")
        self.def_scan = ctk.CTkLabel(dcard.body, text="", font=T.font(12), text_color=T.MUTED, anchor="w", justify="left")
        self.def_scan.pack(anchor="w")
        row = ctk.CTkFrame(dcard.body, fg_color="transparent")
        row.pack(anchor="w", pady=(10, 0))
        button(row, "Быстрая проверка…", self.quick_scan, kind="primary").pack(side="left")
        button(row, "Открыть «Безопасность Windows»", open_windows_security).pack(side="left", padx=8)
        button(row, "↻", self.refresh_defender, kind="ghost", width=36).pack(side="left")

        rcard = Card(top, "Точка восстановления")
        rcard.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(rcard.body, text="Снимок системных настроек, к которому можно откатиться, если после изменений что-то сломалось.",
                     font=T.font(13), text_color=T.TEXT, anchor="w", justify="left", wraplength=440).pack(anchor="w")
        ctk.CTkSwitch(rcard.body, text="Создавать перед изменениями автозагрузки и служб", variable=self.app.restore_before,
                      progress_color=T.ACCENT, font=T.font(12), text_color=T.MUTED).pack(anchor="w", pady=10)
        if not self.app.admin:
            ctk.CTkLabel(rcard.body, text="Создание точки требует прав администратора.", font=T.font(12), text_color=T.AMBER, anchor="w").pack(anchor="w")
        row = ctk.CTkFrame(rcard.body, fg_color="transparent")
        row.pack(anchor="w", pady=(6, 0))
        button(row, "Создать точку сейчас…", self.create_point, kind="secondary").pack(side="left")
        button(row, "Откатить систему…", lambda: launch("rstrui.exe"), kind="ghost").pack(side="left", padx=8)

        pcard = Card(self, "Проверка запущенных процессов", "подписи файлов, подозрительные пути, подделки системных имён")
        pcard.pack(fill="both", expand=True)
        self.scan_btn = button(pcard.header_right, "Проверить процессы", self.scan_processes, kind="primary")
        self.scan_btn.pack(side="right")
        self.scan_info = ctk.CTkLabel(pcard.body, text="Проверка занимает 20–60 секунд. Высокий балл — повод присмотреться, а не доказательство вируса.",
                                      text_color=T.MUTED, font=T.font(12), anchor="w")
        self.scan_info.pack(fill="x", pady=(0, 8))
        self.table = DataTable(pcard.body, [("score", "Балл", 60, "e", False), ("level", "Уровень", 120, "w", False), ("name", "Процесс", 200, "w", False),
                                            ("pid", "PID", 70, "e", False), ("why", "Причины", 420, "w", True), ("path", "Путь", 320, "w", True)], height=8)
        self.table.pack(fill="both", expand=True)

    def on_show(self) -> None:
        status = self.app.analysis.get("defender")
        if status:
            self._show_defender(status)
        else:
            self.refresh_defender()

    def refresh_defender(self) -> None:
        self.app.run_task("defender", lambda _c: get_defender_status(), self._show_defender,
                          on_err=lambda e: self.def_title.configure(text=f"Статус недоступен: {short(str(e), 80)}", text_color=T.AMBER), busy="Читаю статус Защитника…")

    def _show_defender(self, st) -> None:
        self.def_title.configure(text="Защита включена" if st.ok else "Защита выключена!", text_color=T.GREEN if st.ok else T.RED)
        self.p_av.set("Антивирус: " + ("вкл" if st.antivirus_enabled else "выкл"), T.GREEN if st.antivirus_enabled else T.RED)
        self.p_rt.set("Реальное время: " + ("вкл" if st.realtime_enabled else "выкл"), T.GREEN if st.realtime_enabled else T.RED)
        self.def_scan.configure(text=f"Быстрая проверка: {_age(st.quick_scan_age_hours)}   ·   Полная проверка: {_age(st.full_scan_age_hours)}")
        self.app.analysis["defender_ok"] = st.ok

    def quick_scan(self) -> None:
        if not ask(self, "Быстрая проверка", "Запустить быструю проверку Защитником Windows?", confirm="Запустить",
                   note="Проверка идёт в фоне 5–15 минут. Результат и найденные угрозы — в «Безопасность Windows»."):
            return
        try:
            start_quick_scan()
            log_action("Безопасность", "Запущена быстрая проверка Защитником")
            self.app.set_status("Быстрая проверка запущена в фоне")
        except Exception as exc:  # noqa: BLE001
            inform(self, "Не удалось запустить", str(exc), level="danger")

    def create_point(self) -> None:
        if not self.app.admin:
            inform(self, "Нужны права администратора", "Нажмите «Запустить от администратора» внизу бокового меню.", level="warn")
            return
        if not ask(self, "Точка восстановления", "Создать точку восстановления Windows сейчас?", confirm="Создать"):
            return

        def work(_ctx):
            create_restore_point("WinOpt — ручная точка восстановления")

        def ok(_r) -> None:
            log_action("Безопасность", "Создана точка восстановления")
            inform(self, "Готово", "Точка восстановления создана.", note="Откат: кнопка «Откатить систему…» или Параметры → Система → Восстановление.")

        self.app.run_task("restore", work, ok, busy="Создаю точку восстановления…")

    def scan_processes(self) -> None:
        self.scan_info.configure(text="Проверяю подписи и пути процессов…")
        self.app.run_task("proc-scan", lambda _c: iter_processes(with_meta=True), self._show_scan, busy="Проверяю процессы…")

    def _show_scan(self, procs) -> None:
        flagged = [p for p in procs if p.score >= 25]
        rows = []
        for n, p in enumerate(flagged[:60]):
            level = score_level(p.score)
            tag = "danger" if p.score >= 60 else "warn"
            rows.append({"iid": f"p{n}", "values": [p.score, level, p.name, p.pid, "; ".join(f.message for f in p.findings), short(p.exe, 80)],
                         "sort": [p.score, p.score, p.name, p.pid, "", p.exe], "tags": [tag]})
        self.table.set_rows(rows, "Подозрительных процессов не найдено ✓")
        self.scan_info.configure(text=f"Проверено процессов: {len(procs)}. Требуют внимания: {len(flagged)}. Для лечения используйте Защитник Windows.",
                                 text_color=T.AMBER if flagged else T.GREEN)


def _age(hours: int) -> str:
    if hours <= 0:
        return "недавно / нет данных"
    if hours < 24:
        return f"{hours} ч назад"
    return f"{hours // 24} дн назад"
