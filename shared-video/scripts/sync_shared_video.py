#!/usr/bin/env python3
"""Copy an explicit shared-video profile without copying the provider Skill.

Provider manifest: distribution/shared-video-manifest.json, for example::

    {"source_key": "shared-video", "files": {"full": ["scripts/example.py"]}}

Only the selected list is copied. The destination is TARGET / BUNDLE_DIR.
Check mode needs only the destination lock, so a derived bundle is standalone.
Existing untracked files require --adopt-existing before they can be replaced.
The lock records before/after hashes for those explicitly adopted files.
Previously tracked files are never removed or silently dropped from the lock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
import tempfile


PROFILES = ("full", "publication", "audio-subtitles", "shared-quality")
MANIFEST_PATH = "distribution/shared-video-manifest.json"
LOCK_PATH = "distribution/shared-video-lock.json"
LOCK_SCHEMA = 1


class SyncError(Exception):
    """A validation error, reported without a traceback by the CLI."""


def relative_path(value: object, label: str, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise SyncError(f"{label} must be a nonempty relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or PureWindowsPath(value).drive
        or ".." in path.parts
        or any(part.casefold() == ".git" for part in path.parts)
        or "\x00" in value
        or any(ord(char) < 32 for char in value)
    ):
        raise SyncError(f"{label} must be relative and cannot contain '..' or '.git'")
    normalized = path.as_posix()
    if normalized == "." and not allow_dot:
        raise SyncError(f"{label} must name a file")
    return normalized


def source_key(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(char in value for char in "/\\")
        or any(ord(char) < 32 for char in value)
        or PureWindowsPath(value).drive
    ):
        raise SyncError("source_key must be a nonempty portable identifier")
    return value


def root_directory(path: Path, label: str, *, must_exist: bool) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise SyncError(f"cannot resolve {label}: {exc}") from exc
    if resolved.exists() and not resolved.is_dir():
        raise SyncError(f"{label} must be a directory")
    if any(part.casefold() == ".git" for part in resolved.parts):
        raise SyncError(f"{label} cannot be inside '.git'")
    return resolved


def contained_file(root: Path, relative: str, *, required: bool) -> Path:
    """Check containment and reject symlink components below the chosen root."""
    path = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise SyncError(f"symlink is not allowed in managed path: {relative}")
    try:
        resolved = path.resolve(strict=required)
        resolved.relative_to(root)
    except (ValueError, OSError, RuntimeError) as exc:
        raise SyncError(f"missing or out-of-bounds managed path: {relative}") from exc
    if resolved.exists() and not resolved.is_file():
        raise SyncError(f"managed path is not a regular file: {relative}")
    if required and not resolved.is_file():
        raise SyncError(f"missing managed file: {relative}")
    for parent in path.parents:
        if parent == root:
            break
        if parent.exists() and not parent.is_dir():
            raise SyncError(f"managed path has a non-directory parent: {relative}")
    return path


def read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise SyncError(f"{label} must contain a JSON object")
    return value


def record(data: bytes) -> dict:
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def lock_records(lock: dict) -> dict[str, dict]:
    if type(lock.get("schema")) is not int or lock["schema"] != LOCK_SCHEMA:
        raise SyncError("unsupported lock schema")
    source_key(lock.get("source_key"))
    if lock.get("profile") not in PROFILES:
        raise SyncError("lock has an invalid profile")
    files = lock.get("files")
    if not isinstance(files, dict):
        raise SyncError("lock files must be an object")
    checked = {}
    for raw, metadata in files.items():
        relative = relative_path(raw, "lock file")
        if relative in checked or relative == LOCK_PATH:
            raise SyncError(f"duplicate or reserved lock path: {relative}")
        if not isinstance(metadata, dict):
            raise SyncError(f"invalid lock metadata: {relative}")
        digest, size = metadata.get("sha256"), metadata.get("bytes")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(size) is not int
            or size < 0
        ):
            raise SyncError(f"invalid lock hash or byte count: {relative}")
        checked[relative] = {"sha256": digest, "bytes": size}
    return checked


def verify_files(destination: Path, files: dict[str, dict]) -> None:
    for relative, expected in files.items():
        path = contained_file(destination, relative, required=True)
        if record(path.read_bytes()) != expected:
            raise SyncError(f"local file differs from lock; refusing overwrite: {relative}")


def adoption_records(lock: dict, files: dict[str, dict]) -> dict[str, dict]:
    adoption = lock.get("adoption", {})
    if not isinstance(adoption, dict):
        raise SyncError("lock adoption must be an object")
    checked = {}
    for raw, metadata in adoption.items():
        relative = relative_path(raw, "adoption file")
        if relative not in files or relative in checked or not isinstance(metadata, dict):
            raise SyncError(f"invalid adoption path or metadata: {relative}")
        hashes = {}
        for field in ("before_sha256", "after_sha256"):
            digest = metadata.get(field)
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise SyncError(f"invalid adoption hash: {relative}")
            hashes[field] = digest
        checked[relative] = hashes
    return checked


def load_lock(destination: Path, *, required: bool) -> tuple[dict | None, dict]:
    path = contained_file(destination, LOCK_PATH, required=required)
    if not path.exists():
        return None, {}
    lock = read_json(path, "destination lock")
    return lock, lock_records(lock)


def load_profile(source: Path, profile: str) -> tuple[str, list[str]]:
    manifest = read_json(
        contained_file(source, MANIFEST_PATH, required=True), "provider manifest"
    )
    key = source_key(manifest.get("source_key"))
    profiles = manifest.get("files")
    if not isinstance(profiles, dict) or not isinstance(profiles.get(profile), list):
        raise SyncError(f"manifest files.{profile} must be an explicit file list")
    files = []
    for raw in profiles[profile]:
        relative = relative_path(raw, "manifest file")
        if relative == LOCK_PATH or relative in files:
            raise SyncError(f"duplicate or reserved manifest path: {relative}")
        files.append(relative)
    return key, files


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    """Stage beside the file, then replace it; never delete tracked paths."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staged = tempfile.mkstemp(prefix=".shared-video-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(staged, mode)
        os.replace(staged, path)
    except OSError as exc:
        # Retain a failed stage for recovery instead of deleting any files.
        raise SyncError(f"write failed; any staged data was retained: {exc}") from exc


