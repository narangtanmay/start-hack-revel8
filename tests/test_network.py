from revel8_agent.ladder import _NAMED_CONTACT, prompt
from revel8_agent.network import network_prompt, relationships
from revel8_agent.schemas import VerifiedDossier, VerifiedFact


def _d(*facts):
    return VerifiedDossier(target_id="x", target_name="Anna Berg", role="CFO", company="Acme",
                           facts=[VerifiedFact(id=f"f{i}", fact=t, category=c, source_url="https://a.example/x",
                                               verbatim_quote=t, recency="2026") for i, (c, t) in enumerate(facts)])


def test_relationships_rank_investors_and_colleagues_and_skip_the_target():
    d = _d(("network", "Anna Berg works with new hires Jonas Klein and Mia Roth at Acme."),
           ("network", "Acme is backed by investors including Nordlicht Capital and angel Peter Haas."),
           ("background", "Anna Berg studied in Cologne."))
    rels = relationships(d)
    assert rels[0]["relationship"] == "investor/angel" and "Peter Haas" in rels[0]["names"]
    assert any("Jonas Klein" in r["names"] for r in rels)
    assert all("Anna Berg" not in r["names"] for r in rels)
    assert "THEIR REAL NETWORK" in network_prompt(d)


def test_named_contact_in_reply_is_picked_up():
    said = "Katharina Pohl can confirm the slot. Please send this to Claudia Lannes, Solution Engineering."
    assert set(_NAMED_CONTACT.findall(said)) == {"Katharina Pohl", "Claudia Lannes"}
    steps = [{"touch": 1, "payload": {"body": "x"}, "events": [{"type": "reply", "body": said}]}]
    assert "THEY NAMED A REAL CONTACT" in prompt(steps, [])
