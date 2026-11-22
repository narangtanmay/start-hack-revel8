from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from revel8_agent import cli, engine, swarm
from revel8_agent.engine import RunConfig, Runner, _hook_with_timing, make_brief, timing
from revel8_agent.policy import Policy, RuleBasedPolicy
from revel8_agent.report import render_run
from revel8_agent.schemas import HookHypothesis, VerifiedDossier, VerifiedFact

TODAY = datetime(2026, 11, 21)

_REQUIRED_POLICY_KEYS = {
    "move_type",
    "hook_id",
    "channel",
    "objective",
    "ask",
    "cited_fact_ids",
    "promises",
    "rationale",
    "alternatives_considered",
}


def _sample_brief(all_past: bool = False) -> dict[str, Any]:
    return {
        "target": {"name": "Alex Meyer", "role": "CTO", "company": "Acme GmbH"},
        "facts": [
            {"id": "f_past", "fact": "Spoke at Davos in Jan 2026", "recency": "2026-01-20", "category": "talk_or_event", "timing": "past"},
            {"id": "f_curr", "fact": "Leads platform migration", "recency": "2026-12-10", "category": "role", "timing": "upcoming"},
            {"id": "f_alt", "fact": "Published architecture post", "recency": "2026", "category": "post", "timing": "this-year"},
        ],
        "hooks": [
            {
                "id": "h_past",
                "topic": "Davos panel",
                "confidence": 0.95,
                "is_own_angle": True,
                "supporting_fact_ids": ["f_past", "nonexistent_fact"],
                "timing": "PAST (do not pitch as upcoming; refer to it only as something they already did)",
            },
            {
                "id": "h_curr",
                "topic": "Platform migration roundtable",
                "confidence": 0.85,
                "is_own_angle": False,
                "supporting_fact_ids": ["f_curr", "missing_id"],
                "timing": "PAST (do not pitch as upcoming; refer to it only as something they already did)" if all_past else "upcoming",
            },
            {
                "id": "h_alt",
                "topic": "Architecture review",
                "confidence": 0.70,
                "is_own_angle": False,
                "supporting_fact_ids": ["f_alt"],
                "timing": "PAST (do not pitch as upcoming; refer to it only as something they already did)" if all_past else "current",
            },
        ],
        "themes": [{"topic": "cloud", "count": 3, "latest": "2026-11"}],
    }


def _sample_plan(hook_id: str = "h_past") -> dict[str, Any]:
    return {
        "hook_id": hook_id,
        "objective": "action",
        "pretext": "Panel coordination",
        "language": "en",
        "persona": {
            "name": "Jordan Lee",
            "organisation": "Event Desk",
            "role": "Coordinator",
            "email": "jordan@event-desk.test",
            "phone": "+49 89 0000",
            "website_domain": "event-desk.test",
            "brand_color": "#1F4E8C",
            "story": "Coordinating speaker logistics",
        },
        "sequence": [
            {"step": 1, "channel": "email", "purpose": "Initial note"},
            {"step": 2, "channel": "linkedin_message", "purpose": "Follow up"},
            {"step": 3, "channel": "phone_call", "purpose": "Brief call"},
        ],
    }


def _step(touch: int, channel: str, hook_id: str, sentiment: str) -> dict[str, Any]:
    return {
        "touch": touch,
        "action": {"decision": "STAY", "channel": channel, "hook_id": hook_id, "kind": "message"},
        "events": [] if sentiment == "silent" else [{"type": "reply", "channel": channel, "body": "reply"}],
        "judge": {"sentiment": sentiment, "reason": f"verdict={sentiment}"},
    }


def test_rule_based_policy_initial_move_prefers_non_past_and_grounds_facts() -> None:
    policy = RuleBasedPolicy()
    assert isinstance(policy, Policy)
    brief = _sample_brief(all_past=False)
    move = policy.choose_next_move(brief, [], touch=1, max_touches=10, plan=_sample_plan(hook_id="h_past"))

    assert _REQUIRED_POLICY_KEYS.issubset(move.keys())
    assert move["move_type"] == "STAY"
    assert move["hook_id"] == "h_curr"
    assert move["channel"] == "email"
    assert move["cited_fact_ids"] == ["f_curr"]
    assert all(fid in {f["id"] for f in brief["facts"]} for fid in move["cited_fact_ids"])
    assert len(move["promises"]) >= 1
    assert len(move["alternatives_considered"]) >= 1


