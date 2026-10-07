"""Установленные программы и приложения Магазина: поиск, фильтры, удаление отмеченных.

Ничего не удаляется, пока пользователь не отметит пункты галочками, не нажмёт
«Удалить отмеченные» и не подтвердит список в диалоге.
"""

from __future__ import annotations

import customtkinter as ctk

from winopt.history import log_action
from winopt.programs import REVIEW_LABELS, build_removal_plan, filter_programs, list_programs, open_uninstall_settings, uninstall_program
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import DataTable, PageHeader, StatTile, ask_with_option, button, inform, short
from winopt.winutil import format_size, open_path

FILTERS = {
    "Все": "all",
    "Лишнее (A)": "A",
    "На усмотрение (B)": "B",
    "Магазин": "store",
    "Крупные": "large",
    "Недавние": "recent",
}

STATUS_TEXT = {
    "queued": "в очереди",
    "running": "удаляется…",
    "removed": "✓ удалена",
    "unconfirmed": "? не подтверждено",
    "cancelled": "отменено",
    "error": "✕ ошибка",
}
STATUS_TAG = {"removed": "ok", "unconfirmed": "warn", "cancelled": "muted", "error": "danger", "running": "accent", "queued": "info"}


def _mb(mb: float) -> str:
    return format_size(mb * 1024**2) if mb else "—"


def plural_programs(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} программу"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} программы"
    return f"{n} программ"


