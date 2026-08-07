"""Фильтрация шума из stdout перед записью в exec-report.json.

Зачем: уменьшаем токены которые Codex тратит на чтение результата.
Из вывода вырезаем системный шум (managed-workstation hooks, uv progress, ANSI коды).

Принципы безопасности:
- stderr НЕ фильтруется никогда — там обычно реальные ошибки
- При exit_code != 0 stdout тоже НЕ фильтруется — модели нужен полный контекст
- Только успешный stdout проходит через фильтр

Если что-то полезное случайно отфильтровалось — это видно в audit log
(там пишется оригинальный вывод) и в verbose окне watcher'а.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------- ANSI escape sequences ----------

# Управляющие коды цветов и форматирования: \x1b[30m, \x1b[1;31m, \x1b[K и т.п.
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

# Не-ANSI control characters кроме обычных пробельных
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ---------- Default noise patterns ----------

# Каждый паттерн — regex который, если матчится с строкой, означает что строку выбросить.
# Используется re.search (не match), потому что иногда префикс с timestamp/уровень логирования.
DEFAULT_NOISE_PATTERNS = [
    # Известный системный шум managed-workstation pre-exec hook (grouped-apps-pin)
    r"create_arm_desktop_files\.py.*DeprecationWarning",
    r"^\s*lang = locale\.getdefaultlocale",
    r"^Arm types:\s*\[",
    r"^JSON files found for ARM type",
    r"^\s*/opt/grouped-apps-pin/",
    r"grouped-apps-pin-.*\.desktop created$",
    r"^Directory checked/created:.*grouped-apps-pin",

    # uv: warnings про VIRTUAL_ENV не-совпадение
    r"^warning: `VIRTUAL_ENV=.*` does not match",
    r"will be ignored; use `--active`",

    # uv: создание виртуального окружения (только если у нас всё ок и venv уже есть)
    r"^Using CPython \d",
    r"^Creating virtual environment at:",
    r"^Removed virtual environment at:",

    # uv: download/build progress (десятки строк при первой установке)
    r"^Downloading \S+\s*\([0-9.]+(KiB|MiB|GiB|B)\)",
    r"^\s+Downloaded \S+",
    r"^\s+Built \S+ @ file://",
    r"^\s+Building \S+ @ file://",
    r"^Prepared \d+ packages? in",
    r"^Resolved \d+ packages? in",
    r"^Installed \d+ packages? in",
    r"^Uninstalled \d+ packages? in",
    r"^Audited \d+ packages? in",
    r"^\s+\+ [a-zA-Z0-9_-]+==.+",  # uv `+ package==version` install lines

    # Прочее uv
    r"^\s*\^",  # стрелки из tracebacks которые приходят пустыми
]


@dataclass
class FilterConfig:
    """Конфигурация фильтра. Создаётся из Config или с дефолтами."""

    enabled: bool = True
    strip_ansi: bool = True
    strip_defaults: bool = True
    extra_patterns: list[str] | None = None
    min_kept_lines: int = 1
    # Если после фильтра осталось меньше этого числа строк — не фильтруем вообще
    # (чтобы не получить пустой вывод когда вся команда была "шумом" с точки зрения паттернов)


def make_filter(cfg: FilterConfig) -> "NoiseFilter":
    """Фабрика — компилирует регулярки один раз."""
    return NoiseFilter(cfg)


class NoiseFilter:
    def __init__(self, cfg: FilterConfig):
        self.cfg = cfg
        patterns: list[str] = []
        if cfg.strip_defaults:
            patterns.extend(DEFAULT_NOISE_PATTERNS)
        if cfg.extra_patterns:
            patterns.extend(cfg.extra_patterns)
        # Компилируем
        self._compiled = [re.compile(p) for p in patterns] if patterns else []

    def filter_stdout(self, text: str, exit_code: int = 0) -> tuple[str, int]:
        """Отфильтровать stdout. Возвращает (filtered_text, removed_lines_count).

        НЕ фильтрует если:
        - cfg.enabled = False
        - exit_code != 0 (команда упала, модели нужен полный контекст)
        """
        if not self.cfg.enabled:
            return text, 0
        if exit_code != 0:
            # Команда упала — оставляем всё, только ANSI убираем
            if self.cfg.strip_ansi:
                return _strip_ansi(text), 0
            return text, 0

        if not text:
            return "", 0

        # Сначала ANSI
        if self.cfg.strip_ansi:
            text = _strip_ansi(text)

        lines = text.splitlines(keepends=True)
        kept: list[str] = []
        removed = 0

        for line in lines:
            stripped = line.rstrip("\r\n")
            if self._matches_noise(stripped):
                removed += 1
            else:
                kept.append(line)

        # Safety check: если все строки выкинули — это подозрительно, лучше вернуть оригинал
        if removed > 0 and len(kept) < self.cfg.min_kept_lines:
            return text, 0

        return "".join(kept), removed

    def _matches_noise(self, line: str) -> bool:
        """True если строка соответствует хотя бы одному noise-паттерну."""
        for pattern in self._compiled:
            if pattern.search(line):
                return True
        return False


def _strip_ansi(text: str) -> str:
    """Удаляет ANSI escape sequences и непечатные control characters."""
    text = ANSI_RE.sub("", text)
    text = CONTROL_RE.sub("", text)
    return text