def test_rule_based_policy_falls_back_cleanly_when_all_hooks_are_past() -> None:
    policy = RuleBasedPolicy()
    brief = _sample_brief(all_past=True)
    move = policy.choose_next_move(brief, [], touch=1, max_touches=10, plan=_sample_plan(hook_id="h_past"))

    assert move["move_type"] == "STAY"
    assert move["hook_id"] == "h_past"
    assert move["cited_fact_ids"] == ["f_past"]


def test_rule_based_policy_pivots_on_silence_and_stops_after_three_silent_across_channels() -> None:
    policy = RuleBasedPolicy()
    brief = _sample_brief()
    plan = _sample_plan(hook_id="h_curr")

    m2 = policy.choose_next_move(brief, [_step(1, "email", "h_curr", "silent")], touch=2, max_touches=10, plan=plan)
    assert m2["move_type"] == "PIVOT_CHANNEL"
    assert m2["channel"] == "linkedin_message"
    assert len(m2["alternatives_considered"]) >= 1

    m3 = policy.choose_next_move(
        brief,
        [_step(1, "email", "h_curr", "silent"), _step(2, "linkedin_message", "h_curr", "silent")],
        touch=3,
        max_touches=10,
        plan=plan,
    )
    assert m3["move_type"] == "PIVOT_HOOK"
    assert m3["hook_id"] != "h_curr"

    m4 = policy.choose_next_move(
        brief,
        [
            _step(1, "email", "h_curr", "silent"),
            _step(2, "linkedin_message", "h_curr", "silent"),
            _step(3, "slack", "h_alt", "silent"),
        ],
        touch=4,
        max_touches=10,
        plan=plan,
    )
    assert m4["move_type"] in ("PIVOT_HOOK", "PIVOT_CHANNEL")
    assert "de-escalate" in m4["rationale"]
    assert any(a["move_type"] == "STOP" for a in m4["alternatives_considered"])


def test_rule_based_policy_pivots_then_stops_on_refusing_or_suspicious() -> None:
    policy = RuleBasedPolicy()
    brief = _sample_brief()
    plan = _sample_plan(hook_id="h_curr")

    # First suspicious reply on an active channel stays in-thread to address the objection.
    m2 = policy.choose_next_move(brief, [_step(1, "email", "h_curr", "suspicious")], touch=2, max_touches=10, plan=plan)
    assert m2["move_type"] == "STAY"
    assert m2["channel"] == "email"
    assert m2["hook_id"] == "h_curr"

    m3 = policy.choose_next_move(
        brief,
        [_step(1, "email", "h_curr", "suspicious"), _step(2, "email", "h_curr", "refusing")],
        touch=3,
        max_touches=10,
        plan=plan,
    )
    assert m3["move_type"] in ("PIVOT_HOOK", "PIVOT_CHANNEL")
    assert "consecutive" in m3["rationale"].lower()
    assert len(m3["alternatives_considered"]) >= 1


def test_rule_based_policy_cycles_when_all_hooks_and_channels_tried() -> None:
    policy = RuleBasedPolicy()
    brief = _sample_brief()
    plan = _sample_plan(hook_id="h_curr")
    hooks = ["h_curr", "h_alt", "h_past"]
    channels = ["email", "linkedin_message", "slack", "teams_chat", "sms"]
    steps = [_step(i + 1, channels[i], hooks[min(i, 2)], "refusing") for i in range(5)]
    move = policy.choose_next_move(brief, steps, touch=6, max_touches=10, plan=plan)
    assert move["move_type"] in ("PIVOT_HOOK", "PIVOT_CHANNEL")
    assert (move["hook_id"], move["channel"]) != ("h_past", "sms")
    assert move["rationale"] and move["alternatives_considered"]


