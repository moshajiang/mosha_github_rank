from dataclasses import dataclass
from pathlib import Path
import os
import yaml


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    db_path: Path
    config_path: Path
    github_token: str = ""
    summary_model: str = ""
    summary_url: str = "http://127.0.0.1:11434"
    summary_daily_limit: int = 20
    summary_auto: bool = False

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        return cls(
            Path(env.get("GITHUB_RANK_DB", str(ROOT / "data/github_rank.sqlite3"))),
            Path(env.get("GITHUB_RANK_CONFIG", str(ROOT / "config/sources.yaml"))),
            env.get("GITHUB_TOKEN", ""),
            env.get("GITHUB_RANK_SUMMARY_MODEL", ""),
            env.get("GITHUB_RANK_SUMMARY_URL", "http://127.0.0.1:11434"),
            max(int(env.get("GITHUB_RANK_SUMMARY_DAILY_LIMIT", "20")), 0),
            env.get("GITHUB_RANK_AUTO_SUMMARY", "").lower() in ("1", "true"),
        )

    def config(self):
        with self.config_path.open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
        if not isinstance(config, dict):
            raise ValueError("Configuration must be a mapping")
        return config
