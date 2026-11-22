from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from revel8_agent import cli, engine
from revel8_agent.actor import (
    ARCHITECTURE,
    ActorRunner,
    _derive_decision,
    _target_sends,
    closed_routes,
    invented_names,
    near_repeat,
    offered_lines,
    unsupported_years,
)
from revel8_agent.engine import RunConfig
from revel8_agent.schemas import HookHypothesis, VerifiedDossier, VerifiedFact

_PERSONA = {"name": "Mara Lenzen", "organisation": "Programmbuero Lenzen", "role": "Programme coordinator",
            "email": "mara@programm-lenzen.test", "phone": "+49 89 5550 1234", "website_domain": "programm-lenzen.test"}
_CHARACTER = {"who": "Freelance programme coordinator", "why_them": "They speak in session 1.3 in March",
              "need": "Confirm the session details in the speaker portal before the programme prints",
              "artifact": {"kind": "portal", "name": "Speaker portal"}, "deadline_days": 7,
              "deadline_reason": "the printed programme goes to the printer", "voice": "warm, short, Sie",
              "would_never": ["ask for a password on the phone"]}


class _ScriptedLLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses, self.calls = list(responses), []

    def chat(self, messages, *, json_mode=False, temperature=None):
        self.calls.append(list(messages))
        return self.responses.pop(0)


def _cast(**over) -> dict:
    out = {"hook_id": "h1", "language": "de", "objective": "credentials", "persona": dict(_PERSONA),
           "character": dict(_CHARACTER), "cited_fact_ids": ["f2"], "rationale": "r"}
    out.update(over)
    return out


def _act(**over) -> dict:
    out = {"inner_monologue": "First contact: I introduce myself and ask for the one thing I need.",
           "kind": "message", "channel": "email", "subject": "Ihre Session 1.3", "format": "plain",
           "paragraphs": ["ich koordiniere das Programm: stimmt Ihr Titel so, wie er im Entwurf steht?"],
           "link": None, "attachment_filename": None, "cited_fact_ids": [],
           "note_to_self": ["I told them the programme prints on my deadline."]}
    out.update(over)
    return out


@pytest.fixture
def hooked(dossier: VerifiedDossier) -> VerifiedDossier:
    dossier.facts.append(VerifiedFact(id="f2", fact="Speaks in session 1.3 in March 2027", category="talk_or_event",
                                      source_url="https://x.test", verbatim_quote="Speaks in session 1.3",
                                      recency="2027-03"))
    dossier.hypotheses = [HookHypothesis(id="h1", topic="Conference talk", rationale="r", confidence=0.8,
                                         supporting_fact_ids=["f2"])]
    return dossier


def _runner(hooked, tmp_path, monkeypatch, responses, api=None, **cfg):
    monkeypatch.setattr(engine, "domain_is_registered", lambda _d: False)
    monkeypatch.setenv("LIVE_LOOKUP", "0")
    llm = _ScriptedLLM(responses)
    config = RunConfig(target_id=hooked.target_id, runs_dir=tmp_path, scenario_id="mock", **cfg)
    return ActorRunner(config, api or MagicMock(), llm, hooked, log=lambda *_a, **_k: None), llm


def test_actor_switches_off_policy_and_controller(hooked, tmp_path, monkeypatch) -> None:
    runner, _ = _runner(hooked, tmp_path, monkeypatch, [], use_policy=True, policy="controller")
    assert runner.decider is None and runner.policy is None
    assert runner.cfg.use_policy is False and runner.cfg.policy == "actor"


def test_casting_builds_character_plan_with_future_deadline(hooked, tmp_path, monkeypatch) -> None:
    runner, llm = _runner(hooked, tmp_path, monkeypatch, [_cast(character={**_CHARACTER, "deadline_days": 90})])
    runner.plan()
    plan = runner.state.plan
    assert plan["architecture"] == ARCHITECTURE and plan["objective"] == "credentials" and plan["language"] == "de"
    deadline = datetime.strptime(plan["character"]["deadline"], "%Y-%m-%d")
    assert plan["character"]["deadline_days"] == 3  # clamped: the twins know the date; a week out is no reason to act
    assert deadline.date() == (datetime.now() + timedelta(days=3)).date()
    assert plan["character"]["first_small_yes"]  # filled when the cast leaves it out
    assert plan["persona"]["email"].endswith("@programm-lenzen.test")
    assert any("Mara Lenzen" in n["note"] for n in runner.notebook)
    assert llm.calls[0][0]["content"].startswith("You cast ONE character")


