from revel8_agent.language import decide_language, detect, infer_language
from revel8_agent.schemas import VerifiedDossier, VerifiedFact


def _d(quotes, kind="social"):
    facts = [VerifiedFact(id=f"f{i}", fact=q, category="publication", source_url=f"https://ex.test/{i}",
                          verbatim_quote=q, recency="2026", source_kind=kind) for i, q in enumerate(quotes)]
    return VerifiedDossier(target_id="x", target_name="Claire Dubois", role="CEO", company="acme", facts=facts)


def test_detect_common_languages():
    assert detect("We are building the future of security and we love it")[0] == "en"
    assert detect("Wir bauen die Zukunft der Sicherheit und das ist nicht einfach")[0] == "de"
    assert detect("Nous construisons la sécurité pour les entreprises et les équipes")[0] == "fr"
    assert detect("ok")[0] == ""


def test_profile_language_french_and_fallback():
    fr = infer_language(_d(["Nous lançons une nouvelle offre pour les équipes de sécurité"] * 5))
    assert fr["language"] == "fr" and decide_language(fr)["language"] == "fr"
    mixed = infer_language(_d(["We are hiring engineers for our team", "Nous lançons une offre pour les équipes"]))
    assert decide_language(mixed, threshold=0.9)["language"] == "en"   # unclear -> English


def test_reply_language_wins():
    en = infer_language(_d(["We are building the future of security and we love it"] * 3))
    d = decide_language(en, ["Hallo, vielen Dank, das passt grundsätzlich. Schicken Sie mir den Entwurf bitte per Mail."])
    assert d["language"] == "de" and "replied" in d["why"]
