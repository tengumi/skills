"""Конфигурация harness-watcher.

Загружается из ~/.config/harness-watcher/config.toml или из пути в env HARNESS_WATCHER_CONFIG.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
    _HAS_TOMLLIB = True
except ImportError:
    _HAS_TOMLLIB = False


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "harness-watcher" / "config.toml"


@dataclass
class Config:
    # remote
    ssh_host: str
    ssh_port: int
    ssh_key: str
    remote_repo_root: str

    # local
    local_repo_root: Path

    # SSH host identity. Secure by default: use OpenSSH known_hosts resolution.
    strict_host_key_checking: bool = True
    user_known_hosts_file: str | None = None

    # poller
    poll_interval_seconds: int = 3
    default_timeout_seconds: int = 600
    stdout_max_chars: int = 8000
    stderr_max_chars: int = 4000

    # executor
    sync_before_exec: bool = True
    sync_after_exec: bool = False
    pre_exec_hook: str = ""  # bash-команды перед каждым exec (напр. 'source ~/.venvs/proj/bin/activate')

    # filter — убирает шум из stdout перед записью в report.
    # Не влияет на verbose окно watcher'а и не трогает stderr / failed commands.
    filter_enabled: bool = True
    filter_strip_ansi: bool = True
    filter_strip_defaults: bool = True
    filter_extra_patterns: list[str] = field(default_factory=list)
    pre_exec_hook: str = ""
    post_exec_hook: str = ""

    # paths
    audit_log_path: Path = field(default_factory=lambda: Path.home() / ".config" / "harness-watcher" / "audit.log")
    state_path: Path = field(default_factory=lambda: Path.home() / ".config" / "harness-watcher" / "state.json")

    # rsync
    rsync_exclude: list[str] = field(default_factory=list)

    # meta
    config_path: Path | None = None


class ConfigError(Exception):
    pass


def load_config(path: Path | None = None) -> Config:
    """Загрузить конфиг. Бросает ConfigError если что-то не так."""
    if path is None:
        env = os.environ.get("HARNESS_WATCHER_CONFIG")
        path = Path(env) if env else DEFAULT_CONFIG_PATH

    if not path.exists():
        raise ConfigError(f"config not found at {path}. Скопируй watcher.toml.example и заполни.")

    try:
        with open(path, "rb") as f:
            data = _load_toml(f)
    except Exception as e:
        raise ConfigError(f"failed to parse {path}: {e}")

    try:
        return _build_config(data, path)
    except (KeyError, ValueError, TypeError) as e:
        raise ConfigError(f"invalid config: {e}")


def _load_toml(f) -> dict:
    if _HAS_TOMLLIB:
        return tomllib.load(f)
    text = f.read().decode("utf-8")
    return _parse_toml_simple(text)


def _parse_toml_simple(text: str) -> dict:
    """Минимальный TOML парсер для Python 3.9/3.10."""
    result: dict = {}
    current: dict = result
    in_list_key: str | None = None
    list_buf: list = []

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if in_list_key is not None:
            if "]" in line:
                items = line.split("]")[0]
                _append_items(list_buf, items)
                current[in_list_key] = list_buf
                in_list_key = None
                list_buf = []
            else:
                _append_items(list_buf, line)
            continue

        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            current = result.setdefault(s[1:-1].strip(), {})
            continue

        if "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        val = val.strip()

        if val.startswith("["):
            if "]" in val:
                items = val[1:val.index("]")]
                current[key] = _parse_items(items)
            else:
                in_list_key = key
                list_buf = []
                _append_items(list_buf, val[1:])
        elif val.startswith('"') and val.endswith('"'):
            current[key] = val[1:-1]
        elif val.lower() in ("true", "false"):
            current[key] = val.lower() == "true"
        else:
            try:
                current[key] = int(val)
            except ValueError:
                try:
                    current[key] = float(val)
                except ValueError:
                    current[key] = val
    return result


def _parse_items(s: str) -> list:
    result = []
    for item in s.split(","):
        item = item.strip()
        if not item:
            continue
        if item.startswith('"') and item.endswith('"'):
            result.append(item[1:-1])
        else:
            result.append(item)
    return result


def _append_items(buf: list, s: str) -> None:
    buf.extend(_parse_items(s))


def _build_config(data: dict, path: Path) -> Config:
    remote = data.get("remote") or {}
    local = data.get("local") or {}
    poller = data.get("poller") or {}
    executor = data.get("executor") or {}
    paths = data.get("paths") or {}
    rsync = data.get("rsync") or {}

    ssh_host = _require(remote, "ssh_host", "remote")
    ssh_port = int(remote.get("ssh_port", 22))
    ssh_key = _expand(_require(remote, "ssh_key", "remote"))
    if not Path(ssh_key).exists():
        raise ValueError(f"ssh_key not found: {ssh_key}")

    remote_repo_root = _require(remote, "remote_repo_root", "remote")
    local_repo_root = Path(_expand(_require(local, "local_repo_root", "local")))
    strict_host_key_checking = bool(remote.get("strict_host_key_checking", True))
    known_hosts_raw = str(remote.get("user_known_hosts_file", "") or "").strip()
    user_known_hosts_file = _expand(known_hosts_raw) if known_hosts_raw else None
    if user_known_hosts_file and not Path(user_known_hosts_file).exists():
        raise ValueError(f"user_known_hosts_file not found: {user_known_hosts_file}")

    return Config(
        ssh_host=ssh_host,
        ssh_port=ssh_port,
        ssh_key=ssh_key,
        remote_repo_root=remote_repo_root,
        local_repo_root=local_repo_root,
        strict_host_key_checking=strict_host_key_checking,
        user_known_hosts_file=user_known_hosts_file,
        poll_interval_seconds=int(poller.get("poll_interval_seconds", 3)),
        default_timeout_seconds=int(poller.get("default_timeout_seconds", 600)),
        stdout_max_chars=int(poller.get("stdout_max_chars", 8000)),
        stderr_max_chars=int(poller.get("stderr_max_chars", 4000)),
        sync_before_exec=bool(executor.get("sync_before_exec", True)),
        sync_after_exec=bool(executor.get("sync_after_exec", False)),
        pre_exec_hook=str(executor.get("pre_exec_hook", "") or ""),
        filter_enabled=bool(data.get("filter", {}).get("enabled", True)),
        filter_strip_ansi=bool(data.get("filter", {}).get("strip_ansi", True)),
        filter_strip_defaults=bool(data.get("filter", {}).get("strip_defaults", True)),
        filter_extra_patterns=list(data.get("filter", {}).get("extra_patterns") or []),
        audit_log_path=Path(_expand(paths.get("audit_log_path", "~/.config/harness-watcher/audit.log"))),
        state_path=Path(_expand(paths.get("state_path", "~/.config/harness-watcher/state.json"))),
        rsync_exclude=list(rsync.get("exclude") or []),
        config_path=path,
    )


def _require(d: dict, key: str, section: str) -> str:
    if key not in d:
        raise KeyError(f"[{section}].{key} is required")
    v = d[key]
    if not isinstance(v, str) or not v:
        raise ValueError(f"[{section}].{key} must be non-empty string")
    return v


def _expand(p: str) -> str:
    return str(Path(p).expanduser())
