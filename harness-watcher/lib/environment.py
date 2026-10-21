"""Explicit, per-profile target environments; never installs the watcher itself.

An installation recipe is workstation-owner configuration, not request data.
Its output is deliberately discarded: package-manager logs may contain index
credentials. Child processes receive a small environment allowlist and offline
package-manager settings. Build hooks run as the local user, without OS isolation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from functools import partial
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from lib.command_policy import inspect_command
from lib.config import ConfigError
from lib.sandbox import command_context, sandbox_settings, shell_argv, require_execution_policy, EXECUTION_POLICY_VERSION
from lib.secret_paths import effective_excludes, is_secret_path, matches_excludes

_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
              ".ruff_cache", ".mypy_cache", "dist", "build", ".cache", ".harness-watcher-tmp"}
_RUNTIME_PATHS = {"docs/harness/exec-requests", "docs/harness/exec-reports", "docs/harness/exec-processed"}
_MANIFESTS = {"pyproject.toml", "uv.lock", "uv.toml", ".python-version", ".python-versions",
              "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock", "poetry.lock"}
_SECRET_DIRS = {"certs", "certificates", "keys", "secrets", ".ssh", ".aws", ".azure", ".gcp"}
_BAD_FLAGS = {"--system", "--user", "--prefix", "--target", "--break-system-packages",
              "--active", "--directory", "--project", "--env-file", "--python"}


def validate_environment(spec: dict) -> dict:
    """Normalize a saved, explicitly selected recipe without executing it."""
    if not isinstance(spec, dict):
        raise ConfigError("environment must be an object")
    if set(spec) - {"mode", "python", "command", "inputs", "timeout_seconds"}:
        raise ConfigError("unknown environment option")
    mode = spec.get("mode", "none")
    if not isinstance(mode, str) or mode not in {"none", "uv", "command"}:
        raise ConfigError("environment mode must be none, uv or command")
    if mode == "none":
        return {"mode": "none"}
    python = spec.get("python")
    if not isinstance(python, str) or not python.strip() or any(c in python for c in "\n\r\0$"):
        raise ConfigError("choose an installed Python version or executable")
    python = python.strip()
    if python.startswith("-") or (not Path(python).is_absolute() and not re.fullmatch(r"[A-Za-z0-9_.+-]+", python)):
        raise ConfigError("invalid Python selection")
    command = spec.get("command", "uv sync --locked" if mode == "uv" else "")
    if not isinstance(command, str) or not command.strip():
        raise ConfigError("an explicit installation command is required")
    _validate_command(command, mode)
    inputs = spec.get("inputs", ["Makefile"])
    if not isinstance(inputs, list) or not all(isinstance(item, str) for item in inputs):
        raise ConfigError("environment inputs must be relative paths")
    for item in inputs:
        _validate_input(item)
    timeout = spec.get("timeout_seconds", 600)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
        raise ConfigError("environment timeout_seconds must be 1..86400")
    return {"mode": mode, "python": python, "command": command.strip(),
            "inputs": sorted(set(inputs)), "timeout_seconds": timeout}


def environment_hook(cfg) -> str:
    """Exports run *after* bash startup, so the selected environment wins."""
    spec = validate_environment(getattr(cfg, "environment", {}) or {})
    if spec["mode"] == "none":
        return ""
    root = getattr(cfg, "managed_root", None)
    if root is None:
        raise ConfigError("automatic environments require a managed project profile")
    venv = Path(root) / "venv"
    return "\n".join([
        "export VIRTUAL_ENV=" + shlex.quote(str(venv)),
        "export UV_PROJECT_ENVIRONMENT=" + shlex.quote(str(venv)),
        "export UV_PYTHON_DOWNLOADS=never",
        "export UV_PYTHON=" + shlex.quote(spec["python"]),
        "export UV_NO_ENV_FILE=1",
        "export PIP_REQUIRE_VIRTUALENV=true",
        "export PATH=" + shlex.quote(str(venv / "bin")) + ':"$PATH"',
    ])


def is_lock_maintenance_request(cfg, request) -> bool:
    """Only a single explicit root uv-lock action can run before installation."""
    if getattr(cfg, "environment", {}).get("mode", "none") == "none":
        return False
    commands = request.get("commands")
    if not isinstance(commands, list) or len(commands) != 1:
        return False
    item = commands[0]
    if not isinstance(item, dict) or item.get("cwd", ".") != ".":
        return False
    try:
        tokens = shlex.split(item.get("cmd", ""))
    except (TypeError, ValueError):
        return False
    return tokens[:2] == ["uv", "lock"] and all(token in {"--offline", "--check"} for token in tokens[2:])


def invalidate_for_lock_maintenance(cfg) -> dict:
    try:
        _, mirror, _, stamp = _paths(cfg)
        _validate_secret_collisions(cfg, sandbox_settings(cfg))
        _invalidate(stamp)
        manifest = mirror / "pyproject.toml"
        _no_symlink(manifest)
        if not manifest.is_file() or manifest.stat().st_nlink != 1:
            raise _SetupError("lock maintenance requires a regular pyproject.toml in the mirror root")
        return {"status": "maintenance", "reason": "lock-only request; environment not prepared"}
    except (OSError, _SetupError, ConfigError, ValueError):
        return {"status": "error", "error": "lock maintenance requires safe local metadata and a root pyproject.toml"}


def prepare_environment(cfg) -> dict:
    """Prepare after a successful pull, failing closed before request commands.

