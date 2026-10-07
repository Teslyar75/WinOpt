"""Главное окно: боковое меню, страницы, строка состояния и фоновые задачи."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import traceback

import customtkinter as ctk

from winopt import __version__
from winopt.system import LiveSampler
from winopt.ui import theme as T
from winopt.ui.widgets import button, inform
from winopt.winutil import format_rate, format_size, is_admin, relaunch_as_admin, IS_WINDOWS

NAV = [
    ("dashboard", "Панель"),
    ("optimize", "Оптимизация"),
    ("processes", "Процессы"),
    ("startup", "Автозагрузка"),
    ("cleanup", "Очистка"),
    ("disk", "Диски и файлы"),
    ("programs", "Программы"),
    ("services", "Службы"),
    ("network", "Сеть"),
    ("security", "Безопасность"),
    ("health", "Здоровье ПК"),
    ("journal", "Журнал"),
]


def _work_area() -> tuple[int, int, int, int] | None:
    """Рабочая область экрана без панели задач (физические пиксели)."""
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    except Exception:  # не Windows
        pass
    return None


class TaskContext:
    def __init__(self, app: "WinOptApp", key: str) -> None:
        self._app = app
        self.key = key
        self._cancel = False

    def progress(self, message: str) -> None:
        self._app._queue.put(("progress", self.key, message, None))

    def ui(self, callback) -> None:
        """Выполнить callback() в потоке интерфейса (для обновления таблиц из фоновой задачи)."""
        self._app._queue.put(("call", self.key, callback, None))

    def cancel(self) -> None:
        self._cancel = True

    def cancelled(self) -> bool:
        return self._cancel


class Page(ctk.CTkFrame):
    """Базовая страница. Содержимое строится при первом открытии."""

    def __init__(self, master, app: "WinOptApp") -> None:
        super().__init__(master, fg_color=T.BG, corner_radius=0)
        self.app = app
        self.built = False

    def ensure_built(self) -> None:
        if not self.built:
            self.build()
            self.built = True

    def build(self) -> None:  # переопределяется
        pass

    def on_show(self) -> None:
        pass

    def on_hide(self) -> None:
        pass

    def on_tick(self, snapshot) -> None:
        pass


class NavItem(ctk.CTkFrame):
    def __init__(self, master, key: str, title: str, command) -> None:
        super().__init__(master, fg_color="transparent", corner_radius=10, height=40)
        self.key = key
        self._command = command
        self._active = False
        self.bar = ctk.CTkFrame(self, width=3, height=22, corner_radius=2, fg_color="transparent")
        self.bar.pack(side="left", padx=(4, 6))
        self.icon = ctk.CTkLabel(self, text=T.icon(key), font=T.icon_font(16), width=26, text_color=T.MUTED)
        self.icon.pack(side="left", padx=(2, 8))
        self.label = ctk.CTkLabel(self, text=title, font=T.font(14), text_color=T.MUTED, anchor="w")
        self.label.pack(side="left", fill="x", expand=True, pady=6)
        self.badge = ctk.CTkLabel(self, text="", font=T.font(11, "bold"), text_color=T.AMBER, width=10)
        self.badge.pack(side="right", padx=8)
        for widget in (self, self.icon, self.label, self.badge):
            widget.bind("<Button-1>", lambda _e: self._command(self.key))
            widget.bind("<Enter>", lambda _e: self._hover(True))
            widget.bind("<Leave>", lambda _e: self._hover(False))
            widget.configure(cursor="hand2")

    def set_active(self, active: bool) -> None:
        self._active = active
        self.configure(fg_color=T.CARD_HI if active else "transparent")
        self.bar.configure(fg_color=T.ACCENT if active else "transparent")
        self.icon.configure(text_color=T.ACCENT if active else T.MUTED)
        self.label.configure(text_color=T.TEXT if active else T.MUTED, font=T.font(14, "bold" if active else "normal"))

    def set_badge(self, text: str, color: str = T.AMBER) -> None:
        self.badge.configure(text=text, text_color=color)

    def _hover(self, inside: bool) -> None:
        if not self._active:
            self.configure(fg_color=T.CARD if inside else "transparent")
            self.label.configure(text_color=T.TEXT if inside else T.MUTED)


class WinOptApp(ctk.CTk):
    def __init__(self, start_page: str = "dashboard") -> None:
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=T.BG)
        self.title("WinOpt — Оптимизация Windows")
        T.init_fonts(self)
        T.setup_ttk(self)
        self._set_icon()
        self._place_window()

        self._queue: queue.Queue = queue.Queue()
        self._tasks: dict[str, TaskContext] = {}
        self._task_text: dict[str, str] = {}
        self.sampler = LiveSampler()
        self.admin = is_admin()
        self.restore_before = tk.BooleanVar(value=True)
        # Общие результаты анализа (для рекомендаций на панели)
        self.analysis: dict = {"startup_recommended": None, "defender_ok": None, "junk_bytes": None}
        self._analysis_listeners: list = []

        self.pages: dict[str, Page] = {}
        self.nav_items: dict[str, NavItem] = {}
        self.current: str | None = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._poll_queue)
        self.after(400, self._tick)
        self.show(start_page if start_page in dict(NAV) else "dashboard")
        self.after(1200, self.run_analysis)
        self.after(3000, self._ensure_shortcut)

    # --- окно ---------------------------------------------------------------
    def _set_icon(self) -> None:
        try:
            from winopt.shortcut import icon_path

            path = icon_path()
            if IS_WINDOWS and path.exists():
                self.iconbitmap(str(path))
        except Exception:
            pass

    def _place_window(self) -> None:
        scale = T.SCALE or 1.0
        left, top, phys_w, phys_h = _work_area() or (0, 0, int(self.winfo_screenwidth() * scale), int(self.winfo_screenheight() * scale))
        avail_w = phys_w / scale
        avail_h = phys_h / scale
        w = int(min(1320, avail_w * 0.94))
        h = int(min(860, avail_h * 0.92))
        # размеры CustomTkinter масштабирует сам, а координаты — в физических пикселях
        x = int(left + (phys_w - w * scale) / 2)
        y = int(top + max(0, (phys_h - h * scale) / 2 - 10 * scale))
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(1040, 660)

    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, fg_color=T.SIDEBAR, corner_radius=0, width=236)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.pack_propagate(False)
        self._build_sidebar(side)

        main = ctk.CTkFrame(self, fg_color=T.BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)
        self.content = ctk.CTkFrame(main, fg_color=T.BG, corner_radius=0)
        self.content.grid(row=0, column=0, sticky="nsew", padx=26, pady=(20, 6))
        self._build_statusbar(main)

    def _build_sidebar(self, side) -> None:
        logo = ctk.CTkFrame(side, fg_color="transparent")
        logo.pack(fill="x", padx=18, pady=(22, 18))
        canvas = tk.Canvas(logo, width=T.px(42), height=T.px(42), bg=T.SIDEBAR, highlightthickness=0)
        canvas.pack(side="left")
        self._draw_logo(canvas, T.px(42))
        text = ctk.CTkFrame(logo, fg_color="transparent")
        text.pack(side="left", padx=12)
        ctk.CTkLabel(text, text="WinOpt", font=T.font(20, "bold"), text_color=T.TEXT, anchor="w", height=24).pack(anchor="w")
        ctk.CTkLabel(text, text="оптимизация Windows", font=T.font(11), text_color=T.MUTED, anchor="w", height=14).pack(anchor="w")

        nav = ctk.CTkFrame(side, fg_color="transparent")
        nav.pack(fill="x", padx=10)
        for key, title in NAV:
            item = NavItem(nav, key, title, self.show)
            item.pack(fill="x", pady=1)
            self.nav_items[key] = item

        footer = ctk.CTkFrame(side, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=16, pady=16)
        if self.admin:
            ctk.CTkLabel(footer, text="●  Права администратора", text_color=T.GREEN, font=T.font(12), anchor="w").pack(fill="x")
        else:
            ctk.CTkLabel(footer, text="●  Обычные права", text_color=T.AMBER, font=T.font(12), anchor="w").pack(fill="x")
            button(footer, "Перезапуск от администратора", self._elevate, kind="secondary", height=30, size=12).pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(footer, text=f"версия {__version__}", text_color=T.DIM, font=T.font(11), anchor="w").pack(fill="x", pady=(8, 0))

    def _draw_logo(self, c: tk.Canvas, s: int) -> None:
        import math

        cx = cy = s / 2
        pts = []
        for i in range(6):
            a = math.radians(60 * i - 90)
            pts += [cx + (s / 2 - 2) * math.cos(a), cy + (s / 2 - 2) * math.sin(a)]
        c.create_polygon(*pts, fill=T.blend(T.ACCENT, T.SIDEBAR, 0.18), outline=T.ACCENT, width=2)
        r = s * 0.22
        c.create_arc(cx - r, cy - r, cx + r, cy + r, start=120, extent=300, style="arc", outline=T.ACCENT, width=3)
        c.create_line(cx, cy - r - 3, cx, cy + 1, fill=T.TEXT, width=3)

    def _build_statusbar(self, main) -> None:
        bar = ctk.CTkFrame(main, fg_color=T.SIDEBAR, corner_radius=0, height=34)
        bar.grid(row=1, column=0, sticky="ew")
        self.status_dot = ctk.CTkLabel(bar, text="●", text_color=T.GREEN, font=T.font(12), width=14)
        self.status_dot.pack(side="left", padx=(18, 6))
        self.status_label = ctk.CTkLabel(bar, text="Готово", text_color=T.MUTED, font=T.font(12), anchor="w")
        self.status_label.pack(side="left")
        self.progress = ctk.CTkProgressBar(bar, width=140, height=6, progress_color=T.ACCENT, fg_color=T.GRID, mode="indeterminate")
        self.live_label = ctk.CTkLabel(bar, text="", text_color=T.DIM, font=T.font(12))
        self.live_label.pack(side="right", padx=18)

    # --- навигация ----------------------------------------------------------
    def show(self, key: str) -> None:
        if key == self.current:
            return
        if self.current and self.current in self.pages:
            self.pages[self.current].on_hide()
            self.pages[self.current].pack_forget()
        page = self.pages.get(key)
        if page is None:
            page = self._create_page(key)
            self.pages[key] = page
        page.ensure_built()
        page.pack(fill="both", expand=True)
        for k, item in self.nav_items.items():
            item.set_active(k == key)
        self.current = key
        page.on_show()

    def _create_page(self, key: str) -> Page:
        from winopt.ui.pages import PAGE_CLASSES

        return PAGE_CLASSES[key](self.content, self)

    # --- фоновые задачи -----------------------------------------------------
    def run_task(self, key: str, work, on_ok=None, on_err=None, busy: str = "Выполняется…") -> bool:
        if key in self._tasks:
            self.set_status("Эта операция уже выполняется…")
            return False
        ctx = TaskContext(self, key)
        self._tasks[key] = ctx
        self._task_text[key] = busy
        self._refresh_status()

        def runner() -> None:
            try:
                result = work(ctx)
            except Exception as exc:  # noqa: BLE001 — любую ошибку показываем пользователю
                exc.__winopt_tb__ = traceback.format_exc()  # type: ignore[attr-defined]
                self._queue.put(("err", key, exc, on_err))
                return
            self._queue.put(("ok", key, result, on_ok))

        threading.Thread(target=runner, daemon=True, name=f"winopt-{key}").start()
        return True

    def is_running(self, key: str) -> bool:
        return key in self._tasks

    def cancel_task(self, key: str) -> None:
        ctx = self._tasks.get(key)
        if ctx:
            ctx.cancel()
            self._task_text[key] = "Останавливаю…"
            self._refresh_status()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, key, payload, callback = self._queue.get_nowait()
                if kind == "progress":
                    if key in self._tasks:
                        self._task_text[key] = payload
                        self._refresh_status()
                    continue
                if kind == "call":
                    try:
                        payload()
                    except Exception as exc:  # noqa: BLE001
                        self.set_status(f"Ошибка интерфейса: {exc}", error=True)
                    continue
                self._tasks.pop(key, None)
                self._task_text.pop(key, None)
                self._refresh_status()
                try:
                    if kind == "ok":
                        if callback:
                            callback(payload)
                    else:
                        if callback:
                            callback(payload)
                        else:
                            self.set_status(f"Ошибка: {payload}", error=True)
                            inform(self, "Ошибка", str(payload) or payload.__class__.__name__, level="danger")
                except Exception as exc:  # noqa: BLE001
                    self.set_status(f"Ошибка интерфейса: {exc}", error=True)
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _refresh_status(self) -> None:
        if self._tasks:
            text = list(self._task_text.values())[-1]
            more = f"  (+{len(self._tasks) - 1})" if len(self._tasks) > 1 else ""
            self.status_label.configure(text=text + more, text_color=T.TEXT)
            self.status_dot.configure(text_color=T.ACCENT)
            if not self.progress.winfo_ismapped():
                self.progress.pack(side="left", padx=14)
                self.progress.start()
        else:
            if self.progress.winfo_ismapped():
                self.progress.stop()
                self.progress.pack_forget()
            self.status_dot.configure(text_color=T.GREEN)
            if self.status_label.cget("text_color") == T.TEXT:
                self.status_label.configure(text="Готово", text_color=T.MUTED)

    def set_status(self, text: str, error: bool = False) -> None:
        self.status_label.configure(text=text, text_color=T.RED if error else T.MUTED)
        self.status_dot.configure(text_color=T.RED if error else T.GREEN)

    # --- живые показатели ---------------------------------------------------
    def _tick(self) -> None:
        try:
            snap = self.sampler.sample()
            self.live_label.configure(
                text=f"CPU {snap.cpu_percent:4.0f}%   ·   RAM {snap.ram_percent:4.0f}%   ·   ↓ {format_rate(snap.net_down)}   ↑ {format_rate(snap.net_up)}"
            )
            if self.current and self.current in self.pages:
                self.pages[self.current].on_tick(snap)
        except Exception:
            pass
        self.after(1000, self._tick)

    # --- общий анализ (для рекомендаций) -----------------------------------
    def on_analysis(self, callback) -> None:
        self._analysis_listeners.append(callback)

    def run_analysis(self) -> None:
        def work(ctx):
            result = {}
            from winopt.cleanup import scan_categories

            ctx.progress("Анализ: временные файлы и кэши…")
            try:
                scans = scan_categories()
                result["junk_bytes"] = sum(s.size_bytes for s in scans if s.default_selected and not s.blocked_reason and s.category_id != "recycle_bin")
                result["cleanup_scans"] = scans
            except Exception:
                result["junk_bytes"] = None
            ctx.progress("Анализ: автозагрузка…")
            try:
                from winopt.actions import collect_actionable_startup
                from winopt.advice import is_recommended

                items = collect_actionable_startup()
                result["startup_items"] = items
                result["startup_recommended"] = sum(1 for i in items if is_recommended(i))
            except Exception:
                result["startup_recommended"] = None
            ctx.progress("Анализ: Защитник Windows…")
            try:
                from winopt.defender import get_defender_status

                status = get_defender_status()
                result["defender"] = status
                result["defender_ok"] = status.ok
            except Exception:
                result["defender_ok"] = None
            return result

        def ok(result) -> None:
            self.analysis.update(result)
            rec = result.get("startup_recommended")
            if rec:
                self.nav_items["startup"].set_badge(str(rec))
            junk = result.get("junk_bytes")
            if junk and junk > 300 * 1024**2:
                self.nav_items["cleanup"].set_badge(format_size(junk).replace(" ", ""), T.ACCENT)
            if result.get("defender_ok") is False:
                self.nav_items["security"].set_badge("!", T.RED)
            for cb in self._analysis_listeners:
                try:
                    cb(self.analysis)
                except Exception:
                    pass
            self.set_status("Анализ системы завершён")

        self.run_task("analysis", work, ok, on_err=lambda e: self.set_status(f"Анализ не завершён: {e}", error=True), busy="Анализ системы…")

    # --- точка восстановления -----------------------------------------------
    def maybe_restore_point(self, action: str) -> str:
        """Вызывается в фоновом потоке перед изменениями. Возвращает понятный итог."""
        if not self.restore_before.get():
            return "Точка восстановления: отключено пользователем."
        if not self.admin:
            return "Точка восстановления не создана: нужны права администратора."
        try:
            from winopt.restore import create_restore_point

            create_restore_point(f"WinOpt — {action}")
            return "Точка восстановления создана."
        except Exception as exc:  # noqa: BLE001
            return f"Точка восстановления не создана: {exc}"

    # --- прочее -------------------------------------------------------------
    def _elevate(self) -> None:
        if relaunch_as_admin():
            self._on_close()
        else:
            self.set_status("Запуск с правами администратора отменён", error=True)

    def _ensure_shortcut(self) -> None:
        def work(_ctx):
            from winopt.shortcut import install_desktop_shortcut, shortcut_path

            if IS_WINDOWS and not shortcut_path().exists():
                install_desktop_shortcut()
                return True
            return False

        self.run_task("shortcut", work, lambda created: created and self.set_status("Ярлык создан на рабочем столе"), on_err=lambda _e: None, busy="Проверяю ярлык…")

    def _on_close(self) -> None:
        for ctx in self._tasks.values():
            ctx.cancel()
        self.destroy()


def run_gui(start_page: str = "dashboard") -> int:
    app = WinOptApp(start_page)
    app.mainloop()
    return 0
