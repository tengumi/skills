"""Non-optional name boundaries for source transport and fingerprints.

These are conservative path rules, not a content classifier or an OS sandbox.
All .env variants (including examples) stay outside the transport. Secrets in
arbitrarily named files still require a separate execution/filesystem boundary.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path, PurePath


MANDATORY_SECRET_EXCLUDES = (
    ".git", ".env*", "*.env", ".ENV*", "*.ENV", ".netrc", ".npmrc", ".pypirc",
    "credentials", "credentials.*", ".credentials.json", "auth.json", "secrets", "secrets.*", "certs", "certificates", "keys",
    ".ssh", ".aws", ".azure", ".gcp", ".kube", ".docker", ".config/gcloud", ".config/gh",
    "application_default_credentials.json",
    "service-account*.json", "service_account*.json", "id_rsa*", "id_dsa*", "id_ecdsa*",
    "id_ed25519*", "*.key", "*.pem", "*.p12", "*.pfx", "*.keystore",
)


def with_secret_excludes(excludes: list[str] | tuple[str, ...]) -> list[str]:
    """Caller exclusions may add restrictions, never replace the boundary."""
    return list(dict.fromkeys([*MANDATORY_SECRET_EXCLUDES, *excludes]))


def effective_excludes(cfg, excludes: list[str] | tuple[str, ...], *, root: Path | None = None) -> list[str]:
    """Map explicit OS-denied local paths to the corresponding source paths.

    Both literal and resolved spellings are checked without opening content.
    An explicit secret root containing the whole source is a configuration
    error, never permission to replace/delete/hash that source.
    """
    source = Path(root if root is not None else cfg.local_repo_root).absolute()
    source_paths = (source, source.resolve())
    custom = []
    for raw in getattr(cfg, "sandbox_secret_roots", []):
        secret = Path(raw)
        if not secret.is_absolute() or ".." in secret.parts or any(char in str(secret) for char in "*?[]\n\r\0"):
            raise ValueError("invalid explicit secret boundary")
        for secret_path in (secret, secret.resolve()):
            for source_path in source_paths:
                if source_path == secret_path or secret_path in source_path.parents:
                    raise ValueError("explicit secret boundary contains source root")
                if source_path in secret_path.parents:
                    custom.append(secret_path.relative_to(source_path).as_posix())
    return with_secret_excludes([*excludes, *custom])


def matches_excludes(path: PurePath, patterns: list[str] | tuple[str, ...]) -> bool:
    """Match a relative path or any component, like tar's source exclusions."""
    # Match every contiguous component range: a match on a parent directory
    # protects all descendants, including explicitly named input files.
    fragments = ["/".join(path.parts[start:end])
                 for start in range(len(path.parts))
                 for end in range(start + 1, len(path.parts) + 1)]
    for raw in patterns:
        # Leading/trailing spaces are legal filename characters, including
        # in exact owner-specified secret paths. Never normalize them away.
        pattern = raw.strip("/")
        if pattern and any(fnmatch.fnmatchcase(fragment, pattern) for fragment in fragments):
            return True
    return False


def is_secret_path(path: PurePath) -> bool:
    return matches_excludes(path, MANDATORY_SECRET_EXCLUDES)
