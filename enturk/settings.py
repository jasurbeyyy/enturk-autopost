"""Sozlamalarni .env va config.yaml fayllaridan o'qish."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    bot_token: str
    gemini_key: str
    eleven_key: str
    admin_ids: list[int]
    channel: str
    mock: bool
    cfg: dict
    styles: list[dict]
    data_dir: Path
    tz: ZoneInfo = field(init=False)

    def __post_init__(self) -> None:
        self.tz = ZoneInfo(self.cfg.get("timezone", "Asia/Tashkent"))

    # --- yordamchilar ---
    def post_type(self, key: str) -> dict:
        try:
            return self.cfg["post_types"][key]
        except KeyError as exc:
            raise KeyError(f"Noma'lum post turi: {key}") from exc

    @property
    def media_dir(self) -> Path:
        p = self.data_dir / "media"
        p.mkdir(parents=True, exist_ok=True)
        return p


def load_settings(root: Path | None = None) -> Settings:
    root = root or ROOT
    load_dotenv(root / ".env")
    with open(root / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    with open(root / "styles.yaml", encoding="utf-8") as f:
        styles = yaml.safe_load(f)["styles"]

    admin_raw = os.getenv("ADMIN_IDS", "").replace(" ", "")
    admin_ids = [int(x) for x in admin_raw.split(",") if x.strip().lstrip("-").isdigit()]

    data_dir = Path(os.getenv("DATA_DIR", str(root / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        gemini_key=os.getenv("GEMINI_API_KEY", ""),
        eleven_key=os.getenv("ELEVENLABS_API_KEY", ""),
        admin_ids=admin_ids,
        channel=os.getenv("CHANNEL_ID", "@EnTurk_CSR"),
        mock=os.getenv("MOCK", "0") == "1",
        cfg=cfg,
        styles=styles,
        data_dir=data_dir,
    )
