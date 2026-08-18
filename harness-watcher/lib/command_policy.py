"""Fail-closed checks for secret-introspection exec requests.

The watcher is an execution bridge, not a way for Codex to inspect the
workstation's environment.  This module blocks common commands that print
environment variables or read secret-bearing ``.env`` files before a shell is
started.  It is deliberately a defence-in-depth guard, not a shell sandbox.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class CommandPolicyViolation:
    code: str
    message: str


_BOUNDARIES = {";", "&&", "||", "|", "&", "(", ")"}
_RESERVED_WORDS = {"then", "do", "else", "elif", "if", "while", "until"}
_WRAPPERS = {"builtin", "command", "exec", "nice", "nohup", "stdbuf", "sudo", "timeout"}
_ENV_DUMP_TOOLS = {"printenv"}
_ENV_FILE_READERS = {
    "awk",
    "base64",
    "cat",
    "cmp",
    "comm",
    "cut",
    "dd",
    "diff",
    "egrep",
    "fgrep",
    "grep",
    "head",
    "jq",
    "less",
    "more",
    "nl",
    "od",
    "paste",
    "perl",
    "rg",
    "sed",
    "sha256sum",
    "shasum",
    "sort",
    "strings",
    "tail",
    "tac",
    "tr",
    "uniq",
    "xxd",
    "yq",
}
_ENV_FILE_COPY_TOOLS = {"cp", "install", "mv", "rsync", "scp", "tar", "zip"}
_SHELLS = {"bash", "dash", "ksh", "sh", "zsh"}
_INLINE_RUNTIMES = {"node", "nodejs", "perl", "python", "python3", "ruby"}
_SAFE_ENV_FILE_SUFFIXES = (".example", ".sample", ".template", ".dist")
_SUDO_OPTIONS_WITH_VALUE = {
    "-C",
    "-D",
    "-g",
    "-h",
    "-p",
    "-R",
    "-r",
    "-t",
    "-T",
    "-u",
    "--chdir",
    "--close-from",
    "--group",
    "--host",
    "--prompt",
    "--role",
    "--type",
    "--user",
}
_ENV_OPTIONS_WITH_VALUE = {"-C", "-S", "-u", "--chdir", "--split-string", "--unset"}

_SHELL_VALUE = re.compile(
    r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[#!]?[A-Za-z_][A-Za-z0-9_]*(?:[^}]*)\})"
)
_INLINE_ENV_ACCESS = re.compile(
    r"(?:"
    r"\bos\s*\.\s*(?:environ|getenv)\b|"
    r"\bfrom\s+os\s+import\s+[^;\n]*(?:environ|getenv)\b|"
    r"\bprocess\s*\.\s*env\b|"
    r"\bENV\s*(?:\[|\.fetch\b|\.to_h\b|\.each\b|\.keys\b|\.values\b)|"
    r"[%$]ENV\s*\{|"
    r"\bgetenv\s*\("
    r")"
)
_INLINE_ENV_FILE_READ = re.compile(
    r"\b(?:open|read_text|read_bytes|readFile|readFileSync)\b|"
    r"\bFile\.(?:read|binread)\b"
)
_INPUT_REDIRECTION = re.compile(r"(?<!<)<(?!<)\s*(?:['\"])?(?P<path>[^\s'\";&|]+)")
_ENV_FILE_IN_INLINE_CODE = re.compile(
    r"(?:open|read_text|read_bytes)\s*\(\s*['\"][^'\"]*(?:\.env(?:\.[A-Za-z0-9_-]+)?|[^/'\"]+\.env)['\"]"
)
_PROCESS_ENVIRON = re.compile(r"/(?:proc|dev/fd)/[^\s'\"]*/environ\b|/proc/(?:self|\d+)/environ\b")


def inspect_command(command: str) -> CommandPolicyViolation | None:
    """Return a safe diagnostic when a command tries to inspect secret values."""
    if not isinstance(command, str) or not command.strip():
        return None

    if _PROCESS_ENVIRON.search(command):
        return _violation("process-environment-read")

    for match in _INPUT_REDIRECTION.finditer(command):
        path = match.group("path")
        if _is_sensitive_env_reference(path) or _is_sensitive_credential_reference(path):
            return _violation("sensitive-file-read")

    try:
        segments = _command_segments(command)
    except ValueError:
        # The shell will report malformed quoting.  Do not turn the policy
        # checker into a second, inconsistent shell parser.
        return None

    for segment in segments:
        violation = _inspect_segment(segment)
        if violation is not None:
            return violation
    return None


def _command_segments(command: str) -> list[list[str]]:
    segments: list[list[str]] = []
    for line in command.splitlines() or [command]:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        current: list[str] = []
        for token in lexer:
            if token in _BOUNDARIES:
                if current:
                    segments.append(current)
                    current = []
                continue
            if token in _RESERVED_WORDS:
                if current:
                    segments.append(current)
                    current = []
                continue
            current.append(token)
        if current:
            segments.append(current)
    return segments


def _inspect_segment(tokens: list[str]) -> CommandPolicyViolation | None:
    executable, args = _unwrap_command(tokens)
    if executable is None:
        return None

    tool = PurePosixPath(executable).name.lower()

    if tool == "env":
        nested = _env_invoked_command(args)
        if nested is None:
            if args and all(arg in {"--help", "--version"} for arg in args):
                return None
            return _violation("environment-dump")
        return _inspect_segment(nested)

    if tool in _ENV_DUMP_TOOLS:
        return _violation("environment-dump")

    if tool == "set" and not args:
        return _violation("environment-dump")

    if tool in {"declare", "typeset", "export", "readonly"}:
        option_args = [arg for arg in args if arg.startswith(("-", "+"))]
        operands = [arg for arg in args if not arg.startswith(("-", "+"))]
        if not args:
            return _violation("environment-dump")
        if any(arg == "-p" or (arg.startswith("-") and "p" in arg[1:]) for arg in option_args):
            return _violation("environment-dump")
        if not operands:
            return _violation("environment-dump")

    if tool == "compgen" and "-e" in args:
        return _violation("environment-enumeration")

    if tool == "systemctl" and args and args[0] == "show-environment":
        return _violation("environment-dump")

    if tool in {"dotenv", "direnv"} and args and args[0] in {"dump", "export", "get", "list"}:
        return _violation("environment-dump")

    if tool in {"echo", "printf"} and any(_SHELL_VALUE.search(arg) for arg in args):
        return _violation("environment-value-output")

    if tool == "eval" and any(_SHELL_VALUE.search(arg) for arg in args):
        return _violation("environment-value-output")

    if tool == "busybox" and args:
        return _inspect_segment(args)

    if _is_secret_store_read(tool, args):
        return _violation("secret-store-read")

    if tool in _SHELLS:
        nested = _shell_inline_program(args)
        if nested is not None:
            return inspect_command(nested)

    if tool in _INLINE_RUNTIMES:
        flags = {"-c"} if tool.startswith("python") else {"-e", "-c"}
        inline = _inline_program(args, flags=flags)
        if inline is not None:
            reads_sensitive_file = (
                _INLINE_ENV_FILE_READ.search(inline)
                and any(
                    _is_sensitive_env_reference(token)
                    or _is_sensitive_credential_reference(token)
                    for token in _quoted_words(inline)
                )
            )
            if (
                _INLINE_ENV_ACCESS.search(inline)
                or _ENV_FILE_IN_INLINE_CODE.search(inline)
                or reads_sensitive_file
            ):
                return _violation("inline-environment-read")

    has_env_file = any(_is_sensitive_env_reference(arg) for arg in args)
    has_credential_file = any(_is_sensitive_credential_reference(arg) for arg in args)
    if (has_env_file or has_credential_file) and tool in _ENV_FILE_READERS | _ENV_FILE_COPY_TOOLS:
        return _violation("sensitive-file-read")

    if (has_env_file or has_credential_file) and tool in {".", "source"}:
        return _violation("sensitive-file-source")

    if (has_env_file or has_credential_file) and tool == "git" and any(
        arg in {"cat-file", "grep", "show"} for arg in args
    ):
        return _violation("sensitive-file-read")

    if (has_env_file or has_credential_file) and tool == "find" and any(
        arg in {"-exec", "-execdir", "-ok", "-okdir"} for arg in args
    ):
        return _violation("sensitive-file-read")

    if tool == "make" and any(
        arg.lower() in {"dump-config", "dump-env", "env-dump", "print-config", "print-env", "show-env"}
        for arg in args
    ):
        return _violation("environment-dump")

    return None


def _unwrap_command(tokens: list[str]) -> tuple[str | None, list[str]]:
    idx = 0
    while idx < len(tokens) and _is_assignment(tokens[idx]):
        idx += 1
    while idx < len(tokens) and PurePosixPath(tokens[idx]).name.lower() in _WRAPPERS:
        wrapper = PurePosixPath(tokens[idx]).name.lower()
        idx += 1
        if wrapper == "command" and idx < len(tokens) and tokens[idx] in {"-v", "-V"}:
            return None, []
        if wrapper == "sudo":
            idx = _skip_sudo_options(tokens, idx)
            while idx < len(tokens) and _is_assignment(tokens[idx]):
                idx += 1
        elif wrapper == "nice":
            idx = _skip_options_with_values(tokens, idx, {"-n", "--adjustment"})
        elif wrapper == "timeout":
            idx = _skip_options_with_values(
                tokens,
                idx,
                {"-k", "-s", "--kill-after", "--signal"},
            )
            if idx < len(tokens):
                idx += 1  # mandatory DURATION before the command
        elif wrapper == "stdbuf":
            idx = _skip_options_with_values(
                tokens,
                idx,
                {"-e", "-i", "-o", "--error", "--input", "--output"},
            )
        else:
            while idx < len(tokens) and tokens[idx].startswith("-"):
                idx += 1
    if idx >= len(tokens):
        return None, []
    return tokens[idx], tokens[idx + 1 :]


def _inline_program(args: list[str], flags: set[str]) -> str | None:
    for idx, arg in enumerate(args[:-1]):
        if arg in flags:
            return args[idx + 1]
    return None


def _shell_inline_program(args: list[str]) -> str | None:
    for idx, arg in enumerate(args[:-1]):
        if arg == "--command" or (arg.startswith("-") and "c" in arg[1:]):
            return args[idx + 1]
    return None


def _env_invoked_command(args: list[str]) -> list[str] | None:
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--":
            idx += 1
            break
        if arg in _ENV_OPTIONS_WITH_VALUE:
            if idx + 1 >= len(args):
                return None
            if arg in {"-S", "--split-string"}:
                try:
                    expanded = shlex.split(args[idx + 1])
                except ValueError:
                    return None
                args = [*args[:idx], *expanded, *args[idx + 2 :]]
                continue
            idx += 2
            continue
        if any(
            arg.startswith(prefix)
            for prefix in ("--chdir=", "--split-string=", "--unset=")
        ):
            if arg.startswith("--split-string="):
                try:
                    expanded = shlex.split(arg.split("=", 1)[1])
                except ValueError:
                    return None
                args = [*args[:idx], *expanded, *args[idx + 1 :]]
                continue
            idx += 1
            continue
        if arg.startswith("-"):
            idx += 1
            continue
        if _is_assignment(arg):
            idx += 1
            continue
        return args[idx:]
    return args[idx:] or None


def _skip_sudo_options(tokens: list[str], idx: int) -> int:
    while idx < len(tokens):
        arg = tokens[idx]
        if arg == "--":
            return idx + 1
        if arg in _SUDO_OPTIONS_WITH_VALUE:
            idx += 2
            continue
        if any(arg.startswith(f"{option}=") for option in _SUDO_OPTIONS_WITH_VALUE if option.startswith("--")):
            idx += 1
            continue
        if arg.startswith("-"):
            idx += 1
            continue
        return idx
    return idx


def _skip_options_with_values(
    tokens: list[str],
    idx: int,
    options_with_values: set[str],
) -> int:
    while idx < len(tokens):
        arg = tokens[idx]
        if arg == "--":
            return idx + 1
        if arg in options_with_values:
            idx += 2
            continue
        if any(
            arg.startswith(f"{option}=")
            for option in options_with_values
            if option.startswith("--")
        ):
            idx += 1
            continue
        if arg.startswith("-"):
            idx += 1
            continue
        return idx
    return idx


def _quoted_words(text: str) -> list[str]:
    """Return path-like words from inline code without evaluating it."""
    return re.findall(r"['\"]([^'\"]+)['\"]", text)


def _is_assignment(token: str) -> bool:
    name, sep, _value = token.partition("=")
    return bool(sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))


def _is_sensitive_env_reference(token: str) -> bool:
    candidate = token.strip("'\"=:,")
    if "=" in candidate and candidate.startswith("--"):
        candidate = candidate.split("=", 1)[1]
    candidate = candidate.replace("\\ ", " ")
    name = PurePosixPath(candidate).name.lower()
    if name.endswith(_SAFE_ENV_FILE_SUFFIXES):
        return False
    return (
        name == ".env"
        or name == ".envrc"
        or name.startswith(".env.")
        or name.endswith(".env")
        or (any(char in name for char in "*?[") and ".env" in name)
    )


def _is_sensitive_credential_reference(token: str) -> bool:
    candidate = token.strip("'\"=:,")
    if "=" in candidate and candidate.startswith("--"):
        candidate = candidate.split("=", 1)[1]
    path = PurePosixPath(candidate)
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    if parts.intersection({"credentials", "secrets"}):
        return True
    if name in {
        ".netrc",
        ".npmrc",
        ".pypirc",
        "credentials.json",
        "credentials.yaml",
        "credentials.yml",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "service-account.json",
    }:
        return True
    if name.endswith((".key", ".p12", ".pfx")):
        return True
    return name.endswith(".pem") and ("key" in name or "private" in name)


def _is_secret_store_read(tool: str, args: list[str]) -> bool:
    lowered = [arg.lower() for arg in args]
    if tool in {"kubectl", "oc"}:
        action_positions = [
            idx for idx, arg in enumerate(lowered) if arg in {"describe", "get"}
        ]
        return any(
            any(arg in {"secret", "secrets"} or arg.startswith("secret/") for arg in lowered[idx + 1 :])
            for idx in action_positions
        )
    if tool == "aws":
        return _ordered_words(lowered, "secretsmanager", "get-secret-value")
    if tool == "vault":
        return "read" in lowered or _ordered_words(lowered, "kv", "get")
    if tool == "gcloud":
        return _ordered_words(lowered, "secrets", "versions", "access")
    if tool == "security":
        return "find-generic-password" in lowered and "-w" in lowered
    if tool in {"op", "pass"}:
        return bool(lowered and lowered[0] in {"read", "show"})
    return False


def _ordered_words(words: list[str], *expected: str) -> bool:
    cursor = 0
    for word in words:
        if word == expected[cursor]:
            cursor += 1
            if cursor == len(expected):
                return True
    return False


def _violation(code: str) -> CommandPolicyViolation:
    return CommandPolicyViolation(
        code=code,
        message=(
            "blocked by watcher secret-safety policy: exec requests may verify "
            "presence or run approved application checks, but may not read or "
            "print environment, .env, credential, or secret-store values"
        ),
    )
