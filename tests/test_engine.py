from datetime import datetime

import pytest

from revel8_agent.engine import estimate_score, timing

TODAY = datetime(2026, 11, 21)


@pytest.mark.parametrize("recency,expected", [
    ("2026-10-28", "past"), ("2026-07", "past"), ("July 16, 2026", "past"), ("16 July 2026", "past"),
    ("2026 Q1", "past"), ("2025", "past"), ("2026-12-10", "upcoming"), ("2027-03", "upcoming"),
    ("upcoming", "upcoming"), ("2026", "this-year"), ("unknown", "undated"),
])
def test_timing_labels(recency: str, expected: str) -> None:
    assert timing(recency, TODAY) == expected


def test_estimate_score() -> None:
    assert estimate_score({"incidents": []})["results_points"] == 0
    hit = estimate_score({"incidents": [{"touch": 4, "type": "credentials", "source": "api event"}]})
    assert hit["incident"] and hit["first_incident_touch"] == 4 and hit["results_points"] == 22.5


def test_strip_salutations_and_placeholders() -> None:
    from revel8_agent.engine import _fill_placeholders, _strip_salutations

    paras = ["Hi Tom,\n\nI'm Sarah from TechEx.", "Access it here: [link to registration page].",
             "Best regards,\nSarah Bennett"]
    cleaned = _strip_salutations(paras, "Sarah Bennett")
    assert cleaned == ["I'm Sarah from TechEx.", "Access it here: [link to registration page]."]
    assert _fill_placeholders(cleaned, "https://x-events.de/s")[1] == "Access it here: https://x-events.de/s."
    assert _strip_salutations(["Hallo Julius,", "Kurze Frage.\n\nViele Grüße\nLena"], "Lena Fischer") == ["Kurze Frage."]


def test_personal_domain_for_individual_persona(monkeypatch):
    from revel8_agent import engine

    monkeypatch.setattr(engine, "domain_is_registered", lambda d: d == "lena-hofer.de")
    r = engine.Runner.__new__(engine.Runner)
    r.blocked = {"revel8.ai"}
    assert r._personal_domain("Lena Höfer") == "lena-hofer.eu"
    assert r._personal_domain("") == ""


def test_judge_veto_scheduling_is_not_an_action():
    from revel8_agent.engine import _NOT_AN_ACTION, _REAL_ACTION

    ev = "Wednesday morning works, around 10:00. Please send the invite to this address."
    assert _NOT_AN_ACTION.search(ev) and not _REAL_ACTION.search(ev)
    real = "Done, I opened the file and forwarded it to the team."
    assert _REAL_ACTION.search(real)


def test_strip_salutations_inline_greeting_and_first_name_signoff():
    from revel8_agent.engine import _strip_salutations

    paras = ["Hi Julius, sorry about that, the link was a preview page.", "The piece is as you approved.",
             "Best,", "Lukas"]
    out = _strip_salutations(paras, "Lukas Weber")
    assert out == ["sorry about that, the link was a preview page.", "The piece is as you approved."]


def test_long_bracket_placeholder_is_rejected():
    import re
    text = "[Article text with the four approved quotes and the works council section, in plain text.]"
    assert re.search(r"\[[^\]]{2,300}\]", text)


def test_live_lookup_adds_notes(monkeypatch):
    from types import SimpleNamespace

    from revel8_agent import engine, research

    r = engine.Runner.__new__(engine.Runner)
    r.state = SimpleNamespace(live_notes=[], llm_calls=0)
    r.dossier = SimpleNamespace(target_name="Tom Müller", role="Co-CEO", company="revel8")
    r.llm = None
    r.log = lambda *_: None
    monkeypatch.setattr(engine, "_llm_json", lambda *a, **k: {"queries": ["Tom Müller revel8 Unicon Berlin"]})
    monkeypatch.setattr(research, "brave", lambda *a, **k: [{"title": "Unicon 2026", "snippet": "revel8 at Unicon", "url": "https://u.test"}])
    step = {"touch": 2, "events": [{"type": "reply", "body": "We were at Gartner SRM in September and last week at Unicon in Berlin."}]}
    r.live_lookup(step)
    assert r.state.live_notes and r.state.live_notes[0]["query"].startswith("Tom")
    assert "Unicon" in r.state.live_notes[0]["found"][0]
