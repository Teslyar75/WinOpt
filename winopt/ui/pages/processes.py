"""Процессы: живая таблица с поиском и безопасным завершением программ пользователя."""

from __future__ import annotations

import time

import customtkinter as ctk

from winopt.history import log_action
from winopt.processes import ProcessMonitor, terminate_process
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import DataTable, PageHeader, StatTile, ask, button, inform, short
from winopt.winutil import format_size, reveal_in_explorer


class ProcessesPage(Page):
    def build(self) -> None:
        self.monitor = ProcessMonitor()
        self.rows = {}
        self._last = 0.0

        header = PageHeader(self, "Процессы", "Обновляется каждые 3 секунды. Системные процессы Windows завершить нельзя — это защита от ошибок.", "processes")
        header.pack(fill="x", pady=(0, 14))

        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.pack(fill="x", pady=(0, 12))
        self.t_count = StatTile(tiles, "процессов")
        self.t_cpu = StatTile(tiles, "загрузка CPU", color=T.ACCENT)
        self.t_ram = StatTile(tiles, "занято памяти", color=T.VIOLET)
        self.t_top = StatTile(tiles, "самый «тяжёлый»", color=T.AMBER)
        for t in (self.t_count, self.t_cpu, self.t_ram, self.t_top):
            t.pack(side="left", fill="x", expand=True, padx=(0, 10))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 10))
        self.search = ctk.CTkEntry(bar, placeholder_text="Поиск по имени…", width=260, height=34, fg_color=T.CARD, border_color=T.BORDER, text_color=T.TEXT, font=T.font(13))
        self.search.pack(side="left")
        self.search.bind("<KeyRelease>", lambda _e: self._render())
        self.mode = ctk.CTkSegmentedButton(bar, values=["Все", "Мои программы", "Тяжёлые"], command=lambda _v: self._render(),
                                           selected_color=T.ACCENT_DARK, selected_hover_color=T.ACCENT_DARK, unselected_color=T.CARD,
                                           unselected_hover_color=T.CARD_HI, fg_color=T.CARD, font=T.font(12), height=34)
        self.mode.set("Все")
        self.mode.pack(side="left", padx=12)
        button(bar, "Завершить процесс…", self.kill, kind="danger").pack(side="right")
        button(bar, "Открыть расположение", self.reveal).pack(side="right", padx=8)
        self.group_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(bar, text="Группировать", variable=self.group_var, command=self._render, progress_color=T.ACCENT, font=T.font(12), text_color=T.MUTED).pack(side="right", padx=12)

        self.table = DataTable(
            self,
            [
                ("name", "Имя", 240, "w", True),
                ("cpu", "CPU", 80, "e", False),
                ("mem", "Память", 110, "e", False),
                ("count", "Шт.", 50, "center", False),
                ("pid", "PID", 70, "e", False),
                ("user", "Пользователь", 130, "w", False),
                ("path", "Путь", 360, "w", True),
            ],
            height=16,
        )
        self.table.pack(fill="both", expand=True)
        self.table._sort_state = ("mem", True)

    def on_show(self) -> None:
        self._refresh()

    def on_tick(self, snap) -> None:
        self.t_cpu.set(f"{snap.cpu_percent:.0f}%", T.load_color(snap.cpu_percent))
        self.t_ram.set(f"{snap.ram_percent:.0f}%", label=f"занято памяти · {format_size(snap.ram_used)}")
        if time.monotonic() - self._last > 3:
            self._refresh()

    def _refresh(self) -> None:
        if self.app.is_running("procs"):
            return
        self._last = time.monotonic()
        self.app.run_task("procs", lambda _c: self.monitor.refresh(), self._loaded, on_err=lambda _e: None, busy="Обновляю список процессов…")

    def _loaded(self, rows) -> None:
        self._data = rows
        self._render()

    def _render(self) -> None:
        rows = getattr(self, "_data", [])
        q = self.search.get().strip().casefold()
        mode = self.mode.get()
        if q:
            rows = [r for r in rows if q in r.name.casefold()]
        if mode == "Мои программы":
            rows = [r for r in rows if self.monitor.can_terminate(r)[0]]
        self.rows = {}
        out = []
        if self.group_var.get():
            groups: dict[str, list] = {}
            for r in rows:
                groups.setdefault(r.name.casefold(), []).append(r)
            items = []
            for members in groups.values():
                main = max(members, key=lambda r: r.memory)
                cpu = sum(r.cpu for r in members)
                mem = sum(r.memory for r in members)
                items.append((main, cpu, mem, members))
        else:
            items = [(r, r.cpu, r.memory, [r]) for r in rows]
        if mode == "Тяжёлые":
            items = [i for i in items if i[2] >= 300 * 1024**2 or i[1] >= 10]
        self.t_count.set(str(len(getattr(self, "_data", []))))
        if items:
            heavy = max(items, key=lambda i: i[2])
            self.t_top.set(short(heavy[0].name, 22), label=f"самый «тяжёлый» · {format_size(heavy[2])}")
        for main, cpu, mem, members in items:
            iid = f"{main.pid}"
            count = len(members)
            self.rows[iid] = (main, members)
            ok, _reason = self.monitor.can_terminate(main)
            tags = []
            if cpu >= 25 or mem >= 1024**3:
                tags.append("warn")
            elif not ok:
                tags.append("muted")
            out.append(
                {
                    "iid": iid,
                    "values": [main.name, f"{cpu:.1f}%", format_size(mem), count, main.pid, main.username.split("\\")[-1] or "система", short(main.exe, 80)],
                    "sort": [main.name, cpu, mem, count, main.pid, main.username, main.exe],
                    "tags": tags,
                }
            )
        self.table.set_rows(out, "Нет процессов по фильтру")

    def _selected_rows(self):
        return [self.rows[i] for i in self.table.selected() if i in self.rows]

    def reveal(self) -> None:
        for row, _members in self._selected_rows()[:3]:
            if row.exe:
                reveal_in_explorer(row.exe)

    def kill(self) -> None:
        selected = self._selected_rows()
        if not selected:
            inform(self, "Ничего не выбрано", "Выделите процесс в таблице.", level="info")
            return
        allowed, blocked = [], []
        for _main, members in selected:
            for row in members:
                ok, reason = self.monitor.can_terminate(row)
                (allowed if ok else blocked).append((row, 1, reason))
        if len(blocked) > 1:
            seen = {}
            for r, c, reason in blocked:
                seen.setdefault(r.name, (r, c, reason))
            blocked = list(seen.values())
        if blocked:
            inform(self, "Нельзя завершить", "Эти процессы защищены:", [f"{r.name} — {reason}" for r, _c, reason in blocked], level="warn")
        if not allowed:
            return
        names = [f"{r.name} (PID {r.pid})" for r, _c, _x in allowed]
        if not ask(self, "Завершить процесс?", "Несохранённые данные в этих программах будут потеряны:", names, confirm="Завершить", danger=True,
                   note="Завершается только выбранный процесс, программа не удаляется."):
            return

        def work(_ctx):
            done, errors = [], []
            for row, _count, _x in allowed:
                try:
                    terminate_process(row)
                    done.append(row.name)
                    log_action("Процессы", f"Завершён «{row.name}»", f"PID {row.pid}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{row.name}: {exc}")
            return done, errors

        def finish(res) -> None:
            done, errors = res
            if errors:
                inform(self, "Не всё получилось", "Некоторые процессы не завершены:", errors, level="warn")
            self.app.set_status(f"Завершено процессов: {len(done)}")
            self._refresh()

        self.app.run_task("kill", work, finish, busy="Завершаю процесс…")
