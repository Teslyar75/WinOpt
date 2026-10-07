"""Автозагрузка: оценка влияния, отключение с подтверждением и возврат."""

from __future__ import annotations

import customtkinter as ctk

from winopt.actions import KIND_LABELS, collect_actionable_startup, disable_item, is_caution, is_protected, load_disabled, restore_record
from winopt.startup import pretty_name
from winopt.advice import analyze_startup, is_recommended
from winopt.ui import theme as T
from winopt.ui.app import Page
from winopt.ui.widgets import Card, DataTable, PageHeader, StatTile, ask, button, inform, short

IMPACT = {
    "тяжёлая": ("высокое", "danger"),
    "обновлятор": ("среднее", "warn"),
    "задача обновления": ("среднее", "warn"),
    "браузер": ("среднее", "warn"),
    "мессенджер": ("среднее", "warn"),
    "по желанию": ("низкое", "info"),
    "обычная": ("низкое", ""),
    "системный": ("—", "muted"),
}


class StartupPage(Page):
    def build(self) -> None:
        self.items = {}
        header = PageHeader(self, "Автозагрузка", "Программы, которые запускаются вместе с Windows. Отключение не удаляет программу — её можно вернуть.", "startup")
        header.pack(fill="x", pady=(0, 14))

        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.pack(fill="x", pady=(0, 12))
        self.t_total = StatTile(tiles, "записей автозагрузки")
        self.t_rec = StatTile(tiles, "рекомендуем отключить", color=T.AMBER)
        self.t_high = StatTile(tiles, "с высоким влиянием", color=T.RED)
        self.t_off = StatTile(tiles, "отключено программой", color=T.GREEN)
        for t in (self.t_total, self.t_rec, self.t_high, self.t_off):
            t.pack(side="left", fill="x", expand=True, padx=(0, 10))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 10))
        button(bar, "↻  Обновить", self.refresh).pack(side="left")
        button(bar, "Отметить рекомендуемые", self.select_recommended).pack(side="left", padx=8)
        ctk.CTkSwitch(bar, text="Точка восстановления перед изменением", variable=self.app.restore_before, progress_color=T.ACCENT, font=T.font(12), text_color=T.MUTED).pack(side="left", padx=12)
        button(bar, "Отключить отмеченные…", self.disable_selected, kind="primary").pack(side="right")

        self.table = DataTable(
            self,
            [
                ("name", "Программа", 220, "w", False),
                ("impact", "Влияние", 90, "w", False),
                ("advice", "Оценка", 120, "w", False),
                ("reason", "Совет", 300, "w", True),
                ("kind", "Где", 150, "w", False),
                ("cmd", "Команда", 300, "w", True),
            ],
            checkable=True,
            height=11,
        )
        self.table.pack(fill="both", expand=True)

        self.disabled_card = Card(self, "Отключено программой WinOpt", "отметьте и нажмите «Вернуть», чтобы программа снова запускалась с Windows")
        # упаковывается раньше основной таблицы, чтобы не сжиматься в ноль на небольших экранах
        self.disabled_card.pack(fill="x", pady=(12, 0), side="bottom", before=self.table)
        button(self.disabled_card.header_right, "Вернуть отмеченные…", self.restore_selected).pack(side="right")
        self.disabled_table = DataTable(self.disabled_card.body, [("name", "Программа", 260, "w", True), ("kind", "Где", 180, "w", False), ("when", "Когда отключено", 180, "w", False)], checkable=True, height=4)
        self.disabled_table.pack(fill="x")

        self.app.on_analysis(self._from_analysis)

    def _from_analysis(self, analysis) -> None:
        if "startup_items" in analysis and not self.items:
            self._render(analysis["startup_items"])

    def on_show(self) -> None:
        cached = self.app.analysis.get("startup_items")
        if cached and not self.items:
            self._render(cached)
        elif not self.items:
            self.refresh()
        self._render_disabled()

    def refresh(self) -> None:
        self.app.run_task("startup", lambda _c: collect_actionable_startup(), self._render, busy="Читаю автозагрузку…")

    def _render(self, items) -> None:
        self.items = {}
        rows = []
        rec = high = 0
        for n, item in enumerate(items):
            iid = f"s{n}"
            self.items[iid] = item
            advice = analyze_startup(item)
            protected = is_protected(item)
            label = advice.label if advice else "защищено"
            impact, tag = IMPACT.get(label, ("—", ""))
            if protected:
                impact, tag, label = "—", "muted", "защищено"
            if is_recommended(item):
                rec += 1
            if impact == "высокое":
                high += 1
            rows.append(
                {
                    "iid": iid,
                    "values": [pretty_name(item.name), impact, label, advice.reason if advice else "Компонент Windows — отключать нельзя",
                               KIND_LABELS.get(item.kind, item.kind), short(item.command, 90)],
                    "sort": [pretty_name(item.name), {"высокое": 3, "среднее": 2, "низкое": 1}.get(impact, 0), label, "", item.kind, item.command],
                    "tags": [tag] if tag else [],
                    "checkable": not protected,
                    "check_text": "🔒" if protected else "·",
                }
            )
        self.table.set_rows(rows, "Автозагрузка пуста")
        self.t_total.set(str(len(items)))
        self.t_rec.set(str(rec))
        self.t_high.set(str(high))
        self.app.analysis["startup_recommended"] = rec
        self.app.nav_items["startup"].set_badge(str(rec) if rec else "")

    def _render_disabled(self) -> None:
        records = load_disabled()
        self._disabled = {f"d{n}": r for n, r in enumerate(records)}
        rows = [
            {"iid": iid, "values": [pretty_name(str(r.get("name") or "")), KIND_LABELS.get(r.get("kind"), r.get("kind")), _local_time(r.get("disabled_at", ""))]}
            for iid, r in self._disabled.items()
        ]
        self.disabled_table.set_rows(rows, "Пока ничего не отключено")
        self.t_off.set(str(len(records)))

    def select_recommended(self) -> None:
        self.table.clear_checks()
        ids = [iid for iid, item in self.items.items() if is_recommended(item) and not is_protected(item)]
        self.table.set_checked(ids, True)
        self.app.set_status(f"Отмечено рекомендуемых: {len(ids)}")

    def disable_selected(self) -> None:
        chosen = [self.items[i] for i in self.table.get_checked() if i in self.items]
        if not chosen:
            inform(self, "Ничего не отмечено", "Отметьте галочкой программы, которые не должны запускаться с Windows.", level="info")
            return
        caution = [pretty_name(i.name) for i in chosen if is_caution(i)]
        note = "Программы не удаляются. Вернуть можно в блоке «Отключено программой WinOpt» ниже."
        if caution:
            note = "Внимание: среди выбранных есть системные компоненты: " + ", ".join(caution) + ". " + note
        if not ask(self, "Отключить автозапуск?", f"Эти программы перестанут запускаться вместе с Windows ({len(chosen)}):",
                   [f"{pretty_name(i.name)}  ({KIND_LABELS.get(i.kind, i.kind)})" for i in chosen], confirm="Отключить", danger=bool(caution), note=note):
            return

        def work(ctx):
            restore_msg = self.app.maybe_restore_point("отключение автозагрузки")
            done, errors = [], []
            for item in chosen:
                ctx.progress(f"Отключаю: {pretty_name(item.name)}")
                try:
                    disable_item(item)
                    done.append(pretty_name(item.name))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{pretty_name(item.name)}: {exc}")
            return done, errors, restore_msg, collect_actionable_startup()

        def finish(res) -> None:
            done, errors, restore_msg, items = res
            self.table.clear_checks()
            self._render(items)
            self._render_disabled()
            level = "ok" if not errors else "warn"
            inform(self, "Готово" if not errors else "Частично выполнено", f"Отключено: {len(done)}", done + [f"Ошибка — {e}" for e in errors], level=level, note=restore_msg)

        self.app.run_task("startup-disable", work, finish, busy="Отключаю автозагрузку…")

    def restore_selected(self) -> None:
        chosen = [self._disabled[i] for i in self.disabled_table.get_checked() if i in self._disabled]
        if not chosen:
            inform(self, "Ничего не отмечено", "Отметьте программы, которые нужно вернуть в автозагрузку.", level="info")
            return
        if not ask(self, "Вернуть в автозагрузку?", "Эти программы снова будут запускаться с Windows:", [r.get("name") for r in chosen], confirm="Вернуть"):
            return

        def work(_ctx):
            done, errors = [], []
            for record in chosen:
                try:
                    restore_record(record)
                    done.append(record.get("name"))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{record.get('name')}: {exc}")
            return done, errors, collect_actionable_startup()

        def finish(res) -> None:
            done, errors, items = res
            self._render(items)
            self._render_disabled()
            inform(self, "Готово", f"Возвращено: {len(done)}", done + errors, level="ok" if not errors else "warn")

        self.app.run_task("startup-restore", work, finish, busy="Возвращаю автозагрузку…")


def _local_time(value: str) -> str:
    from datetime import datetime

    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return str(value or "")[:16]
