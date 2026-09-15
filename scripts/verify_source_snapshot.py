#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "paper-v1" / "reproducibility" / "source-file-hashes.json"
SCAFFOLD_PATHS = {
    Path(".gitignore"),
    Path("data/artifacts/.gitkeep"),
    Path("data/processed/.gitkeep"),
    Path("data/raw/.gitkeep"),
}


def normalize_relative_path(raw_path: str) -> Path:
    normalized = raw_path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    relative = Path(normalized)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe source path: {raw_path}")
    return relative


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(repo_root: Path, manifest_path: Path) -> tuple[int, int]:
    detector_root = (repo_root / "lightweight-detector").resolve()
    entries = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    source_entries = []
    excluded = 0
    for entry in entries:
        relative = normalize_relative_path(str(entry["path"]))
        if relative.suffix.lower() == ".pyc" or "__pycache__" in relative.parts:
            excluded += 1
            continue
        source_entries.append((relative, entry))

    errors: list[str] = []
    expected_paths = {relative for relative, _ in source_entries}
    actual_paths = {
        path.relative_to(detector_root)
        for path in detector_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() not in {".pyc", ".pyo"}
        and "__pycache__" not in path.relative_to(detector_root).parts
        and path.relative_to(detector_root) not in SCAFFOLD_PATHS
    }
    for relative in sorted(actual_paths - expected_paths, key=lambda path: path.as_posix()):
        errors.append(f"Unexpected source file: {relative.as_posix()}")

    for relative, entry in source_entries:
        source_path = (detector_root / relative).resolve()
        if detector_root not in source_path.parents:
            errors.append(f"Source path escaped detector root: {relative.as_posix()}")
            continue
        if not source_path.is_file():
            errors.append(f"Missing source file: {relative.as_posix()}")
            continue
        actual_hash = sha256_file(source_path)
        expected_hash = str(entry["sha256"]).lower()
        if actual_hash != expected_hash:
            errors.append(
                f"SHA-256 mismatch for {relative.as_posix()}: "
                f"expected {expected_hash}, got {actual_hash}"
            )

    if errors:
        raise ValueError("\n".join(errors))
    return len(source_entries), excluded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the byte-exact May 25 detector source.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        verified, excluded = verify(args.repo_root, args.manifest)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"source verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"Verified {verified}/{verified} source files")
    suffix = "cache" if excluded == 1 else "caches"
    print(f"Excluded {excluded} Python bytecode {suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
