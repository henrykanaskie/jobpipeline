from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def load(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text()) or {}
