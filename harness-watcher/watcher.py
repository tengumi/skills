#!/usr/bin/env python3
"""harness-watcher — фоновый процесс на ноутбуке.

Опрашивает доверенный удалённый хост, выполняет exec-requests локально и загружает reports обратно.

Использование:
    harness-watcher              # запустить watcher с дефолтным конфигом
    harness-watcher --once       # один цикл проверки, выйти
    harness-watcher --config PATH  # альтернативный конфиг
    harness-watcher --status     # показать audit log tail
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.audit import AuditLog
from lib.config import ConfigError, load_config
from lib.poller import Poller

def main() -> int:
    parser = argparse.ArgumentParser(description="harness-watcher: bridges a trusted remote queue to local execution")
    parser.add_argument("--config", type=Path, help="path to config.toml")
    parser.add_argument("--once", action="store_true", help="run one poll cycle and exit")
    parser.add_argument("--status", action="store_true", help="show recent audit log entries")
    parser.add_argument("--check", action="store_true", help="diagnose connection and permissions, exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose SSH debug output (use with --check)")
    parser.add_argument("--audit-tail", type=int, default=20, help="number of audit entries to show with --status")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print(f"Подсказка: скопируй watcher.toml.example в ~/.config/harness-watcher/config.toml и заполни.", file=sys.stderr)
        return 2

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
    print()

    poller = Poller(cfg, audit, verbose=args.verbose)

    if args.once:
        ok, err = poller.ensure_remote_dirs()
        if not ok:
            print(f"ERROR: could not create remote dirs", file=sys.stderr)
            print(f"  {err}", file=sys.stderr)
            print(file=sys.stderr)
            print("Подсказки:", file=sys.stderr)
            print("  1. Запусти `python3 watcher.py --check` — увидишь детали SSH-подключения", file=sys.stderr)
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
