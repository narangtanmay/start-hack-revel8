from revel8_agent.osint import (
    SourceDoc, Target, html_to_text, mentions_target, normalize, rank_hooks, verify_fact,
)
from revel8_agent.schemas import VerifiedFact

T = Target("tom", "Tom Müller", "Co-Founder & Co-CEO", "revel8")
DOC = SourceDoc(
    "doc_1", "https://example.test/p", "Team",
    "Tom Müller, co-founder of revel8, will speak at the Munich Cyber Summit in March 2026.",
)


def test_verify_accepts_exact_quote_modulo_whitespace_and_case() -> None:
    raw = {"fact": "Speaking at Munich Cyber Summit", "category": "talk_or_event",
           "verbatim_quote": "will speak at the munich cyber summit in March", "recency": "2026-03"}
    vf = verify_fact(raw, DOC, T)
    assert vf is not None and vf.source_url == DOC.url and vf.category == "talk_or_event"


def test_verify_rejects_paraphrase_ellipsis_and_short_quotes() -> None:
    base = {"fact": "x", "category": "other"}
    assert verify_fact({**base, "verbatim_quote": "is giving a keynote at the summit"}, DOC, T) is None
    assert verify_fact({**base, "verbatim_quote": "Tom Müller, co-founder ... summit"}, DOC, T) is None
    assert verify_fact({**base, "verbatim_quote": "March 2026"}, DOC, T) is None


def test_verify_rejects_docs_not_about_target() -> None:
    other = SourceDoc("doc_2", "https://x.test", "", "Tom Müller is a football player at FC Example in 2026.")
    raw = {"fact": "plays football", "verbatim_quote": "is a football player at FC Example"}
    assert verify_fact(raw, other, T) is None


def test_mentions_target_folds_umlauts() -> None:
    assert mentions_target("Tom Mueller from REVEL8", T)
    assert mentions_target("Tom Muller, revel8", T)
    assert not mentions_target("Tom Müller", T)


def test_html_to_text_skips_scripts_and_keeps_meta_description() -> None:
    title, text = html_to_text(
        "<html><head><title>Hi</title><meta name='description' content='About revel8'>"
        "<script>var a=1</script></head><body><p>Hello&nbsp;world</p></body></html>"
    )
    assert title == "Hi" and "About revel8" in text and "var a" not in text
    assert normalize("Hello  World") == "hello world"


class _FakeLLM:
    def __init__(self, out): self.out = out
    def chat(self, *_a, **_k): return self.out


def test_rank_hooks_drops_hooks_without_verified_support() -> None:
    facts = [VerifiedFact(id="f1", fact="a", category="other", source_url="u", verbatim_quote="q q q q", recency="x")]
    llm = _FakeLLM({
        "hooks": [{"topic": "good", "confidence": 0.9, "supporting_fact_ids": ["f1"]},
                  {"topic": "invented", "confidence": 0.9, "supporting_fact_ids": ["f99"]}],
        "own_angle": {"topic": "own", "confidence": 2, "supporting_fact_ids": ["f1"]},
    })
    hooks = rank_hooks(llm, T, facts)
    assert [h.topic for h in hooks] == ["good", "own"]
    assert hooks[1].is_own_angle and hooks[1].confidence == 1.0
