import json
import re

from revel8_agent.report_replay import compact_run, render_replay


def _state(**over):
    st = {
        "run_id": "20261122-000000-tom-test",
        "status": "done",
        "config": {"max_touches": "10", "label": "test"},
        "target": {"id": "tom", "name": "Tom Müller", "role": "CEO"},
        "brief": {"facts": [{"id": "f1", "fact": "Speaks at X"}], "hooks": [{"id": "h1", "topic": "X talk"}]},
        "plan": {"hook_id": "h1", "persona": {"name": "Lena Hoffmann", "website_domain": "example-events.org"},
                 "character": {"first_small_yes": "Stimmt das?"},
                 "notebook": [{"touch": 0, "note": "I am Lena"}, {"touch": 2, "note": "ROUTE CLOSED: no login"}]},
        "steps": [
            {"touch": 1, "action": {"kind": "message", "channel": "email", "decision": "STAY", "inner_monologue": "think",
                                    "sender": {"name": "Lena Hoffmann"}, "note_to_self": ["n1"], "cited_fact_ids": ["f1"]},
             "payload": {"from": {"name": "Lena Hoffmann", "address": "lena@example-events.org"}, "subject": "Hi",
                         "body": "Hallo </script><script>alert(1)</script>"},
             "attempts": [{"try": 1, "errors": ["too long"]}, {"try": 2, "errors": []}],
             "events": [{"type": "reply", "channel": "email", "body": "Ja"}], "judge": {"sentiment": "engaged"},
             "page": {"url": "https://example-events.org/login", "fields": ["email", "password"], "html": "<p>login</p>"}},
        ],
        "incidents": [{"touch": 1, "type": "disclosure", "detail": "Ja"}],
    }
    st.update(over)
    return st


def test_compact_run_keeps_the_decision_trail():
    r = compact_run(_state())
    s = r["steps"][0]
    assert s["sender"]["address"] == "lena@example-events.org"
    assert s["mind"] == "think" and s["notes"] == ["n1"] and s["cited"] == ["f1"]
    assert [a["errors"] for a in s["attempts"]] == [["too long"], []]
    assert s["page"]["html"] == "<p>login</p>"
    assert r["notebook"][1]["note"].startswith("ROUTE CLOSED")


def test_public_snapshot_drops_landing_page_html():
    s = compact_run(_state(), redact=True)["steps"][0]
    assert s["page"]["html"] == "" and s["page"]["fields"] == ["email", "password"]


def test_render_embeds_data_without_breaking_out_of_the_script_tag(tmp_path):
    out = render_replay([_state()], tmp_path, lambda title, crumbs, body, live: f"<html>{body}</html>")
    html = out.read_text(encoding="utf-8")
    data = re.search(r"<script type='application/json' id='rp-data'>(.*?)</script>", html, re.S).group(1)
    assert "</script" not in data
    assert json.loads(data)[0]["steps"][0]["body"].endswith("</script>")