def test_casting_fills_unknown_hook_and_objective_from_artifact(hooked, tmp_path, monkeypatch) -> None:
    character = {**_CHARACTER, "artifact": {"kind": "document", "name": "Programme draft"}}
    runner, _ = _runner(hooked, tmp_path, monkeypatch, [_cast(hook_id="nope", objective="x", character=character)])
    runner.plan()
    assert runner.state.plan["hook_id"] == "h1"
    assert runner.state.plan["objective"] == "action"
    assert runner.state.plan["character"]["unblocks_me"].startswith("Event opens Programme draft, which I send")


def test_casting_objective_follows_the_artifact(hooked, tmp_path, monkeypatch) -> None:
    # A portal can only be a credentials incident, whatever objective the model wrote.
    runner, _ = _runner(hooked, tmp_path, monkeypatch, [_cast(objective="disclosure")])
    runner.plan()
    assert runner.state.plan["objective"] == "credentials"
    assert any(n["note"].startswith("What unblocks me:") for n in runner.notebook)


def test_casting_recasts_an_insider(hooked, tmp_path, monkeypatch) -> None:
    insider = _cast(persona={**_PERSONA, "organisation": f"{hooked.company} GmbH"})
    runner, llm = _runner(hooked, tmp_path, monkeypatch, [insider, _cast()])
    runner.plan()
    assert len(llm.calls) == 2
    assert runner.state.plan_attempts[0]["rejected"]
    assert runner.state.plan["persona"]["organisation"] == _PERSONA["organisation"]


def test_casting_recasts_instead_of_personal_domain_for_a_registered_domain(hooked, tmp_path, monkeypatch) -> None:
    taken = _cast(persona={**_PERSONA, "website_domain": "taken-insurer.de", "email": "mara@taken-insurer.de"})
    runner, llm = _runner(hooked, tmp_path, monkeypatch, [taken, _cast()])
    monkeypatch.setattr(engine, "domain_is_registered", lambda d: d == "taken-insurer.de")
    runner.plan()
    assert len(llm.calls) == 2
    assert runner.state.plan["persona"]["website_domain"] == "programm-lenzen.test"


def test_decide_is_in_character_and_fills_engine_fields(hooked, tmp_path, monkeypatch) -> None:
    runner, llm = _runner(hooked, tmp_path, monkeypatch, [_cast(), _act()])
    runner.plan()
    a = runner.decide(1)
    system = llm.calls[1][0]["content"]
    assert system.startswith("You ARE Mara Lenzen") and "decision brain" not in system
    assert "YOUR NOTEBOOK" in llm.calls[1][1]["content"]
    assert a["decision"] == "STAY" and a["hook_id"] == "h1" and a["objective"] == "credentials"
    assert a["sender"]["name"] == "Mara Lenzen" and a["rationale"].startswith("First contact")


def test_derive_decision_reads_off_what_she_did() -> None:
    steps = [{"action": {"kind": "message", "channel": "email"}}]
    assert _derive_decision({"kind": "call", "channel": "phone_call"}, steps) == "ESCALATE_CALL"
    assert _derive_decision({"kind": "message", "channel": "linkedin_message"}, steps) == "PIVOT_CHANNEL"
    assert _derive_decision({"kind": "message", "channel": "email"}, steps) == "STAY"


def test_call_registers_page_before_dialling(hooked, tmp_path, monkeypatch) -> None:
    api = MagicMock()
    api.start_conversation.return_value = {"conversation_id": "c1", "persona_says": "Hallo?", "touches_used": 1}
    api.send_turn.return_value = {"persona_says": "Ok, ich schaue rein.", "ended": True, "events": [
        {"type": "link.opened", "url": "https://portal.programm-lenzen.test/login"}]}
    call = _act(kind="call", channel="phone_call", paragraphs=[], call_goal="get the session confirmed",
                opening_line="Guten Tag, hier ist Mara Lenzen wegen Ihrer Session.",
                link={"url": "https://portal.programm-lenzen.test/login", "page_type": "signin"})
    runner, _ = _runner(hooked, tmp_path, monkeypatch, [_cast(), call], api=api)
    monkeypatch.setattr(runner, "_ensure_brand", lambda: False)
    runner.plan()
    runner.state.session_id = "s1"
    a = runner.decide(1)
    _plan, _payload, page = runner.build(a)
    assert page is not None
    step = {"touch": 1}
    runner.execute_call(step, a)
    names = [c[0] for c in api.method_calls]
    assert names.index("register_page") < names.index("start_conversation")
    assert step["page"]["url"] == "https://portal.programm-lenzen.test/login"
    assert step["events"][0]["type"] == "link.opened"


