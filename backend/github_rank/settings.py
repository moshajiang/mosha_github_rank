from dataclasses import dataclass, field
from pathlib import Path
import os
import yaml


ROOT = Path(__file__).resolve().parents[2]


def read_dotenv(path):
    values = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key != "GITHUB_TOKEN" and not key.startswith("GITHUB_RANK_"):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


@dataclass(frozen=True)
class Settings:
    db_path: Path
    config_path: Path
    github_token: str = ""
    summary_model: str = ""
    summary_url: str = "http://127.0.0.1:11434"
    summary_daily_limit: int = 20
    summary_auto: bool = False
    summary_provider: str = "ollama"
    inkstone_api_key: str = field(default="", repr=False)

    @property
    def summary_configuration_error(self):
        if self.summary_provider not in ("ollama", "inkstone"):
            return "Set GITHUB_RANK_SUMMARY_PROVIDER to ollama or inkstone"
        if self.summary_provider == "inkstone" and not self.inkstone_api_key:
            return "Configure GITHUB_RANK_INKSTONE_API_KEY to enable InkStone summaries"
        if not self.summary_model:
            return "Configure GITHUB_RANK_SUMMARY_MODEL to enable summaries"
        return None

    @property
    def summary_model_id(self):
        if self.summary_provider == "inkstone":
            return "inkstone/" + self.summary_model
        return self.summary_model

    @classmethod
    def from_env(cls, environ=None):
        if environ is None:
            env = {**read_dotenv(ROOT / ".env"), **os.environ}
        else:
            env = environ
        provider = env.get("GITHUB_RANK_SUMMARY_PROVIDER", "ollama").strip().lower() or "ollama"
        model = env.get("GITHUB_RANK_SUMMARY_MODEL", "").strip()
        if provider == "inkstone" and not model:
            model = "intern-s2"
        return cls(
            db_path=Path(env.get("GITHUB_RANK_DB", str(ROOT / "data/github_rank.sqlite3"))),
            config_path=Path(env.get("GITHUB_RANK_CONFIG", str(ROOT / "config/sources.yaml"))),
            github_token=env.get("GITHUB_TOKEN", ""),
            summary_model=model,
            summary_url=env.get("GITHUB_RANK_SUMMARY_URL", "http://127.0.0.1:11434"),
            summary_daily_limit=max(int(env.get("GITHUB_RANK_SUMMARY_DAILY_LIMIT", "20")), 0),
            summary_auto=env.get("GITHUB_RANK_AUTO_SUMMARY", "").lower() in ("1", "true"),
            summary_provider=provider,
            inkstone_api_key=env.get("GITHUB_RANK_INKSTONE_API_KEY", "").strip(),
        )

    def config(self):
        with self.config_path.open(encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
        if not isinstance(config, dict):
            raise ValueError("Configuration must be a mapping")
        return config