Only success is cached. uv mode tracks packaging/dependency inputs; arbitrary
owner commands conservatively track all non-secret, non-generated source files.
The caller owns the profile process lock and managed-root ownership check.
"""
    stamp = None
    try:
        spec = validate_environment(getattr(cfg, "environment", {}) or {})
        if spec["mode"] == "none":
            return {"status": "disabled"}
        sandbox = require_execution_policy(cfg)
        _validate_secret_collisions(cfg, sandbox)
        root, mirror, venv, stamp = _paths(cfg)
        run = partial(_run, cfg=cfg)
        deadline = time.monotonic() + spec["timeout_seconds"]
        if spec["mode"] == "uv" and not all((mirror / name).is_file() for name in ("pyproject.toml", "uv.lock")):
            raise _SetupError("uv mode requires pyproject.toml and uv.lock in the mirrored repository root")
        python, tool = _resolve_python(spec, mirror, deadline, run=run)
        fingerprint = _fingerprint(mirror, spec, python, tool, sandbox=sandbox)
        prior = _read_stamp(stamp)
        if prior and prior.get("fingerprint") == fingerprint:
            if prior.get("venv_identity") == _venv_identity(venv, python, deadline, run=run):
                return {"status": "reused", "fingerprint": fingerprint}
        _invalidate(stamp)
        _fresh_owned_venv(root, venv)
        cfg._bootstrap_write_root = venv.resolve()
        if spec["mode"] == "uv":
            argv = [str(tool), "venv", "--python", str(python), "--no-python-downloads", str(venv)]
        else:
            argv = [str(python), "-m", "venv", str(venv)]
        run(argv, mirror, deadline, "venv creation")
        _venv_identity(venv, python, deadline, run=run)
        # Paths are shell-quoted and selected after login-shell startup. Do not
        # pass arbitrary pre_exec_hook here: bootstrap must not need activation.
        command = spec["command"]
        if spec["mode"] == "uv":
            tokens = shlex.split(command)
            command = " ".join(shlex.quote(token) for token in [str(tool), *tokens[1:]])
        script = "set -e\n" + environment_hook(cfg) + "\n" + command
        run(shell_argv(cfg, script), mirror, deadline, "dependency installation")
        if _fingerprint(mirror, spec, python, tool, sandbox=sandbox) != fingerprint:
            raise _SetupError("installation changed its inputs; restore the lock/source and retry")
        identity = _venv_identity(venv, python, deadline, run=run)
        _write_stamp(stamp, {"schema_version": 1, "fingerprint": fingerprint,
                             "venv_identity": identity})
        return {"status": "ready", "fingerprint": fingerprint}
    except (ConfigError, _SetupError, OSError, ValueError) as exc:
        # Do not expose exception text from subprocesses, paths, recipes or
        # package managers. Only our fixed diagnostics are allowed out.
        if stamp is not None:
            try:
                _invalidate(stamp)
            except OSError:
                pass
        message = str(exc) if isinstance(exc, _SetupError) else "environment setup failed; check the saved profile and local tools"
        return {"status": "error", "error": message}
    finally:
        if hasattr(cfg, "_bootstrap_write_root"):
            del cfg._bootstrap_write_root


class _SetupError(Exception):
    pass


def _fresh_owned_venv(root, venv):
    """Archive prior owned inputs; give the installer only a new empty venv.

    Ownership metadata is outside child write roots. Older/user-provided
    directories without this record are never adopted, deleted or renamed.
    """
    marker = root / ".watcher-venv-owner.json"
    _no_symlink(marker)
    _no_symlink(venv)
    if venv.exists():
        prior = _read_stamp(marker)
        info = venv.stat()
        if (not venv.is_dir() or not prior or
                prior.get("device") != info.st_dev or prior.get("inode") != info.st_ino):
            raise _SetupError("existing environment has no watcher ownership record; preserve it and create a new profile")
        archive = Path(tempfile.mkdtemp(prefix="venv-retained-", dir=str(root)))
        venv.rename(archive / "venv")
    elif marker.exists():
        raise _SetupError("owned environment is missing; preserve project state and create a new profile")
    venv.mkdir(mode=0o700)
    info = venv.stat()
    _write_stamp(marker, {"schema_version": 1, "device": info.st_dev, "inode": info.st_ino})


def _validate_secret_collisions(cfg, sandbox):
    """Never inspect, invalidate or bootstrap a reserved path called secret."""
    if getattr(cfg, "managed_root", None) is None:
        raise _SetupError("automatic environments require a managed project profile")
    root = Path(cfg.managed_root).resolve()
    mirror = Path(cfg.local_repo_root).resolve()
    reserved = [root / name for name in ("venv", "environment.json", ".harness-watcher-project.json", ".watcher.lock", ".watcher-venv-owner.json")]
    reserved.extend(mirror / name for name in ("pyproject.toml", "uv.lock"))
    for value in sandbox["secret_roots"]:
        secret = Path(value)
        if any(path == secret or path in secret.parents or secret in path.parents for path in reserved):
            raise _SetupError("configured secret root overlaps required environment metadata or runtime")


def _validate_command(command: str, mode: str) -> None:
    if inspect_command(command, owner_setup=True) is not None:
        raise ConfigError("installation command violates the secret-safety policy")
    # A single explicit command is sufficient for make/uv/pip. Disallow shell
    # programs, variable assignments and embedded credentials in saved profiles.
    if any(c in command for c in "\n\r\0$`"):
        raise ConfigError("use one installation command, without shell substitutions")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        raise ConfigError("invalid installation command quoting") from None
    if not tokens or any(set(token) <= set(";&|<>()") for token in tokens):
        raise ConfigError("use one installation command, without shell operators")
    if any(re.match(r"[A-Za-z_][A-Za-z0-9_]*=", token) for token in tokens):
        raise ConfigError("keep environment values outside the installation command")
    if any(re.search(r"(?i)(?:https?://)[^/\s]*@", token) for token in tokens):
        raise ConfigError("keep package-index credentials outside the profile")
    if any(_sensitive(PurePosixPath(token.split("=", 1)[-1])) for token in tokens):
        raise ConfigError("installation commands must not reference secret files")
    words = [Path(tokens[0]).name, *tokens[1:]]
    if words[0] in {"sudo", "su", "env", "bash", "sh", "zsh", "pipx", "curl", "wget"}:
        raise ConfigError("global installers and shell wrappers are not supported")
    if any(token.split("=", 1)[0] in _BAD_FLAGS for token in tokens):
        raise ConfigError("installation must use the profile's local environment")
    if words[:2] in (["uv", "tool"], ["uv", "self"], ["uv", "python"], ["uv", "venv"]):
        raise ConfigError("global tool/Python installation is not supported")
    if any(re.search(r"(?i)(?:token|password|secret|credential|api[-_]?key)(?:=|$)", token) for token in tokens):
        raise ConfigError("keep secrets outside the installation command")
    if mode == "uv" and (words[:2] != ["uv", "sync"] or "--locked" not in words or "--frozen" in words):
        raise ConfigError("uv mode requires uv sync --locked; use command mode for a team recipe")
    if mode == "uv" and "--no-editable" in words:
        raise ConfigError("non-editable installation requires command mode with source invalidation")


def _sensitive(path: PurePosixPath) -> bool:
    if is_secret_path(path):
        return True
    for part in path.parts:
        name = part.lower()
        if (name in _SECRET_DIRS or name.startswith(".env") or name.endswith(".env")
                or name in {"credentials", "credentials.json", "auth.json", ".netrc", ".npmrc", ".pypirc"}
                or name.endswith((".pem", ".key", ".p12", ".pfx", ".crt"))):
            return True
    return False


def _validate_input(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or "\0" in value or _sensitive(path):
        raise ConfigError("environment inputs must be non-secret relative paths")


def _no_symlink(path: Path) -> None:
    for current in (path, *path.parents):
        if current.is_symlink():
            raise _SetupError("managed environment or input path contains a symlink")


def _paths(cfg):
    if getattr(cfg, "managed_root", None) is None:
        raise _SetupError("automatic environments require a managed project profile")
    root = Path(cfg.managed_root).absolute()
    mirror = Path(cfg.local_repo_root).absolute()
    venv = root / "venv"
    stamp = root / "environment.json"
    for path in (root, mirror, venv, stamp):
        _no_symlink(path)
    if not root.is_dir() or not mirror.is_dir() or mirror == root or root not in mirror.parents or venv == mirror or mirror in venv.parents:
        raise _SetupError("managed mirror/environment layout is invalid")
    return root, mirror, venv, stamp


def _resolve_python(spec, cwd, deadline, run=None):
    run = _run if run is None else run
    tool = None
    if spec["mode"] == "uv":
        location = shutil.which("uv")
        if not location:
            raise _SetupError("uv is not installed or not on PATH; no global installation was attempted")
        tool = Path(location).resolve()
        output = run([str(tool), "python", "find", spec["python"], "--system", "--no-python-downloads"],
                      cwd, deadline, "local Python lookup", capture=True)
        if len(output.splitlines()) != 1:
            raise _SetupError("local Python lookup did not return one executable")
        python = Path(output.strip())
    else:
        selected = Path(spec["python"]).expanduser()
        location = str(selected) if selected.is_absolute() else shutil.which(str(selected))
        if not location:
            raise _SetupError("selected local Python was not found; no Python download was attempted")
        python = Path(location)
    if not python.is_absolute() or not python.is_file() or not os.access(python, os.X_OK):
        raise _SetupError("selected local Python executable is unavailable")
    return python.resolve(), tool


def _file_identity(path: Path) -> dict:
    value = path.stat()
    return {"path": str(path.resolve()), "device": value.st_dev, "inode": value.st_ino,
            "size": value.st_size, "mtime_ns": value.st_mtime_ns}


def _fingerprint(root, spec, python, tool, sandbox=None):
    files = {}
    excludes = effective_excludes(SimpleNamespace(sandbox_secret_roots=(sandbox or {}).get("secret_roots", [])), [], root=root)
    def private(path):
        return matches_excludes(path.relative_to(root), excludes)
    if spec["mode"] == "uv" and any(private(root / name) for name in ("uv.lock", "pyproject.toml")):
        raise _SetupError("configured secret root overlaps required environment metadata")
    track_source = _track_source(root, spec)
    for directory, names, filenames in os.walk(root, followlinks=False):
        relative = Path(directory).relative_to(root)
        names[:] = sorted(name for name in names if name not in _SKIP_DIRS and not name.endswith(".egg-info")
                           and (relative / name).as_posix() not in _RUNTIME_PATHS
                           and not private(Path(directory) / name)
                           and not _sensitive(PurePosixPath((relative / name).as_posix())))
        for name in names:
            if (Path(directory) / name).is_symlink():
                raise _SetupError("source input directories must not be symlinks")
        for name in sorted(filenames):
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if private(path) or _sensitive(PurePosixPath(rel)) or name.endswith((".pyc", ".pyo")):
                continue
            selected = (track_source or name in _MANIFESTS
                        or (name.startswith(("requirements", "constraints")) and name.endswith((".txt", ".in"))))
            if selected:
                _add_input(files, root, path)
    for entry in spec["inputs"]:
        path = root / entry
        if private(path):
            raise _SetupError("environment inputs overlap a configured secret root")
        _no_symlink(path)
        if not path.exists():
            files[entry] = None
        elif path.is_dir():
            for directory, names, filenames in os.walk(path, followlinks=False):
                names[:] = sorted(name for name in names if name not in _SKIP_DIRS and not _sensitive(PurePosixPath(name))
                                  and not private(Path(directory) / name))
                for name in names:
                    _no_symlink(Path(directory) / name)
                for name in sorted(filenames):
                    child = Path(directory) / name
                    if not private(child) and not _sensitive(PurePosixPath(child.relative_to(root).as_posix())):
                        _add_input(files, root, child)
        else:
            _add_input(files, root, path)
    value = {"schema": 1, "recipe": spec, "python": _file_identity(python),
             "tool": _file_identity(tool) if tool else None, "files": files,
             "sandbox": sandbox or {"mode": "commands"}, "execution_policy": EXECUTION_POLICY_VERSION}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _track_source(root, spec):
    """Only a proven editable local installation can skip source invalidation.

