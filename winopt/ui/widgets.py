"""Переиспользуемые элементы интерфейса: карточки, кольцевые индикаторы,
графики, таблицы, кнопки и диалоги подтверждения."""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from winopt.ui import theme as T


# --- Кнопки ------------------------------------------------------------------

_BUTTON_STYLES = {
    "primary": dict(fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER, text_color="#04131A"),
    "secondary": dict(fg_color=T.CARD_HI, hover_color=T.CARD_HOVER, text_color=T.TEXT, border_width=1, border_color=T.BORDER),
    "danger": dict(fg_color=T.blend(T.RED, T.CARD, 0.22), hover_color=T.blend(T.RED, T.CARD, 0.38), text_color=T.RED, border_width=1, border_color=T.blend(T.RED, T.CARD, 0.5)),
    "ghost": dict(fg_color="transparent", hover_color=T.CARD_HI, text_color=T.MUTED),
    "violet": dict(fg_color=T.VIOLET, hover_color="#8B6CF0", text_color="#120A2A"),
}


def button(master, text: str, command=None, kind: str = "secondary", width: int = 0, height: int = 34, size: int = 13, **kw) -> ctk.CTkButton:
    style = dict(_BUTTON_STYLES.get(kind, _BUTTON_STYLES["secondary"]))
    style.update(kw)
    weight = "bold" if kind in {"primary", "violet"} else "normal"
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        width=width or 0,
        height=height,
        corner_radius=10,
        font=T.font(size, weight),
        **style,
    )


# --- Карточки и подписи --------------------------------------------------------


class Card(ctk.CTkFrame):
    """Карточка с рамкой и необязательным заголовком."""

    def __init__(self, master, title: str | None = None, subtitle: str | None = None, pad: int = 16, **kw):
        kw.setdefault("fg_color", T.CARD)
        kw.setdefault("corner_radius", 16)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", T.BORDER)
        super().__init__(master, **kw)
        self.pad = pad
        self.header = None
        self.header_right = None
        if title:
            self.header = ctk.CTkFrame(self, fg_color="transparent")
            self.header.pack(fill="x", padx=pad, pady=(pad - 2, 4))
            left = ctk.CTkFrame(self.header, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(left, text=title.upper(), font=T.font(11, "bold"), text_color=T.MUTED, anchor="w", height=18).pack(anchor="w")
            if subtitle:
                self.subtitle_label = ctk.CTkLabel(left, text=subtitle, font=T.font(12), text_color=T.DIM, anchor="w", height=16)
                self.subtitle_label.pack(anchor="w")
            self.header_right = ctk.CTkFrame(self.header, fg_color="transparent", width=1, height=1)
            self.header_right.pack(side="right")
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=pad, pady=(4 if title else pad, pad))


class Pill(ctk.CTkLabel):
    def __init__(self, master, text: str, color: str = T.ACCENT, bg: str = T.CARD, **kw):
        super().__init__(
            master,
            text=f"  {text}  ",
            fg_color=T.blend(color, bg, 0.16),
            text_color=color,
            corner_radius=9,
            height=24,
            font=T.font(12, "bold"),
            **kw,
        )

    def set(self, text: str, color: str | None = None, bg: str = T.CARD) -> None:
        if color:
            self.configure(fg_color=T.blend(color, bg, 0.16), text_color=color)
        self.configure(text=f"  {text}  ")


class StatTile(ctk.CTkFrame):
    """Маленькая плитка «значение + подпись»."""

    def __init__(self, master, label: str, value: str = "—", color: str = T.TEXT, **kw):
        kw.setdefault("fg_color", T.CARD_HI)
        kw.setdefault("corner_radius", 12)
        super().__init__(master, **kw)
        self.value = ctk.CTkLabel(self, text=value, font=T.font(20, "bold"), text_color=color, anchor="w", height=28)
        self.value.pack(anchor="w", padx=14, pady=(10, 0))
        self.label = ctk.CTkLabel(self, text=label, font=T.font(12), text_color=T.MUTED, anchor="w", height=18)
        self.label.pack(anchor="w", padx=14, pady=(0, 10))

    def set(self, value: str, color: str | None = None, label: str | None = None) -> None:
        self.value.configure(text=value)
        if color:
            self.value.configure(text_color=color)
        if label is not None:
            self.label.configure(text=label)


