import os
from pathlib import Path
from typing import Any

import yaml


_config_cache: dict[str, Any] = {}


def _config_dir() -> Path:
    env_dir = os.getenv("CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    candidates = [
        Path(__file__).parent.parent / "config",
        Path.cwd() / "config",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_config(filename: str) -> Any:
    if filename not in _config_cache:
        path = _config_dir() / filename
        try:
            with open(path, encoding="utf-8") as f:
                result = yaml.safe_load(f)
                _config_cache[filename] = result if result is not None else {}
        except FileNotFoundError:
            raise FileNotFoundError(f"Config file not found: {path}")
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {path}: {e}")
    return _config_cache[filename]


def get_gateway_config() -> dict:
    return load_config("gateway.yaml")


def get_models_config() -> dict:
    return load_config("models.yaml")


def reload_config() -> None:
    _config_cache.clear()