Python 3.9/3.10 has no stdlib TOML reader; its safe fallback is a complete
non-secret source fingerprint, never a guessed editable installation.
"""
    if spec["mode"] != "uv":
        return True
    lock = root / "uv.lock"
    _no_symlink(lock)
    if not lock.is_file() or lock.stat().st_nlink != 1 or lock.stat().st_size > 32 * 1024 * 1024:
        raise _SetupError("uv lock must be a regular local file")
    text = lock.read_text()
    # Check ordinary lock spellings even on Python versions without tomllib.
    # Escaped local paths are deliberately unsupported instead of being decoded
    # by an incomplete fallback parser.
    for match in re.finditer(r"\b(?:directory|editable|virtual|path)\s*=\s*([\"'])(.*?)\1", text):
        _check_local_source(match.group(2))
    try:
        import tomllib
    except ImportError:
        return True
    try:
        data = tomllib.loads(text)
    except ValueError:
        return True
    packages = data.get("package")
    if not isinstance(packages, list) or not packages:
        return True
    saw_local_editable = False
    for package in packages:
        source = package.get("source") if isinstance(package, dict) else None
        if not isinstance(source, dict) or not source:
            return True
        for key in ("directory", "editable", "virtual", "path"):
            if key in source:
                _check_local_source(source[key])
        if "directory" in source or "path" in source:
            return True
        if "editable" in source or "virtual" in source:
            saw_local_editable = True
        elif not any(key in source for key in ("registry", "git", "url")):
            return True
    return not saw_local_editable


def _check_local_source(value):
    if (not isinstance(value, str) or not value or PurePosixPath(value).is_absolute()
            or ".." in PurePosixPath(value).parts or "\\" in value or _sensitive(PurePosixPath(value))):
        raise _SetupError("local dependency sources must stay inside the mirrored repository")


def _add_input(files, root, path):
    _no_symlink(path)
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_nlink != 1:
        raise _SetupError("environment input is not a regular file")
    if path.stat().st_size > 32 * 1024 * 1024:
        raise _SetupError("environment input exceeds the 32 MiB fingerprint limit")
    files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()


def _venv_identity(venv, python, deadline, run=None):
    run = _run if run is None else run
    _no_symlink(venv)
    config = venv / "pyvenv.cfg"
    _no_symlink(config)
    executable = venv / "bin" / "python"
    if not config.is_file() or config.stat().st_nlink != 1 or not executable.is_file():
        raise _SetupError("managed virtual environment is incomplete; repair it or create a new profile")
    script = "import json,sys; print(json.dumps([sys.prefix, sys.base_prefix, sys._base_executable]))"
    raw = run([str(executable), "-I", "-c", script], venv.parent, deadline, "environment Python validation", capture=True)
    try:
        prefix, base_prefix, base = json.loads(raw)
        valid = Path(prefix).resolve() == venv.resolve() and prefix != base_prefix and Path(base).resolve() == python
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise _SetupError("managed environment uses a different Python; create a new profile for the new Python")
    return {"directory_inode": venv.stat().st_ino, "python": _file_identity(executable),
            "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest()}


def _read_stamp(path):
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > 16384:
        raise _SetupError("environment success record is invalid")
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) and data.get("schema_version") == 1 else None
    except (ValueError, UnicodeError):
        return None


def _invalidate(path):
    if path.exists():
        path.unlink()


def _write_stamp(path, data):
    _no_symlink(path)
    descriptor, filename = tempfile.mkstemp(prefix=".environment-", suffix=".tmp", dir=str(path.parent))
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(data, handle, sort_keys=True)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _run(argv, cwd, deadline, stage, capture=False, cfg=None):
    with command_context(cfg, argv, installation=stage in {"dependency installation", "venv creation"}, cwd=cwd) as (command, environment):
        return _run_process(command, cwd, deadline, stage, capture=capture, environment=environment)


def _run_process(argv, cwd, deadline, stage, capture=False, environment=None):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _SetupError("environment preparation timed out")
    proc = subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.DEVNULL, env=environment,
                            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        output, _ = proc.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        raise _SetupError("environment preparation timed out") from None
    except BaseException:
        _kill_group(proc)
        raise
    # Successful installers must not leave background children with write
    # access to the newly created environment after this step has ended.
    _kill_group(proc)
    if proc.returncode:
        raise _SetupError(f"{stage} failed (exit {proc.returncode}); installer output withheld")
    if capture and len(output) > 16384:
        raise _SetupError(f"{stage} returned unexpected output")
    return output.decode("utf-8", errors="strict").strip() if capture else ""


def _kill_group(proc):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass
    proc.communicate()
