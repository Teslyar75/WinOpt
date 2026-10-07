"""Рекомендации по пунктам автозагрузки."""

from __future__ import annotations

from dataclasses import dataclass

from winopt.actions import is_caution, is_protected
from winopt.startup import StartupItem

HEAVY_MARKERS = (
    "docker desktop",
    "torrserver",
    "zona",
    "vmware",
    "virtualbox",
    "steam",
    "epicgameslauncher",
)

BROWSER_MARKERS = (
    "opera",
    "chrome",
    "msedge",
    "firefox",
    "brave",
    "yandex",
)

MESSENGER_MARKERS = (
    "viber",
    "telegram",
    "discord",
    "whatsapp",
    "skype",
)

UPDATER_MARKERS = (
    "updater",
    "autoupdate",
    "cometupdater",
)

OPTIONAL_MARKERS = (
    "onedrive",
    "spotify",
    "comet",
    "perplexity",
)


@dataclass(frozen=True)
class StartupAdvice:
    label: str
    reason: str
    recommend_disable: bool
    priority: int


def analyze_startup(item: StartupItem) -> StartupAdvice | None:
    if is_protected(item):
        return None
    if is_caution(item):
        return StartupAdvice(
            label="системный",
            reason="Компонент Windows или драйвер — отключайте только осознанно",
            recommend_disable=False,
            priority=0,
        )

    blob = f"{item.name} {item.command} {item.location}".casefold().replace("/", "\\")

    for marker in UPDATER_MARKERS:
        if marker in blob:
            return StartupAdvice(
                label="обновлятор",
                reason="Фоновый обновлятор, обычно не нужен при каждом входе",
                recommend_disable=True,
                priority=80,
            )

    for marker in HEAVY_MARKERS:
        if marker in blob:
            return StartupAdvice(
                label="тяжёлая",
                reason="Заметно удлиняет загрузку и может грузить систему",
                recommend_disable=True,
                priority=70,
            )

    for marker in BROWSER_MARKERS:
        if marker in blob and ("autostart" in blob or "autolaunch" in blob or item.kind == "registry"):
            return StartupAdvice(
                label="браузер",
                reason="Браузер можно запускать вручную, когда нужен",
                recommend_disable=True,
                priority=60,
            )

    for marker in MESSENGER_MARKERS:
        if marker in blob:
            return StartupAdvice(
                label="мессенджер",
                reason="Можно отключить, если не нужны уведомления сразу после входа",
                recommend_disable=True,
                priority=55,
            )

    for marker in OPTIONAL_MARKERS:
        if marker in blob:
            return StartupAdvice(
                label="по желанию",
                reason="Не обязательна для работы Windows — решайте по своим задачам",
                recommend_disable=True,
                priority=40,
            )

    if item.kind == "scheduled_task" and "autoupdate" in blob:
        return StartupAdvice(
            label="задача обновления",
            reason="Планировщик для автообновления — часто можно отключить",
            recommend_disable=True,
            priority=65,
        )

    return StartupAdvice(
        label="обычная",
        reason="Нет явных признаков лишней нагрузки",
        recommend_disable=False,
        priority=0,
    )


def is_recommended(item: StartupItem) -> bool:
    advice = analyze_startup(item)
    return advice is not None and advice.recommend_disable and advice.priority >= 40
