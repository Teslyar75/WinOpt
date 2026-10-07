"""Диски и файлы: обзор дисков, крупные папки, большие файлы, дубликаты."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import customtkinter as ctk

from winopt.disk import default_large_file_roots, find_large_files, list_drives, scan_largest_folders
from winopt.duplicates import default_scan_roots, delete_files, scan_duplicates
from winopt.history import log_action
from winopt.recycle import send_to_recycle_bin
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import Card, DataTable, PageHeader, RingGauge, ask, button, inform, short, text_bar
from winopt.winutil import format_size, open_path, reveal_in_explorer

VIEWS = ["Обзор дисков", "Крупные папки", "Большие файлы", "Дубликаты"]


def _seg(master, values, command):
    seg = ctk.CTkSegmentedButton(master, values=values, command=command, selected_color=T.ACCENT_DARK, selected_hover_color=T.ACCENT_DARK,
                                 unselected_color=T.CARD, unselected_hover_color=T.CARD_HI, fg_color=T.CARD, font=T.font(13), height=36)
    return seg


class DiskPage(Page):
    def build(self) -> None:
        header = PageHeader(self, "Диски и файлы", "Что занимает место. Файлы удаляются только в Корзину и только после подтверждения.", "disk")
        header.pack(fill="x", pady=(0, 14))
        self.seg = _seg(self, VIEWS, self._switch)
        self.seg.pack(anchor="w", pady=(0, 12))
        self.host = ctk.CTkFrame(self, fg_color="transparent")
        self.host.pack(fill="both", expand=True)
        self.views = {
            "Обзор дисков": DrivesView(self.host, self),
            "Крупные папки": FoldersView(self.host, self),
            "Большие файлы": LargeFilesView(self.host, self),
            "Дубликаты": DuplicatesView(self.host, self),
        }
        self.seg.set(VIEWS[0])
        self._switch(VIEWS[0])

    def _switch(self, name: str) -> None:
        for view in self.views.values():
            view.pack_forget()
        self.views[name].pack(fill="both", expand=True)
        self.views[name].on_show()

    def on_show(self) -> None:
        self.views[self.seg.get()].on_show()


class DrivesView(ctk.CTkFrame):
    def __init__(self, master, page: DiskPage) -> None:
        super().__init__(master, fg_color="transparent")
        self.page = page
        self.grid_host = ctk.CTkFrame(self, fg_color="transparent")
        self.grid_host.pack(fill="both", expand=True)

    def on_show(self) -> None:
        for child in self.grid_host.winfo_children():
            child.destroy()
        drives = list_drives()
        for col in range(3):
            self.grid_host.grid_columnconfigure(col, weight=1, uniform="d")
        for n, d in enumerate(drives):
            card = Card(self.grid_host, f"Диск {d.drive}", f"{d.label or 'без метки'} · {d.fstype}")
            card.grid(row=n // 3, column=n % 3, sticky="nsew", padx=(0, 12), pady=(0, 12))
            free_pct = 100 - d.used_percent
            color = T.RED if free_pct < 10 else (T.AMBER if free_pct < 20 else T.BLUE)
            row = ctk.CTkFrame(card.body, fg_color="transparent")
            row.pack(fill="x")
            ring = RingGauge(row, size=120, thickness=10, color=color)
            ring.pack(side="left")
            ring.set(d.used_percent, f"{d.used_percent:.0f}%", "занято", color)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", padx=14, fill="x", expand=True)
            ctk.CTkLabel(info, text=format_size(d.free_bytes), font=T.font(22, "bold"), text_color=color, anchor="w").pack(anchor="w")
            ctk.CTkLabel(info, text="свободно", font=T.font(12), text_color=T.MUTED, anchor="w").pack(anchor="w")
            ctk.CTkLabel(info, text=f"Занято {format_size(d.used_bytes)}\nВсего {format_size(d.total_bytes)}", font=T.font(12), text_color=T.MUTED, anchor="w", justify="left").pack(anchor="w", pady=(6, 0))
            btns = ctk.CTkFrame(card.body, fg_color="transparent")
            btns.pack(fill="x", pady=(10, 0))
            button(btns, "Анализ папок", lambda dr=d.drive: self._analyze(dr), height=30).pack(side="left")
            button(btns, "Открыть", lambda dr=d.drive: open_path(dr + "\\"), kind="ghost", height=30).pack(side="left", padx=6)
            if free_pct < 15:
                ctk.CTkLabel(card.body, text="Мало места — начните с «Очистки».", font=T.font(12), text_color=T.AMBER, anchor="w", wraplength=240, justify="left").pack(fill="x", pady=(8, 0))

    def _analyze(self, drive: str) -> None:
        self.page.seg.set("Крупные папки")
        self.page._switch("Крупные папки")
        self.page.views["Крупные папки"].scan(drive)


class FoldersView(ctk.CTkFrame):
    def __init__(self, master, page: DiskPage) -> None:
        super().__init__(master, fg_color="transparent")
        self.page = page
        self.app = page.app
        self.items = {}
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 10))
        drives = [d.drive for d in list_drives()] or ["C:"]
        self.drive = ctk.CTkOptionMenu(bar, values=drives, width=90, height=34, fg_color=T.CARD_HI, button_color=T.CARD_HOVER, button_hover_color=T.BORDER, font=T.font(13))
        self.drive.set(drives[0])
        self.drive.pack(side="left")
        button(bar, "Сканировать", lambda: self.scan(self.drive.get()), kind="primary").pack(side="left", padx=8)
        button(bar, "Стоп", lambda: self.app.cancel_task("folders"), kind="ghost").pack(side="left")
        self.info = ctk.CTkLabel(bar, text="Профиль пользователя раскрыт подробнее (Загрузки, AppData\\Local\\…).", text_color=T.MUTED, font=T.font(12))
        self.info.pack(side="left", padx=12)
        button(bar, "Открыть в Проводнике", self.open_selected).pack(side="right")
        self.table = DataTable(self, [("path", "Папка", 460, "w", True), ("bar", "Доля", 160, "w", False), ("size", "Размер", 110, "e", False), ("files", "Файлов", 90, "e", False)],
                               height=16, on_double=lambda iid: self._open(iid))
        self.table.pack(fill="both", expand=True)

    def on_show(self) -> None:
        pass

    def scan(self, drive: str) -> None:
        self.drive.set(drive)
        self.info.configure(text="Сканирование может занять 1–3 минуты…")

        def work(ctx):
            return scan_largest_folders(drive + "\\", progress=ctx.progress, cancel=ctx.cancelled)

        self.app.run_task("folders", work, self._render, busy="Считаю размер папок…")

    def _render(self, items) -> None:
        peak = items[0].size_bytes if items else 1
        self.items = {f"f{n}": it for n, it in enumerate(items)}
        rows = []
        for iid, it in self.items.items():
            ratio = it.size_bytes / peak
            rows.append({
                "iid": iid,
                "values": [it.path + (" (неполный подсчёт)" if it.partial else ""), text_bar(ratio), format_size(it.size_bytes), f"{it.file_count:,}".replace(",", " ")],
                "sort": [it.path, it.size_bytes, it.size_bytes, it.file_count],
                "tags": ["warn"] if it.size_bytes > 10 * 1024**3 else [],
            })
        self.table.set_rows(rows, "Крупных папок не найдено")
        total = sum(i.size_bytes for i in items)
        self.info.configure(text=f"Найдено папок: {len(items)} · в сумме {format_size(total)}. Двойной щелчок — открыть папку.")

    def _open(self, iid) -> None:
        if iid in self.items:
            open_path(self.items[iid].path)

    def open_selected(self) -> None:
        for iid in self.table.selected()[:3]:
            self._open(iid)


class LargeFilesView(ctk.CTkFrame):
    def __init__(self, master, page: DiskPage) -> None:
        super().__init__(master, fg_color="transparent")
        self.page = page
        self.app = page.app
        self.items = {}
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(bar, text="Больше чем", text_color=T.MUTED, font=T.font(13)).pack(side="left")
        self.min = ctk.CTkOptionMenu(bar, values=["100 МБ", "250 МБ", "500 МБ", "1 ГБ"], width=100, height=34, fg_color=T.CARD_HI, button_color=T.CARD_HOVER, button_hover_color=T.BORDER, font=T.font(13))
        self.min.set("250 МБ")
        self.min.pack(side="left", padx=8)
        button(bar, "Найти", self.scan, kind="primary").pack(side="left")
        button(bar, "Стоп", lambda: self.app.cancel_task("largefiles"), kind="ghost").pack(side="left", padx=6)
        button(bar, "В корзину отмеченные…", self.recycle, kind="danger").pack(side="right")
        button(bar, "Показать в Проводнике", self.reveal).pack(side="right", padx=8)
        roots = ", ".join(str(p) for p in default_large_file_roots())
        self.info = ctk.CTkLabel(self, text=f"Где ищем: {roots}. Системные и программные папки (Windows, Program Files, AppData) пропускаются.",
                                 text_color=T.MUTED, font=T.font(12), anchor="w", justify="left", wraplength=980)
        self.info.pack(fill="x", pady=(0, 8))
        self.table = DataTable(self, [("name", "Файл", 300, "w", True), ("size", "Размер", 100, "e", False), ("type", "Тип", 70, "w", False),
                                      ("date", "Изменён", 110, "w", False), ("folder", "Папка", 420, "w", True)],
                               checkable=True, height=15, on_double=lambda iid: self._reveal(iid))
        self.table.pack(fill="both", expand=True)

    def on_show(self) -> None:
        pass

    def scan(self) -> None:
        mb = {"100 МБ": 100, "250 МБ": 250, "500 МБ": 500, "1 ГБ": 1024}[self.min.get()]
        self.app.run_task("largefiles", lambda ctx: find_large_files(min_size_mb=mb, progress=ctx.progress, cancel=ctx.cancelled), self._render, busy="Ищу большие файлы…")

    def _render(self, files) -> None:
        self.items = {f"l{n}": f for n, f in enumerate(files)}
        rows = []
        now = datetime.now().timestamp()
        for iid, f in self.items.items():
            p = Path(f.path)
            old = now - f.mtime > 365 * 86400
            rows.append({
                "iid": iid,
                "values": [p.name, format_size(f.size_bytes), f.extension or "—", datetime.fromtimestamp(f.mtime).strftime("%d.%m.%Y"), short(str(p.parent), 80)],
                "sort": [p.name.casefold(), f.size_bytes, f.extension, f.mtime, str(p.parent)],
                "tags": ["warn"] if old else [],
            })
        self.table.set_rows(rows, "Больших файлов не найдено")
        total = sum(f.size_bytes for f in files)
        self.info.configure(text=f"Найдено файлов: {len(files)} · в сумме {format_size(total)}. Жёлтым — не изменялись больше года. Двойной щелчок — показать в Проводнике.")

    def _reveal(self, iid) -> None:
        if iid in self.items:
            reveal_in_explorer(self.items[iid].path)

    def reveal(self) -> None:
        for iid in self.table.selected()[:3]:
            self._reveal(iid)

    def recycle(self) -> None:
        chosen = [self.items[i] for i in self.table.get_checked() if i in self.items]
        if not chosen:
            inform(self, "Ничего не отмечено", "Отметьте галочкой файлы, которые нужно убрать в корзину.", level="info")
            return
        total = sum(f.size_bytes for f in chosen)
        if not ask(self, "Переместить в корзину?", f"{len(chosen)} файл(ов), {format_size(total)}:", [f"{f.path}  ({format_size(f.size_bytes)})" for f in chosen],
                   confirm="В корзину", danger=True, note="Файлы можно будет восстановить из Корзины. Место освободится после очистки Корзины."):
            return

        def work(_ctx):
            return send_to_recycle_bin([f.path for f in chosen])

        def finish(res) -> None:
            log_action("Диск", "Большие файлы → Корзина", f"{res.moved_files} файлов, {format_size(res.moved_bytes)}", ok=not res.errors)
            inform(self, "Готово", f"В корзину перемещено: {res.moved_files} ({format_size(res.moved_bytes)})", res.errors, level="ok" if not res.errors else "warn")
            done = {f.path for f in chosen if not Path(f.path).exists()}
            self._render([f for f in self.items.values() if f.path not in done])

        self.app.run_task("recycle", work, finish, busy="Перемещаю в корзину…")


class DuplicatesView(ctk.CTkFrame):
    def __init__(self, master, page: DiskPage) -> None:
        super().__init__(master, fg_color="transparent")
        self.page = page
        self.app = page.app
        self.files = {}
        self.groups = []
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 10))
        button(bar, "Найти дубликаты", self.scan, kind="primary").pack(side="left")
        button(bar, "Стоп", lambda: self.app.cancel_task("dups"), kind="ghost").pack(side="left", padx=6)
        button(bar, "Отметить копии", self.mark_copies).pack(side="left", padx=6)
        button(bar, "В корзину отмеченные…", self.recycle, kind="danger").pack(side="right")
        button(bar, "Показать в Проводнике", self.reveal).pack(side="right", padx=8)
        roots = ", ".join(p.name for p in default_scan_roots())
        self.info = ctk.CTkLabel(self, text=f"Ищем одинаковые по содержимому файлы (от 256 КБ) в папках: {roots}. «Отметить копии» оставляет самый старый файл в каждой группе.",
                                 text_color=T.MUTED, font=T.font(12), anchor="w", justify="left", wraplength=980)
        self.info.pack(fill="x", pady=(0, 8))
        self.table = DataTable(self, [("name", "Файл", 340, "w", True), ("size", "Размер", 100, "e", False), ("date", "Изменён", 110, "w", False), ("folder", "Папка", 440, "w", True)],
                               checkable=True, height=15, sortable=False, on_double=lambda iid: self._reveal(iid))
        self.table.pack(fill="both", expand=True)

    def on_show(self) -> None:
        pass

    def scan(self) -> None:
        self.app.run_task("dups", lambda ctx: scan_duplicates(progress=ctx.progress, cancel=ctx.cancelled), self._render, busy="Ищу дубликаты…")

    def _render(self, result) -> None:
        self.groups = result.groups
        self.files = {}
        rows = []
        for g, group in enumerate(result.groups[:300]):
            gid = f"g{g}"
            rows.append({"iid": gid, "values": [f"Группа {g + 1}: {len(group.files)} копии по {format_size(group.size_bytes)}", f"−{format_size(group.reclaimable_bytes)}", "", ""],
                         "tags": ["group"], "checkable": False, "check_text": ""})
            for n, f in enumerate(group.files):
                iid = f"{gid}f{n}"
                self.files[iid] = (f, n == 0)
                p = Path(f.path)
                rows.append({"iid": iid, "parent": gid,
                             "values": [("★ " if n == 0 else "    ") + p.name, format_size(f.size_bytes), datetime.fromtimestamp(f.mtime).strftime("%d.%m.%Y") if f.mtime else "—", short(str(p.parent), 80)],
                             "tags": ["ok"] if n == 0 else []})
        self.table.set_rows(rows, "Дубликатов не найдено")
        reclaim = sum(g.reclaimable_bytes for g in result.groups)
        self.info.configure(text=f"Просмотрено файлов: {result.scanned_files}. Групп: {len(result.groups)}. Можно освободить ≈ {format_size(reclaim)}. ★ — самый старый файл (оригинал).")

    def mark_copies(self) -> None:
        self.table.clear_checks()
        self.table.set_checked([iid for iid, (_f, keep) in self.files.items() if not keep], True)

    def _reveal(self, iid) -> None:
        if iid in self.files:
            reveal_in_explorer(self.files[iid][0].path)

    def reveal(self) -> None:
        for iid in self.table.selected()[:3]:
            self._reveal(iid)

    def recycle(self) -> None:
        chosen = [self.files[i][0] for i in self.table.get_checked() if i in self.files]
        if not chosen:
            inform(self, "Ничего не отмечено", "Нажмите «Отметить копии» или отметьте файлы вручную.", level="info")
            return
        # Защита: в каждой группе должна остаться хотя бы одна копия.
        chosen_paths = {f.path for f in chosen}
        for group in self.groups:
            if all(f.path in chosen_paths for f in group.files):
                inform(self, "Так нельзя", "В одной из групп отмечены ВСЕ копии — тогда файл пропадёт совсем. Оставьте хотя бы один.", [group.files[0].path], level="warn")
                return
        total = sum(f.size_bytes for f in chosen)
        if not ask(self, "Переместить копии в корзину?", f"{len(chosen)} файл(ов), {format_size(total)}:", [f.path for f in chosen], confirm="В корзину", danger=True,
                   note="Оригиналы остаются на месте. Копии можно восстановить из Корзины."):
            return

        def work(_ctx):
            return delete_files([f.path for f in chosen])

        def finish(res) -> None:
            log_action("Дубликаты", "Копии → Корзина", f"{res.moved_files} файлов, {format_size(res.moved_bytes)}", ok=not res.errors)
            inform(self, "Готово", f"В корзину перемещено: {res.moved_files} ({format_size(res.moved_bytes)})", res.errors, level="ok" if not res.errors else "warn")
            self.scan()

        self.app.run_task("dups-delete", work, finish, busy="Перемещаю копии в корзину…")