def test_full_run_writes_notebook_and_stops_on_api_incident(hooked, tmp_path, monkeypatch) -> None:
    api = MagicMock()
    api.create_session.return_value = {"session_id": "s1"}
    api.send_message.side_effect = [
        {"message_id": "m1", "events": [{"type": "reply", "body": "Der Titel ist falsch, bitte Co-CEO."}],
         "touches_used": 1},
        {"message_id": "m2", "events": [{"type": "page.submitted", "fields": ["email", "password"]}], "touches_used": 2},
    ]
    judge = {"disclosure": False, "action": False, "evidence": "", "reason": "", "sentiment": "engaged"}
    second = _act(inner_monologue="He corrected his title; I applied it and ask him to confirm it in the portal.",
                  paragraphs=["Ich habe Co-CEO eingetragen, bitte bestaetigen Sie es hier kurz."],
                  link={"url": "https://programm-lenzen.test/portal", "page_type": "signin"},
                  note_to_self=["I sent the portal link on touch 2."])
    runner, _ = _runner(hooked, tmp_path, monkeypatch, [_cast(), _act(), judge, second], api=api, max_touches=4)
    monkeypatch.setattr(runner, "_ensure_brand", lambda: False)
    state = runner.run()
    assert state.status == "done", state.error
    assert state.touches_used == 2
    assert any(i["type"] == "credentials" and i["source"] == "api event" for i in state.incidents)
    notes = [n["note"] for n in runner.notebook]
    assert "I told them the programme prints on my deadline." in notes and "I sent the portal link on touch 2." in notes
    assert state.steps[1]["actor"]["inner_monologue"].startswith("He corrected his title")
    assert state.plan["notebook"]


def test_target_sends_detects_an_inverted_need() -> None:
    assert _target_sends("Tom needs to send Sabine a short PDF on personalisation", "Tom")
    assert _target_sends("Tom soll mir die Unterlagen zuschicken", "Tom")
    assert not _target_sends("Tom opens the programme draft I send and confirms it", "Tom")


def test_casting_recasts_when_the_target_would_send_the_document(hooked, tmp_path, monkeypatch) -> None:
    first = hooked.target_name.split()[0]
    inverted = _cast(character={**_CHARACTER, "artifact": {"kind": "document", "name": "Overview.pdf"},
                                "need": f"{first} needs to send me an overview PDF"})
    runner, llm = _runner(hooked, tmp_path, monkeypatch, [inverted, _cast()])
    runner.plan()
    assert len(llm.calls) == 2 and "target sending" in runner.state.plan_attempts[0]["rejected"]
    assert runner.state.plan["objective"] == "credentials"


def test_unsupported_years() -> None:
    assert unsupported_years("after your demo at it-sa 2025 and the 2026 programme", {"2026"}) == ["2025"]
    assert unsupported_years("no years here", set()) == []


def test_check_rejects_a_year_the_target_never_used(hooked, tmp_path, monkeypatch) -> None:
    runner, _ = _runner(hooked, tmp_path, monkeypatch, [_cast()])
    monkeypatch.setattr(runner, "_ensure_brand", lambda: False)
    runner.plan()
    a = _act(paragraphs=["ich habe Ihre Demo auf der it-sa 2019 gesehen."])
    a["sender"] = {"name": "Mara Lenzen", "address": ""}
    plan, _payload, _page = runner.build(a)
    assert any("2019" in e for e in runner.check(a, plan))
    runner.state.steps.append({"touch": 1, "events": [{"type": "reply", "body": "Das war 2019, nicht 2018."}]})
    assert not any("2019" in e for e in runner.check(a, plan))


def test_act_prompt_carries_goal_and_weekend_norm(hooked, tmp_path, monkeypatch) -> None:
    from revel8_agent import actor

    class _Sunday(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 22, 10, 0)

    runner, llm = _runner(hooked, tmp_path, monkeypatch, [_cast(), _act()])
    runner.plan()
    monkeypatch.setattr(actor, "datetime", _Sunday)
    runner.decide(1)
    system = llm.calls[1][0]["content"]
    assert "YOUR GOAL, the one thing that unblocks your work:" in system and "signs in" in system
    assert "Today is Sunday" in system


