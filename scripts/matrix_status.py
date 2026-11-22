"""Summarise eval_sim trials: per (target, profile) the 3 sessions, touches, events, first API incident touch."""
import glob, json, re
from collections import defaultdict

rows = defaultdict(dict)
for f in sorted(glob.glob("runs/*-sim-*-s[123]-*.json")):
    d = json.load(open(f))
    m = re.search(r"-sim-(\w+?)(?:-(qwen|ds|self))?-s(\d)-", f)
    if not m:
        continue
    tgt, prof, s = m.group(1), m.group(2) or "ds", m.group(3)
    evs = [e.get("type") for st in d["steps"] for e in st.get("events") or []]
    api = [i["touch"] for i in d.get("incidents") or [] if i.get("source") == "api event"]
    cell = f"{d['status']}:{d.get('touches_used')}t {evs.count('reply')}r"
    cell += f" WIN@T{min(api)}" if api else ""
    cell += " ERR" if d.get("error") else ""
    rows[(tgt, prof)][s] = cell
for (t, p), ss in sorted(rows.items()):
    print(f"{t:7} {p:5} | " + " | ".join(ss.get(k, "-") for k in "123"))
