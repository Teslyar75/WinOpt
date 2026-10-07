"""Панель: живые показатели, графики, оценка состояния и рекомендации."""

from __future__ import annotations

import time

import customtkinter as ctk

from winopt.disk import list_drives
from winopt.processes import ProcessMonitor
from winopt.system import assess_health, system_info
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import Card, HBar, LineChart, PageHeader, RingGauge, button, short
from winopt.winutil import format_duration, format_rate, format_size


class _KV:
    """Пара «подпись / значение» в карточке индикатора."""

    def __init__(self, master) -> None:
        box = ctk.CTkFrame(master, fg_color="transparent")
        box.pack(fill="x", pady=(0, 3))
        self.key = ctk.CTkLabel(box, text="", text_color=T.DIM, font=T.font(10), anchor="w", height=13)
        self.key.pack(fill="x")
        self.val = ctk.CTkLabel(box, text="—", text_color=T.TEXT, font=T.font(12, "bold"), anchor="w", height=17)
        self.val.pack(fill="x")

    def configure(self, text: str = "", text_color: str | None = None) -> None:
        key, _sep, val = text.partition("  ")
        self.key.configure(text=key.upper())
        self.val.configure(text=val or "—")
        if text_color:
            self.val.configure(text_color=text_color)


class DashboardPage(Page):
    def build(self) -> None:
        self._monitor = ProcessMonitor()
        self._last_procs = 0.0
        self._last_disks = 0.0
        self._disks = []
        self._info = None

        header = PageHeader(self, "Панель управления", "Состояние компьютера в реальном времени", "dashboard")
        header.pack(fill="x", pady=(0, 12))
        self.header = header
        button(header.right, f"{T.icon('optimize')}  Быстрая оптимизация" if not T.ICON_FAMILY else "⚡  Быстрая оптимизация",
               lambda: self.app.show("optimize"), kind="primary", height=40, width=210).pack(side="right")

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        for col in range(4):
            grid.grid_columnconfigure(col, weight=1, uniform="col")
        # ряд с графиком имеет естественную высоту, нижний ряд забирает остаток
        grid.grid_rowconfigure(2, weight=1)

        # --- Ряд 1: кольцевые индикаторы ---
        self.cpu_card, self.cpu_ring, self.cpu_lines = self._gauge_card(grid, "Процессор", T.ACCENT, 0)
        self.ram_card, self.ram_ring, self.ram_lines = self._gauge_card(grid, "Память", T.VIOLET, 1)
        self.disk_card, self.disk_ring, self.disk_lines = self._gauge_card(grid, "Системный диск", T.BLUE, 2)
        self.health_card, self.health_ring, self.health_lines = self._gauge_card(grid, "Индекс здоровья", T.GREEN, 3)
        self.health_ring.set(0, "…", "анализ")

        # --- Ряд 2: график + сеть ---
        chart_card = Card(grid, "Нагрузка за 90 секунд")
        chart_card.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=(0, 12), pady=(0, 12))
        legend = chart_card.header_right
        for text, color in (("CPU", T.ACCENT), ("RAM", T.VIOLET)):
            ctk.CTkLabel(legend, text=f"●  {text}", text_color=color, font=T.font(12, "bold")).pack(side="left", padx=8)
        self.chart = LineChart(chart_card.body, height=112)
        self.chart.pack(fill="both", expand=True)

        net_card = Card(grid, "Сеть и диск")
        net_card.grid(row=1, column=3, sticky="nsew", pady=(0, 12))
        rates = ctk.CTkFrame(net_card.body, fg_color="transparent")
        rates.pack(fill="x")
        self.down_lbl = self._rate(rates, "↓ Загрузка", T.GREEN)
        self.up_lbl = self._rate(rates, "↑ Отдача", T.PINK)
        self.net_chart = LineChart(net_card.body, height=52, max_value=None, fmt=format_rate, grid_labels=False)
        self.net_chart.pack(fill="both", expand=True, pady=(6, 4))
        self.diskio_lbl = ctk.CTkLabel(net_card.body, text="Диск: —", text_color=T.MUTED, font=T.font(12), anchor="w")
        self.diskio_lbl.pack(fill="x")

        # --- Ряд 3: рекомендации + процессы/диски ---
        rec_card = Card(grid, "Рекомендации", "что стоит сделать сейчас")
        rec_card.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=(0, 12))
        self.rec_host = ctk.CTkFrame(rec_card.body, fg_color="transparent")
        self.rec_host.pack(fill="both", expand=True)
        ctk.CTkLabel(self.rec_host, text="Анализирую систему…", text_color=T.MUTED, font=T.font(13)).pack(anchor="w")

        top_card = Card(grid, "Топ по памяти")
        top_card.grid(row=2, column=2, sticky="nsew", padx=(0, 12))
        self.top_rows = []
        for _ in range(5):
            row = ctk.CTkFrame(top_card.body, fg_color="transparent")
            row.pack(fill="x", pady=(0, 4))
            line = ctk.CTkFrame(row, fg_color="transparent")
            line.pack(fill="x")
            val = ctk.CTkLabel(line, text="", text_color=T.MUTED, font=T.font(11), anchor="e", height=18)
            val.pack(side="right")
            name = ctk.CTkLabel(line, text="—", text_color=T.TEXT, font=T.font(12), anchor="w", height=18)
            name.pack(side="left", fill="x", expand=True)
            bar = HBar(row, height=4, color=T.VIOLET)
            bar.pack(fill="x", pady=(1, 0))
            self.top_rows.append((name, bar, val))
        button(top_card.body, "Все процессы →", lambda: self.app.show("processes"), kind="ghost", height=26).pack(anchor="e", pady=(6, 0))

        drives_card = Card(grid, "Диски")
        drives_card.grid(row=2, column=3, sticky="nsew")
        self.drives_host = drives_card.body

        self.app.on_analysis(lambda _a: self._update_health())
        self.after(100, self._load_info)

    # --- построение ---
    def _gauge_card(self, grid, title, color, col):
        card = Card(grid, title, pad=14)
        card.grid(row=0, column=col, sticky="nsew", padx=(0, 12) if col < 3 else 0, pady=(0, 12))
        inner = ctk.CTkFrame(card.body, fg_color="transparent")
        inner.pack(fill="both", expand=True)
        ring = RingGauge(inner, size=96, thickness=9, color=color)
        ring.pack(side="left")
        lines = ctk.CTkFrame(inner, fg_color="transparent")
        lines.pack(side="left", fill="both", expand=True, padx=(8, 0))
        labels = []
        for _ in range(3):
            labels.append(_KV(lines))
        return card, ring, labels

    def _rate(self, master, title, color):
        box = ctk.CTkFrame(master, fg_color="transparent")
        box.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(box, text=title, text_color=color, font=T.font(11, "bold"), anchor="w", height=16).pack(anchor="w")
        value = ctk.CTkLabel(box, text="—", text_color=T.TEXT, font=T.font(14, "bold"), anchor="w", height=22)
        value.pack(anchor="w")
        return value

    def _load_info(self) -> None:
        def work(_ctx):
            return system_info()

        def ok(info) -> None:
            self._info = info
            self.header.subtitle.configure(text=f"{info.os_name} · {info.os_build}   |   {info.cpu_name}   |   ОЗУ {format_size(info.ram_total)}")
            self.header.subtitle.pack(anchor="w", pady=(2, 0))

        self.app.run_task("sysinfo", work, ok, on_err=lambda _e: None, busy="Читаю сведения о системе…")

    # --- обновление ---
    def on_show(self) -> None:
        self._refresh_disks(force=True)
        self._update_health()

    def on_tick(self, snap) -> None:
        s = self.app.sampler
        self.cpu_ring.set(snap.cpu_percent, f"{snap.cpu_percent:.0f}%", "загрузка", T.load_color(snap.cpu_percent))
        freq = f"{snap.cpu_freq_mhz / 1000:.2f} ГГц" if snap.cpu_freq_mhz else "—"
        self.cpu_lines[0].configure(text=f"Частота  {freq}")
        self.cpu_lines[1].configure(text=f"Процессов  {snap.process_count}")
        self.cpu_lines[2].configure(text=f"Работает  {format_duration(snap.uptime_seconds)}")

        ram_color = T.RED if snap.ram_percent >= 88 else (T.AMBER if snap.ram_percent >= 75 else T.VIOLET)
        self.ram_ring.set(snap.ram_percent, f"{snap.ram_percent:.0f}%", "занято", ram_color)
        self.ram_lines[0].configure(text=f"Занято  {format_size(snap.ram_used)}")
        self.ram_lines[1].configure(text=f"Всего  {format_size(snap.ram_total)}")
        self.ram_lines[2].configure(text=f"Подкачка  {snap.swap_percent:.0f}%")

        self.chart.set_series([(list(s.ram), T.VIOLET), (list(s.cpu), T.ACCENT)])
        self.down_lbl.configure(text=format_rate(snap.net_down))
        self.up_lbl.configure(text=format_rate(snap.net_up))
        self.net_chart.set_series([(list(s.down), T.GREEN), (list(s.up), T.PINK)])
        self.diskio_lbl.configure(text=f"Диск: чтение {format_rate(snap.disk_read)} · запись {format_rate(snap.disk_write)}")
        if snap.battery_percent is not None:
            plug = "сеть" if snap.battery_plugged else "батарея"
            self.cpu_lines[2].configure(text=f"Батарея  {snap.battery_percent:.0f}% · {plug}")

        now = time.monotonic()
        if now - self._last_procs > 3 and not self.app.is_running("dash-procs"):
            self._last_procs = now
            self.app.run_task("dash-procs", lambda _c: self._monitor.refresh(), self._show_top, on_err=lambda _e: None, busy="Обновляю процессы…")
        self._refresh_disks()

    def _show_top(self, rows) -> None:
        groups: dict[str, int] = {}
        for r in rows:
            groups[r.name] = groups.get(r.name, 0) + r.memory
        top = sorted(groups.items(), key=lambda kv: kv[1], reverse=True)[:5]
        peak = top[0][1] if top else 1
        for (name, bar, val), item in zip(self.top_rows, top + [("", 0)] * 5):
            pname, mem = item
            name.configure(text=short(pname, 28) or "—")
            bar.set(mem / peak if peak else 0)
            val.configure(text=format_size(mem) if mem else "")

    def _refresh_disks(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_disks < 15:
            return
        self._last_disks = now
        try:
            self._disks = list_drives()
        except Exception:
            return
        for child in self.drives_host.winfo_children():
            child.destroy()
        for d in self._disks[:4]:
            row = ctk.CTkFrame(self.drives_host, fg_color="transparent")
            row.pack(fill="x", pady=4)
            top = ctk.CTkFrame(row, fg_color="transparent")
            top.pack(fill="x")
            name = f"{d.drive} {d.label}".strip()
            ctk.CTkLabel(top, text=name, text_color=T.TEXT, font=T.font(13, "bold"), anchor="w").pack(side="left")
            free_pct = 100 - d.used_percent
            color = T.RED if free_pct < 10 else (T.AMBER if free_pct < 20 else T.BLUE)
            ctk.CTkLabel(top, text=f"своб. {format_size(d.free_bytes)}", text_color=color, font=T.font(12), anchor="e").pack(side="right")
            bar = HBar(row, height=8, color=color)
            bar.pack(fill="x", pady=(2, 0))
            bar.set(d.used_percent / 100)
            ctk.CTkLabel(row, text=f"{d.used_percent:.0f}% из {format_size(d.total_bytes)}", text_color=T.DIM, font=T.font(11), anchor="w", height=14).pack(fill="x")
        sys_disk = self._disks[0] if self._disks else None
        if sys_disk:
            free_pct = 100 - sys_disk.used_percent
            color = T.RED if free_pct < 10 else (T.AMBER if free_pct < 20 else T.BLUE)
            self.disk_ring.set(sys_disk.used_percent, f"{sys_disk.used_percent:.0f}%", "занято", color)
            self.disk_lines[0].configure(text=f"Диск  {sys_disk.drive}")
            self.disk_lines[1].configure(text=f"Свободно  {format_size(sys_disk.free_bytes)}", text_color=color)
            self.disk_lines[2].configure(text=f"Всего  {format_size(sys_disk.total_bytes)}")

    def _update_health(self) -> None:
        a = self.app.analysis
        if a.get("startup_recommended") is None and a.get("junk_bytes") is None and a.get("defender_ok") is None:
            return
        disks = self._disks or list_drives()
        score, issues = assess_health(
            self.app.sampler.last, disks, a.get("startup_recommended"), a.get("defender_ok"), a.get("junk_bytes"),
            list(self.app.sampler.ram),
        )
        color = T.level_color(score)
        word = "отлично" if score >= 85 else ("хорошо" if score >= 70 else ("внимание" if score >= 50 else "плохо"))
        self.health_ring.set(score, str(score), word, color)
        problems = [i for i in issues if i.level in ("warn", "danger")]
        self.health_lines[0].configure(text=f"Проблем  {len(problems)}", text_color=T.RED if problems else T.GREEN)
        defender = a.get("defender_ok")
        self.health_lines[1].configure(text="Защитник  " + ("включён" if defender else ("выключен" if defender is False else "—")),
                                       text_color=T.GREEN if defender else (T.RED if defender is False else T.MUTED))
        junk = a.get("junk_bytes")
        self.health_lines[2].configure(text=f"Мусор  {format_size(junk) if junk is not None else '—'}")

        for child in self.rec_host.winfo_children():
            child.destroy()
        for issue in issues[:4]:
            col = T.LEVEL_COLORS.get(issue.level, T.BLUE)
            row = ctk.CTkFrame(self.rec_host, fg_color=T.CARD_HI, corner_radius=10)
            row.pack(fill="x", pady=3)
            ctk.CTkFrame(row, width=4, height=1, fg_color=col, corner_radius=2).pack(side="left", fill="y", padx=(0, 10), pady=6)
            text = ctk.CTkFrame(row, fg_color="transparent")
            text.pack(side="left", fill="x", expand=True, pady=5)
            ctk.CTkLabel(text, text=issue.title, text_color=T.TEXT, font=T.font(12, "bold"), anchor="w", height=17).pack(fill="x")
            ctk.CTkLabel(text, text=issue.text, text_color=T.MUTED, font=T.font(12), anchor="w", justify="left", wraplength=420, height=16).pack(fill="x")
            if issue.page:
                button(row, "Исправить →", lambda p=issue.page: self.app.show(p), kind="ghost", height=28, width=110, text_color=col).pack(side="right", padx=8)
