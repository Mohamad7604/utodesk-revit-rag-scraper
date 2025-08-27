import json, time
from pathlib import Path
from typing import Iterable, Dict
import pandas as pd

def write_jsonl(records: Iterable[Dict], out_path: str):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def write_csv(records: Iterable[Dict], out_path: str):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    df = pd.json_normalize(list(records))
    df.to_csv(out_path, index=False, encoding="utf-8")

def sleep_safely(secs: float):
    try:
        time.sleep(secs)
    except Exception:
        pass
