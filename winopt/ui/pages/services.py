"""Службы: сторонние службы с автозапуском. Драйверы и защита — заблокированы."""

from __future__ import annotations

import customtkinter as ctk

from winopt.services import list_services, load_changed, revert_service, set_service_manual
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import Banner, Card, DataTable, PageHeader, ask, button, inform, short

CAT_TAG = {"updater": "accent", "other": "", "hardware": "muted", "security": "muted"}
STATE_RU = {"running": "работает", "stopped": "остановлена"}


class ServicesPage(Page):
    def build(self) -> None:
        self.items = {}
        header = PageHeader(self, "Службы", "Сторонние службы, которые стартуют автоматически. Перевод в «Вручную» — служба запустится, только когда понадобится.", "services")
        header.pack(fill="x", pady=(0, 12))
        if not self.app.admin:
            b = Banner(self, "Для изменения служб нужны права администратора. Просмотр доступен и так.", "warn")
            b.pack(fill="x", pady=(0, 10))
            button(b.right, "Перезапустить от администратора", self.app._elevate, kind="secondary", height=30).pack()

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 10))
        button(bar, "↻  Обновить", self.refresh).pack(side="left")
        button(bar, "Отметить обновляторы", self.select_updaters).pack(side="left", padx=8)
        ctk.CTkSwitch(bar, text="Точка восстановления перед изменением", variable=self.app.restore_before, progress_color=T.ACCENT, font=T.font(12), text_color=T.MUTED).pack(side="left", padx=12)
        button(bar, "Перевести в «Вручную»…", self.set_manual, kind="primary").pack(side="right")

        legend = ctk.CTkFrame(self, fg_color="transparent")
        legend.pack(fill="x", pady=(0, 8))
        for text, color in (("● обновлятор — можно «Вручную»", T.ACCENT), ("● сторонняя — на ваше усмотрение", T.TEXT), ("🔒 драйвер / оборудование / антивирус — заблокировано", T.DIM)):
            ctk.CTkLabel(legend, text=text, text_color=color, font=T.font(12)).pack(side="left", padx=(0, 18))

        self.table = DataTable(self, [("name", "Служба", 320, "w", True), ("state", "Состояние", 110, "w", False), ("mode", "Запуск", 90, "w", False),
                                      ("cat", "Оценка", 260, "w", False), ("desc", "Описание", 360, "w", True)],
                               checkable=True, height=12)
        self.table.pack(fill="both", expand=True)

        card = Card(self, "Изменено программой WinOpt", "можно вернуть прежний режим запуска")
        card.pack(fill="x", pady=(12, 0), side="bottom", before=self.table)
        button(card.header_right, "Вернуть отмеченные…", self.revert).pack(side="right")
        self.changed_table = DataTable(card.body, [("name", "Служба", 320, "w", True), ("prev", "Было", 120, "w", False), ("when", "Когда", 180, "w", False)], checkable=True, height=3)
        self.changed_table.pack(fill="x")

    def on_show(self) -> None:
        if not self.items:
            self.refresh()
        self._render_changed()

    def refresh(self) -> None:
        self.app.run_task("services", lambda _c: list_services(), self._render, busy="Читаю службы Windows…")

    def _render(self, services) -> None:
        self.items = {f"v{n}": s for n, s in enumerate(services)}
        rows = []
        for iid, s in self.items.items():
            rows.append({
                "iid": iid,
                "values": [s.display_name, STATE_RU.get(s.state.casefold(), s.state), "Авто" if s.start_mode.casefold().startswith("auto") else s.start_mode, s.note, short(s.description, 90)],
                "sort": [s.display_name.casefold(), s.state, s.start_mode, s.category, s.description],
                "tags": [CAT_TAG.get(s.category, "")] if CAT_TAG.get(s.category) else [],
                "checkable": s.changeable,
                "check_text": "🔒",
            })
        self.table.set_rows(rows, "Сторонних служб с автозапуском нет")

    def _render_changed(self) -> None:
        self.changed = {f"c{n}": r for n, r in enumerate(load_changed())}
        rows = [{"iid": i, "values": [r.get("display_name"), r.get("previous"), str(r.get("changed_at", "")).replace("T", " ")]} for i, r in self.changed.items()]
        self.changed_table.set_rows(rows, "Пока ничего не изменено")

    def select_updaters(self) -> None:
        self.table.clear_checks()
        self.table.set_checked([i for i, s in self.items.items() if s.recommend_manual], True)

    def set_manual(self) -> None:
        chosen = [self.items[i] for i in self.table.get_checked() if i in self.items]
        if not chosen:
            inform(self, "Ничего не отмечено", "Отметьте службы. Подсказка: «Отметить обновляторы» выбирает безопасные варианты.", level="info")
            return
        if not self.app.admin:
            inform(self, "Нужны права администратора", "Windows разрешает менять службы только администратору. Нажмите «Перезапустить от администратора».", level="warn")
            return
        others = [s.display_name for s in chosen if not s.recommend_manual]
        note = "Службы не удаляются и не останавливаются сейчас. Вернуть можно в блоке ниже."
        if others:
            note = "Не обновляторы: " + ", ".join(others) + " — убедитесь, что они вам не нужны при старте. " + note
        if not ask(self, "Перевести в «Вручную»?", "Эти службы перестанут запускаться автоматически:", [s.display_name for s in chosen], confirm="Применить", danger=bool(others), note=note):
            return

        def work(ctx):
            restore_msg = self.app.maybe_restore_point("изменение служб")
            done, errors = [], []
            for s in chosen:
                ctx.progress(f"Изменяю: {s.display_name}")
                try:
                    set_service_manual(s)
                    done.append(s.display_name)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{s.display_name}: {exc}")
            return done, errors, restore_msg, list_services()

        def finish(res) -> None:
            done, errors, restore_msg, services = res
            self.table.clear_checks()
            self._render(services)
            self._render_changed()
            inform(self, "Готово" if not errors else "Частично выполнено", f"Переведено в «Вручную»: {len(done)}", done + errors, level="ok" if not errors else "warn", note=restore_msg)

        self.app.run_task("services-set", work, finish, busy="Изменяю службы…")

    def revert(self) -> None:
        chosen = [self.changed[i] for i in self.changed_table.get_checked() if i in self.changed]
        if not chosen:
            return
        if not ask(self, "Вернуть режим запуска?", "Вернуть прежний режим для:", [r.get("display_name") for r in chosen], confirm="Вернуть"):
            return

        def work(_ctx):
            errors = []
            for r in chosen:
                try:
                    revert_service(r)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{r.get('display_name')}: {exc}")
            return errors, list_services()

        def finish(res) -> None:
            errors, services = res
            self._render(services)
            self._render_changed()
            if errors:
                inform(self, "Не всё получилось", "Ошибки:", errors, level="warn")

        self.app.run_task("services-revert", work, finish, busy="Возвращаю службы…")
