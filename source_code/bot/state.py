"""
state.py - Pengelolaan persis state volatil ke data/state.json secara atomik.
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATE_PATH = DATA_DIR / "state.json"


@dataclass
class BotState:
    consecutive_losses: int = 0
    locked_date: Optional[str] = None  # YYYY-MM-DD
    override_active: bool = False
    open_position: Optional[dict] = None
    last_update: Optional[str] = None


def save_state(state: BotState, file_path: Path = STATE_PATH) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_suffix(".tmp")
    data = asdict(state)
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    temp_path.replace(file_path)


def load_state(file_path: Path = STATE_PATH) -> BotState:
    if not file_path.exists():
        return BotState()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return BotState(**data)
    except Exception:
        # Tahan terhadap file rusak: buat backup dan kembalikan state bersih
        backup_path = file_path.with_suffix(".bak")
        if file_path.exists():
            file_path.replace(backup_path)
        return BotState()