class ProgramsPage(Page):
    def build(self) -> None:
        self.programs = []
        self.by_iid: dict[str, object] = {}
        self.iid_of: dict[str, str] = {}
        self.ticked: set[str] = set()  # uid отмеченных — сохраняются при поиске и смене фильтра
        self.status: dict[str, tuple[str, str]] = {}  # uid → (статус, текст)
        self.visible: set[str] = set()

        header = PageHeader(self, "Программы", "Обычные программы и приложения Магазина. Отметьте лишнее галочками — удаляются только отмеченные и только после подтверждения.", "programs")
        header.pack(fill="x", pady=(0, 14))
        button(header.right, "Параметры → Приложения", open_uninstall_settings, kind="ghost").pack(side="right")
        button(header.right, "↻  Обновить", self.refresh).pack(side="right", padx=8)

        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.pack(fill="x", pady=(0, 12))
        self.t_count = StatTile(tiles, "программ и приложений")
        self.t_size = StatTile(tiles, "занимают (по данным установщиков)", color=T.VIOLET)
        self.t_a = StatTile(tiles, "помечено «лишнее» в обзоре", color=T.AMBER)
        self.t_sel = StatTile(tiles, "отмечено к удалению", value="0", color=T.RED)
        for t in (self.t_count, self.t_size, self.t_a, self.t_sel):
            t.pack(side="left", fill="x", expand=True, padx=(0, 10))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))
        self.search = ctk.CTkEntry(bar, placeholder_text="Поиск по названию или издателю…", width=260, height=34, fg_color=T.CARD, border_color=T.BORDER, text_color=T.TEXT, font=T.font(13))
        self.search.pack(side="left")
        self.search.bind("<KeyRelease>", lambda _e: self._render())
        self.filter = ctk.CTkSegmentedButton(bar, values=list(FILTERS), command=lambda _v: self._render(), selected_color=T.ACCENT_DARK, selected_hover_color=T.ACCENT_DARK,
                                             unselected_color=T.CARD, unselected_hover_color=T.CARD_HI, fg_color=T.CARD, font=T.font(12), height=34)
        self.filter.set("Все")
        self.filter.pack(side="left", padx=12)
        self.locked_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(bar, text="Показывать защищённые", variable=self.locked_var, command=self._render, progress_color=T.ACCENT,
                      font=T.font(12), text_color=T.MUTED).pack(side="left", padx=4)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 10))
        self.sel_label = ctk.CTkLabel(actions, text="Ничего не отмечено. 🔒 — защищённые пункты, их отметить нельзя.", font=T.font(12), text_color=T.MUTED, anchor="w")
        self.sel_label.pack(side="left")
        self.remove_btn = button(actions, "Удалить отмеченные (0)", self.remove_ticked, kind="danger", width=220)
        self.remove_btn.pack(side="right")
        self.clear_btn = button(actions, "Снять все", self.clear_ticks)
        self.clear_btn.pack(side="right", padx=8)
        self.stop_btn = button(actions, "Остановить после текущей", self.stop_removal, kind="ghost")

        self.table = DataTable(
            self,
            [
                ("name", "Название", 230, "w", True),
                ("kind", "Тип", 78, "w", False),
                ("mark", "Оценка", 128, "w", False),
                ("why", "Почему", 205, "w", True),
                ("size", "Размер", 78, "e", False),
                ("date", "Установлена", 88, "w", False),
                ("publisher", "Издатель", 105, "w", False),
                ("status", "Статус", 110, "w", False),
            ],
            checkable=True,
            height=14,
            on_double=self._open_location,
            on_check=self._on_check,
        )
        self.table.pack(fill="both", expand=True)

    # --- данные ---------------------------------------------------------------
    def on_show(self) -> None:
        if not self.programs and not self.app.is_running("programs"):
            self.refresh()

    def refresh(self) -> None:
        if self.app.is_running("uninstall"):
            return
        self.app.run_task("programs", lambda _c: list_programs(), self._loaded, busy="Читаю программы и приложения Магазина…")

    def _loaded(self, programs) -> None:
        self.programs = programs
        self.by_iid = {f"k{n}": p for n, p in enumerate(programs)}
        self.iid_of = {p.uid: iid for iid, p in self.by_iid.items()}
        present = {p.uid for p in programs if not p.locked}
        self.ticked &= present
        store = sum(1 for p in programs if p.is_store)
        self.t_count.set(str(len(programs)), label=f"программ и приложений (Магазин: {store})")
        self.t_size.set(format_size(sum(p.size_mb for p in programs) * 1024**2))
        a_items = [p for p in programs if p.review == "A"]
        if a_items:
            self.t_a.set(str(len(a_items)), label=f"помечено «лишнее» · ≈ {_mb(sum(p.size_mb for p in a_items))}")
        else:
            self.t_a.set("—", label="нет данных обзора (data\\programs-review.csv)")
        self._render()

    def _render(self) -> None:
        mode = FILTERS.get(self.filter.get(), "all")
        progs = filter_programs(self.programs, mode)
        if not self.locked_var.get():
            progs = [p for p in progs if not p.locked]
        q = self.search.get().strip().casefold()
        if q:
            progs = [p for p in progs if q in p.name.casefold() or q in p.publisher.casefold() or q in p.package_name.casefold()]
        rows = []
        self.visible = set()
        for p in progs:
            iid = self.iid_of[p.uid]
            self.visible.add(p.uid)
            mark, why, tags = "", p.review_reason, []
            if p.locked:
                mark, why, tags = "🔒 защищено", p.lock_reason, ["muted"]
            elif p.review in REVIEW_LABELS:
                mark = REVIEW_LABELS[p.review]
                tags = ["warn"] if p.review == "A" else ["info"]
            st = self.status.get(p.uid)
            if st:
                tags = [STATUS_TAG.get(st[0], "muted")]
            rows.append({
                "iid": iid,
                "values": [p.name, p.kind_label, mark or "—", short(why, 90) or "—", _mb(p.size_mb), p.install_date or "—",
                           short(p.publisher, 30) or "—", STATUS_TEXT.get(st[0], "") if st else ""],
                "sort": [p.name.casefold(), p.kind_label, {"A": 0, "B": 1}.get(p.review, 3 if p.locked else 2), why, p.size_mb, p.install_sort,
                         p.publisher.casefold(), st[0] if st else ""],
                "tags": tags,
                "checkable": not p.locked,
                "check_text": "🔒",
            })
        self.table.checked = {self.iid_of[u] for u in self.ticked if u in self.iid_of}
        self.table.set_rows(rows, "Ничего не найдено")
        self._update_counter()

    # --- галочки ----------------------------------------------------------------
    def _on_check(self, checked_iids) -> None:
        visible_checkable = {p.uid for p in (self.by_iid[i] for i in self.table._checkable_rows) if p}
        now = {self.by_iid[i].uid for i in checked_iids if i in self.by_iid}
        self.ticked = (self.ticked - visible_checkable) | now
        self._update_counter()

    def ticked_programs(self):
        return [p for p in self.programs if p.uid in self.ticked and not p.locked]

    def _update_counter(self) -> None:
        items = self.ticked_programs()
        n = len(items)
        self.remove_btn.configure(text=f"Удалить отмеченные ({n})", state="normal" if n and not self.app.is_running("uninstall") else "disabled")
        self.t_sel.set(str(n), label=f"отмечено к удалению · ≈ {_mb(sum(p.size_mb for p in items))}" if n else "отмечено к удалению")
        hidden = len([p for p in items if p.uid not in self.visible])
        if n:
            extra = f" (из них {hidden} скрыто фильтром/поиском)" if hidden else ""
            self.sel_label.configure(text=f"Отмечено: {n}{extra} · ≈ {_mb(sum(p.size_mb for p in items))}", text_color=T.TEXT)
        else:
            self.sel_label.configure(text="Ничего не отмечено. 🔒 — защищённые пункты, их отметить нельзя.", text_color=T.MUTED)

    def clear_ticks(self) -> None:
        self.ticked.clear()
        self.table.checked.clear()
        self._render()

    def _open_location(self, iid) -> None:
        p = self.by_iid.get(iid)
        if p and p.location:
            try:
                open_path(p.location)
            except OSError:
                pass

    # --- удаление -------------------------------------------------------------
    def confirm_texts(self, plan) -> tuple[str, str, list[str]]:
        """Заголовок, текст и список для диалога подтверждения (без побочных эффектов)."""
        title = f"Удалить {plural_programs(len(plan.items))}?"
        message = (f"Будет удалено: {plural_programs(len(plan.items))}, всего ≈ {_mb(plan.total_mb)}.\n"
                   "Удаление идёт по очереди. У обычных программ откроется их собственный деинсталлятор — "
                   "следуйте его шагам. Приложения Магазина удаляются для вашей учётной записи.")
        notes = []
        if plan.admin_count:
            notes.append(f"Для {plan.admin_count} из них Windows запросит разрешение администратора (UAC).")
        if plan.skipped:
            notes.append(f"Защищённые пункты ({len(plan.skipped)}) будут пропущены.")
        notes.append("Удалённое вернуть можно только переустановкой — проверьте список.")
        return title, message + "\n\n" + " ".join(notes), plan.lines

    def remove_ticked(self) -> None:
        if self.app.is_running("uninstall"):
            return
        plan = build_removal_plan(self.ticked_programs())
        if not plan.items:
            inform(self, "Ничего не отмечено", "Отметьте галочками программы, которые хотите удалить.", level="info")
            return
        title, message, lines = self.confirm_texts(plan)
        ok, restore = ask_with_option(self, title, message, lines, option=("Сначала создать точку восстановления (рекомендуется)", True),
                                      confirm=f"Удалить ({len(plan.items)})", danger=True)
        if not ok:
            return
        if restore:
            self.app.run_task("restore-point", lambda _c: self._make_restore_point(), lambda res: self._after_restore(plan, res),
                              on_err=lambda exc: self._after_restore(plan, exc), busy="Создаю точку восстановления…")
        else:
            self._start_removal(plan, "Точка восстановления: не создавалась (выбор пользователя).")

    def _make_restore_point(self) -> str:
        from winopt.restore import create_restore_point, create_restore_point_elevated

        if self.app.admin:
            create_restore_point("WinOpt — перед удалением программ")
            return "Точка восстановления создана."
        return create_restore_point_elevated("WinOpt — перед удалением программ")

    def _after_restore(self, plan, result) -> None:
        if isinstance(result, Exception):
            from winopt.ui.widgets import ask

            log_action("Программы", "Точка восстановления не создана", str(result), ok=False)
            if not ask(self, "Точка восстановления не создана", f"{result}\n\nПродолжить удаление без точки восстановления?",
                       confirm="Продолжить", danger=True):
                self.app.set_status("Удаление отменено.")
                return
            self._start_removal(plan, f"Точка восстановления не создана: {result}")
        else:
            log_action("Программы", "Точка восстановления перед удалением", str(result))
            self._start_removal(plan, str(result))

    def _set_status(self, uid: str, status: str, text: str = "") -> None:
        self.status[uid] = (status, text)
        iid = self.iid_of.get(uid)
        if iid and self.table.tree.exists(iid):
            self.table.tree.set(iid, "status", STATUS_TEXT.get(status, status))
            self.table.tree.item(iid, tags=(STATUS_TAG.get(status, "muted"),))

    def _start_removal(self, plan, restore_note: str) -> None:
        for p in plan.items:
            self._set_status(p.uid, "queued")
        self.stop_btn.pack(side="right", padx=8, before=self.clear_btn)
        admin = self.app.admin

        def work(ctx):
            results = []
            total = len(plan.items)
            for n, prog in enumerate(plan.items, 1):
                if ctx.cancelled():
                    for rest in plan.items[n - 1:]:
                        ctx.ui(lambda u=rest.uid: self._set_status(u, "cancelled", "остановлено"))
                        results.append((rest, "cancelled", "остановлено пользователем"))
                    break
                ctx.progress(f"Удаление {n}/{total}: {prog.name}")
                ctx.ui(lambda u=prog.uid: self._set_status(u, "running"))
                try:
                    outcome = uninstall_program(prog, admin, ctx.cancelled)
                    status, text = outcome.status, outcome.message
                except Exception as exc:  # noqa: BLE001
                    status, text = "error", str(exc)
                log_action("Программы", f"Удаление «{prog.name}» — {STATUS_TEXT.get(status, status)}",
                           f"{prog.kind_label}; {text}", ok=status == "removed")
                ctx.ui(lambda u=prog.uid, s=status, t=text: self._set_status(u, s, t))
                results.append((prog, status, text))
            return results

        self.app.run_task("uninstall", work, lambda res: self._finished(res, restore_note),
                          on_err=lambda exc: self._finished([], restore_note, exc), busy="Удаление программ…")
        self._update_counter()

    def stop_removal(self) -> None:
        self.app.cancel_task("uninstall")

    def _finished(self, results, restore_note: str, error=None) -> None:
        self.stop_btn.pack_forget()
        removed = [r for r in results if r[1] == "removed"]
        for prog, status, _t in results:
            if status == "removed":
                self.ticked.discard(prog.uid)
        lines = [f"{p.name}: {STATUS_TEXT.get(s, s)} — {t}" for p, s, t in results]
        if error:
            lines.append(f"Ошибка: {error}")
        level = "ok" if results and len(removed) == len(results) else "warn"
        inform(self, "Удаление завершено", f"Удалено: {len(removed)} из {len(results)}.\n{restore_note}\n\nПодробности — в разделе «Журнал».",
               items=lines, level=level)
        self.app.set_status(f"Удаление завершено: {len(removed)} из {len(results)}")
        self.refresh()