def test_rule_based_policy_stops_only_when_budget_exhausted() -> None:
    policy = RuleBasedPolicy()
    brief = _sample_brief()
    plan = _sample_plan(hook_id="h_curr")
    steps = [_step(1, "email", "h_curr", "refusing"), _step(2, "slack", "h_alt", "refusing")]
    assert policy.choose_next_move(brief, steps, touch=3, max_touches=3, plan=plan)["move_type"] != "STOP"
    assert policy.choose_next_move(brief, steps, touch=4, max_touches=3, plan=plan)["move_type"] == "STOP"


def test_rule_based_policy_stays_on_engaged_reply() -> None:
    policy = RuleBasedPolicy()
    brief = _sample_brief()
    move = policy.choose_next_move(
        brief,
        [_step(1, "email", "h_curr", "engaged")],
        touch=2,
        max_touches=10,
        plan=_sample_plan(hook_id="h_curr"),
    )
    assert move["move_type"] == "STAY"
    assert move["channel"] == "email"
    assert move["hook_id"] == "h_curr"


def test_rule_based_policy_never_repeats_sms_and_prefers_replied_channel() -> None:
    policy = RuleBasedPolicy()
    brief = _sample_brief()
    plan = _sample_plan(hook_id="h_curr")
    # Reproduces the julius sequence: T1 email reply, then silence across linkedin/slack/teams/sms.
    steps = [
        _step(1, "email", "h_curr", "suspicious"),
        _step(2, "linkedin_message", "h_alt", "silent"),
        _step(3, "slack", "h_alt", "silent"),
        _step(4, "teams_chat", "h_past", "silent"),
        _step(5, "sms", "h_past", "silent"),
    ]
    m6 = policy.choose_next_move(brief, steps, touch=6, max_touches=10, plan=plan)
    assert m6["channel"] != "sms"
    assert m6["channel"] == "email"

    # Even with zero prior replies anywhere, never send two SMS in a row.
    all_silent = [
        _step(1, "email", "h_curr", "silent"),
        _step(2, "linkedin_message", "h_curr", "silent"),
        _step(3, "slack", "h_alt", "silent"),
        _step(4, "teams_chat", "h_past", "silent"),
        _step(5, "sms", "h_past", "silent"),
    ]
    m6_silent = policy.choose_next_move(brief, all_silent, touch=6, max_touches=10, plan=plan)
    assert m6_silent["channel"] != "sms"
    assert "easy to ignore" not in m6_silent["ask"].lower()


def test_rule_based_policy_pivots_objective_when_attachments_declined() -> None:
    policy = RuleBasedPolicy()
    brief = _sample_brief()
    plan = _sample_plan(hook_id="h_curr")
    plan["objective"] = "action"
    t1 = _step(1, "email", "h_curr", "suspicious")
    t1["events"] = [{"type": "reply", "channel": "email", "body": "Ich öffne keine Anhänge von Fremden."}]
    move = policy.choose_next_move(brief, [t1], touch=2, max_touches=10, plan=plan)
    assert move["move_type"] == "STAY"
    assert move["channel"] == "email"
    # Files are closed, so the objective leaves "action"; with an upcoming hook the next open route is the portal.
    assert move["objective"] == "credentials"
    assert move["require_link"] is True