class PageHeader(ctk.CTkFrame):
    def __init__(self, master, title: str, subtitle: str = "", icon_name: str | None = None):
        super().__init__(master, fg_color="transparent")
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        row = ctk.CTkFrame(left, fg_color="transparent")
        row.pack(anchor="w")
        if icon_name:
            ctk.CTkLabel(row, text=T.icon(icon_name), font=T.icon_font(22), text_color=T.ACCENT, width=30).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(row, text=title, font=T.font(26, "bold"), text_color=T.TEXT, anchor="w").pack(side="left")
        self.subtitle = ctk.CTkLabel(left, text=subtitle, font=T.font(13), text_color=T.MUTED, anchor="w", justify="left", wraplength=760)
        if subtitle:
            self.subtitle.pack(anchor="w", pady=(2, 0))
        self.right = ctk.CTkFrame(self, fg_color="transparent", width=1, height=1)
        self.right.pack(side="right", anchor="n")


class Banner(ctk.CTkFrame):
    """Цветная полоса-подсказка (предупреждение, информация)."""

    def __init__(self, master, text: str, level: str = "info", **kw):
        color = T.LEVEL_COLORS.get(level, T.BLUE)
        super().__init__(master, fg_color=T.blend(color, T.BG, 0.12), corner_radius=12, border_width=1, border_color=T.blend(color, T.BG, 0.35))
        ctk.CTkLabel(self, text="●", text_color=color, font=T.font(14), width=18).pack(side="left", padx=(14, 6), pady=10)
        self.label = ctk.CTkLabel(self, text=text, text_color=T.TEXT, font=T.font(13), anchor="w", justify="left", wraplength=820)
        self.label.pack(side="left", fill="x", expand=True, pady=10)
        self.right = ctk.CTkFrame(self, fg_color="transparent", width=1, height=1)
        self.right.pack(side="right", padx=10)


# --- Кольцевой индикатор -----------------------------------------------------------


class RingGauge(tk.Canvas):
    """Кольцо с плавной анимацией значения и делениями — как на приборной панели."""

    def __init__(self, master, size: int = 150, thickness: int = 12, color: str = T.ACCENT, bg: str = T.CARD, max_value: float = 100.0):
        self._size = T.px(size)
        super().__init__(master, width=self._size, height=self._size, bg=bg, highlightthickness=0, bd=0)
        self._thickness = T.px(thickness)
        self._color = color
        self._bg = bg
        self._max = max_value
        self._value = 0.0
        self._target = 0.0
        self._text = "—"
        self._sub = ""
        self._animating = False
        self._draw()

    def set(self, value: float, text: str | None = None, sub: str | None = None, color: str | None = None) -> None:
        self._target = max(0.0, min(self._max, float(value)))
        if text is not None:
            self._text = text
        if sub is not None:
            self._sub = sub
        if color:
            self._color = color
        if not self._animating:
            self._animating = True
            self._step()

    def _step(self) -> None:
        diff = self._target - self._value
        if abs(diff) < 0.3:
            self._value = self._target
            self._animating = False
        else:
            self._value += diff * 0.22
        self._draw()
        if self._animating:
            self.after(16, self._step)

    def _draw(self) -> None:
        self.delete("all")
        s = self._size
        t = self._thickness
        pad = t + T.px(8)
        box = (pad, pad, s - pad, s - pad)
        cx = cy = s / 2
        r_out = s / 2 - T.px(3)
        # деления
        for i in range(40):
            ang = math.radians(90 - i * 9)
            r1 = r_out - T.px(4 if i % 5 else 7)
            lit = i / 40 <= self._value / self._max and self._value > 0
            col = T.blend(self._color, self._bg, 0.75) if lit else T.GRID
            self.create_line(
                cx + r1 * math.cos(ang), cy - r1 * math.sin(ang),
                cx + r_out * math.cos(ang), cy - r_out * math.sin(ang),
                fill=col, width=max(1, T.px(2 if i % 5 == 0 else 1)),
            )
        self.create_oval(*box, outline=T.GRID, width=t)
        extent = -359.9 * (self._value / self._max)
        if abs(extent) > 0.5:
            self.create_arc(*box, start=90, extent=extent, style="arc", outline=T.blend(self._color, self._bg, 0.25), width=t + T.px(8))
            self.create_arc(*box, start=90, extent=extent, style="arc", outline=self._color, width=t)
            ang = math.radians(90 + extent)
            r_mid = (box[2] - box[0]) / 2
            ex, ey = cx + r_mid * math.cos(ang), cy - r_mid * math.sin(ang)
            dot = t / 2 + T.px(1)
            self.create_oval(ex - dot, ey - dot, ex + dot, ey + dot, fill="#FFFFFF", outline="")
        self.create_text(cx, cy - T.px(6), text=self._text, fill=T.TEXT, font=T.tk_font(int(s / T.SCALE * 0.17), "bold"))
        if self._sub:
            self.create_text(cx, cy + s * 0.14, text=self._sub, fill=T.MUTED, font=T.tk_font(max(9, min(11, int(s / T.SCALE * 0.1)))))


