import revel8_agent.domains as dom


def test_org_stems_and_lookalikes_match_the_claimed_organisation(monkeypatch):
    assert dom.org_stems("Kessler Antriebstechnik GmbH")[:2] == ["kessler-antriebstechnik", "kesslerantriebstechnik"]
    taken = {"kessler-antriebstechnik.de"}
    monkeypatch.setattr(dom, "registered", lambda d: d in taken)
    out = dom.lookalikes("Kessler Antriebstechnik GmbH", k=2)
    assert out and all(d.startswith("kessler") for d in out) and "kessler-antriebstechnik.de" not in out


def test_registered_uses_public_dns_status(monkeypatch):
    dom.registered.cache_clear()
    monkeypatch.setattr(dom, "_doh", lambda name, rtype: 0 if name == "real-org.com" else 3)
    assert dom.registered("real-org.com") and not dom.registered("free-lookalike-xyz.de")
    dom.registered.cache_clear()


def test_real_domain_prefers_research_source_hosts(monkeypatch):
    monkeypatch.setattr(dom, "registered", lambda d: False)
    assert dom.real_domain_for("Merantix Capital", {"www.merantix-capital.com", "news.example.org"}) == "merantix-capital.com"
