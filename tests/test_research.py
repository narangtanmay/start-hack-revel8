from revel8_agent.osint import Target
from revel8_agent.research import Doc, Identity, merge_duplicates, verify
from revel8_agent.schemas import VerifiedFact

T = Target("tom", "Tom Müller", "Co-Founder & Co-CEO", "revel8")


def test_identity_needs_name_and_anchor() -> None:
    ident = Identity(T, ["Celonis"])
    assert ident.about("Tom Müller, co-founder of revel8, spoke in Munich")
    assert ident.about("Tom Mueller joined Celonis in 2019")            # earlier employer as anchor
    assert ident.about("Müller from revel8 said")                       # surname + the company itself
    assert not ident.about("Tom Müller scored twice for FC Example")     # namesake: no anchor
    assert not ident.about("Matthias Hinkelmann on LinkedIn: revel8 is hiring")  # anchor but not the person


def test_add_anchor_rejects_names_and_duplicates() -> None:
    ident = Identity(T)
    assert ident.add_anchor("TU München")
    assert not ident.add_anchor("tu münchen")
    assert not ident.add_anchor("Müller")


def test_verify_requires_quote_on_page_and_identity() -> None:
    ident = Identity(T)
    doc = Doc("d1", "https://x.test", "t", "Tom Müller of revel8 will speak at the Cyber Night on 10 December 2026.", "web", "2026-11-01")
    ok = verify({"fact": "Speaking at Cyber Night", "verbatim_quote": "will speak at the Cyber Night", "recency": "unknown"}, doc, ident)
    assert ok is not None and ok.recency == "2026-11-01" and ok.lane == "web"
    assert verify({"fact": "x", "verbatim_quote": "is giving the keynote at Cyber Night"}, doc, ident) is None


def _f(fid: str, fact: str, url: str, lane: str) -> VerifiedFact:
    return VerifiedFact(id=fid, fact=fact, category="other", source_url=url, verbatim_quote="q q q q", recency="2026", lane=lane)


def test_merge_duplicates_keeps_best_source_and_corroboration() -> None:
    facts = [_f("a", "revel8 raised a seed round led by Peak", "https://news.test/1", "news"),
             _f("b", "revel8 raised a seed round led by Peak Capital", "https://linkedin.com/posts/x", "social"),
             _f("c", "Tom spoke at it-sa in Nuremberg", "https://web.test/2", "web")]
    merged = merge_duplicates(facts)
    assert len(merged) == 2
    seed = next(f for f in merged if "seed" in f.fact)
    assert seed.source_url == "https://linkedin.com/posts/x" and seed.corroborated_by == ["https://news.test/1"]
