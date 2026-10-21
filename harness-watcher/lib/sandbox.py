"""Command execution context; no external runner or OS sandbox.

The legacy module/config names remain for compatibility. Command filtering is
performed before execution; scripts and build hooks run with local user rights.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import tempfile

from lib.config import ConfigError
from lib.secret_paths import effective_excludes, matches_excludes

EXECUTION_POLICY_VERSION = "command-filter/v1"


class SandboxError(ConfigError):
    """Compatibility error type for execution settings."""


def validate_sandbox(spec: dict | None) -> dict:
    """Read owner settings, never settings supplied by an execution request."""
    spec = {} if spec is None else spec
    if not isinstance(spec, dict) or set(spec) - {"mode", "binary", "read_roots", "secret_roots", "install_network"}:
        raise ConfigError("invalid execution settings")
    mode = spec.get("mode", "commands")
    if not isinstance(mode, str) or mode not in {"none", "codex", "commands"}:
        raise ConfigError("execution_sandbox must be commands (legacy modes are accepted)")
    # Legacy binary/read_roots are accepted but never used to launch a runner
    # or grant filesystem access. All supported modes now use the same filter.
    binary = spec.get("binary", "")
    if (not isinstance(binary, str) or binary.startswith("-")
            or any(ord(char) < 32 for char in binary)):
        raise ConfigError("sandbox_binary must be an executable name or absolute path")
    if "/" in binary and not Path(binary).expanduser().is_absolute():
        raise ConfigError("sandbox_binary path must be absolute")
    network = spec.get("install_network", False)
    if not isinstance(network, bool):
        raise ConfigError("sandbox_install_network must be true or false")
    result = {"mode": "commands", "binary": binary, "install_network": network}
    for key in ("read_roots", "secret_roots"):
        values = spec.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ConfigError(f"execution {key} must be a list of absolute paths")
        result[key] = [_path(value) for value in values]
    return result


def sandbox_settings(cfg) -> dict:
    return validate_sandbox({
        "mode": getattr(cfg, "execution_sandbox", "commands"),
        "binary": getattr(cfg, "sandbox_binary", ""),
        "read_roots": [str(path) for path in getattr(cfg, "sandbox_read_roots", [])],
        "secret_roots": [str(path) for path in getattr(cfg, "sandbox_secret_roots", [])],
        "install_network": getattr(cfg, "sandbox_install_network", False),
    })


def require_execution_policy(cfg) -> dict:
    settings = sandbox_settings(cfg)
    if settings["install_network"]:
        raise SandboxError("dependency installation requires offline settings; remove sandbox_install_network")
    return settings


def _path(value) -> str:
    raw = str(value)
    if not raw or any(ord(char) < 32 for char in raw) or any(char in raw for char in "*?[]{}"):
        raise ConfigError("execution roots must be exact paths without glob or control characters")
    path = Path(raw).expanduser()
    if not path.is_absolute() or ".." in path.parts or str(path) == "/":
        raise ConfigError("execution roots must be bounded absolute paths")
    return str(path.resolve())


def safe_environment() -> dict[str, str]:
    """Do not inherit credentials or shell/Python injection variables.

    This environment allowlist does not restrict filesystem or network access.
    """
    return {"PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def shell_argv(cfg, command: str) -> list[str]:
    return ["/bin/bash", "--noprofile", "--norc", "-c", command]


def _validate_repository_inputs(cfg):
    """Reject ambiguous mirror inputs; this is not OS access control."""
    root = Path(cfg.local_repo_root).resolve()
    def failed(error):
        raise error
    try:
        excludes = effective_excludes(cfg, [], root=root)
        for directory, names, filenames in os.walk(root, followlinks=False, onerror=failed):
            relative = Path(directory).relative_to(root)
            if len(relative.parts) > 63:
                raise SandboxError("repository exceeds the supported metadata scan depth")
            names[:] = [name for name in names if not matches_excludes(relative / name, excludes)]
            for name in [*names, *filenames]:
                path = Path(directory) / name
                if matches_excludes(path.relative_to(root), excludes):
                    continue
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode)
                        and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
                    raise SandboxError("repository inputs must not be symlinks, hardlinks or special files")
    except (OSError, ValueError):
        raise SandboxError("repository metadata validation failed; no command was run") from None



@contextmanager
def command_context(cfg, argv, *, installation=False, cwd=None):
    """Run directly with clean environment and private temporary directories."""
    require_execution_policy(cfg)
    _validate_repository_inputs(cfg)
    if installation and getattr(cfg, "managed_root", None) is not None:
        venv = Path(cfg.managed_root) / "venv"
        if getattr(cfg, "_bootstrap_write_root", None) != venv.resolve():
            raise SandboxError("installation requires a watcher-owned environment directory")
    with tempfile.TemporaryDirectory(prefix="harness-command-") as private:
        private = Path(private).resolve()
        home, temporary = private / "home", private / "tmp"
        for directory in (home, temporary):
            directory.mkdir(mode=0o700)
        environment = safe_environment()
        environment.update(
            HOME=str(home), TMPDIR=str(temporary),
            XDG_CACHE_HOME=str(temporary / "cache"), UV_CACHE_DIR=str(temporary / "uv-cache"),
            PIP_CONFIG_FILE=os.devnull, UV_NO_ENV_FILE="1", UV_OFFLINE="1",
            PIP_NO_INDEX="1", PYTHONDONTWRITEBYTECODE="1",
            HARNESS_OUTPUT_DIR=str(temporary),
            PYTEST_ADDOPTS="-o cache_dir=" + str(temporary / "pytest-cache"),
        )
        yield list(argv), environment
