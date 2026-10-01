"""Locate the frozen paper v1 detector and make its modules importable.

Import this module before any ``from src...`` import. The detector root can
be overridden with the ``CRACKEDPDFS_DETECTOR_ROOT`` environment variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DETECTOR_ROOT = Path(
    os.environ.get("CRACKEDPDFS_DETECTOR_ROOT", REPO_ROOT / "lightweight-detector")
).resolve()
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
WORK_ROOT = Path(
    os.environ.get("CRACKEDPDFS_REANALYSIS_WORK", REPO_ROOT / ".cache" / "crackedpdfs-reanalysis")
).resolve()
TABLES_DIR = WORK_ROOT / "tables"
ARTIFACTS_DIR = WORK_ROOT / "artifacts"

if not (DETECTOR_ROOT / "src" / "models" / "text_preprocessing.py").is_file():
    raise ImportError(f"Frozen detector not found at {DETECTOR_ROOT}; set CRACKEDPDFS_DETECTOR_ROOT.")
if str(DETECTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(DETECTOR_ROOT))

# Several directories in this repository are called ``src``. Make sure the
# ``src`` package that later imports resolve is the frozen detector's.
for _name in [name for name in sys.modules if name == "src" or name.startswith("src.")]:
    _module_file = getattr(sys.modules[_name], "__file__", None) or ""
    if not str(Path(_module_file).resolve()).startswith(str(DETECTOR_ROOT)):
        del sys.modules[_name]
import src  # noqa: E402

if not str(Path(src.__file__ or "").resolve()).startswith(str(DETECTOR_ROOT)):
    raise ImportError(
        f"The 'src' package resolved to {src.__file__}, not the frozen detector at {DETECTOR_ROOT}."
    )


def frozen_config(name: str) -> Path:
    """Path of a training configuration shipped with the frozen detector."""
    return DETECTOR_ROOT / "configs" / name


def package_config(name: str) -> Path:
    """Path of a training configuration maintained in this package."""
    return PACKAGE_ROOT / "configs" / name
