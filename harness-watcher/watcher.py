#!/usr/bin/env python3
"""harness-watcher — фоновый процесс на ноутбуке.

Опрашивает доверенный удалённый хост, выполняет exec-requests локально и загружает reports обратно.

Использование:
    python3 watcher.py add NAME   # сохранить проект через мастер настройки
    python3 watcher.py start NAME # запуск сохранённого проекта
    python3 watcher.py list       # список проектов
    harness-watcher              # старый запуск с TOML-конфигом
    harness-watcher --once       # один цикл проверки, выйти
    harness-watcher --config PATH  # альтернативный конфиг
    harness-watcher --status     # показать audit log tail
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.audit import AuditLog
from lib.config import ConfigError, load_config
from lib.environment import validate_environment
from lib.poller import Poller
from lib.profiles import (
    DEFAULT_PROFILES_DIR, create_profile, list_profiles, load_profile, profile_lock, validate_profile_name,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="harness-watcher: bridges a trusted remote queue to local execution")
    parser.add_argument("action", nargs="?", choices=("add", "start", "list"), help="сохранить, запустить или показать проекты")
    parser.add_argument("name", nargs="?", help="имя сохранённого проекта")
    parser.add_argument("--profiles-dir", type=Path, default=DEFAULT_PROFILES_DIR, help="каталог профилей (обычно менять не нужно)")
    parser.add_argument("--connection-from", help="в add: использовать SSH-настройки сохранённого проекта")
    parser.add_argument("--protected", action="store_true", help="устаревший совместимый флаг: фильтр команд уже включён")
    parser.add_argument("--sandbox-binary", default=None, help="устаревший параметр, игнорируется")
    parser.add_argument("--sandbox-read-root", type=Path, action="append", default=[], help="устаревший параметр, игнорируется")
    parser.add_argument("--sandbox-secret-root", type=Path, action="append", default=[], help="дополнительный секретный файл/каталог для исключения из синхронизации")
    parser.add_argument("--sandbox-install-network", action="store_true", help="не поддерживается: установка использует offline-настройки")
    parser.add_argument("--config", type=Path, help="path to config.toml")
    parser.add_argument("--once", action="store_true", help="run one poll cycle and exit")
    parser.add_argument("--status", action="store_true", help="show recent audit log entries")
    parser.add_argument("--check", action="store_true", help="diagnose connection and permissions, exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose SSH debug output (use with --check)")
    parser.add_argument("--audit-tail", type=int, default=20, help="number of audit entries to show with --status")
    args = parser.parse_args(argv)

    if args.action in ("add", "start") and not args.name:
        parser.error("укажите имя проекта")
    if args.name and args.action == "list":
        parser.error("list не принимает имя проекта")
    if args.config and args.action:
        parser.error("--config — старый TOML-режим, без add/start/list")
    if args.connection_from and args.action != "add":
        parser.error("--connection-from используется только с add")
    if args.action in ("add", "list") and (args.once or args.status or args.check):
        parser.error("--once/--status/--check используются с start или TOML-режимом")
    sandbox_options = args.sandbox_binary or args.sandbox_read_root or args.sandbox_secret_root or args.sandbox_install_network
    if args.sandbox_install_network:
        parser.error("установка использует offline-настройки; --sandbox-install-network больше не поддерживается")
    if args.action == "list" and (args.protected or sandbox_options):
        parser.error("--protected/--sandbox-* используются с add/start или TOML-режимом")

    if args.sandbox_binary or args.sandbox_read_root:
        print("Предупреждение: --sandbox-binary/--sandbox-read-root устарели и игнорируются; используется фильтр команд.", file=sys.stderr)

    try:
        if args.action == "list":
            names = list_profiles(profiles_dir=args.profiles_dir)
            print("\n".join(names) if names else "Проектов пока нет. Начните с: python3 watcher.py add <имя>")
            return 0
        if args.action == "add":
            return _add_project(args)
        cfg = load_profile(args.name, profiles_dir=args.profiles_dir) if args.action == "start" else load_config(args.config)
        if args.protected:
            cfg.execution_sandbox = "commands"
        if args.sandbox_binary:
            cfg.sandbox_binary = args.sandbox_binary
        cfg.sandbox_read_roots = list(dict.fromkeys([*cfg.sandbox_read_roots, *args.sandbox_read_root]))
        cfg.sandbox_secret_roots = list(dict.fromkeys([*cfg.sandbox_secret_roots, *args.sandbox_secret_root]))
        cfg.environment = validate_environment(cfg.environment)
        # Diagnostics never synchronize code or prepare dependencies. Running a
        # profile holds one lock for its mirror, environment and request state.
        if args.status or args.check:
            return _run(cfg, args)
        with profile_lock(cfg):
            return _run(cfg, args)
    except (ConfigError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Новый проект: python3 watcher.py add <имя>. Старый конфиг: --config <путь>.", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("\nНастройка или запуск отменены.", file=sys.stderr)
        return 130


def _ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _add_project(args) -> int:
    validate_profile_name(args.name)
    print("Настройка проекта. Значения секретов не вводите — нужны только адреса и пути.")
    names = list_profiles(profiles_dir=args.profiles_dir)
    if args.name in names:
        raise ConfigError("Проект уже существует; настройки и очередь не перезаписываются. Выберите другое имя.")
    connection = args.connection_from
    if names and not connection:
        print("Сохранённые проекты: " + ", ".join(names))
        connection = _ask("SSH как у проекта (имя или '-' для нового подключения)", names[0])
    if connection and connection != "-":
        previous = load_profile(connection, profiles_dir=args.profiles_dir)
        host, port, key = previous.ssh_host, previous.ssh_port, previous.ssh_key
        print(f"Использую SSH {host}:{port}; ключ — {key}.")
    else:
        host = _ask("SSH-хост или alias, например user@host")
        try:
            port = int(_ask("SSH-порт", "22"))
        except ValueError:
            raise ConfigError("SSH-порт должен быть числом") from None
        key = _ask("Путь к SSH-ключу", "~/.ssh/id_ed25519")
    remote = _ask("Полный путь к репозиторию на удалённой машине")
    print("Окружение: uv — проект с uv.lock; command — командная инструкция установки; none — без подготовки Python.")
    mode = _ask("Способ подготовки", "uv")
    spec = {"mode": mode}
    if mode in ("uv", "command"):
        python_hint = "Версия/путь Python из шаблона (например 3.12.3)" if mode == "uv" else "Локальная команда/путь Python из шаблона (например python3.12)"
        spec["python"] = _ask(python_hint)
        spec["command"] = _ask("Команда установки из документации проекта", "uv sync --locked" if mode == "uv" else "")
        extra = _ask("Дополнительные входы установки, пути через запятую (Enter — стандартные)")
        if extra:
            spec["inputs"] = [part.strip() for part in extra.split(",") if part.strip()]
    spec = validate_environment(spec)
    if mode != "none":
        print("Перед первым запросом watcher создаст отдельное окружение и выполнит выбранную установку.")
        print("Установка использует offline-настройки. Нужные пакеты подготовьте заранее вне watcher.")
        print("Команды проверяются фильтром, затем выполняются с вашими правами; тесты и сборка могут менять рабочую копию.")
        print("uv и нужный Python должны быть установлены; глобально watcher ничего не устанавливает.")
        if _ask("Разрешить автоматическую подготовку для этого проекта? да/нет", "нет").lower() not in ("да", "yes", "y"):
            print("Отменено. Профиль не сохранён, установка не запускалась.")
            return 1
    cfg = create_profile(
        args.name, ssh_host=host, ssh_port=port, ssh_key=key,
        remote_repo_root=remote, environment=spec, profiles_dir=args.profiles_dir,
        sandbox={"mode": "commands", "binary": "",
                 "read_roots": [],
                 "secret_roots": [str(path) for path in args.sandbox_secret_root],
                 "install_network": False},
    )
    print(f"\nПроект {args.name} сохранён. Подключений и установки пока не было.")
    print(f"Профиль: {cfg.config_path}")
    print(f"Рабочая копия: {cfg.local_repo_root}")
    print(f"Окружение и состояние: {cfg.managed_root}")
    print(f"Проверка SSH: {_start_hint(args)} --check")
    print(f"Запуск: {_start_hint(args)}")
    return 0


def _start_hint(args) -> str:
    command = ["python3", "watcher.py"]
    if args.action:
        command.extend(["start", args.name])
        if args.profiles_dir != DEFAULT_PROFILES_DIR:
            command.extend(["--profiles-dir", str(args.profiles_dir)])
    elif args.config:
        command.extend(["--config", str(args.config)])
    for root in args.sandbox_secret_root:
        command.extend(["--sandbox-secret-root", str(root)])
    return shlex.join(command)


def _run(cfg, args) -> int:
    audit = AuditLog(cfg.audit_log_path)

    if args.status:
        entries = audit.tail(args.audit_tail)
        if not entries:
            print("audit log is empty")
            return 0
        for e in entries:
            print(_format_audit_entry(e))
        return 0

    if args.check:
        poller = Poller(cfg, audit, verbose=args.verbose)
        print(f"Checking connection to {cfg.ssh_host}:{cfg.ssh_port}...")
        print(f"  ssh_key: {cfg.ssh_key}")
        print(f"  remote_repo_root: {cfg.remote_repo_root}")
        print()
        result = poller.check_connection(verbose=args.verbose)
        for key, value in result.items():
            if key == "ssh_debug_output":
                print(f"\n--- SSH debug output (last 3000 chars) ---")
                print(value)
                print("--- end ssh debug ---\n")
            else:
                print(f"  {key}: {value}")
        return 0 if result.get("ok") else 1

    print(f"harness-watcher starting...")
    print(f"  config:      {cfg.config_path}")
    print(f"  remote:      {cfg.ssh_host}:{cfg.remote_repo_root}")
    print(f"  local:       {cfg.local_repo_root}")
    print(f"  host key:    {'strict' if cfg.strict_host_key_checking else 'NOT VERIFIED (high risk)'}")
    print(f"  known hosts: {cfg.user_known_hosts_file or 'OpenSSH default'}")
    print(f"  audit log:   {cfg.audit_log_path}")
    print(f"  interval:    {cfg.poll_interval_seconds}s")
    print(f"  sync before: {cfg.sync_before_exec}, sync after: {cfg.sync_after_exec}")
    print(f"  verbose:     {args.verbose}")
    print("  policy:      фильтр команд; не изоляция ОС. Тесты и скрипты выполняются с правами пользователя.")
    if cfg.sandbox_install_network:
        print("  Ошибка настроек: автоматическая установка требует install_network=false.")
    if cfg.profile_name:
        print(f"  project:     {cfg.profile_name}")
        print(f"  environment: {cfg.environment.get('mode', 'none')} (подготовка при первом запросе)")
    print()

    poller = Poller(cfg, audit, verbose=args.verbose)

    if args.once:
        ok, err = poller.ensure_remote_dirs()
        if not ok:
            print(f"ERROR: could not create remote dirs", file=sys.stderr)
            print(f"  {err}", file=sys.stderr)
            print(file=sys.stderr)
            print("Подсказки:", file=sys.stderr)
            print(f"  1. Запусти `{_start_hint(args)} --check` — увидишь детали SSH-подключения", file=sys.stderr)
            print("  2. Проверь что remote_repo_root в конфиге существует на удалённой машине", file=sys.stderr)
            print("  3. Проверь права на запись: ssh ... 'touch /path/to/repo/.test'", file=sys.stderr)
            return 3
        n = poller.run_once()
        print(f"processed {n} requests")
        return 0

    print("starting poll loop (Ctrl+C to stop)...")
    poller.loop()
    return 0


def _format_audit_entry(e: dict) -> str:
    ts = e.get("ts", "")
    event = e.get("event", "")
    rest = {k: v for k, v in e.items() if k not in ("ts", "event")}
    return f"{ts} [{event}] {rest}"


if __name__ == "__main__":
    sys.exit(main())
