"""Avanzamento della prova del modo libero: ``python -m tools.libero_avanzamento`` → «fatte N su 70»."""
import json
import subprocess

from tools import event_check as ec
from tools.libero_check import PARTIAL

features = ec._usable()
features = features[features["season"].eq("2324") & features["league"].isin(["E0", "I1", "D1"])]
rows = ec.pd.concat([f.sample(min(70, len(f)), random_state=5) for _, f in features.groupby("league")]).sort_values("date").reset_index(drop=True)
rank = rows.groupby("league").cumcount().to_numpy()
subset = {p for p in range(len(rows)) if rank[p] % 3 == 0}
done = {json.loads(line)["i"] for line in (PARTIAL / "parziali.jsonl").read_text().splitlines()}
alive = subprocess.run(["pgrep", "-f", "tools.libero_check"], capture_output=True).returncode == 0
print(f"fatte {len(subset & done)} su {len(subset)} ({'in corso' if alive else 'fermo o finito'})")
