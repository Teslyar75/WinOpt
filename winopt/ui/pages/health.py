"""Здоровье ПК: состояние дисков (SMART), износ батареи, сведения о системе."""

from __future__ import annotations

import customtkinter as ctk

from winopt.health import battery_health, battery_report_html, physical_disks
from winopt.system import system_info
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import Card, DataTable, PageHeader, RingGauge, button, inform
from winopt.winutil import format_duration, format_size, open_path


class HealthPage(Page):
    def build(self) -> None:
        header = PageHeader(self, "Здоровье ПК", "Состояние накопителей, износ батареи и характеристики компьютера.", "health")
        header.pack(fill="x", pady=(0, 14))

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        top.grid_columnconfigure(0, weight=2, uniform="h")
        top.grid_columnconfigure(1, weight=3, uniform="h")

        bcard = Card(top, "Батарея")
        bcard.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        row = ctk.CTkFrame(bcard.body, fg_color="transparent")
        row.pack(fill="x")
        self.batt_ring = RingGauge(row, size=150, thickness=12, color=T.GREEN)
        self.batt_ring.pack(side="left")
        self.batt_ring.set(0, "…", "здоровье")
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", padx=16, fill="both", expand=True)
        self.batt_lines = [ctk.CTkLabel(info, text="", font=T.font(13), text_color=T.MUTED, anchor="w", justify="left") for _ in range(5)]
        for lbl in self.batt_lines:
            lbl.pack(anchor="w", pady=1)
        button(bcard.body, "Подробный отчёт Windows о батарее", self.battery_report).pack(anchor="w", pady=(10, 0))

        scard = Card(top, "Компьютер")
        scard.grid(row=0, column=1, sticky="nsew")
        self.sys_grid = ctk.CTkFrame(scard.body, fg_color="transparent")
        self.sys_grid.pack(fill="both", expand=True)

        dcard = Card(self, "Накопители (SMART)", "данные Windows Storage; температура и износ доступны не на всех дисках")
        dcard.pack(fill="both", expand=True)
        button(dcard.header_right, "↻  Обновить", self.refresh_disks).pack(side="right")
        self.disk_note = ctk.CTkLabel(dcard.body, text="", text_color=T.MUTED, font=T.font(12), anchor="w")
        self.disk_note.pack(fill="x", pady=(0, 6))
        self.disks = DataTable(dcard.body, [("name", "Диск", 260, "w", True), ("type", "Тип", 70, "w", False), ("bus", "Шина", 80, "w", False), ("size", "Объём", 100, "e", False),
                                            ("health", "Состояние", 130, "w", False), ("temp", "Темп.", 70, "e", False), ("wear", "Износ", 70, "e", False),
                                            ("hours", "Наработка", 110, "e", False), ("errors", "Ошибки чт./зап.", 130, "e", False)], height=5)
        self.disks.pack(fill="both", expand=True)
        self._loaded = False

    def on_show(self) -> None:
        if not self._loaded:
            self._loaded = True
            self.refresh_disks()
            self.app.run_task("battery", lambda _c: battery_health(), self._show_battery, on_err=self._no_battery, busy="Читаю данные батареи…")
            self.app.run_task("sysinfo-h", lambda _c: system_info(), self._show_info, on_err=lambda _e: None, busy="Сведения о системе…")

    def on_tick(self, snap) -> None:
        if snap.battery_percent is not None:
            plug = "от сети" if snap.battery_plugged else "от батареи"
            left = f" · ≈{format_duration(snap.battery_secs_left)}" if snap.battery_secs_left else ""
            self.batt_lines[0].configure(text=f"Заряд: {snap.battery_percent:.0f}% — {plug}{left}", text_color=T.TEXT)
        if hasattr(self, "_uptime_lbl"):
            self._uptime_lbl.configure(text=format_duration(snap.uptime_seconds))

    def refresh_disks(self) -> None:
        self.app.run_task("smart", lambda _c: physical_disks(), self._show_disks, busy="Читаю состояние дисков…")

    def _show_disks(self, disks) -> None:
        rows = []
        missing = False
        for n, d in enumerate(disks):
            if d.temperature is None and d.wear is None:
                missing = True
            tag = {"ok": "ok", "warn": "warn", "danger": "danger"}[d.level]
            errs = "—" if d.read_errors is None and d.write_errors is None else f"{d.read_errors or 0} / {d.write_errors or 0}"
            rows.append({"iid": f"d{n}", "values": [d.name, d.media, d.bus, format_size(d.size_bytes), d.health_ru,
                                                   f"{d.temperature} °C" if d.temperature else "—", f"{d.wear}%" if d.wear is not None else "—",
                                                   f"{d.power_on_hours} ч" if d.power_on_hours else "—", errs],
                         "sort": [d.name, d.media, d.bus, d.size_bytes, d.health, d.temperature or 0, d.wear or 0, d.power_on_hours or 0, 0], "tags": [tag]})
        self.disks.set_rows(rows, "Диски не найдены")
        note = "«Износ» — процент израсходованного ресурса SSD (0% — новый). "
        if missing and not self.app.admin:
            note += "Температура и износ видны только при запуске от имени администратора."
        self.disk_note.configure(text=note)

    def _show_battery(self, batteries) -> None:
        if not batteries:
            self._no_battery(None)
            return
        b = batteries[0]
        h = b.health_percent
        color = T.GREEN if h >= 80 else (T.AMBER if h >= 60 else T.RED)
        self.batt_ring.set(h, f"{h:.0f}%", "здоровье", color)
        self.batt_lines[1].configure(text=f"Ёмкость сейчас: {b.full_mwh:,} мВт·ч".replace(",", " "))
        self.batt_lines[2].configure(text=f"Ёмкость новой: {b.design_mwh:,} мВт·ч".replace(",", " "))
        self.batt_lines[3].configure(text=f"Износ: {b.wear_percent:.0f}%" + (f" · циклов заряда: {b.cycle_count}" if b.cycle_count else ""), text_color=color)
        self.batt_lines[4].configure(text=f"{b.manufacturer} {b.name} {b.chemistry}".strip())

    def _no_battery(self, _exc) -> None:
        self.batt_ring.set(0, "—", "нет данных", T.DIM)
        self.batt_lines[1].configure(text="Батарея не найдена или данные недоступны.")

    def battery_report(self) -> None:
        def ok(path) -> None:
            open_path(path)
            self.app.set_status(f"Отчёт сохранён: {path}")

        self.app.run_task("battery-report", lambda _c: battery_report_html(), ok,
                          on_err=lambda e: inform(self, "Отчёт не создан", str(e), level="warn"), busy="Создаю отчёт о батарее…")

    def _show_info(self, info) -> None:
        for child in self.sys_grid.winfo_children():
            child.destroy()
        rows = [
            ("Система", info.os_name),
            ("Версия", info.os_build),
            ("Процессор", info.cpu_name),
            ("Ядра / потоки", f"{info.cores} / {info.threads}"),
            ("Память", format_size(info.ram_total)),
            ("Компьютер", f"{info.computer}  ·  пользователь {info.user}"),
            ("Работает без перезагрузки", "…"),
        ]
        self.sys_grid.grid_columnconfigure(1, weight=1)
        for r, (k, v) in enumerate(rows):
            ctk.CTkLabel(self.sys_grid, text=k, text_color=T.MUTED, font=T.font(13), anchor="w").grid(row=r, column=0, sticky="w", pady=3, padx=(0, 18))
            lbl = ctk.CTkLabel(self.sys_grid, text=v, text_color=T.TEXT, font=T.font(13, "bold"), anchor="w", justify="left", wraplength=480)
            lbl.grid(row=r, column=1, sticky="w", pady=3)
        self._uptime_lbl = lbl
