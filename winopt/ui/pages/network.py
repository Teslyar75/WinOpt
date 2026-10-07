"""Сеть: скорость в реальном времени и активные подключения программ."""

from __future__ import annotations

import time

import customtkinter as ctk

from winopt.network import collect_connections
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import Card, DataTable, LineChart, PageHeader, StatTile, button
from winopt.winutil import format_rate, format_size

STATUS_RU = {"ESTABLISHED": "установлено", "TIME_WAIT": "закрывается", "CLOSE_WAIT": "ожидает закрытия", "SYN_SENT": "подключается", "LISTEN": "слушает"}


class NetworkPage(Page):
    def build(self) -> None:
        self._last = 0.0
        self._conns = []
        header = PageHeader(self, "Сеть", "Скорость интернета сейчас и какие программы подключены к сети.", "network")
        header.pack(fill="x", pady=(0, 14))

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        chart_card = Card(top, "Трафик за 90 секунд")
        chart_card.pack(side="left", fill="both", expand=True, padx=(0, 12))
        for text, color in (("загрузка", T.GREEN), ("отдача", T.PINK)):
            ctk.CTkLabel(chart_card.header_right, text=f"●  {text}", text_color=color, font=T.font(12, "bold")).pack(side="left", padx=8)
        self.chart = LineChart(chart_card.body, height=150, max_value=None, fmt=format_rate)
        self.chart.pack(fill="both", expand=True)
        tiles = ctk.CTkFrame(top, fg_color="transparent", width=260)
        tiles.pack(side="left", fill="y")
        self.t_down = StatTile(tiles, "загрузка сейчас", color=T.GREEN)
        self.t_up = StatTile(tiles, "отдача сейчас", color=T.PINK)
        self.t_conn = StatTile(tiles, "внешних подключений", color=T.ACCENT)
        for t in (self.t_down, self.t_up, self.t_conn):
            t.pack(fill="x", pady=(0, 8))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 10))
        button(bar, "↻  Обновить", self.refresh).pack(side="left")
        self.external = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(bar, text="Только интернет (внешние адреса)", variable=self.external, command=self._render, progress_color=T.ACCENT, font=T.font(12), text_color=T.MUTED).pack(side="left", padx=14)
        self.note = ctk.CTkLabel(bar, text="", text_color=T.DIM, font=T.font(12))
        self.note.pack(side="right")
        self.table = DataTable(self, [("proc", "Программа", 220, "w", True), ("pid", "PID", 70, "e", False), ("remote", "Удалённый адрес", 240, "w", False),
                                      ("local", "Локальный адрес", 200, "w", False), ("status", "Состояние", 140, "w", False), ("type", "Тип", 100, "w", False)], height=12)
        self.table.pack(fill="both", expand=True)

    def on_show(self) -> None:
        self.refresh()

    def on_tick(self, snap) -> None:
        s = self.app.sampler
        self.chart.set_series([(list(s.down), T.GREEN), (list(s.up), T.PINK)])
        self.t_down.set(format_rate(snap.net_down))
        self.t_up.set(format_rate(snap.net_up))
        if time.monotonic() - self._last > 10:
            self.refresh()

    def refresh(self) -> None:
        if self.app.is_running("net"):
            return
        self._last = time.monotonic()
        self.app.run_task("net", lambda _c: collect_connections(), self._loaded, on_err=lambda e: self.note.configure(text=str(e)), busy="Читаю подключения…")

    def _loaded(self, conns) -> None:
        self._conns = conns
        self._render()
        try:
            import psutil

            io = psutil.net_io_counters()
            self.note.configure(text=f"С момента включения: получено {format_size(io.bytes_recv)}, отправлено {format_size(io.bytes_sent)}")
        except Exception:
            pass

    def _render(self) -> None:
        conns = [c for c in self._conns if c.external] if self.external.get() else self._conns
        self.t_conn.set(str(sum(1 for c in self._conns if c.external)))
        rows = [{
            "iid": f"n{n}",
            "values": [c.process_name, c.pid, c.remote, c.local, STATUS_RU.get(c.status, c.status.lower()), "интернет" if c.external else "локальная сеть"],
            "sort": [c.process_name.casefold(), c.pid, c.remote, c.local, c.status, c.external],
            "tags": ["accent"] if c.external else ["muted"],
        } for n, c in enumerate(conns)]
        self.table.set_rows(rows, "Подключений нет")
