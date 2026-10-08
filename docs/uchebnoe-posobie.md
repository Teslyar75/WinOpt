# Учебное пособие: как написать программу вроде WinOpt

Версия программы, на которой основан гайд: **1.1.0**  
Репозиторий: [github.com/Teslyar75/WinOpt](https://github.com/Teslyar75/WinOpt)

> **Как пользоваться ссылками.** Почти каждое имя файла и функции кликабельно.  
> Относительные пути (`../winopt/...`) открываются в Cursor / VS Code и на GitHub.  
> Суффикс `#L24` ведёт к конкретной строке (например [`run_powershell`](../winopt/winutil.py#L24)).  
> На GitHub то же самое:  
> `https://github.com/Teslyar75/WinOpt/blob/main/winopt/winutil.py#L24`

Это не «шпаргалка скопируй-вставь», а дорожная карта студента: **в каком порядке думать**, **какие модули за что отвечают** и **какие правила безопасности нельзя нарушать**. Рядом лежат справочники:

- [docs/README.txt](README.txt) — что умеет готовая программа и команды CLI  
- [docs/opisanie-fajlov.txt](opisanie-fajlov.txt) — краткий каталог файлов  
- [Быстрый индекс файлов](#быстрый-индекс-всех-файлов) — все исходники одним списком ссылок  

Ниже — как **собрать такую программу с нуля**.

### Оглавление

1. [Что вы строите](#1-что-вы-строите)  
2. [Стек и минимальные знания](#2-стек-и-минимальные-знания)  
3. [Архитектура: два слоя](#3-архитектура-два-слоя)  
4. [Структура проекта](#4-структура-проекта-карта)  
5. [Порядок разработки](#5-порядок-разработки-учебный-план)  
6. [Ключевые паттерны](#6-ключевые-паттерны-запомните)  
7. [Описание файлов](#7-описание-файлов-что-писать-и-чему-учиться)  
8. [Мини-проекты](#8-мини-проекты-если-пишете-такую-же-по-частям)  
9. [Типичные ошибки](#9-типичные-ошибки-студентов)  
10. [Как читать исходники](#10-как-читать-исходники-эффективно)  
11. [Чеклист](#11-чеклист-я-написал-аналог)  
12. [Оговорка](#12-юридическая-и-этическая-оговорка-для-учёбы)  
13. [Куда смотреть дальше](#13-куда-смотреть-дальше)  

---

## 1. Что вы строите

WinOpt — настольная утилита для Windows 10/11 на Python ([витрина на GitHub](https://github.com/Teslyar75/WinOpt), [README.md](../README.md)):

1. **показывает** живое состояние ПК — см. [`LiveSampler`](../winopt/system.py#L38), страницу [Панель](../winopt/ui/pages/dashboard.py#L37);
2. **предлагает** безопасные действия — [очистка](../winopt/cleanup.py), [автозагрузка](../winopt/actions.py), [службы](../winopt/services.py);
3. **ничего не меняет** без подтверждения — диалоги [`ask`](../winopt/ui/widgets.py#L573) / [`ask_with_option`](../winopt/ui/widgets.py#L564).

Главный принцип продукта (запишите на стену):

> Диагностика и бережные действия ≠ «чистильщик реестра» и ≠ антивирус.

### Чего программа сознательно НЕ делает

- не чистит реестр «для ускорения»;
- не удаляет файлы пользователя безвозвратно (кроме заведомо мусорных TEMP/кэшей) — пользовательские файлы идут в [Корзину](../winopt/recycle.py#L52);
- не завершает системные процессы — см. [`can_terminate`](../winopt/processes.py#L187);
- не трогает службы драйверов и антивирусов — [`PROTECTED_SERVICES`](../winopt/services.py#L42);
- не отправляет данные в интернет.

Если при учебной работе хочется «ускорить в 10 раз» — остановитесь: вы пишете **инструмент с прозрачными действиями**, а не магическую кнопку.

---

## 2. Стек и минимальные знания

| Инструмент | Зачем | Где в проекте |
|------------|--------|----------------|
| Python 3.10+ | язык программы | весь пакет [`winopt/`](../winopt/) |
| [`psutil`](https://psutil.readthedocs.io/) | процессы, CPU, RAM, диски, сеть, батарея | [`system.py`](../winopt/system.py), [`processes.py`](../winopt/processes.py), [`network.py`](../winopt/network.py) |
| [`customtkinter`](https://customtkinter.tomschimansky.com/) | современный GUI | [`ui/app.py`](../winopt/ui/app.py), [`ui/widgets.py`](../winopt/ui/widgets.py) |
| PowerShell (из Python) | реестр, AppX, SMART, службы | [`run_powershell`](../winopt/winutil.py#L24), [`programs._PS_SCRIPT`](../winopt/programs.py#L22) |
| `ctypes` / `shell32` | админ, Корзина, ярлыки | [`is_admin`](../winopt/winutil.py#L64), [`recycle.py`](../winopt/recycle.py), [`shortcut.py`](../winopt/shortcut.py) |

Зависимости зафиксированы в [`requirements.txt`](../requirements.txt).

Полезно заранее понимать:

- пакеты Python (`python -m package`) — вход [`__main__._entry`](../winopt/__main__.py#L6);
- потоки (`threading`) — [`WinOptApp.run_task`](../winopt/ui/app.py#L278);
- очередь сообщений UI ← фон — [`TaskContext`](../winopt/ui/app.py#L48);
- JSON / JSONL — [`history.log_action`](../winopt/history.py#L35);
- основы Windows: TEMP, Run, Uninstall, UAC.

---

## 3. Архитектура: два слоя

Самая важная идея проекта:

```
┌─────────────────────────────────────────────┐
│  UI  (winopt/ui/)                           │
│  кнопки, таблицы, диалоги, анимации         │
│  НЕ знает деталей PowerShell и реестра      │
└─────────────────┬───────────────────────────┘
                  │ вызывает функции
┌─────────────────▼───────────────────────────┐
│  Логика  (winopt/*.py)                      │
│  cleanup, programs, startup, system, …      │
│  можно тестировать из CLI без окна          │
└─────────────────────────────────────────────┘
```

| Слой | Папка | Примеры |
|------|--------|---------|
| UI | [`winopt/ui/`](../winopt/ui/) | [`app.py`](../winopt/ui/app.py), [`pages/cleanup.py`](../winopt/ui/pages/cleanup.py) |
| Логика | [`winopt/*.py`](../winopt/) | [`cleanup.py`](../winopt/cleanup.py), [`programs.py`](../winopt/programs.py) |

**Правило:** страница UI только рисует и спрашивает подтверждение;  
**модуль логики** сканирует, считает размеры, меняет систему и пишет журнал.

Благодаря этому:

- `python -m winopt cleanup --scan` работает без GUI — обработчик [`cmd_cleanup`](../winopt/cli.py#L220) → [`scan_categories`](../winopt/cleanup.py#L271);
- баг в кнопке не ломает алгоритм очистки;
- студент может сначала написать CLI ([`cli.py`](../winopt/cli.py)), потом «одеть» окно ([`gui.py`](../winopt/gui.py)).

Точка входа:

```
python -m winopt
       → winopt/__main__.py          (_entry)
            → без аргументов: gui.run_gui()
            → с аргументами:  cli.main()
```

Ссылки:

- [`__main__._entry`](../winopt/__main__.py#L6)  
- [`gui.run_gui`](../winopt/gui.py#L9) → [`ui.app.run_gui`](../winopt/ui/app.py#L472)  
- [`cli.main`](../winopt/cli.py#L23)  

---

## 4. Структура проекта (карта)

Каждая строка — ссылка на файл (или папку через типичный файл внутри).

```
WinOpt/
├── requirements.txt                 → зависимости
├── README.md                        → витрина GitHub
├── assets/                          → иконки
├── docs/                            → эта папка
├── screenshots/                     → скриншоты README
├── data/                            → локальный CSV (не в git)
└── winopt/                          → исходный код
    ├── каркас, утилиты, логика…
    └── ui/ + pages/
```

| Путь | Ссылка |
|------|--------|
| зависимости | [`requirements.txt`](../requirements.txt) |
| README | [`README.md`](../README.md) |
| иконка ICO | [`assets/winopt.ico`](../assets/winopt.ico) |
| иконка PNG | [`assets/winopt-icon.png`](../assets/winopt-icon.png) |
| этот гайд | [`docs/uchebnoe-posobie.md`](uchebnoe-posobie.md) |
| док пользователя | [`docs/README.txt`](README.txt) |
| каталог файлов | [`docs/opisanie-fajlov.txt`](opisanie-fajlov.txt) |
| скриншоты | [`screenshots/`](../screenshots/dashboard.png) (пример: [dashboard](../screenshots/dashboard.png)) |
| пакет | [`winopt/__init__.py`](../winopt/__init__.py) → [`__version__`](../winopt/__init__.py#L3) |
| вход | [`winopt/__main__.py`](../winopt/__main__.py) |
| CLI | [`winopt/cli.py`](../winopt/cli.py) |
| GUI-обёртка | [`winopt/gui.py`](../winopt/gui.py) |
| Windows-утилиты | [`winopt/winutil.py`](../winopt/winutil.py) |
| журнал | [`winopt/history.py`](../winopt/history.py) |
| Корзина | [`winopt/recycle.py`](../winopt/recycle.py) |
| ярлык | [`winopt/shortcut.py`](../winopt/shortcut.py) |
| метрики | [`winopt/system.py`](../winopt/system.py) |
| процессы | [`winopt/processes.py`](../winopt/processes.py) |
| эвристики | [`winopt/heuristics.py`](../winopt/heuristics.py) |
| метаданные exe | [`winopt/meta.py`](../winopt/meta.py) |
| Защитник | [`winopt/defender.py`](../winopt/defender.py) |
| точки восстановления | [`winopt/restore.py`](../winopt/restore.py) |
| чтение автозагрузки | [`winopt/startup.py`](../winopt/startup.py) |
| действия автозагрузки | [`winopt/actions.py`](../winopt/actions.py) |
| советы автозагрузки | [`winopt/advice.py`](../winopt/advice.py) |
| службы | [`winopt/services.py`](../winopt/services.py) |
| очистка | [`winopt/cleanup.py`](../winopt/cleanup.py) |
| быстрая оптимизация | [`winopt/optimize.py`](../winopt/optimize.py) |
| диски | [`winopt/disk.py`](../winopt/disk.py) |
| дубликаты | [`winopt/duplicates.py`](../winopt/duplicates.py) |
| программы | [`winopt/programs.py`](../winopt/programs.py) |
| сеть | [`winopt/network.py`](../winopt/network.py) |
| здоровье ПК | [`winopt/health.py`](../winopt/health.py) |
| тема UI | [`winopt/ui/theme.py`](../winopt/ui/theme.py) |
| виджеты | [`winopt/ui/widgets.py`](../winopt/ui/widgets.py) |
| главное окно | [`winopt/ui/app.py`](../winopt/ui/app.py) |
| реестр страниц | [`winopt/ui/pages/__init__.py`](../winopt/ui/pages/__init__.py) |

Данные программы в рантайме (`%LOCALAPPDATA%\WinOpt\` — создаёт [`data_dir()`](../winopt/winutil.py#L109)):

- `history.jsonl` — пишет [`log_action`](../winopt/history.py#L35)  
- `disabled.json` — [`load_disabled` / `save_disabled`](../winopt/actions.py#L50)  
- `services_changed.json` — [`load_changed`](../winopt/services.py#L160)  
- `reports\` — [`reports_dir`](../winopt/winutil.py#L116), отчёты [`optimize._write_report`](../winopt/optimize.py#L82)  

---

## 5. Порядок разработки (учебный план)

Пишите **по этапам**. Каждый этап должен запускаться и что-то показывать.

### Этап A — скелет пакета (1–2 занятия)

1. Создайте папку `winopt/` и файлы [`__init__.py`](../winopt/__init__.py) ([`__version__`](../winopt/__init__.py#L3)), [`__main__.py`](../winopt/__main__.py).  
2. Сделайте [`cli.py`](../winopt/cli.py) с одной командой, например [`cmd_resources`](../winopt/cli.py#L170) через `psutil`.  
3. Проверьте: `python -m winopt resources`.

**Цель:** понять пакет и точку входа — [`_entry`](../winopt/__main__.py#L6).

### Этап B — утилиты Windows ([`winutil.py`](../winopt/winutil.py))

Реализуйте по очереди:

- [`run_powershell`](../winopt/winutil.py#L24) — без мигающей консоли ([`CREATE_NO_WINDOW`](../winopt/winutil.py#L21));
- [`is_admin`](../winopt/winutil.py#L64) / [`relaunch_as_admin`](../winopt/winutil.py#L73);
- [`data_dir`](../winopt/winutil.py#L109) → `%LOCALAPPDATA%\WinOpt`;
- [`format_size`](../winopt/winutil.py#L122), [`format_rate`](../winopt/winutil.py#L135).

**Цель:** один раз решить «как говорить с Windows», потом переиспользовать везде.

### Этап C — только чтение (диагностика)

Модули без изменения системы:

| Модуль | Задача | Якоря в коде |
|--------|--------|--------------|
| [`system.py`](../winopt/system.py) | живые метрики | [`HISTORY_POINTS`](../winopt/system.py#L15), [`LiveSampler`](../winopt/system.py#L38), [`assess_health`](../winopt/system.py#L205) |
| [`processes.py`](../winopt/processes.py) | список + защита | [`iter_processes`](../winopt/processes.py#L34), [`can_terminate`](../winopt/processes.py#L187) |
| [`startup.py`](../winopt/startup.py) | автозагрузка | [`collect_startup`](../winopt/startup.py#L103), [`pretty_name`](../winopt/startup.py#L89) |
| [`network.py`](../winopt/network.py) | TCP | [`collect_connections`](../winopt/network.py#L22) |
| [`disk.py`](../winopt/disk.py) | диски / папки | [`list_drives`](../winopt/disk.py#L80), [`scan_largest_folders`](../winopt/disk.py#L109) |
| [`programs.py`](../winopt/programs.py) (часть) | список | [`_PS_SCRIPT`](../winopt/programs.py#L22), [`list_programs`](../winopt/programs.py#L218) |
| [`health.py`](../winopt/health.py) | SMART / батарея | [`physical_disks`](../winopt/health.py#L66), [`battery_health`](../winopt/health.py#L114) |

Сразу добавьте вывод в CLI — см. команды в [`cli.main`](../winopt/cli.py#L23).

### Этап D — безопасные изменения

Только после подтверждения и с возможностью отката:

1. [`history.py`](../winopt/history.py) — [`log_action`](../winopt/history.py#L35);  
2. [`recycle.py`](../winopt/recycle.py) — [`send_to_recycle_bin`](../winopt/recycle.py#L52);  
3. [`cleanup.py`](../winopt/cleanup.py) — [`ALLOWED_LEAF_NAMES`](../winopt/cleanup.py#L23), [`scan_categories`](../winopt/cleanup.py#L271), [`clean_categories`](../winopt/cleanup.py#L308);  
4. [`actions.py`](../winopt/actions.py) + [`advice.py`](../winopt/advice.py) — [`disable_item`](../winopt/actions.py#L94) / [`restore_record`](../winopt/actions.py#L125), [`analyze_startup`](../winopt/advice.py#L59);  
5. [`services.py`](../winopt/services.py) — [`set_service_manual`](../winopt/services.py#L184), [`revert_service`](../winopt/services.py#L203);  
6. [`restore.py`](../winopt/restore.py) — [`create_restore_point`](../winopt/restore.py#L44);  
7. [`programs.py`](../winopt/programs.py) (удаление) — [`lock_reason_for`](../winopt/programs.py#L196), [`uninstall_program`](../winopt/programs.py#L446).

### Этап E — GUI

1. [`theme.py`](../winopt/ui/theme.py) + виджеты в [`widgets.py`](../winopt/ui/widgets.py) — [`RingGauge`](../winopt/ui/widgets.py#L144), [`LineChart`](../winopt/ui/widgets.py#L221), [`DataTable`](../winopt/ui/widgets.py#L315);  
2. [`app.py`](../winopt/ui/app.py): [`NAV`](../winopt/ui/app.py#L18), [`Page`](../winopt/ui/app.py#L68), [`run_task`](../winopt/ui/app.py#L278);  
3. страницы: сначала [`dashboard`](../winopt/ui/pages/dashboard.py) и [`cleanup`](../winopt/ui/pages/cleanup.py); реестр — [`PAGE_CLASSES`](../winopt/ui/pages/__init__.py#L16);  
4. [`gui.py`](../winopt/gui.py) — дружелюбная ошибка без `customtkinter`.

### Этап F — полировка

- ярлык — [`install_desktop_shortcut`](../winopt/shortcut.py#L51);  
- быстрая оптимизация — [`build_plan`](../winopt/optimize.py#L47) / [`run_plan`](../winopt/optimize.py#L67);  
- эвристики — [`evaluate_process`](../winopt/heuristics.py#L65), [`collect_file_meta`](../winopt/meta.py#L80), [`get_defender_status`](../winopt/defender.py#L59);  
- [`README.md`](../README.md) и [`screenshots/`](../screenshots/optimize.png).

---

## 6. Ключевые паттерны (запомните)

### 6.1. UI не блокировать

Долгое сканирование диска / PowerShell — в фоне:

```text
кнопка → app.run_task(key, work, on_ok, on_err)
       → threading + queue
       → в UI-потоке обновить таблицу
```

Смотрите:

- [`TaskContext`](../winopt/ui/app.py#L48)  
- [`WinOptApp.run_task`](../winopt/ui/app.py#L278)  
- пример вызова: [скан очистки](../winopt/ui/pages/cleanup.py#L87), [список программ](../winopt/ui/pages/programs.py#L123)

### 6.2. Сначала scan, потом act

Для очистки и оптимизации:

1. посчитать — [`scan_categories`](../winopt/cleanup.py#L271) / [`build_plan`](../winopt/optimize.py#L47);  
2. показать диалог — [`ask`](../winopt/ui/widgets.py#L573);  
3. выполнить — [`clean_categories`](../winopt/cleanup.py#L308) / [`run_plan`](../winopt/optimize.py#L67).

UI-поток очистки: [`CleanupPage`](../winopt/ui/pages/cleanup.py#L20) → scan → confirm → run ([строка ~161](../winopt/ui/pages/cleanup.py#L161)).

### 6.3. Белый список путей

В [`cleanup.py`](../winopt/cleanup.py) удалять можно только внутри заранее известных листьев — [`ALLOWED_LEAF_NAMES`](../winopt/cleanup.py#L23), проверка [`_is_safe_root`](../winopt/cleanup.py#L411).

### 6.4. Защищённые объекты

| Что защищаем | Где код |
|--------------|---------|
| системные процессы | [`can_terminate`](../winopt/processes.py#L187) |
| службы драйверов / AV | [`PROTECTED_SERVICES`](../winopt/services.py#L42), [`_categorize`](../winopt/services.py#L141) |
| ключевые программы | [`lock_reason_for`](../winopt/programs.py#L196) |
| автозагрузка Защитника | [`is_protected`](../winopt/actions.py#L81) |

### 6.5. Откат

| Действие | Хранение / код |
|----------|----------------|
| автозагрузка | [`disable_item`](../winopt/actions.py#L94) ↔ [`restore_record`](../winopt/actions.py#L125) |
| службы | [`set_service_manual`](../winopt/services.py#L184) ↔ [`revert_service`](../winopt/services.py#L203) |
| файлы пользователя | [`send_to_recycle_bin`](../winopt/recycle.py#L52) |
| точка восстановления | [`create_restore_point`](../winopt/restore.py#L44) |

### 6.6. PowerShell как «мост»

Тяжёлую выборку собрать скриптом в JSON (`$env:WINOPT_OUT`), в Python прочитать:

- программы: [`_PS_SCRIPT`](../winopt/programs.py#L22) → [`list_programs`](../winopt/programs.py#L218)  
- метаданные exe: [`meta._PS_SCRIPT`](../winopt/meta.py#L12) → [`collect_file_meta`](../winopt/meta.py#L80)  
- общий запуск: [`run_powershell`](../winopt/winutil.py#L24)  

---

## 7. Описание файлов: что писать и чему учиться

### Корень

| Файл | Содержание | Учебный смысл |
|------|------------|---------------|
| [`requirements.txt`](../requirements.txt) | зависимости | фиксировать окружение |
| [`README.md`](../README.md) | описание для людей | учиться объяснять продукт |
| [`assets/winopt.ico`](../assets/winopt.ico), [`winopt-icon.png`](../assets/winopt-icon.png) | иконка | «настоящая» программа |
| `data/programs-review.csv` | личные метки A/B | **не коммитить**; читает [`load_review`](../winopt/programs.py#L144) |

### Каркас пакета

| Файл | Роль | Ключевые якоря |
|------|------|----------------|
| [`winopt/__init__.py`](../winopt/__init__.py) | версия | [`__version__`](../winopt/__init__.py#L3) |
| [`winopt/__main__.py`](../winopt/__main__.py) | GUI vs CLI | [`_entry`](../winopt/__main__.py#L6) |
| [`winopt/cli.py`](../winopt/cli.py) | argparse | [`main`](../winopt/cli.py#L23), [`cmd_cleanup`](../winopt/cli.py#L220), [`cmd_report`](../winopt/cli.py#L335) |
| [`winopt/gui.py`](../winopt/gui.py) | безопасный импорт UI | [`run_gui`](../winopt/gui.py#L9) |

### Инфраструктура

| Файл | Роль | Якоря |
|------|------|-------|
| [`winutil.py`](../winopt/winutil.py) | PowerShell, админ, форматы | [`CREATE_NO_WINDOW`](../winopt/winutil.py#L21), [`run_powershell`](../winopt/winutil.py#L24), [`data_dir`](../winopt/winutil.py#L109) |
| [`history.py`](../winopt/history.py) | журнал JSONL | [`log_action`](../winopt/history.py#L35), [`read_history`](../winopt/history.py#L53) |
| [`recycle.py`](../winopt/recycle.py) | Корзина | [`send_to_recycle_bin`](../winopt/recycle.py#L52), [`empty_recycle_bin`](../winopt/recycle.py#L92) |
| [`shortcut.py`](../winopt/shortcut.py) | ярлык `.lnk` | [`install_desktop_shortcut`](../winopt/shortcut.py#L51), [`pythonw_path`](../winopt/shortcut.py#L20) |

### Диагностика и «здоровье»

| Файл | Роль | Якоря |
|------|------|-------|
| [`system.py`](../winopt/system.py) | метрики, индекс здоровья | [`Snapshot`](../winopt/system.py#L19), [`LiveSampler`](../winopt/system.py#L38), [`assess_health`](../winopt/system.py#L205) |
| [`processes.py`](../winopt/processes.py) | процессы | [`ProcessMonitor`](../winopt/processes.py#L135), [`terminate_process`](../winopt/processes.py#L203) |
| [`heuristics.py`](../winopt/heuristics.py) | баллы подозрительности | [`evaluate_process`](../winopt/heuristics.py#L65), [`score_level`](../winopt/heuristics.py#L162) |
| [`meta.py`](../winopt/meta.py) | Authenticode | [`FileMeta`](../winopt/meta.py#L61), [`collect_file_meta`](../winopt/meta.py#L80) |
| [`defender.py`](../winopt/defender.py) | Защитник | [`get_defender_status`](../winopt/defender.py#L59), [`start_quick_scan`](../winopt/defender.py#L75) |
| [`restore.py`](../winopt/restore.py) | точки восстановления | [`create_restore_point`](../winopt/restore.py#L44) |
| [`health.py`](../winopt/health.py) | SMART, батарея | [`physical_disks`](../winopt/health.py#L66), [`battery_report_html`](../winopt/health.py#L143) |
| [`network.py`](../winopt/network.py) | TCP | [`collect_connections`](../winopt/network.py#L22) |

### Автозагрузка и службы

| Файл | Роль | Якоря |
|------|------|-------|
| [`startup.py`](../winopt/startup.py) | **чтение** | [`collect_startup`](../winopt/startup.py#L103) |
| [`advice.py`](../winopt/advice.py) | политика / советы | [`analyze_startup`](../winopt/advice.py#L59) |
| [`actions.py`](../winopt/actions.py) | **запись** | [`disable_item`](../winopt/actions.py#L94), [`restore_record`](../winopt/actions.py#L125) |
| [`services.py`](../winopt/services.py) | службы | [`list_services`](../winopt/services.py#L104), [`set_service_manual`](../winopt/services.py#L184) |

Разделение read / write / policy — хороший пример для курсовой: [`startup`](../winopt/startup.py) · [`actions`](../winopt/actions.py) · [`advice`](../winopt/advice.py).

### Очистка и диски

| Файл | Роль | Якоря |
|------|------|-------|
| [`cleanup.py`](../winopt/cleanup.py) | scan → clean | [`CleanupCategory`](../winopt/cleanup.py#L44), [`list_categories`](../winopt/cleanup.py#L166), [`_is_safe_root`](../winopt/cleanup.py#L411) |
| [`optimize.py`](../winopt/optimize.py) | одна кнопка + отчёт | [`OptimizePlan`](../winopt/optimize.py#L28), [`build_plan`](../winopt/optimize.py#L47) |
| [`disk.py`](../winopt/disk.py) | диски, папки, large files | [`find_large_files`](../winopt/disk.py#L168) |
| [`duplicates.py`](../winopt/duplicates.py) | дубликаты | [`scan_duplicates`](../winopt/duplicates.py#L86), [`_file_hash`](../winopt/duplicates.py#L182) |

### Программы

| Файл | Роль | Якоря |
|------|------|-------|
| [`programs.py`](../winopt/programs.py) | список + удаление | [`InstalledProgram`](../winopt/programs.py#L82), [`build_removal_plan`](../winopt/programs.py#L362), [`uninstall_program`](../winopt/programs.py#L446), [`_remove_appx`](../winopt/programs.py#L455) |

Учитесь: программа **не** удаляет папку сама — запускает штатный деинсталлятор ([`_run_win32_uninstaller`](../winopt/programs.py#L472)).

### Интерфейс

| Файл | Роль | Якоря |
|------|------|-------|
| [`ui/theme.py`](../winopt/ui/theme.py) | палитра, шрифты | весь файл |
| [`ui/widgets.py`](../winopt/ui/widgets.py) | контролы | [`RingGauge`](../winopt/ui/widgets.py#L144), [`DataTable`](../winopt/ui/widgets.py#L315), [`ask`](../winopt/ui/widgets.py#L573) |
| [`ui/app.py`](../winopt/ui/app.py) | оболочка | [`NAV`](../winopt/ui/app.py#L18), [`Page`](../winopt/ui/app.py#L68), [`WinOptApp`](../winopt/ui/app.py#L130), [`run_task`](../winopt/ui/app.py#L278) |
| [`ui/pages/__init__.py`](../winopt/ui/pages/__init__.py) | реестр страниц | [`PAGE_CLASSES`](../winopt/ui/pages/__init__.py#L16) |

Шаблон страницы (базовый класс [`Page`](../winopt/ui/app.py#L68)):

1. [`build()`](../winopt/ui/app.py#L81) — виджеты при первом открытии;  
2. [`on_show()`](../winopt/ui/app.py#L84) — загрузить данные;  
3. [`on_tick(snapshot)`](../winopt/ui/app.py#L90) — живые цифры;  
4. кнопки → [`run_task`](../winopt/ui/app.py#L278) + [`ask`](../winopt/ui/widgets.py#L573).

Соответствие меню → файл:

| Ключ | Страница | Файл | Класс |
|------|----------|------|-------|
| `dashboard` | Панель | [`pages/dashboard.py`](../winopt/ui/pages/dashboard.py) | [`DashboardPage`](../winopt/ui/pages/dashboard.py#L37) |
| `optimize` | Оптимизация | [`pages/optimize.py`](../winopt/ui/pages/optimize.py) | [`OptimizePage`](../winopt/ui/pages/optimize.py#L16) |
| `processes` | Процессы | [`pages/processes.py`](../winopt/ui/pages/processes.py) | [`ProcessesPage`](../winopt/ui/pages/processes.py#L17) |
| `startup` | Автозагрузка | [`pages/startup.py`](../winopt/ui/pages/startup.py) | [`StartupPage`](../winopt/ui/pages/startup.py#L26) |
| `cleanup` | Очистка | [`pages/cleanup.py`](../winopt/ui/pages/cleanup.py) | [`CleanupPage`](../winopt/ui/pages/cleanup.py#L20) |
| `disk` | Диски и файлы | [`pages/disk.py`](../winopt/ui/pages/disk.py) | [`DiskPage`](../winopt/ui/pages/disk.py#L28) (+ [`DuplicatesView`](../winopt/ui/pages/disk.py#L233)) |
| `programs` | Программы | [`pages/programs.py`](../winopt/ui/pages/programs.py) | [`ProgramsPage`](../winopt/ui/pages/programs.py#L50) |
| `services` | Службы | [`pages/services.py`](../winopt/ui/pages/services.py) | [`ServicesPage`](../winopt/ui/pages/services.py#L16) |
| `network` | Сеть | [`pages/network.py`](../winopt/ui/pages/network.py) | [`NetworkPage`](../winopt/ui/pages/network.py#L18) |
| `security` | Безопасность | [`pages/security.py`](../winopt/ui/pages/security.py) | [`SecurityPage`](../winopt/ui/pages/security.py#L18) |
| `health` | Здоровье ПК | [`pages/health.py`](../winopt/ui/pages/health.py) | [`HealthPage`](../winopt/ui/pages/health.py#L15) |
| `journal` | Журнал | [`pages/journal.py`](../winopt/ui/pages/journal.py) | [`JournalPage`](../winopt/ui/pages/journal.py#L14) |

Скриншоты разделов: [optimize](../screenshots/optimize.png) · [processes](../screenshots/processes.png) · [startup](../screenshots/startup.png) · [cleanup](../screenshots/cleanup.png) · [disk](../screenshots/disk.png) · [programs](../screenshots/programs.png) · [security](../screenshots/security.png) · [health](../screenshots/health.png) · [journal](../screenshots/journal.png) · [dashboard](../screenshots/dashboard.png).

---

## 8. Мини-проекты (если пишете «такую же» по частям)

Можно сдать как серию лабораторных:

1. **Монитор ресурсов** — [`system.py`](../winopt/system.py) + [`dashboard.py`](../winopt/ui/pages/dashboard.py) ([`LiveSampler`](../winopt/system.py#L38), [`RingGauge`](../winopt/ui/widgets.py#L144)).  
2. **Диспетчер процессов** — [`processes.py`](../winopt/processes.py) + [`pages/processes.py`](../winopt/ui/pages/processes.py) ([`can_terminate`](../winopt/processes.py#L187)).  
3. **Менеджер автозагрузки** — [`startup`](../winopt/startup.py) / [`actions`](../winopt/actions.py) / [`pages/startup.py`](../winopt/ui/pages/startup.py).  
4. **Очистка TEMP** — [`cleanup.py`](../winopt/cleanup.py) + [`pages/cleanup.py`](../winopt/ui/pages/cleanup.py).  
5. **Анализатор диска** — [`disk.py`](../winopt/disk.py) + [`duplicates.py`](../winopt/duplicates.py) + [`pages/disk.py`](../winopt/ui/pages/disk.py).  
6. **Список программ** — [`programs.py`](../winopt/programs.py) + [`pages/programs.py`](../winopt/ui/pages/programs.py).  
7. **Сборка** — [`app.py`](../winopt/ui/app.py), [`history.py`](../winopt/history.py), [`shortcut.py`](../winopt/shortcut.py), [`cli.py`](../winopt/cli.py).

Критерий готовности каждого мини-проекта:

- есть режим «только посмотреть»;
- опасное действие с диалогом ([`ask`](../winopt/ui/widgets.py#L573));
- ошибка одного файла не роняет всё приложение;
- есть запись в журнал ([`log_action`](../winopt/history.py#L35), начиная с п.3–4).

---

## 9. Типичные ошибки студентов

1. **Удалять из UI-потока** → окно «зависает». Нужен [`run_task`](../winopt/ui/app.py#L278).  
2. **`os.remove` всего подряд** → потеря данных. Белый список ([`ALLOWED_LEAF_NAMES`](../winopt/cleanup.py#L23)) + [`Корзина`](../winopt/recycle.py#L52).  
3. **Завершать `csrss` / `explorer` «для оптимизации»** → не делать; см. [`can_terminate`](../winopt/processes.py#L187).  
4. **Смешивать логику и виджеты** в одном файле → держите [`cleanup.py`](../winopt/cleanup.py) отдельно от [`pages/cleanup.py`](../winopt/ui/pages/cleanup.py).  
5. **Обещать антивирус** через эвристики → только подсказки: [`evaluate_process`](../winopt/heuristics.py#L65).  
6. **Хардкод `C:\Users\Имя\...`** → [`data_dir`](../winopt/winutil.py#L109), `Path.home()`, `%TEMP%`.  
7. **Забыть UTF-8 в PowerShell** → префикс в [`run_powershell`](../winopt/winutil.py#L24).

---

## 10. Как читать исходники эффективно

Рекомендуемый порядок (каждый пункт — цепочка ссылок):

1. [`__main__.py`](../winopt/__main__.py) → [`gui.py`](../winopt/gui.py) → [`ui/app.py`](../winopt/ui/app.py) (как живёт окно)  
2. [`winutil.py`](../winopt/winutil.py) (инфраструктура)  
3. [`system.py`](../winopt/system.py) + [`pages/dashboard.py`](../winopt/ui/pages/dashboard.py) (данные → картинка)  
4. [`cleanup.py`](../winopt/cleanup.py) + [`pages/cleanup.py`](../winopt/ui/pages/cleanup.py) (scan / confirm / act)  
5. [`startup.py`](../winopt/startup.py) / [`actions.py`](../winopt/actions.py) / [`pages/startup.py`](../winopt/ui/pages/startup.py) (откат)  
6. [`programs.py`](../winopt/programs.py) + [`pages/programs.py`](../winopt/ui/pages/programs.py) (PowerShell + защита)  
7. остальное по интересу — [быстрый индекс](#быстрый-индекс-всех-файлов)

Параллельно держите открытым [`opisanie-fajlov.txt`](opisanie-fajlov.txt).

---

## 11. Чеклист «я написал аналог»

- [ ] Запуск: `python -m myapp` открывает окно (аналог [`_entry`](../winopt/__main__.py#L6))  
- [ ] CLI хотя бы для одной диагностики (аналог [`cli.py`](../winopt/cli.py))  
- [ ] Живые CPU/RAM ([`LiveSampler`](../winopt/system.py#L38))  
- [ ] Очистка с предпросмотром размера ([`scan_categories`](../winopt/cleanup.py#L271))  
- [ ] Автозагрузка с возвратом ([`restore_record`](../winopt/actions.py#L125))  
- [ ] Процессы: системные нельзя завершить ([`can_terminate`](../winopt/processes.py#L187))  
- [ ] Пользовательские файлы → Корзина ([`send_to_recycle_bin`](../winopt/recycle.py#L52))  
- [ ] Журнал действий ([`log_action`](../winopt/history.py#L35))  
- [ ] Тяжёлые операции в фоне ([`run_task`](../winopt/ui/app.py#L278))  
- [ ] Нет сетевой «телеметрии» без явной нужды  
- [ ] README с принципами безопасности (как [`README.md`](../README.md))  

---

## 12. Юридическая и этическая оговорка для учёбы

Утилиты, меняющие систему, легко превратить во вред. В учебной версии:

- тестируйте на виртуальной машине или копии Windows;
- не распространяйте сборку с отключёнными подтверждениями;
- не добавляйте скрытое удаление «для красоты демо».

Лицензия исходного WinOpt пока не выбрана — при публикации своего форка уточните права автора ([репозиторий](https://github.com/Teslyar75/WinOpt)) или напишите код самостоятельно по этому пособию.

---

## 13. Куда смотреть дальше

| Вопрос | Ссылки |
|--------|--------|
| Как установить и запустить? | [`README.md`](../README.md), [`docs/README.txt`](README.txt) |
| Что в каждом файле коротко? | [`opisanie-fajlov.txt`](opisanie-fajlov.txt) |
| Как устроен UI-поток? | [`ui/app.py`](../winopt/ui/app.py) → [`run_task`](../winopt/ui/app.py#L278) |
| Как устроена безопасная очистка? | [`cleanup.py`](../winopt/cleanup.py) (докстринг с [начала файла](../winopt/cleanup.py#L1)), [`_is_safe_root`](../winopt/cleanup.py#L411) |
| Как устроено удаление программ? | [`programs.py`](../winopt/programs.py#L1), [`lock_reason_for`](../winopt/programs.py#L196), [`uninstall_program`](../winopt/programs.py#L446) |
| Как устроен вход в программу? | [`__main__.py`](../winopt/__main__.py#L6) |

Удачи. Пишите сначала **маленькую работающую диагностику**, потом добавляйте кнопки — так вы реально повторите путь этой программы, а не только её файловое дерево.

---

## Быстрый индекс всех файлов

### Документация и корень

- [`README.md`](../README.md)  
- [`requirements.txt`](../requirements.txt)  
- [`docs/README.txt`](README.txt)  
- [`docs/opisanie-fajlov.txt`](opisanie-fajlov.txt)  
- [`docs/uchebnoe-posobie.md`](uchebnoe-posobie.md) *(этот файл)*  
- [`assets/winopt.ico`](../assets/winopt.ico) · [`assets/winopt-icon.png`](../assets/winopt-icon.png)  
- [`.gitignore`](../.gitignore)  

### Логика `winopt/`

- [`__init__.py`](../winopt/__init__.py) · [`__main__.py`](../winopt/__main__.py) · [`cli.py`](../winopt/cli.py) · [`gui.py`](../winopt/gui.py)  
- [`winutil.py`](../winopt/winutil.py) · [`history.py`](../winopt/history.py) · [`recycle.py`](../winopt/recycle.py) · [`shortcut.py`](../winopt/shortcut.py)  
- [`system.py`](../winopt/system.py) · [`processes.py`](../winopt/processes.py) · [`heuristics.py`](../winopt/heuristics.py) · [`meta.py`](../winopt/meta.py)  
- [`defender.py`](../winopt/defender.py) · [`restore.py`](../winopt/restore.py) · [`health.py`](../winopt/health.py) · [`network.py`](../winopt/network.py)  
- [`startup.py`](../winopt/startup.py) · [`actions.py`](../winopt/actions.py) · [`advice.py`](../winopt/advice.py) · [`services.py`](../winopt/services.py)  
- [`cleanup.py`](../winopt/cleanup.py) · [`optimize.py`](../winopt/optimize.py) · [`disk.py`](../winopt/disk.py) · [`duplicates.py`](../winopt/duplicates.py)  
- [`programs.py`](../winopt/programs.py)  

### UI

- [`ui/__init__.py`](../winopt/ui/__init__.py) · [`ui/theme.py`](../winopt/ui/theme.py) · [`ui/widgets.py`](../winopt/ui/widgets.py) · [`ui/app.py`](../winopt/ui/app.py)  
- [`ui/pages/__init__.py`](../winopt/ui/pages/__init__.py)  
- [`dashboard`](../winopt/ui/pages/dashboard.py) · [`optimize`](../winopt/ui/pages/optimize.py) · [`processes`](../winopt/ui/pages/processes.py) · [`startup`](../winopt/ui/pages/startup.py)  
- [`cleanup`](../winopt/ui/pages/cleanup.py) · [`disk`](../winopt/ui/pages/disk.py) · [`programs`](../winopt/ui/pages/programs.py) · [`services`](../winopt/ui/pages/services.py)  
- [`network`](../winopt/ui/pages/network.py) · [`security`](../winopt/ui/pages/security.py) · [`health`](../winopt/ui/pages/health.py) · [`journal`](../winopt/ui/pages/journal.py)  

### Ключевые фрагменты (шпаргалка якорей)

| Тема | Ссылка на строку |
|------|------------------|
| Версия | [`__version__`](../winopt/__init__.py#L3) |
| Вход | [`_entry`](../winopt/__main__.py#L6) |
| PowerShell без окна | [`run_powershell`](../winopt/winutil.py#L24) |
| Права админа | [`is_admin`](../winopt/winutil.py#L64) |
| Папка данных | [`data_dir`](../winopt/winutil.py#L109) |
| Живые метрики | [`LiveSampler`](../winopt/system.py#L38) |
| Фоновая задача UI | [`run_task`](../winopt/ui/app.py#L278) |
| Базовая страница | [`Page`](../winopt/ui/app.py#L68) |
| Реестр страниц | [`PAGE_CLASSES`](../winopt/ui/pages/__init__.py#L16) |
| Диалог подтверждения | [`ask`](../winopt/ui/widgets.py#L573) |
| Белый список очистки | [`ALLOWED_LEAF_NAMES`](../winopt/cleanup.py#L23) |
| Скан / очистка | [`scan_categories`](../winopt/cleanup.py#L271) · [`clean_categories`](../winopt/cleanup.py#L308) |
| Корзина | [`send_to_recycle_bin`](../winopt/recycle.py#L52) |
| Журнал | [`log_action`](../winopt/history.py#L35) |
| Защита процессов | [`can_terminate`](../winopt/processes.py#L187) |
| Защита программ | [`lock_reason_for`](../winopt/programs.py#L196) |
| PS-скрипт программ | [`_PS_SCRIPT`](../winopt/programs.py#L22) |
| Удаление программы | [`uninstall_program`](../winopt/programs.py#L446) |
| Отключить автозагрузку | [`disable_item`](../winopt/actions.py#L94) |
| Вернуть автозагрузку | [`restore_record`](../winopt/actions.py#L125) |
| Службы Manual | [`set_service_manual`](../winopt/services.py#L184) |
| Точка восстановления | [`create_restore_point`](../winopt/restore.py#L44) |
| Дубликаты | [`scan_duplicates`](../winopt/duplicates.py#L86) |
| Ярлык | [`install_desktop_shortcut`](../winopt/shortcut.py#L51) |

### Зеркало на GitHub (если превью Markdown не кликает локально)

База: `https://github.com/Teslyar75/WinOpt/blob/main/`

Примеры:

- [winopt/winutil.py#L24](https://github.com/Teslyar75/WinOpt/blob/main/winopt/winutil.py#L24)  
- [winopt/ui/app.py#L278](https://github.com/Teslyar75/WinOpt/blob/main/winopt/ui/app.py#L278)  
- [winopt/cleanup.py#L23](https://github.com/Teslyar75/WinOpt/blob/main/winopt/cleanup.py#L23)  
- [winopt/programs.py#L22](https://github.com/Teslyar75/WinOpt/blob/main/winopt/programs.py#L22)  
- [docs/uchebnoe-posobie.md](https://github.com/Teslyar75/WinOpt/blob/main/docs/uchebnoe-posobie.md) — появится после push этого файла  

> Пока пособие не запушено, GitHub-ссылка на сам `.md` откроется только после `git push`. Локальные относительные ссылки работают сразу в Cursor (Ctrl/Cmd+клик по пути).
