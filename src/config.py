"""Load harmonization.yaml and enforce the scratch-not-home invariant.

The single non-negotiable rule: `data_root` MUST resolve to a Sherlock scratch
filesystem. Writing rasters under $HOME will fill the 15 GB quota and break
the run. We refuse to proceed if data_root resolves under /home/ or if the
path is not writable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "harmonization.yaml"


class ConfigError(RuntimeError):
    pass


@dataclass
class Config:
    data_root: Path
    target_crs: str
    target_grid: dict[str, Any]
    resample_kernel: str
    vertical: dict[str, Any]
    coregistration: dict[str, Any]
    nodata: dict[str, Any]
    pair_qa: dict[str, Any]
    storage: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def raw_dir(self) -> Path:
        return self.data_root / "raw"

    @property
    def harmonized_dir(self) -> Path:
        return self.data_root / "harmonized"


def _resolve_env(p: str) -> str:
    return os.path.expandvars(os.path.expanduser(p))


def load(path: Path | str | None = None) -> Config:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(f"config file missing: {path}")
    raw = yaml.safe_load(path.read_text())
    required = {
        "data_root", "target_crs", "target_grid", "resample_kernel",
        "vertical_datum_handling", "coregistration", "nodata_policy",
        "pair_qa", "storage",
    }
    missing = required - set(raw)
    if missing:
        raise ConfigError(f"config missing fields: {sorted(missing)}")
    return Config(
        data_root=Path(_resolve_env(raw["data_root"])).resolve(),
        target_crs=raw["target_crs"],
        target_grid=raw["target_grid"],
        resample_kernel=raw["resample_kernel"],
        vertical=raw["vertical_datum_handling"],
        coregistration=raw["coregistration"],
        nodata=raw["nodata_policy"],
        pair_qa=raw["pair_qa"],
        storage=raw["storage"],
        raw=raw,
    )


def validate_data_root(cfg: Config) -> None:
    """Refuse to proceed if data_root is not on a scratch filesystem."""
    p = cfg.data_root
    s = str(p)
    if s.startswith("/home/") or s.startswith(str(Path.home())):
        raise ConfigError(
            f"data_root {p} resolves under home. Bulk rasters must live on "
            f"Sherlock scratch ($SCRATCH or $GROUP_SCRATCH). Refusing to run."
        )
    if not s.startswith("/scratch/") and not s.startswith("/oak/"):
        raise ConfigError(
            f"data_root {p} is not under /scratch or /oak. Refusing to run."
        )
    p.mkdir(parents=True, exist_ok=True)
    if not os.access(p, os.W_OK):
        raise ConfigError(f"data_root {p} exists but is not writable")
    cfg.raw_dir.mkdir(parents=True, exist_ok=True)
    cfg.harmonized_dir.mkdir(parents=True, exist_ok=True)
