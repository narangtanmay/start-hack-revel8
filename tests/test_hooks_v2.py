from revel8_agent.research import score_hook
from revel8_agent.schemas import HookHypothesis, Theme, VerifiedFact


def _f(i, quote, recency, cat="current_project"):
    return VerifiedFact(id=i, fact=quote, category=cat, source_url=f"https://x.test/{i}", verbatim_quote=quote, recency=recency)


def test_current_open_personal_hook_beats_past_company_news():
    by_id = {
        "f1": _f("f1", "Tom Müller: we are hiring two AI solution engineers in Munich, reach out", "2026-11"),
        "f2": _f("f2", "revel8 raised a seed round to scale the team", "2025-09-25", "company_news"),
    }
    themes = [Theme(topic="hiring", count=3, fact_ids=["f1"])]
    hot = HookHypothesis(id="a", topic="hiring", rationale="", confidence=0.6, supporting_fact_ids=["f1"],
                         open_signal="we are hiring")
    cold = HookHypothesis(id="b", topic="seed", rationale="", confidence=0.9, supporting_fact_ids=["f2"])
    s_hot, parts = score_hook(hot, by_id, themes, "muller")
    s_cold, _ = score_hook(cold, by_id, themes, "muller")
    assert s_hot > s_cold
    assert parts["openness"] > 0.5 and parts["recency"] >= 0.7


def test_fact_date_parses_common_formats():
    from revel8_agent.research import fact_date
    assert fact_date("September 8, 2026").month == 9
    assert fact_date("2026-10-20").day == 20
    assert fact_date("Oct 2026").month == 10
    assert fact_date("vor 3 Wochen") is not None and fact_date("2 weeks ago") is not None
    assert fact_date("unknown") is None


def test_recent_opinion_scores_high_static_profile_low():
    from datetime import datetime, timedelta
    from revel8_agent.research import recency_score
    recent = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    assert recency_score(_f("a", "Robert argues works councils need templates", recent, "publication"))[1] == "recent"
    assert recency_score(_f("b", "Julius is Co-Founder of revel8", recent, "role"))[1] == "static"
