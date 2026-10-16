"""Text-only policy tests; no network, deletion or package command is executed."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.command_policy import inspect_command


@pytest.mark.parametrize("command", [
    "curl https://example.invalid", "/usr/bin/wget https://example.invalid",
    "env TESTING=1 timeout 4 curl https://example.invalid",
    "busybox wget https://example.invalid", "bash -lc 'ssh example.invalid true'",
    "scp file example.invalid:/tmp/file", "sftp example.invalid", "nc -l 9000",
    "printf x | xargs curl", "xargs -I {} wget {}",
    "find . -exec curl https://example.invalid \\;",
    "echo ok; curl https://example.invalid", "true && wget https://example.invalid",
    "echo ok\nssh example.invalid", "(true);curl https://example.invalid",
    "bash -c 'echo text > /dev/tcp/example.invalid/80'",
    "git -C project fetch", "git -c remote.origin.url=example.invalid pull",
    "git clone https://example.invalid/repo", "git ls-remote origin",
    "openssl s_client -connect example.invalid:443",
    "git submodule update --init", "git -C project submodule update --remote",
    "git submodule --quiet add https://example.invalid/repo deps/repo",
    "python3 -c 'import requests; requests.get(\"https://example.invalid\")'",
    "python3.12 -c 'from urllib.request import urlopen; urlopen(\"https://example.invalid\")'",
    "python -c 'import socket; socket.socket()'",
    "node -e 'https.get(\"https://example.invalid\")'",
    "rm -rf old", "rmdir old", "/usr/bin/unlink old", "shred old",
    "env TESTING=1 rm old", "find . -delete", "find . -exec rm {} +",
    "find . -execdir bash -c 'rm old' \\;", "printf old | xargs -n 1 rm",
    "git clean -fd", "git -C project reset --hard HEAD",
    "python3 -c 'import os; os.remove(\"old\")'",
    "python3 -c 'from os import remove; remove(\"old\")'",
    "python3 -c 'from pathlib import Path; Path(\"old\").unlink()'",
    "python3 -c 'import shutil; shutil.rmtree(\"old\")'",
    "node -e 'require(\"fs\").unlinkSync(\"old\")'",
    "pip install pytest", "python3 -m pip install pytest", "pip3.12 download pytest",
    "pip --no-index install https://example.invalid/wheel.whl",
    "uv sync --locked", "uv --directory project sync --locked", "uv pip install pytest",
    "uv tool run ruff", "uvx ruff", "uv run --with requests python helper.py",
    "npm ci", "npx tool", "pipx run tool",
    "echo $(curl https://example.invalid)", "echo `curl https://example.invalid`",
    "eval 'curl https://example.invalid'", "echo 'unterminated",
    "TOOL=curl; $TOOL https://example.invalid",
])
def test_explicit_unsafe_requests_are_rejected(command):
    assert inspect_command(command) is not None, command


@pytest.mark.parametrize("command", [
    "make test", "make verify", "python3 -m pytest tests", "python3.12 -m pytest tests",
    "python3 -m venv /tmp/owned-venv", "ruff check .", "git diff --check",
    "git -C project status --short", "python3 -c 'print(1 + 2)'",
    "python3 -c 'items = [1, 2]; items.remove(1)'",
    "test -f .env", "test -n \"${API_TOKEN+x}\"", "command -v curl",
    "env TESTING=1 make test", "set -euo pipefail; make test",
    "pip install --no-index --find-links /tmp/wheels pytest",
    "python3 -m pip --no-index install pytest", "pip list", "uv pip list",
    "uv sync --locked --offline", "uv --offline sync --locked",
    "uv pip install --no-index pytest", "uvx --offline ruff check .",
    "uv run --offline pytest", "python3 helper.py", "make integration-test",
    "uv run pytest -k install", "uv run pytest -k sync",
    "uv --directory project run pytest -k install",
    "uv run --python python3 pytest -k sync",
    "pip show install", "npm run install",
    "openssl version", "git submodule status", "git -C project submodule --quiet status",
])
def test_normal_checks_and_explicit_offline_setup_remain_allowed(command):
    # helper.py and make targets are intentionally NOT inspected. Their
    # indirect operations are beyond this best-effort text filter's guarantee.
    assert inspect_command(command) is None, command


@pytest.mark.parametrize("command", [
    "uv sync --locked", "pip install pytest", "python3 -m pip install pytest",
    "env TESTING=1 uv sync --locked", "bash -c 'uv sync --locked'",
])
def test_only_trusted_owner_setup_exempts_package_installs(command):
    assert inspect_command(command) is not None
    assert inspect_command(command, owner_setup=True) is None


@pytest.mark.parametrize("tls_flag", ["--native-tls", "--system-certs"])
def test_uv_tls_flags_do_not_hide_network_sync(tls_flag):
    command = f"uv {tls_flag} sync --locked"
    violation = inspect_command(command)
    assert violation is not None
    assert violation.code == "package-network-command"
    assert inspect_command(f"{command} --offline") is None
    assert inspect_command(f"uv --offline {tls_flag} sync --locked") is None
    assert inspect_command(command, owner_setup=True) is None


@pytest.mark.parametrize("command", [
    "curl https://example.invalid", "rm old", "cat .env", "printenv",
    "python3 -c 'import os; print(os.environ)'",
])
def test_owner_setup_does_not_disable_other_guards(command):
    assert inspect_command(command, owner_setup=True) is not None


def test_secret_diagnostics_remain_compatible():
    violation = inspect_command("cat .env")
    assert violation.code == "sensitive-file-read"
    assert violation.message.startswith("blocked by watcher secret-safety policy:")


def test_new_diagnostics_do_not_repeat_request_text():
    violation = inspect_command("curl https://example.invalid/private-canary")
    assert violation.code == "network-command"
    assert violation.message.startswith("blocked by watcher command policy:")
    assert "private-canary" not in violation.message