def destination_root(target: Path, bundle_dir: str, *, check: bool) -> Path:
    target_root = root_directory(target, "target", must_exist=check)
    relative = relative_path(bundle_dir, "bundle-dir", allow_dot=True)
    destination = target_root
    for part in PurePosixPath(relative).parts:
        destination = destination / part
        if destination.is_symlink():
            raise SyncError("bundle-dir cannot pass through a symlink")
        if destination.exists() and not destination.is_dir():
            raise SyncError("bundle-dir must be a directory")
    resolved = root_directory(destination, "destination", must_exist=check)
    try:
        resolved.relative_to(target_root)
    except ValueError as exc:
        raise SyncError("bundle-dir escapes target") from exc
    return resolved


def run(args: argparse.Namespace) -> dict:
    destination = destination_root(args.target, args.bundle_dir, check=args.check)
    lock, old_files = load_lock(destination, required=args.check)
    adoption = adoption_records(lock, old_files) if lock is not None else {}
    if args.check:
        if args.source is not None or args.adopt_existing:
            raise SyncError("--source and --adopt-existing are sync-only options")
        if args.profile is not None and args.profile != lock["profile"]:
            raise SyncError("requested profile differs from destination lock")
        verify_files(destination, old_files)
        if args.compare_source is not None:
            provider = root_directory(args.compare_source, "comparison source", must_exist=True)
            for relative, expected in old_files.items():
                path = contained_file(provider, relative, required=True)
                if record(path.read_bytes()) != expected:
                    raise SyncError(f"provider differs from destination lock: {relative}")
        return {"status": "checked", "profile": lock["profile"], "files": len(old_files),
                "source_compared": args.compare_source is not None}

    if args.compare_source is not None:
        raise SyncError("--compare-source requires --check")
    if args.profile is None:
        raise SyncError("--profile is required for sync")
    provider = root_directory(
        args.source if args.source is not None else Path(__file__).resolve().parent.parent,
        "source", must_exist=True,
    )
    if provider == destination:
        raise SyncError("source and destination must be different directories")
    key, selected = load_profile(provider, args.profile)
    if lock is not None:
        if lock["source_key"] != key:
            raise SyncError("destination lock belongs to another source_key")
        verify_files(destination, old_files)
        omitted = sorted(set(old_files).difference(selected))
        if omitted:
            raise SyncError("whitelist omits previously tracked files; use a fresh destination: "
                            + ", ".join(omitted))

    # Complete every source, containment and ownership check before writing anything.
    prepared = []
    new_files = {}
    adopted = 0
    for relative in selected:
        source_path = contained_file(provider, relative, required=True)
        data = source_path.read_bytes()
        expected = record(data)
        target_path = contained_file(destination, relative, required=False)
        existing = target_path.read_bytes() if target_path.exists() else None
        if existing is not None and relative not in old_files:
            if not args.adopt_existing:
                raise SyncError(f"existing untracked file requires --adopt-existing: {relative}")
            adoption[relative] = {"before_sha256": record(existing)["sha256"],
                                  "after_sha256": expected["sha256"]}
            adopted += 1
        mode = stat.S_IMODE(source_path.stat().st_mode)
        prepared.append((target_path, data, mode, existing != data))
        new_files[relative] = expected

    new_lock = {"schema": LOCK_SCHEMA, "source_key": key, "profile": args.profile,
                "files": new_files}
    if adoption:
        new_lock["adoption"] = adoption
    lock_data = (json.dumps(new_lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    copied = 0
    for path, data, mode, changed in prepared:
        if changed:
            atomic_write(path, data, mode)
            copied += 1
    lock_path = contained_file(destination, LOCK_PATH, required=False)
    if not lock_path.exists() or lock_path.read_bytes() != lock_data:
        atomic_write(lock_path, lock_data)
    return {"status": "synced", "profile": args.profile, "files": len(new_files),
            "copied": copied, "unchanged": len(new_files) - copied, "adopted": adopted}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--profile", choices=PROFILES)
    parser.add_argument("--bundle-dir", default=".")
    parser.add_argument("--source", type=Path, help="provider root; defaults to this script's parent.parent")
    parser.add_argument("--adopt-existing", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--compare-source", type=Path, help="with --check, also compare each locked provider file")
    args = parser.parse_args()
    try:
        result = run(args)
    except (SyncError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
