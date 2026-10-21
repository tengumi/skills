"""Проверка состава wheel по манифесту без изменений; только стандартная библиотека."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    archive_bytes: int = 64 * 1024 * 1024
    member_bytes: int = 8 * 1024 * 1024
    total_bytes: int = 64 * 1024 * 1024
    members: int = 10000


def safe_relative_path(name: str) -> bool:
    return (
        isinstance(name, str)
        and bool(name)
        and not any(ord(char) < 32 or ord(char) == 127 for char in name)
        and not any(char in name for char in "\\:")
        and all(part not in {"", ".", ".."} for part in name.split("/"))
    )


def forbidden_path(name: str) -> bool:
    """Отвергаем рабочие данные, тесты и ключи по имени до чтения или распаковки."""
    return any(
        part in {
            "tests", "test", "__pycache__", ".pytest_cache", ".ruff_cache",
            ".mypy_cache", ".cache", "cache", "caches", ".git", ".hg", ".svn",
            "conftest.py", "id_rsa", "id_ed25519", "id_dsa", "id_ecdsa",
            ".netrc", ".npmrc", ".pypirc", ".ds_store",
        }
        or part.startswith((".env", "test_"))
        or part.endswith((
            "_test.py", ".pyc", ".pyo", ".db", ".db3", ".duckdb", ".mdb",
            ".db-wal", ".db-shm", ".db-journal", ".pem", ".key", ".p12",
            ".pfx", ".crt", ".cer", ".der", ".jks", ".keystore", ".p8", ".pub",
        ))
        or ".sqlite" in part
        or "secret" in part
        or "credential" in part
        for part in name.lower().split("/")
    )


def _manifest(data: object) -> tuple[set[str], dict[str, str]]:
    if not isinstance(data, dict) or set(data) != {"schema_version", "allowed_roots", "required_files"}:
        raise ValueError("invalid_manifest")
    roots, required = data["allowed_roots"], data["required_files"]
    if data["schema_version"] != 1 or isinstance(data["schema_version"], bool):
        raise ValueError("invalid_manifest")
    if not isinstance(roots, list) or not roots or not isinstance(required, dict) or not required:
        raise ValueError("invalid_manifest")
    for root in roots:
        if not safe_relative_path(root) or "/" in root or forbidden_path(root):
            raise ValueError("invalid_manifest")
    if len(roots) != len(set(roots)):
        raise ValueError("invalid_manifest")
    for name, digest in required.items():
        if (
            not safe_relative_path(name) or forbidden_path(name)
            or name.split("/")[0] not in roots
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("invalid_manifest")
    return set(roots), required


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def load_manifest(path: Path) -> dict:
    """Читаем только указанный несекретный JSON, но не исходные файлы или окружение."""
    path = Path(path)
    if path.suffix != ".json" or forbidden_path(path.name) or path.is_symlink():
        raise ValueError("unsafe_manifest_file")
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("unsafe_manifest_file")
    with path.open("rb") as stream:
        content = stream.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError("manifest_too_large")
    data = json.loads(content, object_pairs_hook=_unique_object)
    _manifest(data)
    return data


def check_wheel(wheel: Path, manifest: dict, *, limits: Limits = Limits()) -> dict:
    """Сначала проверяем метаданные архива, затем хешируем разрешённые файлы с лимитом размера.

    Корректный состав не доказывает работоспособность, отсутствие всех секретов или готовность
    к выпуску. Вызывающая сторона передаёт доверенные хеши зафиксированного контракта;
    ожидания не выводятся из проверяемого wheel, файлы прототипа и секреты не читаются.
    """
    result = {"valid": False, "inventory": [], "errors": []}

    def reject(code: str, **details: object) -> None:
        result["errors"].append({"code": code, **details})

    try:
        roots, required = _manifest(manifest)
        if any(type(value) is not int or value <= 0 for value in vars(limits).values()):
            raise ValueError("invalid_limits")
        wheel = Path(wheel)
        if wheel.suffix != ".whl" or forbidden_path(wheel.name) or wheel.is_symlink():
            reject("unsafe_wheel_file")
            return result
        if not wheel.is_file() or wheel.stat().st_size > limits.archive_bytes:
            reject("archive_size_or_type")
            return result
        with wheel.open("rb") as stream, zipfile.ZipFile(stream) as archive:
            members = archive.infolist()
            result["member_count"] = len(members)
            if len(members) > limits.members:
                reject("member_count_limit")
                return result
            seen, folded = set(), set()
            total = 0
            dist_roots = set()
            for member in members:
                name = member.filename
                total += member.file_size
                if not safe_relative_path(name) or member.is_dir() or name != member.orig_filename:
                    reject("unsafe_member_path")
                    continue
                if name in seen or name.casefold() in folded:
                    reject("duplicate_member", member=name)
                seen.add(name)
                folded.add(name.casefold())
                kind = stat.S_IFMT(member.external_attr >> 16)
                if kind not in (0, stat.S_IFREG):
                    reject("non_regular_member", member=name)
                if member.flag_bits & 1:
                    reject("encrypted_member", member=name)
                if forbidden_path(name):
                    reject("forbidden_member", member=name)
                root = name.split("/")[0]
                if root not in roots:
                    reject("outside_allowlist", member=name)
                if root.endswith(".dist-info"):
                    dist_roots.add(root)
                if member.file_size > limits.member_bytes:
                    reject("member_size_limit", member=name)
            result["unpacked_bytes"] = total
            if total > limits.total_bytes:
                reject("total_size_limit")
            for name in sorted(required.keys() - seen):
                reject("missing_required_file", member=name)
            if len(dist_roots) != 1:
                reject("expected_one_dist_info")
            for root in sorted(dist_roots):
                for filename in ("METADATA", "WHEEL", "RECORD"):
                    if f"{root}/{filename}" not in seen:
                        reject("missing_wheel_metadata", member=f"{root}/{filename}")
            # Не распаковываем содержимое, если метаданные архива небезопасны.
            if result["errors"]:
                return result
            for member in members:
                with archive.open(member) as body_stream:
                    body = body_stream.read(limits.member_bytes + 1)
                if len(body) != member.file_size or len(body) > limits.member_bytes:
                    reject("member_size_mismatch", member=member.filename)
                    continue
                digest = hashlib.sha256(body).hexdigest()
                if member.filename in required and digest != required[member.filename]:
                    reject("required_hash_mismatch", member=member.filename)
                if re.search(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----", body):
                    reject("private_key_material", member=member.filename)
                if any(prefix in body for prefix in (b"/Users/", b"/home/", b"/workspace/", b"/private/", b"/tmp/")) or re.search(
                    rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/]", body
                ):
                    reject("embedded_absolute_source_path", member=member.filename)
                result["inventory"].append({
                    "path": member.filename, "size_bytes": len(body), "sha256": digest,
                })
            stream.seek(0)
            result["wheel_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        result["inventory"].sort(key=lambda item: item["path"])
        result["valid"] = not result["errors"]
    except (OSError, ValueError, TypeError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        reject("invalid_or_unreadable_input")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = check_wheel(args.wheel, load_manifest(args.manifest))
    except (OSError, ValueError, TypeError):
        result = {"valid": False, "errors": [{"code": "invalid_or_unreadable_manifest"}]}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
