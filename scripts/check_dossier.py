"""Independent spot-check of a dossier: re-download every source and confirm each quote is really there.

Usage: .venv/bin/python scripts/check_dossier.py dossiers/robert.json
"""

import json
import sys

import httpx

from revel8_agent.osint import html_to_text, normalize


def main(path: str) -> int:
    d = json.load(open(path, encoding="utf-8"))
    print(f"{d['target_name']} - {d['role']}\n")
    pages: dict[str, str] = {}
    bad = 0
    with httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=15) as c:
        for f in d["facts"]:
            url = f["source_url"]
            if url not in pages:
                try:
                    pages[url] = normalize(html_to_text(c.get(url).text)[1])
                except httpx.HTTPError:
                    pages[url] = ""
            if not pages[url]:
                status = "CAN'T FETCH (login wall?) - open the URL and check by hand"
            elif normalize(f["verbatim_quote"]) in pages[url]:
                status = "OK - quote found on live page"
            else:
                status = "NOT FOUND on live page - check by hand"
                bad += 1
            print(f"[{f['id']}] {f['fact']}\n   \"{f['verbatim_quote']}\"\n   {url}\n   -> {status}\n")
    print("HOOKS")
    for h in d["hypotheses"]:
        tag = " (own angle)" if h["is_own_angle"] else ""
        print(f"  {h['confidence']:.2f} {h['topic']}{tag}  <- {', '.join(h['supporting_fact_ids'])}")
    print(f"\n{len(d['facts'])} facts, {bad} not found on the live page")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
