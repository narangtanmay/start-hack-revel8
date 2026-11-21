from revel8_agent.osint import Target
from revel8_agent.research import Doc, Identity, source_kind, verify

T = Target("tom", "Tom Müller", "Co-CEO", "revel8")


def test_source_kind_by_domain():
    assert source_kind("https://www.linkedin.com/posts/tom-mueller_ai-activity-123") == "social"
    assert source_kind("https://www.linkedin.com/in/tom-c-mueller/") == "aggregator"   # profile page
    assert source_kind("https://tracxn.com/d/companies/revel8") == "aggregator"
    assert source_kind("https://www.revel8.ai/magazine/x", "By Tom Müller\nToday we ...", T) == "own_article"
    assert source_kind("https://example-news.de/a", "a story", T) == "web"


def _doc(url, text):
    return Doc("d1", url, "t", text, "web", "2026-11-09")


def test_cofounder_talk_is_not_attributed_to_this_person():
    text = "Tom Müller and Julius Muth founded revel8. Julius gave a live vishing demo at it-sa 2026 in Nuremberg."
    raw = {"fact": "Live vishing demo at it-sa", "verbatim_quote": "Julius gave a live vishing demo at it-sa 2026",
           "category": "talk_or_event", "recency": "2026-10"}
    f = verify(raw, _doc("https://news.example.de/x", text), Identity(T, ["revel8"]))
    assert f is not None and f.category == "company_news"


def test_aggregator_crawl_date_is_not_a_fact_date():
    text = "Tom Müller is Co-Founder of revel8, a seed company based in Berlin providing simulations."
    raw = {"fact": "Co-founder", "verbatim_quote": "Tom Müller is Co-Founder of revel8", "category": "role",
           "recency": "2026-11-09"}
    f = verify(raw, _doc("https://tracxn.com/d/companies/revel8", text), Identity(T, ["revel8"]))
    assert f is not None and f.recency == "unknown" and f.source_kind == "aggregator"


def test_merge_dossiers_unions_by_quote():
    from revel8_agent.research import merge_dossiers
    from revel8_agent.schemas import VerifiedDossier, VerifiedFact

    def fact(i, q):
        return VerifiedFact(id=i, fact=q, category="publication", source_url="https://x.test", verbatim_quote=q, recency="2026-09")
    prev = VerifiedDossier(target_id="robert", target_name="Robert Seilbeck", role="CTO", company="revel8",
                           facts=[fact("f1", "Robert writes about works council agreements"), fact("f2", "same quote here ok")])
    new = VerifiedDossier(target_id="robert", target_name="Robert Seilbeck", role="CTO", company="revel8",
                          facts=[fact("f1", "same quote here ok")])
    merged, added = merge_dossiers(prev, new)
    assert added == 1 and len(merged.facts) == 2 and merged.facts[-1].id == "p1"