# --- Линейный график -------------------------------------------------------------


class LineChart(tk.Canvas):
    """График нескольких рядов с заливкой и сеткой. Ряды — последовательности чисел."""

    def __init__(self, master, height: int = 180, bg: str = T.CARD, max_value: float | None = 100.0, points: int = 90, fmt=None, grid_labels: bool = True):
        super().__init__(master, height=T.px(height), bg=bg, highlightthickness=0, bd=0)
        self._bg = bg
        self._max = max_value
        self._points = points
        self._series: list[tuple[list[float], str]] = []
        self._fmt = fmt or (lambda v: f"{v:.0f}%")
        self._grid_labels = grid_labels
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_series(self, series: list[tuple[list[float], str]]) -> None:
        self._series = series
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w = max(self.winfo_width(), 50)
        h = max(self.winfo_height(), 40)
        left, right, top, bottom = T.px(4), T.px(52 if self._grid_labels else 4), T.px(8), T.px(8)
        pw, ph = w - left - right, h - top - bottom
        peak = self._max
        if peak is None:
            vals = [v for data, _c in self._series for v in data]
            peak = max(vals + [1024.0]) * 1.25
        for i in range(5):
            y = top + ph * i / 4
            self.create_line(left, y, left + pw, y, fill=T.GRID, dash=(2, 4) if 0 < i < 4 else None)
            if self._grid_labels:
                self.create_text(w - T.px(4), y, text=self._fmt(peak * (4 - i) / 4), anchor="e", fill=T.DIM, font=T.tk_font(10))
        for i in range(1, 9):
            x = left + pw * i / 9
            self.create_line(x, top, x, top + ph, fill=T.blend(T.GRID, self._bg, 0.5))
        for data, color in self._series:
            data = list(data)[-self._points:]
            if len(data) < 2:
                continue
            step = pw / (self._points - 1)
            offset = self._points - len(data)
            coords = []
            for i, v in enumerate(data):
                x = left + (offset + i) * step
                y = top + ph - (min(v, peak) / peak) * ph
                coords.extend((x, y))
            poly = [coords[0], top + ph] + coords + [coords[-2], top + ph]
            self.create_polygon(*poly, fill=T.blend(color, self._bg, 0.16), outline="")
            self.create_line(*coords, fill=T.blend(color, self._bg, 0.35), width=T.px(5), smooth=True)
            self.create_line(*coords, fill=color, width=T.px(2), smooth=True)
            x, y = coords[-2], coords[-1]
            r = T.px(4)
            self.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=T.TEXT)


