from pathlib import Path

from app import config


ROOT = Path(__file__).resolve().parents[1]


def test_default_config_dir_falls_back_to_working_directory(monkeypatch):
    monkeypatch.delenv("CONFIG_DIR", raising=False)
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(
        config,
        "__file__",
        "/usr/local/lib/python3.12/site-packages/app/config.py",
    )

    loaded = config.load_config("gateway.yaml")

    assert loaded["server"]["host"] == "0.0.0.0"