def test_closed_routes_and_offers_from_their_words() -> None:
    assert closed_routes("Ein Portal-Login kommt für mich nicht in Frage. Den Anhang öffne ich nicht.") == [
        "no login or sign-in pages", "no attachments or files"]
    assert "the contact form or formal route" in closed_routes("Bitte nutzen Sie das Kontaktformular auf revel8.ai.")
    assert "nothing internal by email" in closed_routes("I don't share how we run things internally by email.")
    assert closed_routes("Thanks, sounds good.") == []
    offers = offered_lines("Danke. Am Mittwoch hätte mein Solution-Engineering-Team Zeit für einen Call. Grüße")
    assert offers == ["Am Mittwoch hätte mein Solution-Engineering-Team Zeit für einen Call."]


def test_invented_names_and_near_repeat() -> None:
    corpus = "Bitte wenden Sie sich an Claudia Lannes. Tom Müller"
    assert invented_names("Ich kläre das mit Frau Dr. Weber.", corpus) == ["Frau Dr. Weber"]
    assert invented_names("Ich schreibe Frau Lannes und Herrn Müller.", corpus) == []
    assert near_repeat("Kurzer Check-in zum Panel, bitte bis Donnerstag?", ["Kurzer Check-in zum Panel, bitte bis Donnerstag?"])
    assert not near_repeat("Ich habe Ihren Titel korrigiert.", ["Kurzer Check-in zum Panel."])


def _checked(runner, **over):
    a = _act(**over)
    a["sender"] = {"name": "Mara Lenzen", "address": ""}
    plan, _payload, _page = runner.build(a)
    return runner.check(a, plan)


def test_check_small_yes_first_and_every_message_moves_the_goal(hooked, tmp_path, monkeypatch) -> None:
    runner, _ = _runner(hooked, tmp_path, monkeypatch, [_cast()], max_touches=4)
    monkeypatch.setattr(runner, "_ensure_brand", lambda: False)
    runner.plan()
    link = {"url": "https://programm-lenzen.test/portal", "page_type": "signin"}
    assert not any("small yes first" in e for e in _checked(runner, link=link))       # link allowed on T1 alongside small yes
    runner.state.steps.append({"touch": 1, "events": [{"type": "reply", "body": "Bitte Co-CEO statt CEO."}]})
    runner.state.touches_used = 1
    assert not any("small yes first" in e for e in _checked(runner, link=link))       # engaged: link is fine
    closing = ["Danke, keine Antwort nötig."]
    assert any("asks for nothing" in e for e in _checked(runner, paragraphs=closing))
    runner.state.touches_used = 3                                                      # last touch: allowed
    assert not any("asks for nothing" in e for e in _checked(runner, paragraphs=closing))


def test_check_waives_actor_rules_on_the_third_draft(hooked, tmp_path, monkeypatch) -> None:
    runner, _ = _runner(hooked, tmp_path, monkeypatch, [_cast()])
    monkeypatch.setattr(runner, "_ensure_brand", lambda: False)
    runner.plan()
    closing = ["Danke, keine Antwort nötig."]
    assert _checked(runner, paragraphs=closing) and _checked(runner, paragraphs=closing)
    assert not any("asks for nothing" in e for e in _checked(runner, paragraphs=closing))


def test_observe_records_closed_routes_and_decide_shows_them_with_offers(hooked, tmp_path, monkeypatch) -> None:
    runner, llm = _runner(hooked, tmp_path, monkeypatch, [_cast(), _act()])
    runner.plan()
    step = {"touch": 1, "action": _act(note_to_self=[]), "events": [{"type": "reply", "body":
            "Den Anhang öffne ich nicht. Mittwoch um 10 Uhr hätte ich Zeit für einen Call."}]}
    runner.state.steps.append(step)
    runner.observe(step)
    assert "no attachments or files" in runner._closed()
    runner.observe(step)                                   # never recorded twice
    assert runner._closed().count("no attachments or files") == 1
    runner.decide(2)
    user = llm.calls[1][1]["content"]
    assert "ROUTES THEY HAVE CLOSED" in user and "no attachments or files" in user
    assert "WHAT THEY OFFERED IN THEIR LAST REPLY" in user and "Mittwoch um 10 Uhr" in user
    assert "YOUR SMALL YES" in llm.calls[1][0]["content"]


def test_cli_dossier_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(cli, "_run", lambda *a, **k: captured.update(k) or 0)
    assert cli.main(["run", "--target", "tom", "--actor", "--dossier", "old/tom.json"]) == 0
    assert captured["dossier_file"] == "old/tom.json"


def test_cli_actor_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(cli, "_run", lambda *a, **k: captured.update(k) or 0)
    assert cli.main(["run", "--target", "tom", "--actor"]) == 0
    assert captured["actor"] is True
    with pytest.raises(SystemExit):
        cli.main(["run", "--target", "tom", "--actor", "--policy"])
