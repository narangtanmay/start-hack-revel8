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



def test_future_dated_fact_is_upcoming_even_if_filed_as_company_news():
    from revel8_agent.research import recency_score
    f = _f("f152", "He is scheduled to speak at Cybersicherheitsforschung 2027, Session 1.3", "2027-03-02", "company_news")
    assert recency_score(f)[1] == "upcoming"


def _hook(**kw):
    from revel8_agent.schemas import HookHypothesis
    base = dict(id="h", topic="t", rationale="", confidence=0.7, supporting_fact_ids=["x"])
    return HookHypothesis(**{**base, **kw})


def test_needs_him_buyer_is_routed_speaker_is_personal():
    from revel8_agent.research import needs_him
    buyer = _hook(sender_archetype="Head of security awareness at a German company that recently ran a vishing test",
                  natural_ask="Ask whether his platform can run a small MS Teams vishing pilot")
    speaker = _hook(sender_archetype="Conference program coordinator at Cybersicherheitsforschung 2027",
                    natural_ask="Confirm his speaker bio and whether he wants a pre-call with the session chair")
    assert needs_him(buyer) == 0.15
    assert needs_him(speaker) == 1.0


def test_speaker_slot_filed_as_company_news_outranks_sales_pilot_hook():
    from revel8_agent.research import score_hook
    talk = _f("t", "He is scheduled to speak at the Cybersicherheitsforschung 2027 conference in Session 1.3", "2027-03-02", "company_news")
    blog = _f("b", "Robert Seilbeck cites the 2026 Verizon DBIR noting that 62% of breaches involve human interaction",
              "2026-09-08", "publication")
    by_id = {"t": talk, "b": blog}
    speaker = _hook(supporting_fact_ids=["t"], sender_archetype="Conference program coordinator",
                    natural_ask="Confirm his speaker bio for Session 1.3")
    buyer = _hook(supporting_fact_ids=["b"], open_signal="multi-channel simulations",
                  sender_archetype="Head of security awareness evaluating vendors",
                  natural_ask="Ask whether his platform can run a vishing pilot")
    s_talk, parts = score_hook(speaker, by_id, [], "seilbeck", "robert")
    s_buy, _ = score_hook(buyer, by_id, [], "seilbeck", "robert")
    assert parts["personal"] == 1.0 and parts["needs_him"] == 1.0
    assert s_talk > s_buy