class HBar(tk.Canvas):
    """Горизонтальная полоса заполнения (для дисков и списков)."""

    def __init__(self, master, height: int = 10, bg: str = T.CARD, color: str = T.ACCENT):
        super().__init__(master, height=T.px(height), bg=bg, highlightthickness=0, bd=0)
        self._ratio = 0.0
        self._color = color
        self._h = T.px(height)
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, ratio: float, color: str | None = None) -> None:
        self._ratio = max(0.0, min(1.0, ratio))
        if color:
            self._color = color
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        w = max(self.winfo_width(), 10)
        h = self._h
        r = h / 2
        self._round_rect(0, 0, w, h, r, T.GRID)
        fill_w = max(h, w * self._ratio) if self._ratio > 0 else 0
        if fill_w:
            self._round_rect(0, 0, fill_w, h, r, self._color)

    def _round_rect(self, x1, y1, x2, y2, r, color):
        self.create_oval(x1, y1, x1 + 2 * r, y2, fill=color, outline="")
        self.create_oval(x2 - 2 * r, y1, x2, y2, fill=color, outline="")
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=color, outline="")


# --- Таблица -------------------------------------------------------------------------

CHECK_ON = "☑"
CHECK_OFF = "☐"
CHECK_NONE = "·"


class DataTable(ctk.CTkFrame):
    """Таблица на основе ttk.Treeview в тёмном стиле: сортировка по клику на заголовок,
    необязательная колонка с галочками, цветные строки по тегам."""

    def __init__(self, master, columns, checkable: bool = False, height: int = 12, sortable: bool = True,
                 on_select=None, on_double=None, on_check=None):
        super().__init__(master, fg_color=T.CARD, corner_radius=12, border_width=1, border_color=T.BORDER)
        self._columns = columns
        self._checkable = checkable
        self._sortable = sortable
        self._sort_values: dict[str, list] = {}
        self._checkable_rows: set[str] = set()
        self.checked: set[str] = set()
        self._on_check = on_check
        self._sort_state: tuple[str, bool] | None = None

        keys = (["_chk"] if checkable else []) + [c[0] for c in columns]
        inner = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=0)
        inner.pack(fill="both", expand=True, padx=T.px(2), pady=T.px(6))
        self.tree = ttk.Treeview(inner, columns=keys, show="headings", style="WinOpt.Treeview", height=height, selectmode="extended")
        if checkable:
            self.tree.heading("_chk", text=CHECK_OFF, command=self._toggle_all)
            self.tree.column("_chk", width=T.px(42), minwidth=T.px(42), anchor="center", stretch=False)
        for key, title, width, anchor, stretch in columns:
            if sortable:
                self.tree.heading(key, text=title, anchor=anchor, command=lambda k=key: self.sort_by(k))
            else:
                self.tree.heading(key, text=title, anchor=anchor)
            self.tree.column(key, width=T.px(width), minwidth=T.px(40), anchor=anchor, stretch=stretch)
        sb = ctk.CTkScrollbar(inner, command=self.tree.yview, button_color=T.BORDER, button_hover_color=T.DIM, fg_color="transparent")
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 2))
        self.tree.pack(side="left", fill="both", expand=True, padx=(T.px(6), 0))

        for tag, color in (("danger", T.RED), ("warn", T.AMBER), ("ok", T.GREEN), ("muted", T.DIM), ("accent", T.ACCENT), ("info", T.BLUE), ("violet", T.VIOLET)):
            self.tree.tag_configure(tag, foreground=color)
        self.tree.tag_configure("odd", background=T.blend("#FFFFFF", T.CARD, 0.025))
        self.tree.tag_configure("group", background=T.CARD_HI, foreground=T.TEXT, font=T.tk_font(13, "bold"))

        self.tree.bind("<Button-1>", self._on_click, add="+")
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda _e: on_select(self.selected()))
        if on_double:
            self.tree.bind("<Double-1>", lambda e: self._double(e, on_double))
        self._empty = ctk.CTkLabel(self, text="", text_color=T.DIM, font=T.font(13), fg_color=T.CARD)

    # --- данные ---
    def set_rows(self, rows: list[dict], empty_text: str = "Нет данных") -> None:
        """rows: [{"iid", "values", "sort"?, "tags"?, "parent"?, "checkable"? (True)}]"""
        yview = self.tree.yview()
        selection = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        self._sort_values.clear()
        self._checkable_rows.clear()
        present = set()
        for row in rows:
            iid = str(row["iid"])
            present.add(iid)
            values = list(row["values"])
            can_check = self._checkable and row.get("checkable", True)
            if self._checkable:
                if can_check:
                    self._checkable_rows.add(iid)
                    values = [CHECK_ON if iid in self.checked else CHECK_OFF] + values
                else:
                    values = [row.get("check_text", CHECK_NONE)] + values
            self.tree.insert(row.get("parent", ""), "end", iid=iid, values=values, tags=tuple(row.get("tags", ())), open=True)
            self._sort_values[iid] = list(row.get("sort", row["values"]))
        self.checked &= self._checkable_rows
        keep = [i for i in selection if i in present]
        if keep:
            self.tree.selection_set(keep)
        if self._sort_state:
            key, desc = self._sort_state
            self._apply_sort(key, desc)
        self._stripe()
        if yview and yview[0] > 0:
            self.tree.yview_moveto(yview[0])
        if rows:
            self._empty.place_forget()
        else:
            self._empty.configure(text=empty_text)
            self._empty.place(relx=0.5, rely=0.5, anchor="center")
        self._update_check_heading()

    def selected(self) -> list[str]:
        return list(self.tree.selection())

    def get_checked(self) -> list[str]:
        order = []
        for iid in self.tree.get_children(""):
            order.append(iid)
            order.extend(self.tree.get_children(iid))
        return [i for i in order if i in self.checked]

    def set_checked(self, iids, value: bool = True) -> None:
        for iid in iids:
            iid = str(iid)
            if iid not in self._checkable_rows:
                continue
            if value:
                self.checked.add(iid)
            else:
                self.checked.discard(iid)
            self.tree.set(iid, "_chk", CHECK_ON if value else CHECK_OFF)
        self._update_check_heading()
        if self._on_check:
            self._on_check(self.get_checked())

    def clear_checks(self) -> None:
        self.set_checked(list(self.checked), False)

    # --- сортировка ---
    def sort_by(self, key: str) -> None:
        desc = True
        if self._sort_state and self._sort_state[0] == key:
            desc = not self._sort_state[1]
        self._sort_state = (key, desc)
        self._apply_sort(key, desc)
        self._stripe()

    def _apply_sort(self, key: str, desc: bool) -> None:
        idx = [c[0] for c in self._columns].index(key)

        def sort_key(iid):
            value = self._sort_values.get(iid, [None] * (idx + 1))[idx]
            if isinstance(value, (int, float)):
                return (0, value, "")
            return (1, 0, str(value).casefold())

        items = list(self.tree.get_children(""))
        items.sort(key=sort_key, reverse=desc)
        for pos, iid in enumerate(items):
            self.tree.move(iid, "", pos)
        for k, title, *_rest in self._columns:
            arrow = (" ▼" if desc else " ▲") if k == key else ""
            self.tree.heading(k, text=title + arrow)

    def _stripe(self) -> None:
        for n, iid in enumerate(self.tree.get_children("")):
            tags = [t for t in self.tree.item(iid, "tags") if t != "odd"]
            if n % 2 and "group" not in tags:
                tags.append("odd")
            self.tree.item(iid, tags=tags)

    # --- галочки ---
    def _on_click(self, event) -> None:
        if not self._checkable:
            return
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self._checkable_rows:
            return
        self.set_checked([iid], iid not in self.checked)
        return "break"

    def _toggle_all(self) -> None:
        if not self._checkable_rows:
            return
        all_on = self._checkable_rows <= self.checked
        self.set_checked(list(self._checkable_rows), not all_on)

    def _update_check_heading(self) -> None:
        if self._checkable:
            on = bool(self._checkable_rows) and self._checkable_rows <= self.checked
            self.tree.heading("_chk", text=CHECK_ON if on else CHECK_OFF)

    def _double(self, event, callback) -> None:
        iid = self.tree.identify_row(event.y)
        if iid:
            callback(iid)


