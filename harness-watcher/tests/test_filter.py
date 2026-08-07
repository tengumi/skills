"""Тесты для lib/filter.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.filter import FilterConfig, _strip_ansi, make_filter


def test_strip_ansi_basic():
    text = "\x1b[31mred text\x1b[0m and \x1b[1;32mbold green\x1b[0m"
    assert _strip_ansi(text) == "red text and bold green"


def test_strip_ansi_complex():
    text = "PASSED \x1b[32m✓\x1b[0m in \x1b[1m0.45s\x1b[0m"
    assert _strip_ansi(text) == "PASSED ✓ in 0.45s"


def test_filter_disabled():
    cfg = FilterConfig(enabled=False)
    f = make_filter(cfg)
    text = "Downloading faker (1.9MiB)\nuseful output"
    result, removed = f.filter_stdout(text, exit_code=0)
    assert result == text
    assert removed == 0


def test_filter_on_failure_not_applied():
    """При exit_code != 0 фильтр НЕ применяется (полный контекст важен)."""
    cfg = FilterConfig(enabled=True)
    f = make_filter(cfg)
    text = "Downloading faker (1.9MiB)\nError: something failed"
    result, removed = f.filter_stdout(text, exit_code=1)
    assert "Downloading faker" in result
    assert removed == 0


def test_filter_on_failure_strips_ansi():
    """Даже при exit_code != 0, ANSI убираем."""
    cfg = FilterConfig(enabled=True, strip_ansi=True)
    f = make_filter(cfg)
    text = "\x1b[31mFailed\x1b[0m"
    result, _ = f.filter_stdout(text, exit_code=1)
    assert "\x1b" not in result
    assert "Failed" in result


def test_filter_uv_downloads():
    cfg = FilterConfig(enabled=True)
    f = make_filter(cfg)
    text = """Downloading faker (1.9MiB)
Downloading ruff (9.6MiB)
Downloading faiss-cpu (29.2MiB)
 Downloaded faker
 Downloaded ruff
test_something PASSED
Resolved 200 packages in 7.98s
Installed 192 packages in 3.00s
"""
    result, removed = f.filter_stdout(text, exit_code=0)
    assert "Downloading" not in result
    assert "Downloaded" not in result
    assert "Resolved" not in result
    assert "Installed" not in result
    assert "test_something PASSED" in result
    assert removed >= 7


def test_filter_managed_workstation_pre_exec_noise():
    cfg = FilterConfig(enabled=True)
    f = make_filter(cfg)
    text = """/opt/grouped-apps-pin/service/create_arm_desktop_files.py:62: DeprecationWarning: 'locale.getdefaultlocale' is deprecated
  lang = locale.getdefaultlocale()[0]
Arm types: ['OFFICE']
JSON files found for ARM type 'OFFICE':
  /opt/grouped-apps-pin/TEAM/application.json
/workspace/user/Desktop/grouped-apps-pin-TEAM-application.desktop created
Directory checked/created: /workspace/user/.local/share/grouped-apps-pin

Actual content here.
"""
    result, removed = f.filter_stdout(text, exit_code=0)
    assert "Actual content here." in result
    assert "grouped-apps-pin" not in result
    assert "Arm types" not in result
    assert "JSON files found" not in result
    assert removed >= 6


def test_filter_uv_install_progress():
    cfg = FilterConfig(enabled=True)
    f = make_filter(cfg)
    text = """ + aiohttp==3.13.3
 + aiosignal==1.4.0
 + alembic==1.16.5
real content
"""
    result, removed = f.filter_stdout(text, exit_code=0)
    assert "aiohttp" not in result
    assert "real content" in result
    assert removed == 3


def test_filter_uv_virtual_env_warning():
    cfg = FilterConfig(enabled=True)
    f = make_filter(cfg)
    text = "warning: `VIRTUAL_ENV=/workspace/venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead\nUsing CPython 3.12.3\nrunning pytest"
    result, removed = f.filter_stdout(text, exit_code=0)
    assert "VIRTUAL_ENV" not in result
    assert "Using CPython" not in result
    assert "running pytest" in result


def test_filter_extra_patterns():
    cfg = FilterConfig(enabled=True, extra_patterns=[r"^MYAPP-DEBUG:"])
    f = make_filter(cfg)
    text = "MYAPP-DEBUG: starting\nuseful info\nMYAPP-DEBUG: ending"
    result, removed = f.filter_stdout(text, exit_code=0)
    assert "MYAPP-DEBUG" not in result
    assert "useful info" in result
    assert removed == 2


def test_filter_safety_returns_original_if_too_aggressive():
    """Если фильтр выкидывает все строки — лучше вернуть оригинал."""
    cfg = FilterConfig(enabled=True, min_kept_lines=2)
    f = make_filter(cfg)
    text = "Downloading a\nDownloading b\nDownloading c"
    result, removed = f.filter_stdout(text, exit_code=0)
    # Все три строки - шум, после фильтра 0 строк. Это меньше min_kept_lines=2.
    # Safety: возвращаем оригинал.
    assert result == text
    assert removed == 0


def test_filter_keeps_pytest_output():
    """Реальный кейс — выход pytest должен полностью пройти."""
    cfg = FilterConfig(enabled=True)
    f = make_filter(cfg)
    text = """============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-8.4.2, pluggy-1.6.0
rootdir: /workspace/service
configfile: pyproject.toml
collected 81 items

tests/test_basic.py::test_add PASSED                                    [ 50%]
tests/test_basic.py::test_subtract PASSED                               [100%]

============================== 2 passed in 0.45s ===============================
"""
    result, removed = f.filter_stdout(text, exit_code=0)
    assert result == text or result.strip() == text.strip()
    assert "test_add PASSED" in result
    assert "test_subtract PASSED" in result


def test_filter_real_uv_run_log():
    """Реалистичный лог из uv run, включающий мусор и полезное."""
    cfg = FilterConfig(enabled=True)
    f = make_filter(cfg)
    text = """/opt/grouped-apps-pin/service/create_arm_desktop_files.py:62: DeprecationWarning: deprecation
  lang = locale.getdefaultlocale()[0]
Arm types: ['OFFICE']
JSON files found for ARM type 'OFFICE':
  /opt/grouped-apps-pin/TEAM/application.json
/workspace/user/Desktop/grouped-apps-pin-TEAM-application.desktop created
warning: `VIRTUAL_ENV=/workspace/venv` does not match
Building project @ file:///workspace/service
Resolved 200 packages in 7.98s
Installed 192 packages in 3.00s
 + faker==38.0.0
 + numpy==2.2.3
workflow_compiled CompiledWorkflow
"""
    result, removed = f.filter_stdout(text, exit_code=0)
    # Полезная строка должна остаться
    assert "workflow_compiled CompiledWorkflow" in result
    # Всё системное должно уйти
    assert "grouped-apps-pin" not in result
    assert "Resolved 200" not in result
    assert "Installed 192" not in result
    assert "faker==38" not in result
    assert removed >= 8  # вырезано не меньше 8 строк


def test_filter_empty_text():
    cfg = FilterConfig(enabled=True)
    f = make_filter(cfg)
    result, removed = f.filter_stdout("", exit_code=0)
    assert result == ""
    assert removed == 0
