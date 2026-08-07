"""Главный цикл watcher: опрос удалённого хоста, обработка request, отправка report.

Алгоритм одной итерации:
1. ssh ls REMOTE/docs/harness/exec-requests/ → список файлов
2. Для каждого нового файла (которого нет в processed удалённо и в state локально):
   a. scp скачать на ноутбук
   b. распарсить JSON
   c. (опционально) tar-sync кода с удалённой машины в local_repo_root
   d. выполнить команды через executor
   e. записать report локально
   f. scp загрузить report на удалённую машину
   g. ssh mv request в exec-processed/
   h. (опционально) tar-sync назад, если sync_after_exec
3. Сохранить state, sleep poll_interval_seconds
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import platform
import posixpath
import re
import socket
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from lib import remote_fs
from lib.executor import ExecResult, exec_result_to_dict, execute_request
from lib.filter import FilterConfig, make_filter

if TYPE_CHECKING:
    from lib.audit import AuditLog
    from lib.config import Config


WATCHER_VERSION = "0.2.0"

_ALLOWED_CONTEXT_KEYS = {
    "branch",
    "commands_fingerprint",
    "commit",
    "execution_mode",
    "execution_profile",
    "lock_fingerprint",
    "profile",
    "purpose",
    "source_revision",
    "ticket",
    "tree_fingerprint",
    "verification_level",
}

_FINGERPRINT_CONTEXT_KEYS = {
    "commands_fingerprint",
    "execution_profile",
    "lock_fingerprint",
    "tree_fingerprint",
}

_FINGERPRINT_EXCLUDES = [
    ".git",
    ".DS_Store",
    ".coverage",
    ".harness-watcher-tmp",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "*.egg-info",
    "*.pyc",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "venv",
    "docs/harness/exec-processed",
    "docs/harness/exec-reports",
    "docs/harness/exec-requests",
]

_DEPENDENCY_FILE_PATTERNS = {
    "Cargo.lock",
    "Cargo.toml",
    "Pipfile",
    "Pipfile.lock",
    "go.mod",
    "go.sum",
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "uv.lock",
    "yarn.lock",
}

_CANONICAL_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")
_LEGACY_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")


class Poller:
    def __init__(self, cfg: "Config", audit: "AuditLog", verbose: bool = False):
        self.cfg = cfg
        self.audit = audit
        self.verbose = verbose
        self.hostname = socket.gethostname()
        self.state = _load_state(cfg.state_path)
        self.requests_dir = f"{cfg.remote_repo_root}/docs/harness/exec-requests"
        self.reports_dir = f"{cfg.remote_repo_root}/docs/harness/exec-reports"
        self.processed_dir = f"{cfg.remote_repo_root}/docs/harness/exec-processed"
        # Фильтр шума — применяется только к stdout успешных команд перед записью в report
        self.noise_filter = make_filter(FilterConfig(
            enabled=cfg.filter_enabled,
            strip_ansi=cfg.filter_strip_ansi,
            strip_defaults=cfg.filter_strip_defaults,
            extra_patterns=cfg.filter_extra_patterns,
        ))

    def _say(self, msg: str) -> None:
        """Печать в stdout если verbose, иначе тишина."""
        if self.verbose:
            print(f"[{_now_local()}] {msg}", flush=True)

    def ensure_remote_dirs(self) -> tuple[bool, str]:
        """Создаёт нужные папки на удалённой машине. Возвращает (ok, error_detail)."""
        for d in (self.requests_dir, self.reports_dir, self.processed_dir):
            r = remote_fs.remote_mkdir(self.cfg, d)
            if not r.ok:
                detail = (
                    f"mkdir {d} failed: exit={r.exit_code}, "
                    f"stderr={r.stderr.strip()[:300] or '(empty)'}, "
                    f"stdout={r.stdout.strip()[:200] or '(empty)'}"
                )
                self.audit.log("ensure_dirs_failed", dir=d, exit_code=r.exit_code,
                               stderr=r.stderr[:500], stdout=r.stdout[:200])
                return False, detail
        return True, ""

    def check_connection(self, verbose: bool = False) -> dict:
        """Проверяет SSH-доступ и собирает диагностику. Не создаёт ничего."""
        result: dict = {
            "ssh_host": self.cfg.ssh_host,
            "ssh_port": self.cfg.ssh_port,
            "strict_host_key_checking": self.cfg.strict_host_key_checking,
            "user_known_hosts_file": self.cfg.user_known_hosts_file or "OpenSSH default",
        }

        # 1. SSH ping
        ping = remote_fs._run(
            [*remote_fs._ssh_base(self.cfg), "echo PING && whoami && hostname && pwd"],
            timeout=15,
        )
        result["ssh_ok"] = ping.ok
        result["ssh_exit_code"] = ping.exit_code
        result["ssh_stdout"] = ping.stdout.strip()[:500]
        result["ssh_stderr"] = ping.stderr.strip()[:500]

        # Если ssh упал и попросили verbose — повторяем с -vvv для деталей
        if not ping.ok and verbose:
            verbose_cmd = [
                "ssh",
                "-vvv",
                "-p", str(self.cfg.ssh_port),
                "-i", self.cfg.ssh_key,
                *remote_fs._ssh_options(self.cfg, log_level="DEBUG3"),
                self.cfg.ssh_host,
                "echo PING",
            ]
            debug = remote_fs._run(verbose_cmd, timeout=20)
            result["ssh_debug_output"] = debug.stderr[-3000:]  # последние 3000 символов

        if not ping.ok:
            result["error"] = "SSH connection failed"
            return result

        # 2. Проверка что remote_repo_root существует
        ls = remote_fs._run(
            [*remote_fs._ssh_base(self.cfg),
             f"test -d {remote_fs._quote(self.cfg.remote_repo_root)} && echo EXISTS || echo NOT_FOUND"],
            timeout=15,
        )
        result["repo_root"] = self.cfg.remote_repo_root
        result["repo_root_exists"] = "EXISTS" in ls.stdout

        if "NOT_FOUND" in ls.stdout:
            result["error"] = f"remote_repo_root does not exist: {self.cfg.remote_repo_root}"
            return result

        # 3. Проверка прав на запись (создать и удалить тестовый файл)
        test_path = f"{self.cfg.remote_repo_root}/.harness-watcher-write-test"
        write_test = remote_fs._run(
            [*remote_fs._ssh_base(self.cfg),
             f"touch {remote_fs._quote(test_path)} && rm {remote_fs._quote(test_path)} && echo OK"],
            timeout=15,
        )
        result["write_ok"] = "OK" in write_test.stdout
        if not result["write_ok"]:
            result["error"] = f"no write permission in {self.cfg.remote_repo_root}: {write_test.stderr.strip()[:200]}"
            return result

        # 4. Legacy-диагностика rsync; текущий poller использует tar-sync.
        rsync_check = remote_fs._run(
            [*remote_fs._ssh_base(self.cfg), "which rsync && rsync --version | head -1"],
            timeout=15,
        )
        result["remote_rsync_available"] = rsync_check.ok
        result["remote_rsync_info"] = rsync_check.stdout.strip()[:200] if rsync_check.ok else "not found"

        result["ok"] = True
        return result

    def run_once(self) -> int:
        """Один цикл: проверить, обработать, вернуть число обработанных request."""
        self._say(f"poll {self.requests_dir}")
        ls = remote_fs.remote_ls(self.cfg, self.requests_dir)
        if not ls.ok:
            self.audit.log("poll_failed", error=ls.stderr[:200])
            self._say(f"  poll FAILED: {ls.stderr.strip()[:200]}")
            return 0

        filenames = [f.strip() for f in ls.stdout.splitlines() if f.strip().endswith(".json")]
        filenames.sort()
        self._say(f"  found {len(filenames)} request file(s) on remote")

        processed = 0
        for filename in filenames:
            self._say(f"  new request: {filename}")
            try:
                if self._handle_request(filename):
                    _append_unique(self.state, "processed", filename)
                    _save_state(self.cfg.state_path, self.state)
                    processed += 1
            except Exception as e:
                self.audit.log("handle_failed", filename=filename, error=str(e))
                self._say(f"  handle FAILED: {e}")
        return processed

    def loop(self) -> None:
        """Бесконечный цикл, прерывается Ctrl+C."""
        self.audit.log("watcher_start", version=WATCHER_VERSION, hostname=self.hostname)
        self._say(f"watcher started, polling every {self.cfg.poll_interval_seconds}s")
        ok, err = self.ensure_remote_dirs()
        if not ok:
            self.audit.log("watcher_exit", reason="cant_create_remote_dirs", detail=err)
            print(f"ERROR: cannot create remote dirs:\n  {err}", flush=True)
            return
        self._say("remote dirs OK, entering poll loop")

        try:
            while True:
                t0 = time.monotonic()
                count = self.run_once()
                if count > 0:
                    self.audit.log("poll_cycle", processed=count, duration_ms=int((time.monotonic() - t0) * 1000))
                time.sleep(self.cfg.poll_interval_seconds)
        except KeyboardInterrupt:
            self.audit.log("watcher_stop", reason="keyboard_interrupt")
            self._say("interrupted by user, exiting")

    def _handle_request(self, filename: str) -> bool:
        self.audit.log("request_found", filename=filename)

        # 1. Скачать
        local_tmp = self.cfg.local_repo_root.parent / ".harness-watcher-tmp"
        local_tmp.mkdir(parents=True, exist_ok=True)
        local_req = local_tmp / filename
        self._say(f"    [1/8] download {filename}")
        dl = remote_fs.download_file(self.cfg, f"{self.requests_dir}/{filename}", str(local_req))
        if not dl.ok:
            self.audit.log("download_failed", filename=filename, error=dl.stderr[:200])
            self._say(f"    download FAILED: {dl.stderr.strip()[:200]}")
            return False

        # 2. Парсим
        try:
            request = json.loads(local_req.read_text(encoding="utf-8"))
        except Exception as e:
            self.audit.log("parse_failed", filename=filename, error=str(e))
            self._say(f"    parse FAILED: {e}")
            result = _error_result(filename, None, "invalid request JSON; commands not executed")
            return self._publish_and_finish(
                filename,
                local_req,
                result,
                request=None,
                request_context={},
                sync_result={"status": "not_started", "reason": "invalid_request"},
                source_snapshot={"status": "unavailable", "reason": "invalid_request"},
            )

        if not isinstance(request, dict):
            result = _error_result(filename, None, "request must be a JSON object; commands not executed")
            return self._publish_and_finish(
                filename,
                local_req,
                result,
                request=None,
                request_context={},
                sync_result={"status": "not_started", "reason": "invalid_request"},
                source_snapshot={"status": "unavailable", "reason": "invalid_request"},
            )

        request_identity = _request_identity(filename, request.get("request_id"))
        if request_identity["status"] == "invalid":
            result = _error_result(
                filename,
                request.get("task_id"),
                "request identity is invalid or filename does not match request_id; commands not executed",
            )
            return self._publish_and_finish(
                filename,
                local_req,
                result,
                request=request,
                request_context=_sanitize_request_context(request.get("context")),
                sync_result={"status": "not_started", "reason": "invalid_request_identity"},
                source_snapshot={"status": "unavailable", "reason": "invalid_request_identity"},
                request_identity=request_identity,
            )

        if request_identity["legacy"]:
            self.audit.log(
                "legacy_request_id",
                request_id=request_identity["request_id"],
                filename=filename,
            )

        claimed, claim_reason = self._claim_request_id(
            request_identity["request_id"],
            filename,
        )
        if not claimed:
            request_identity["claim_status"] = (
                "duplicate" if claim_reason != "state_unavailable" else "rejected"
            )
            request_identity["claim_reason"] = claim_reason
            if claim_reason == "state_unavailable":
                result = _error_result(
                    request_identity["request_id"],
                    request.get("task_id"),
                    "idempotency state is unavailable; commands not executed",
                )
                return self._publish_and_finish(
                    filename,
                    local_req,
                    result,
                    request=request,
                    request_context=_sanitize_request_context(request.get("context")),
                    sync_result={"status": "not_started", "reason": "idempotency_state_unavailable"},
                    source_snapshot={"status": "unavailable", "reason": "idempotency_state_unavailable"},
                    request_identity=request_identity,
                )
            return self._finish_duplicate_request(
                filename,
                local_req,
                request,
                request_identity,
            )
        request_identity["claim_status"] = "claimed"

        commands = request.get("commands") or []
        if not isinstance(commands, list):
            result = _error_result(
                request.get("request_id", filename),
                request.get("task_id"),
                "commands must be a list; commands not executed",
            )
            return self._publish_and_finish(
                filename,
                local_req,
                result,
                request=request,
                request_context=_sanitize_request_context(request.get("context")),
                sync_result={"status": "not_started", "reason": "invalid_commands"},
                source_snapshot={"status": "unavailable", "reason": "invalid_commands"},
                request_identity=request_identity,
            )

        n_commands = len(commands)
        self.audit.log("request_parsed", request_id=request.get("request_id"), commands=n_commands)
        self._say(f"    [2/8] parsed: {n_commands} command(s), sync={request.get('sync')}")

        # 3. Sync кода с удалённой машины, если нужно.
        # Приоритет: поле "sync" в request > глобальные настройки конфига.
        # Возможные значения: "pull" | "push" | "both" | "none"
        sync_mode = request.get("sync")
        if sync_mode not in (None, "pull", "push", "both", "none"):
            result = _error_result(
                request.get("request_id", filename),
                request.get("task_id"),
                "invalid sync mode; commands not executed",
            )
            return self._publish_and_finish(
                filename,
                local_req,
                result,
                request=request,
                request_context=_sanitize_request_context(request.get("context")),
                sync_result={"status": "not_started", "reason": "invalid_sync_mode"},
                source_snapshot={"status": "unavailable", "reason": "invalid_sync_mode"},
                request_identity=request_identity,
            )

        if sync_mode is None:
            # Если в request не указано — берём из конфига
            do_pull = self.cfg.sync_before_exec
            do_push = self.cfg.sync_after_exec
        else:
            do_pull = sync_mode in ("pull", "both")
            do_push = sync_mode in ("push", "both")

        effective_sync_mode = _effective_sync_mode(do_pull, do_push)
        sync_result = {
            "mode": effective_sync_mode,
            "pull": {
                "requested": do_pull,
                "status": "pending" if do_pull else "skipped",
            },
            "push": {
                "requested": do_push,
                "status": "pending" if do_push else "skipped",
            },
        }
        request_context = _sanitize_request_context(request.get("context"))

        if do_pull:
            self.audit.log("sync_before_start")
            self._say(f"    [3/8] tar-sync remote → local ({self.cfg.local_repo_root})")
            sync = remote_fs.tar_sync_from_remote(
                self.cfg, self.cfg.remote_repo_root, str(self.cfg.local_repo_root), self.cfg.rsync_exclude
            )
            if not sync.ok:
                sync_result["pull"] = _sync_evidence(sync, self.cfg, status="failed")
                if do_push:
                    sync_result["push"] = {
                        "requested": True,
                        "status": "skipped",
                        "reason": "pull_failed",
                    }
                self.audit.log("sync_before_failed", error=sync.stderr[:300])
                self._say(f"    sync FAILED: {sync.stderr.strip()[:200]}")
                # Fail closed: never test a stale mirror after a requested
                # pull failed.  The error report is still uploaded and the
                # request is moved to processed so the caller gets a terminal
                # answer rather than an endless retry loop.
                result = _error_result(
                    request.get("request_id", filename),
                    request.get("task_id"),
                    "pull sync failed; commands were not executed",
                )
                return self._publish_and_finish(
                    filename,
                    local_req,
                    result,
                    request=request,
                    request_context=request_context,
                    sync_result=sync_result,
                    source_snapshot={"status": "unavailable", "reason": "pull_failed"},
                    request_identity=request_identity,
                )
            else:
                sync_result["pull"] = _sync_evidence(sync, self.cfg, status="success")
                self.audit.log("sync_before_done", duration_ms=sync.duration_ms)
                self._say(f"    sync done in {sync.duration_ms}ms")
        else:
            self._say(f"    [3/8] sync skipped (sync={sync_mode})")

        # Capture the real local source after the requested pull and before
        # any command can generate or modify files.  The fingerprint is based
        # on file bytes; request.context.commit is never treated as evidence.
        source_snapshot = _capture_source_snapshot(
            self.cfg.local_repo_root,
            self.cfg.rsync_exclude,
        )
        if source_snapshot["status"] != "captured":
            result = _error_result(
                request.get("request_id", filename),
                request.get("task_id"),
                "source fingerprint failed; commands were not executed",
            )
            if do_push:
                sync_result["push"] = {
                    "requested": True,
                    "status": "skipped",
                    "reason": "source_fingerprint_failed",
                }
            return self._publish_and_finish(
                filename,
                local_req,
                result,
                request=request,
                request_context=request_context,
                sync_result=sync_result,
                source_snapshot=source_snapshot,
                request_identity=request_identity,
            )

        requested_commit = request_context.get("commit") or request_context.get("source_revision")
        actual_commit = source_snapshot.get("git_head")
        if requested_commit and actual_commit:
            source_snapshot["requested_revision_matches"] = _revision_matches(
                requested_commit,
                actual_commit,
            )

        evidence = _capture_execution_evidence(
            self.cfg,
            request,
            request_context,
            source_snapshot,
        )
        if evidence.get("errors"):
            result = _error_result(
                request.get("request_id", filename),
                request.get("task_id"),
                "execution evidence could not be fingerprinted; commands were not executed",
            )
            if do_push:
                sync_result["push"] = {
                    "requested": True,
                    "status": "skipped",
                    "reason": "evidence_fingerprint_failed",
                }
            return self._publish_and_finish(
                filename,
                local_req,
                result,
                request=request,
                request_context=request_context,
                sync_result=sync_result,
                source_snapshot=source_snapshot,
                evidence=evidence,
                request_identity=request_identity,
            )

        # 4. Выполнить команды
        self._say(f"    [4/8] execute {n_commands} command(s)...")

        def on_progress(event: str, **fields):
            if not self.verbose:
                return
            if event == "cmd_start":
                self._say(f"    → running ({fields['idx']}/{fields['total']}): {fields['cmd']!r}")
            elif event == "cmd_output":
                # Печатаем построчно с отступом, чтобы не путать с шагами watcher'а
                line = fields.get("line", "").rstrip()
                if line:
                    self._say(f"      | {line}")
            elif event == "cmd_done":
                marker = "TIMEOUT" if fields.get("timed_out") else f"exit={fields['exit_code']}"
                self._say(f"    ← done ({fields['idx']}/{fields['total']}): {marker} ({fields['duration_ms']}ms)")

        result = execute_request(self.cfg, request, on_progress=on_progress)

        # Применяем фильтр шума к stdout каждой успешной команды перед записью в report.
        # ВАЖНО: в verbose окне у тебя уже был показан полный поток через on_progress,
        # фильтр трогает только то что пойдёт Codex'у.
        total_removed = 0
        for cr in result.results:
            filtered, removed = self.noise_filter.filter_stdout(cr.stdout, exit_code=cr.exit_code)
            cr.stdout = filtered
            total_removed += removed
        if total_removed > 0:
            self._say(f"    filter: removed {total_removed} noise line(s) from stdout")

        # 5. Sync артефактов назад если нужно (build/, coverage и т.п.).
        # This happens before report upload so the report can describe both
        # directions of the requested sync.
        if do_push:
            self.audit.log("sync_after_start")
            self._say(f"    [7/8] tar-sync local → remote")
            back = remote_fs.tar_sync_to_remote(
                self.cfg, str(self.cfg.local_repo_root), self.cfg.remote_repo_root, self.cfg.rsync_exclude
            )
            if not back.ok:
                sync_result["push"] = _sync_evidence(back, self.cfg, status="failed")
                self.audit.log("sync_after_failed", error=back.stderr[:300])
                self._say(f"    push-sync FAILED: {back.stderr.strip()[:200]}")
                if result.overall_status == "success":
                    result.overall_status = "error"
                    result.error = "push sync failed after command execution"
            else:
                sync_result["push"] = _sync_evidence(back, self.cfg, status="success")
                self.audit.log("sync_after_done", duration_ms=back.duration_ms)
                self._say(f"    push-sync done in {back.duration_ms}ms")
        else:
            self._say(f"    [7/8] push-sync skipped")

        self.audit.log(
            "exec_done",
            request_id=result.request_id,
            status=result.overall_status,
            duration_ms=result.duration_ms,
            filter_removed_lines=total_removed,
            tree_sha256=source_snapshot.get("tree_sha256"),
        )
        self._say(f"    [4/8] done: overall_status={result.overall_status} in {result.duration_ms}ms")
        return self._publish_and_finish(
            filename,
            local_req,
            result,
            request=request,
            request_context=request_context,
            sync_result=sync_result,
            source_snapshot=source_snapshot,
            evidence=evidence,
            request_identity=request_identity,
        )

    def _claim_request_id(self, request_id: str, filename: str) -> tuple[bool, str]:
        """Persist an idempotency claim before sync or command execution."""
        if self.state.get("_load_error"):
            return False, "state_unavailable"

        claimed = self.state.setdefault("claimed_request_ids", [])
        processed_filenames = self.state.setdefault("processed", [])
        if not isinstance(claimed, list) or not isinstance(processed_filenames, list):
            return False, "state_unavailable"

        # `processed` is the legacy filename-only state.  Treat it as a deny
        # list during migration so upgrading the watcher cannot replay a
        # request that the previous version already handled.
        if request_id in claimed:
            return False, "request_id_already_claimed"
        if filename in processed_filenames:
            _append_unique(self.state, "claimed_request_ids", request_id)
            _save_state(self.cfg.state_path, self.state)
            return False, "filename_in_legacy_processed_state"

        _append_unique(self.state, "claimed_request_ids", request_id)
        request_files = self.state.setdefault("request_id_files", {})
        if not isinstance(request_files, dict):
            return False, "state_unavailable"
        request_files[request_id] = filename
        # Save before sync/exec.  A crash may require a new request_id, but it
        # can never make this request execute twice.
        _save_state(self.cfg.state_path, self.state)
        return True, "claimed"

    def _finish_duplicate_request(
        self,
        filename: str,
        local_req: Path,
        request: dict,
        request_identity: dict,
    ) -> bool:
        """Never re-execute a claimed request; preserve an existing report."""
        self.audit.log(
            "duplicate_request_id",
            request_id=request_identity["request_id"],
            filename=filename,
            reason=request_identity.get("claim_reason"),
        )
        report_path = f"{self.reports_dir}/{filename}"
        exists = remote_fs.remote_file_exists(self.cfg, report_path)
        if not exists.ok:
            self.audit.log("duplicate_report_check_failed", filename=filename, error=exists.stderr[:200])
            return False

        if "EXISTS" in exists.stdout:
            # The prior report is authoritative.  Do not overwrite successful
            # evidence with a duplicate-error report.
            mv = remote_fs.remote_move(
                self.cfg,
                f"{self.requests_dir}/{filename}",
                f"{self.processed_dir}/{filename}",
            )
            if not mv.ok:
                self.audit.log("move_processed_failed", filename=filename, error=mv.stderr[:200])
                return False
            try:
                local_req.unlink()
            except OSError:
                pass
            return True

        result = _error_result(
            request_identity["request_id"],
            request.get("task_id"),
            "duplicate request_id; commands were not executed",
        )
        return self._publish_and_finish(
            filename,
            local_req,
            result,
            request=request,
            request_context=_sanitize_request_context(request.get("context")),
            sync_result={"status": "not_started", "reason": "duplicate_request_id"},
            source_snapshot={"status": "unavailable", "reason": "duplicate_request_id"},
            request_identity=request_identity,
        )

    def _publish_and_finish(
        self,
        filename: str,
        local_req: Path,
        result: ExecResult,
        *,
        request: dict | None,
        request_context: dict,
        sync_result: dict,
        source_snapshot: dict,
        evidence: dict | None = None,
        request_identity: dict | None = None,
    ) -> bool:
        """Upload one terminal report and move its request to processed."""
        local_report = local_req.parent / filename
        # local_req and local_report intentionally have the same filename in
        # the shared temporary directory.  Serialize only after the request
        # has already been parsed.
        report_dict = exec_result_to_dict(result, hostname=self.hostname, version=WATCHER_VERSION)
        report_dict["request_context"] = request_context
        report_dict["sync"] = sync_result
        report_dict["source_snapshot"] = source_snapshot
        if request_identity is not None:
            report_dict["request_identity"] = request_identity
        report_dict["evidence"] = evidence or _capture_execution_evidence(
            self.cfg,
            request,
            request_context,
            source_snapshot,
        )
        local_report.write_text(
            json.dumps(report_dict, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        self._say("    [6/8] report written locally; upload → remote")

        up = remote_fs.upload_file(self.cfg, str(local_report), f"{self.reports_dir}/{filename}")
        if not up.ok:
            self.audit.log("upload_report_failed", filename=filename, error=up.stderr[:200])
            self._say(f"    upload FAILED: {up.stderr.strip()[:200]}")
            return False

        self._say("    [8/8] move request → exec-processed/")
        mv = remote_fs.remote_move(
            self.cfg,
            f"{self.requests_dir}/{filename}",
            f"{self.processed_dir}/{filename}",
        )
        if not mv.ok:
            self.audit.log("move_processed_failed", filename=filename, error=mv.stderr[:200])
            self._say(f"    move FAILED: {mv.stderr.strip()[:200]}")
            return False

        self._say(f"    done. request {filename} processed.")
        try:
            local_report.unlink()
        except OSError:
            pass
        return True


def _request_identity(filename: str, raw_request_id: object) -> dict:
    stem = Path(filename).stem
    stem_is_safe = bool(_LEGACY_REQUEST_ID_RE.fullmatch(stem))
    request_id_is_safe = isinstance(raw_request_id, str) and bool(
        _LEGACY_REQUEST_ID_RE.fullmatch(raw_request_id)
    )
    canonical = bool(
        request_id_is_safe and _CANONICAL_REQUEST_ID_RE.fullmatch(raw_request_id)
    )
    legacy = bool(request_id_is_safe and not canonical)
    matches = bool(request_id_is_safe and stem_is_safe and stem == raw_request_id)
    return {
        "status": "valid" if matches else "invalid",
        "request_id": raw_request_id if request_id_is_safe else None,
        "filename_stem": stem if stem_is_safe else None,
        "filename_matches_request_id": matches,
        "canonical": canonical,
        "legacy": legacy,
    }


def _error_result(request_id: object, task_id: object, message: str) -> ExecResult:
    now = _now()
    return ExecResult(
        request_id=str(request_id),
        task_id=str(task_id) if task_id is not None else None,
        started_at=now,
        completed_at=now,
        duration_ms=0,
        overall_status="error",
        results=[],
        error=message,
    )


def _effective_sync_mode(do_pull: bool, do_push: bool) -> str:
    if do_pull and do_push:
        return "both"
    if do_pull:
        return "pull"
    if do_push:
        return "push"
    return "none"


def _sync_evidence(result: remote_fs.CmdResult, cfg: "Config", *, status: str) -> dict:
    evidence = {
        "requested": True,
        "status": status,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
    }
    if status != "success":
        evidence["error"] = _sanitize_error(result.stderr or result.stdout, cfg)
    return evidence


def _sanitize_request_context(raw_context: object) -> dict:
    """Return only small, non-secret coordination fields from request context."""
    if not isinstance(raw_context, dict):
        return {}

    clean: dict = {}
    for key in sorted(_ALLOWED_CONTEXT_KEYS):
        value = raw_context.get(key)
        if isinstance(value, bool) or isinstance(value, int):
            clean[key] = value
        elif isinstance(value, str):
            # Context is evidence metadata, not a log payload.  Reject control
            # characters and cap length so arbitrary notes/secrets are not
            # reflected into reports.
            value = value.strip()
            if not value or len(value) > 256 or not all(ch.isprintable() for ch in value):
                continue
            if key in _FINGERPRINT_CONTEXT_KEYS:
                normalized = _normalize_fingerprint(value)
                if normalized is not None:
                    clean[key] = normalized
            elif key == "commit":
                if re.fullmatch(r"[0-9a-fA-F]{7,64}", value):
                    clean[key] = value.lower()
            elif key in {"branch", "execution_mode", "profile", "source_revision", "ticket", "verification_level"}:
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,255}", value):
                    clean[key] = value
            elif key == "purpose":
                clean[key] = value
    return clean


def _normalize_fingerprint(value: str) -> str | None:
    value = value.strip()
    if value.upper() == "N/A":
        return "N/A"
    if value.lower().startswith("sha256:"):
        value = value[7:]
    if re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return value.lower()
    return None


def _sanitize_error(message: str, cfg: "Config") -> str:
    clean = (message or "sync failed").strip()
    replacements = {
        str(cfg.local_repo_root): "<local_repo_root>",
        cfg.remote_repo_root: "<remote_repo_root>",
        cfg.ssh_host: "<remote_host>",
        cfg.ssh_key: "<ssh_key>",
    }
    for value, marker in replacements.items():
        if value:
            clean = clean.replace(value, marker)
    return clean[:1000]


def _capture_source_snapshot(root: Path, excludes: list[str]) -> dict:
    """Fingerprint the actual local source without exposing file contents/paths."""
    captured_at = _now()
    try:
        tree_sha256, file_count, byte_count = _fingerprint_tree(root, excludes)
        git_head = _git_revision(root, "HEAD")
        git_tree = _git_revision(root, "HEAD^{tree}")
        git_dirty = _git_dirty(root) if git_head else None
        return {
            "status": "captured",
            "captured_at": captured_at,
            "basis": "post_sync_pre_execution",
            "git_head": git_head,
            "git_tree": git_tree,
            "git_dirty": git_dirty,
            "tree_sha256": tree_sha256,
            "files_hashed": file_count,
            "bytes_hashed": byte_count,
        }
    except Exception as exc:
        return {
            "status": "error",
            "captured_at": captured_at,
            "basis": "post_sync_pre_execution",
            "error": f"{type(exc).__name__}: source tree could not be fingerprinted",
        }


def _fingerprint_tree(root: Path, excludes: list[str]) -> tuple[str, int, int]:
    """Hash paths, modes and bytes in a mirror, excluding sync-excluded data."""
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("local repository root is not a directory")

    patterns = [*_FINGERPRINT_EXCLUDES, *excludes]
    digest = hashlib.sha256()
    file_count = 0
    byte_count = 0

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        next_dirs: list[str] = []
        for name in sorted(dirnames):
            path = current / name
            rel = path.relative_to(root)
            if _is_excluded(rel, patterns):
                continue
            info = path.lstat()
            rel_bytes = rel.as_posix().encode("utf-8", errors="surrogateescape")
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path).encode("utf-8", errors="surrogateescape")
                _hash_record(digest, b"L", rel_bytes, str(mode).encode(), target)
                file_count += 1
            else:
                _hash_record(digest, b"D", rel_bytes, str(mode).encode())
                next_dirs.append(name)
        dirnames[:] = next_dirs
        filenames.sort()

        for name in filenames:
            path = current / name
            rel = path.relative_to(root)
            if _is_excluded(rel, patterns):
                continue

            info = path.lstat()
            rel_bytes = rel.as_posix().encode("utf-8", errors="surrogateescape")
            mode = stat.S_IMODE(info.st_mode)

            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path).encode("utf-8", errors="surrogateescape")
                _hash_record(digest, b"L", rel_bytes, str(mode).encode(), target)
                file_count += 1
                continue

            if not stat.S_ISREG(info.st_mode):
                _hash_record(digest, b"S", rel_bytes, str(mode).encode())
                file_count += 1
                continue

            _hash_record(digest, b"F", rel_bytes, str(mode).encode(), str(info.st_size).encode())
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            byte_count += _hash_file_bytes(digest, path, info, flags)
            file_count += 1

    return digest.hexdigest(), file_count, byte_count


def _hash_file_bytes(digest, path: Path, info, flags: int | None = None) -> int:
    if flags is None:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    byte_count = 0
    try:
        before = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
            raise RuntimeError("source file changed before fingerprinting")
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            byte_count += len(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)

    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("source file changed while fingerprinting")
    digest.update(b"\0")
    return byte_count


def _hash_record(digest, *fields: bytes) -> None:
    for field in fields:
        digest.update(str(len(field)).encode("ascii"))
        digest.update(b":")
        digest.update(field)
        digest.update(b"\0")


def _is_excluded(rel: Path, patterns: list[str]) -> bool:
    rel_text = rel.as_posix()
    for raw_pattern in patterns:
        pattern = raw_pattern.strip().strip("/")
        if not pattern:
            continue
        if fnmatch.fnmatch(rel_text, pattern):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in rel.parts):
            return True
    return False


def _git_revision(root: Path, revision: str) -> str | None:
    if not (root / ".git").exists():
        return None
    try:
        completed = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), "rev-parse", "--verify", revision],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    if completed.returncode != 0 or not (40 <= len(value) <= 64):
        return None
    if any(ch not in "0123456789abcdefABCDEF" for ch in value):
        return None
    return value.lower()


def _git_dirty(root: Path) -> bool | None:
    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-C",
                str(root),
                "status",
                "--porcelain",
                "--untracked-files=normal",
            ],
            capture_output=True,
            text=False,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return bool(completed.stdout)


def _revision_matches(requested: str, actual: str) -> bool:
    requested = requested.lower()
    actual = actual.lower()
    return actual.startswith(requested) or requested.startswith(actual)


def _capture_execution_evidence(
    cfg: "Config",
    request: dict | None,
    request_context: dict,
    source_snapshot: dict,
) -> dict:
    """Build the observed reuse key and compare it with requested metadata."""
    errors: dict[str, str] = {}

    tree_fingerprint = (
        source_snapshot.get("tree_sha256")
        if source_snapshot.get("status") == "captured"
        else None
    )

    lock_fingerprint: str | None = None
    lock_files_hashed = 0
    if source_snapshot.get("status") == "captured":
        try:
            lock_fingerprint, lock_files_hashed = _dependency_fingerprint(
                cfg.local_repo_root,
                cfg.rsync_exclude,
            )
        except Exception as exc:
            errors["lock_fingerprint"] = f"{type(exc).__name__}: dependency files could not be fingerprinted"

    try:
        commands_fingerprint = _commands_fingerprint(request)
    except (TypeError, ValueError) as exc:
        commands_fingerprint = None
        errors["commands_fingerprint"] = str(exc)

    execution_profile = _execution_profile_fingerprint(cfg)
    observed = {
        "tree_fingerprint": tree_fingerprint,
        "lock_fingerprint": lock_fingerprint,
        "lock_files_hashed": lock_files_hashed,
        "execution_profile": execution_profile,
        "commands_fingerprint": commands_fingerprint,
    }

    requested_matches: dict[str, bool | None] = {}
    for key in (
        "tree_fingerprint",
        "lock_fingerprint",
        "execution_profile",
        "commands_fingerprint",
    ):
        requested = request_context.get(key)
        actual = observed.get(key)
        requested_matches[key] = None if requested is None or actual is None else requested == actual
    requested_matches["all"] = all(value is True for value in requested_matches.values())

    evidence = {
        "fingerprint_schema": "harness-watcher/v1",
        "observed": observed,
        "requested_matches": requested_matches,
    }
    if errors:
        evidence["errors"] = errors
    return evidence


def _commands_fingerprint(request: dict | None) -> str | None:
    if request is None:
        return None
    commands = request.get("commands") or []
    if not isinstance(commands, list):
        raise TypeError("commands must be a list")

    normalized: list[dict[str, str]] = []
    for item in commands:
        if not isinstance(item, dict):
            raise TypeError("each command must be an object")
        cmd = item.get("cmd")
        cwd = item.get("cwd", ".")
        if not isinstance(cmd, str) or not cmd:
            raise ValueError("each command must contain a non-empty string cmd")
        if not isinstance(cwd, str) or not cwd:
            raise ValueError("each command cwd must be a non-empty string")
        normalized.append({"cmd": cmd, "cwd": posixpath.normpath(cwd)})

    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _dependency_fingerprint(root: Path, excludes: list[str]) -> tuple[str, int]:
    root = root.resolve(strict=True)
    patterns = [*_FINGERPRINT_EXCLUDES, *excludes]
    selected: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not _is_excluded((current / name).relative_to(root), patterns)
            and not (current / name).is_symlink()
        )
        for name in sorted(filenames):
            path = current / name
            rel = path.relative_to(root)
            if _is_excluded(rel, patterns) or not _is_dependency_file(name):
                continue
            selected.append(path)

    if not selected:
        return "N/A", 0

    digest = hashlib.sha256()
    for path in sorted(selected, key=lambda item: item.relative_to(root).as_posix()):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("dependency metadata must be regular files")
        rel_bytes = path.relative_to(root).as_posix().encode("utf-8", errors="surrogateescape")
        _hash_record(
            digest,
            b"F",
            rel_bytes,
            str(stat.S_IMODE(info.st_mode)).encode(),
            str(info.st_size).encode(),
        )
        _hash_file_bytes(digest, path, info)
    return digest.hexdigest(), len(selected)


def _is_dependency_file(name: str) -> bool:
    if name in _DEPENDENCY_FILE_PATTERNS:
        return True
    return fnmatch.fnmatch(name, "requirements*.txt") or fnmatch.fnmatch(name, "requirements*.in") or fnmatch.fnmatch(name, "constraints*.txt")


def _execution_profile_fingerprint(cfg: "Config") -> str:
    """Hash execution-affecting settings without exposing hook/env values."""
    selected_environment = {
        key: os.environ.get(key, "")
        for key in ("HOME", "LANG", "LC_ALL", "PATH", "PYTHONPATH", "SHELL", "VIRTUAL_ENV")
    }
    profile = {
        "schema": "harness-watcher-profile/v1",
        "watcher_version": WATCHER_VERSION,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "local_repo_root_sha256": hashlib.sha256(str(cfg.local_repo_root.resolve()).encode()).hexdigest(),
        "pre_exec_hook_sha256": hashlib.sha256(cfg.pre_exec_hook.encode()).hexdigest(),
        "selected_environment_sha256": hashlib.sha256(
            json.dumps(selected_environment, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "default_timeout_seconds": cfg.default_timeout_seconds,
        "filter": {
            "enabled": cfg.filter_enabled,
            "strip_ansi": cfg.filter_strip_ansi,
            "strip_defaults": cfg.filter_strip_defaults,
            "extra_patterns_sha256": hashlib.sha256(
                json.dumps(cfg.filter_extra_patterns, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest(),
        },
        "sync_exclude_sha256": hashlib.sha256(
            json.dumps(cfg.rsync_exclude, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    serialized = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"processed": [], "claimed_request_ids": [], "request_id_files": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("state root must be an object")
        return state
    except Exception:
        # Corrupted idempotency state must not silently become an empty state:
        # that would allow previously executed requests to run again.
        return {
            "processed": [],
            "claimed_request_ids": [],
            "request_id_files": {},
            "_load_error": "invalid_state",
        }


def _append_unique(state: dict, key: str, value: str) -> None:
    values = state.setdefault(key, [])
    if not isinstance(values, list):
        raise ValueError(f"state.{key} must be a list")
    if value not in values:
        values.append(value)


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_local() -> str:
    """Локальное время в формате HH:MM:SS для удобного чтения в stdout."""
    return datetime.now().strftime("%H:%M:%S")