# --- Диалоги -------------------------------------------------------------------------


class _Dialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, message: str, items=None, buttons=(), level: str = "info", note: str | None = None,
                 option: tuple[str, bool] | None = None, items_height: int = 220):
        super().__init__(parent)
        self.result = False
        self.option_var = tk.BooleanVar(value=bool(option and option[1]))
        self.title(title)
        self.configure(fg_color=T.CARD)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        try:
            from winopt.shortcut import icon_path

            if icon_path().exists():
                self.iconbitmap(str(icon_path()))
        except Exception:
            pass
        color = T.LEVEL_COLORS.get(level, T.BLUE)
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=24, pady=(22, 18))
        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x")
        badge = {"ok": "✓", "info": "i", "warn": "!", "danger": "!"}.get(level, "i")
        ctk.CTkLabel(head, text=badge, width=34, height=34, corner_radius=17, fg_color=T.blend(color, T.CARD, 0.2), text_color=color, font=T.font(16, "bold")).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(head, text=title, font=T.font(18, "bold"), text_color=T.TEXT, anchor="w").pack(side="left")
        ctk.CTkLabel(wrap, text=message, font=T.font(13), text_color=T.TEXT, justify="left", anchor="w", wraplength=520).pack(fill="x", pady=(14, 6))
        if items:
            box = ctk.CTkTextbox(wrap, width=540, height=min(items_height, 26 + 22 * len(items)), fg_color=T.CARD_HI, text_color=T.TEXT, font=T.font(12), corner_radius=10, border_width=0)
            box.insert("1.0", "\n".join(f"• {i}" for i in items))
            box.configure(state="disabled")
            box.pack(fill="x", pady=(4, 6))
        if note:
            ctk.CTkLabel(wrap, text=note, font=T.font(12), text_color=T.MUTED, justify="left", anchor="w", wraplength=520).pack(fill="x", pady=(2, 4))
        if option:
            ctk.CTkCheckBox(wrap, text=option[0], variable=self.option_var, font=T.font(13), text_color=T.TEXT,
                            fg_color=T.ACCENT, hover_color=T.ACCENT, border_color=T.BORDER, checkmark_color=T.BG).pack(anchor="w", pady=(8, 0))
        row = ctk.CTkFrame(wrap, fg_color="transparent")
        row.pack(fill="x", pady=(14, 0))
        first = None
        for text, value, kind in reversed(list(buttons)):
            b = button(row, text, command=lambda v=value: self._close(v), kind=kind, width=130)
            b.pack(side="right", padx=(8, 0))
            if value and first is None:
                first = b
        self.bind("<Escape>", lambda _e: self._close(False))
        self.protocol("WM_DELETE_WINDOW", lambda: self._close(False))
        self.update_idletasks()
        top = parent.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.winfo_width()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.after(30, self._grab)

    def _grab(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            pass

    def _close(self, value: bool) -> None:
        self.result = value
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def ask_with_option(parent, title: str, message: str, items=None, option: tuple[str, bool] = ("", True), confirm: str = "Подтвердить",
                    cancel: str = "Отмена", danger: bool = False, note: str | None = None) -> tuple[bool, bool]:
    """Диалог подтверждения с одной галочкой. Возвращает (подтверждено, галочка)."""
    dlg = _Dialog(parent, title, message, items, buttons=[(cancel, False, "secondary"), (confirm, True, "danger" if danger else "primary")],
                  level="warn" if danger else "info", note=note, option=option, items_height=260)
    parent.wait_window(dlg)
    return bool(dlg.result), bool(dlg.option_var.get())


def ask(parent, title: str, message: str, items=None, confirm: str = "Подтвердить", cancel: str = "Отмена",
        danger: bool = False, note: str | None = None, level: str | None = None) -> bool:
    dlg = _Dialog(parent, title, message, items, buttons=[(cancel, False, "secondary"), (confirm, True, "danger" if danger else "primary")],
                  level=level or ("warn" if danger else "info"), note=note)
    parent.wait_window(dlg)
    return dlg.result


def inform(parent, title: str, message: str, items=None, level: str = "ok", note: str | None = None) -> None:
    dlg = _Dialog(parent, title, message, items, buttons=[("OK", True, "primary")], level=level, note=note)
    parent.wait_window(dlg)


def short(text: str, limit: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def text_bar(ratio: float, width: int = 14) -> str:
    filled = int(round(max(0.0, min(1.0, ratio)) * width))
    return "█" * filled + "░" * (width - filled)
