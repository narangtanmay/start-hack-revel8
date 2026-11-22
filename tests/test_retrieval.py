from revel8_agent.memory import ground_truth
from revel8_agent.retrieval import FactIndex, dedupe
from revel8_agent.schemas import VerifiedDossier, VerifiedFact


def _d(texts):
    return VerifiedDossier(target_id="x", target_name="Anna Berg", role="CFO", company="Acme",
                           facts=[VerifiedFact(id=f"f{i}", fact=t, category="company_news", source_url="https://a.example/x",
                                               verbatim_quote=t, recency="2026") for i, t in enumerate(texts)])


def test_dedupe_drops_the_same_story_from_many_articles():
    d = _d(["Acme raised 5 million euros in a seed round led by Nordlicht Capital.",
            "Acme raised 5 million euros in a seed round led by Nordlicht Capital and angels.",
            "Anna Berg moved the finance team to SAP S/4HANA in 2026."])
    assert len(dedupe(d.facts)) == 2


def test_retrieval_finds_the_fact_matching_their_reply():
    d = _d(["Anna Berg moved the finance team to SAP S/4HANA in 2026.",
            "Acme opened an office in Vienna.",
            "Jonas Klein leads procurement at Acme and signs off new suppliers."])
    hits = FactIndex(d).search("Please send this to Jonas Klein in procurement, he approves suppliers.", k=1)
    assert hits and hits[0].id == "f2"


def test_ground_truth_trims_a_theme_instead_of_dropping_everything_after_it():
    d = _d([f"Fact number {i} about a distinct project called Project{i} with details." for i in range(40)])
    g = ground_truth(d, max_chars=1500, per_theme=40)
    assert 5 <= len(g["fact_ids"]) < 40 and len(g["text"]) <= 1500