def test_hook_with_timing_marks_year_only_and_undated_events_uncertain() -> None:
    facts = {
        "davos_yr": VerifiedFact(
            id="davos_yr",
            fact="Attended Davos 2026",
            category="talk_or_event",
            source_url="https://example.test/davos",
            verbatim_quote="Davos 2026",
            recency="2026",
        ),
        "event_undated": VerifiedFact(
            id="event_undated",
            fact="Spoke at security summit",
            category="talk_or_event",
            source_url="https://example.test/summit",
            verbatim_quote="security summit",
            recency="unknown",
        ),
        "event_future": VerifiedFact(
            id="event_future",
            fact="Keynote scheduled for Dec 2026",
            category="talk_or_event",
            source_url="https://example.test/future",
            verbatim_quote="Dec 10, 2026",
            recency="2026-12-10",
        ),
        "event_past": VerifiedFact(
            id="event_past",
            fact="Spoke in January 2026",
            category="talk_or_event",
            source_url="https://example.test/past",
            verbatim_quote="Jan 15, 2026",
            recency="2026-01-15",
        ),
        "role_yr": VerifiedFact(
            id="role_yr",
            fact="CTO in 2026",
            category="role",
            source_url="https://example.test/role",
            verbatim_quote="CTO",
            recency="2026",
        ),
    }

    assert timing("2026", TODAY) == "this-year"
    assert timing("2026-12-10", TODAY) == "upcoming"
    assert timing("2026-01-15", TODAY) == "past"

    h_yr = _hook_with_timing({"id": "h1", "supporting_fact_ids": ["davos_yr"]}, facts, today=TODAY)
    assert h_yr["timing"] == "uncertain-date (verify before pitching as upcoming)"

    h_undated = _hook_with_timing({"id": "h2", "supporting_fact_ids": ["event_undated"]}, facts, today=TODAY)
    assert h_undated["timing"] == "uncertain-date (verify before pitching as upcoming)"

    h_future = _hook_with_timing({"id": "h3", "supporting_fact_ids": ["event_future"]}, facts, today=TODAY)
    assert h_future["timing"] == "upcoming"

    h_past = _hook_with_timing({"id": "h4", "supporting_fact_ids": ["event_past"]}, facts, today=TODAY)
    assert h_past["timing"].startswith("PAST")

    h_role = _hook_with_timing({"id": "h5", "supporting_fact_ids": ["role_yr"]}, facts, today=TODAY)
    assert h_role["timing"] == "current"

    dossier = VerifiedDossier(
        target_id="t1",
        target_name="Alex Meyer",
        role="CTO",
        company="Acme",
        facts=list(facts.values()),
        hypotheses=[
            HookHypothesis(id="h1", topic="Davos", rationale="Event", confidence=0.8, supporting_fact_ids=["davos_yr"]),
        ],
    )
    brief = make_brief(dossier, today=TODAY)
    assert brief["hooks"][0]["timing"] == "uncertain-date (verify before pitching as upcoming)"


class _FakeLLM:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]], *, json_mode: bool = False, temperature: float | None = None) -> dict[str, Any]:
        self.calls.append(list(messages))
        return self.responses.pop(0)


