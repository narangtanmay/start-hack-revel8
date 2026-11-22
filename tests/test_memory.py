from revel8_agent.memory import SessionLedger, TargetMemory, archetype, ground_truth
from revel8_agent.schemas import Theme, VerifiedDossier, VerifiedFact


def test_ledger_keeps_numbers_dates_and_promises():
    led = SessionLedger()
    led.record(3, "email", "Quotes", ["All six quotes are approved.", "Nice weather.", "I'll send the link on Wednesday."])
    p = led.prompt()
    assert "six quotes" in p and "Wednesday" in p and "Nice weather" not in p


def test_target_memory_learns_corrections_and_rates(tmp_path):
    m = TargetMemory("Tom Müller", root=tmp_path)
    state = {"run_id": "r1", "plan": {"hook_id": "h2", "pretext": "media interview", "persona": {"role": "Editor", "organisation": "CyberScope"}},
             "steps": [{"touch": 1, "action": {"channel": "email"}, "events": [{"type": "reply", "body": "That doesn't match our calendar. We weren't at TechEx."}]},
                       {"touch": 2, "action": {"channel": "email"}, "events": []}],
             "incidents": []}
    m.learn_from_run(state)
    m.save()
    again = TargetMemory("Tom Müller", root=tmp_path)
    assert again.data["sessions"][0]["reply_rate"] == 0.5
    assert again.data["corrections"] and "TechEx" in again.prompt()


def test_archetype_classification():
    assert archetype("Senior Talent Scout at TalentBridge", "") == "recruiter"
    assert archetype("Editor at CyberScope Media", "") == "journalist/media"


def test_ground_truth_is_bounded_and_prefers_own_voice():
    facts = [VerifiedFact(id=f"f{i}", fact=f"fact number {i} " + "x" * 80, category="publication",
                          source_url="https://linkedin.com/posts/a" if i % 2 else "https://tracxn.com/a",
                          verbatim_quote=f"quote {i}", recency="2026-10", source_kind="social" if i % 2 else "aggregator")
             for i in range(1, 80)]
    d = VerifiedDossier(target_id="t", target_name="Robert Seilbeck", role="CTO", company="revel8", facts=facts,
                        themes=[Theme(topic="security", count=79, fact_ids=[f.id for f in facts])])
    gt = ground_truth(d, max_chars=2000, per_theme=6)
    assert len(gt["text"]) <= 2000 and gt["fact_ids"]
    assert all(int(i[1:]) % 2 == 1 for i in gt["fact_ids"][:6])   # social (own voice) first