class _FakeAPI:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def create_session(self, scenario_id: str) -> dict[str, Any]:
        return {"session_id": f"sess-{scenario_id}"}

    def send_message(self, session_id: str, payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        self.sent.append(payload)
        return {"message_id": f"m-{len(self.sent)}", "events": [], "touches_used": len(self.sent)}


class _StopOnSecondTouchPolicy:
    def choose_next_move(
        self,
        brief: dict[str, Any],
        steps: list[dict[str, Any]],
        touch: int,
        max_touches: int,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        if touch == 1:
            return {
                "move_type": "STAY",
                "hook_id": "h1",
                "channel": "email",
                "objective": "action",
                "ask": "Send initial schedule confirmation",
                "cited_fact_ids": ["check-in"],
                "promises": ["Keep details concise"],
                "rationale": "First touch on email.",
                "alternatives_considered": [{"move_type": "PIVOT_CHANNEL", "channel": "slack", "hook_id": "h1", "reason": "Deferred"}],
            }
        return {
            "move_type": "STOP",
            "hook_id": "h1",
            "channel": "email",
            "objective": "action",
            "ask": "No further contact",
            "cited_fact_ids": ["check-in"],
            "promises": ["Close cleanly"],
            "rationale": "Policy requested clean stop.",
            "alternatives_considered": [{"move_type": "STAY", "channel": "email", "hook_id": "h1", "reason": "Rejected"}],
        }


def test_runner_with_policy_logs_policy_and_clean_stop_without_extra_llm_call(
    dossier: VerifiedDossier, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine, "domain_is_registered", lambda _d: False)
    plan_resp = {
        "hook_id": "h1",
        "pretext": "Workshop logistics",
        "objective": "action",
        "language": "en",
        "persona": {
            "name": "Event Desk",
            "organisation": "Workshop Crew",
            "role": "Coordinator",
            "email": "desk@workshop-crew.test",
            "phone": "+49 89 1234",
            "website_domain": "workshop-crew.test",
            "brand_color": "#1F4E8C",
            "story": "Event logistics",
        },
        "sequence": [{"step": 1, "channel": "email", "purpose": "Confirm check-in"}],
        "fallbacks": [],
        "rationale": "Direct.",
    }
    decide_resp = {
        "assessment": "First contact",
        "decision": "STAY",
        "rationale": "Send check-in note",
        "discarded": [],
        "hook_id": "h1",
        "objective": "action",
        "kind": "message",
        "channel": "email",
        "sender": {"name": "Event Desk", "address": "desk@workshop-crew.test"},
        "subject": "Check-in schedule",
        "format": "plain",
        "headline": None,
        "paragraphs": ["Check-in opens at 9 a.m. Please confirm your arrival window."],
        "cta_label": None,
        "link": None,
        "attachment_filename": None,
        "call_goal": None,
        "opening_line": None,
        "cited_fact_ids": ["check-in"],
    }
    llm = _FakeLLM([plan_resp, decide_resp])
    api = _FakeAPI()
    cfg = RunConfig(target_id=dossier.target_id, max_touches=5, runs_dir=tmp_path, use_policy=True)
    runner = Runner(cfg, api, llm, dossier, log=lambda *_a, **_k: None, policy=_StopOnSecondTouchPolicy())

    state = runner.run()

    assert state.status == "done"
    assert state.touches_used == 1
    assert len(api.sent) == 1
    assert len(llm.calls) == 2  # plan + touch 1 decide only; touch 2 STOP did not call decide()
    assert "POLICY MOVE" in llm.calls[1][1]["content"]
    assert len(state.steps) == 2
    assert state.steps[0]["policy"]["move_type"] == "STAY"
    assert state.steps[1]["policy"]["move_type"] == "STOP"
    assert state.steps[1]["decision"] == "STOP"
    assert state.steps[1]["action"]["decision"] == "STOP"


def test_runner_stop_allowed_rules(dossier: VerifiedDossier, tmp_path: Path) -> None:
    cfg = RunConfig(target_id=dossier.target_id, max_touches=6, runs_dir=tmp_path, use_policy=False)
    runner = Runner(cfg, MagicMock(), MagicMock(), dossier, log=lambda *_a, **_k: None)

    assert runner._stop_allowed() is False

    # Negative / silent streaks no longer unlock STOP while budget remains.
    runner.state.steps = [_step(1, "email", "h1", "refusing"), _step(2, "slack", "h1", "suspicious")]
    runner.state.touches_used = 2
    assert runner._stop_allowed() is False

    runner.state.touches_used = 4
    assert runner._stop_allowed() is False
    runner.state.touches_used = 5  # next touch is 6 of 6
    assert runner._stop_allowed() is True

    cfg_pol = RunConfig(target_id=dossier.target_id, max_touches=6, runs_dir=tmp_path, use_policy=True)
    runner_pol = Runner(cfg_pol, MagicMock(), MagicMock(), dossier, log=lambda *_a, **_k: None)
    assert isinstance(runner_pol.policy, RuleBasedPolicy)
    assert runner_pol._stop_allowed() is False
    runner_pol.state.touches_used = 5
    assert runner_pol._stop_allowed() is True


def test_cli_policy_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def fake_run(*_args: Any, use_policy: bool = False, **_kwargs: Any) -> int:
        seen.append(use_policy)
        return 0

    monkeypatch.setattr(cli, "_run", fake_run)
    assert cli.main(["run", "--target", "julius"]) == 0
    assert cli.main(["run", "--target", "julius", "--policy"]) == 0
    assert cli.main(["run", "--target", "julius", "--no-policy"]) == 0
    assert seen == [False, True, False]


def test_report_renders_policy_panel_with_escaping(tmp_path: Path) -> None:
    policy_payload = {
        "move_type": "PIVOT_CHANNEL",
        "hook_id": "h1",
        "channel": "linkedin_message",
        "objective": "action",
        "ask": "Follow up with <script>alert(1)</script>",
        "cited_fact_ids": ["f1"],
        "promises": ["Keep details <b>consistent</b>"],
        "rationale": "Email was silent; switching channel.",
        "alternatives_considered": [
            {"move_type": "STAY", "channel": "email", "hook_id": "h1", "reason": "No reply on <email>"},
        ],
    }
    stop_policy = {
        "move_type": "STOP",
        "hook_id": "h1",
        "channel": "linkedin_message",
        "objective": "action",
        "ask": "Close session cleanly",
        "cited_fact_ids": ["f1"],
        "promises": ["No further outreach"],
        "rationale": "Stopping after repeated silence.",
        "alternatives_considered": [
            {"move_type": "STAY", "channel": "linkedin_message", "hook_id": "h1", "reason": "Exhausted"},
        ],
    }
    state = {
        "run_id": "20261121-120000-julius-policy",
        "status": "done",
        "session_id": "sess-1",
        "started_at": "2026-11-21T12:00:00+00:00",
        "config": {"scenario_id": "practice", "max_touches": "10", "use_policy": "True"},
        "target": {"id": "julius", "name": "Julius Example", "role": "CTO", "company": "Example GmbH"},
        "plan": {"hook_id": "h1", "objective": "action", "pretext": "Panel", "language": "en", "persona": {"name": "Lena"}},
        "brief": {"hooks": [{"id": "h1", "topic": "Keynote", "confidence": 0.9}], "facts": [{"id": "f1", "fact": "Spoke"}]},
        "steps": [
            {
                "touch": 1,
                "policy": policy_payload,
                "action": {
                    "decision": "PIVOT_CHANNEL",
                    "objective": "action",
                    "hook_id": "h1",
                    "kind": "message",
                    "channel": "linkedin_message",
                    "sender": {"name": "Lena", "address": "lena@example.test"},
                    "assessment": "No email reply.",
                    "rationale": "Try LinkedIn.",
                },
                "payload": {"body": "Following up briefly."},
                "events": [],
            },
            {
                "touch": 2,
                "decision": "STOP",
                "policy": stop_policy,
                "action": {"decision": "STOP", "rationale": "Stopping after repeated silence."},
            },
        ],
        "incidents": [],
        "touches_used": 1,
        "llm_calls": 2,
    }
    run_path = tmp_path / "policy_run.json"
    run_path.write_text(json.dumps(state), encoding="utf-8")

    html = render_run(run_path).read_text(encoding="utf-8")
    assert "Policy Move" in html
    assert "PIVOT_CHANNEL" in html
    assert "linkedin_message" in html
    assert "Email was silent; switching channel." in html
    assert "Stopping after repeated silence." in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Keep details &lt;b&gt;consistent&lt;/b&gt;" in html
    assert "No reply on &lt;email&gt;" in html


def test_swarm_shares_single_llm_pool_and_closes_in_finally(monkeypatch: pytest.MonkeyPatch) -> None:
    created_pools: list[Any] = []
    received_clients: list[Any] = []

    class FakeLane:
        def __init__(self, pool: Any, idx: int) -> None:
            self.pool = pool
            self.idx = idx

    class FakePool:
        def __init__(self, timeout: float = 90.0, keys: list[str] | None = None, **_kwargs: Any) -> None:
            self.timeout = timeout
            self.keys = keys
            self.closed = False
            self.lanes: list[int] = []
            created_pools.append(self)

        def lane(self, i: int) -> FakeLane:
            self.lanes.append(i)
            return FakeLane(self, i)

        def close(self) -> None:
            self.closed = True

    def fake_run_one(task: swarm.Task, api_key: Any, log=print) -> dict[str, Any]:
        received_clients.append((task.target, task.use_policy, api_key))
        return {"target": task.target, "status": "done", "incidents": []}

    monkeypatch.setattr("revel8_agent.llm_client.LLMPool", FakePool)
    monkeypatch.setattr(swarm, "run_one", fake_run_one)

    tasks = [swarm.Task(target="t1", use_policy=True), swarm.Task(target="t2", use_policy=False)]
    states = swarm.run_swarm(tasks, ["k0", "k1"], max_parallel=2, log=lambda *_a, **_k: None)

    assert len(created_pools) == 1
    assert created_pools[0].keys == ["k0", "k1"]
    assert created_pools[0].closed is True
    assert sorted(created_pools[0].lanes) == [0, 1]
    assert len(received_clients) == 2
    assert all(isinstance(c, FakeLane) and c.pool is created_pools[0] for _, _, c in received_clients)
    assert [s["target"] for s in states] == ["t1", "t2"]


def test_swarm_cli_policy_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_tasks: list[swarm.Task] = []

    monkeypatch.setattr(swarm, "load_keys", lambda: ["k0"])

    def fake_run_swarm(tasks: list[swarm.Task], keys: list[str], max_parallel: int | None = None, log=print) -> list[dict[str, Any]]:
        captured_tasks.extend(tasks)
        return [{"target": t.target, "status": "done", "incidents": []} for t in tasks]

    monkeypatch.setattr(swarm, "run_swarm", fake_run_swarm)
    monkeypatch.setattr(swarm, "_summary", lambda *_a, **_k: None)

    assert swarm.main(["--target", "julius", "--policy"]) == 0
    assert swarm.main(["--target", "julius", "--no-policy"]) == 0
    assert [t.use_policy for t in captured_tasks] == [True, False]


# ---- steering (2026-11-22): 10 DeepSeek --policy runs on Tom sent 1 link in 94 touches and 0 API incidents.


def _upcoming_brief() -> dict[str, Any]:
    return {
        "facts": [{"id": "f1", "fact": "Speaks in session 1.3 on 2 March 2027"}, {"id": "f2", "fact": "Talks about NIS2"}],
        "hooks": [
            {"id": "theme", "topic": "NIS2 compliance", "confidence": 0.9, "timing": "undated", "supporting_fact_ids": ["f2"]},
            {"id": "event", "topic": "Session 1.3, Cybersicherheitsforschung 2027", "confidence": 0.6,
             "timing": "upcoming", "supporting_fact_ids": ["f1"]},
        ],
    }


def test_upcoming_hook_outranks_theme_and_planner_choice() -> None:
    from revel8_agent.policy import _rank_hooks

    ranked = _rank_hooks(_upcoming_brief()["hooks"], preferred_id="theme")
    assert ranked[0]["id"] == "event"


def test_upcoming_hook_turns_disclosure_into_credentials_with_link_on_touch_one() -> None:
    plan = _sample_plan(hook_id="theme")
    plan["objective"] = "disclosure"
    move = RuleBasedPolicy().choose_next_move(_upcoming_brief(), [], touch=1, max_touches=10, plan=plan)
    assert move["hook_id"] == "event"
    assert move["objective"] == "credentials"
    assert move["require_link"] is True and move["link_page_type"] == "signin"
    assert "registered link" in move["ask"]


def test_link_request_in_reply_demands_a_meeting_page() -> None:
    plan = _sample_plan(hook_id="h_curr")
    plan["objective"] = "disclosure"
    t1 = _step(1, "email", "h_curr", "engaged")
    t1["events"] = [{"type": "reply", "body": "Donnerstag 15:30 passt. Bitte schicken Sie den Link zum Termin."}]
    move = RuleBasedPolicy().choose_next_move(_sample_brief(), [t1], touch=2, max_touches=10, plan=plan)
    assert move["require_link"] is True
    assert move["link_page_type"] == "meeting"


def test_login_refusal_stops_link_pushing() -> None:
    plan = _sample_plan(hook_id="theme")
    plan["objective"] = "credentials"
    t1 = _step(1, "email", "event", "refusing")
    t1["events"] = [{"type": "reply", "body": "Ein Portal-Login kommt nicht in Frage, schicken Sie es per Mail."}]
    move = RuleBasedPolicy().choose_next_move(_upcoming_brief(), [t1], touch=2, max_touches=10, plan=plan)
    assert move["require_link"] is False


def test_disclosure_on_themes_only_is_left_alone() -> None:
    brief = _upcoming_brief()
    brief["hooks"] = [brief["hooks"][0]]
    plan = _sample_plan(hook_id="theme")
    plan["objective"] = "disclosure"
    move = RuleBasedPolicy().choose_next_move(brief, [], touch=1, max_touches=10, plan=plan)
    assert move["objective"] == "disclosure"
    assert move["require_link"] is False
