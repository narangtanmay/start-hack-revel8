"""Eval-day safety: sequential eval, no practice->eval dossier leak, multi-word company domain guard."""

from __future__ import annotations

import pytest

from revel8_agent import research, swarm
from revel8_agent.osint import Target
from revel8_agent.schemas import VerifiedDossier, VerifiedFact
from revel8_agent.templates.brand import org_domains_from_dossier


def _fact(fid: str, quote: str, url: str = "https://example.org/x") -> VerifiedFact:
    return VerifiedFact(id=fid, fact=quote, category="role", source_url=url, verbatim_quote=quote, recency="2026-01")


def _dossier(name: str, company: str, *facts: VerifiedFact) -> VerifiedDossier:
    return VerifiedDossier(target_id="tom", target_name=name, role="CTO", company=company, facts=list(facts))


# 1. eval forces one worker -------------------------------------------------------------------------------------

def test_run_swarm_forces_one_worker_for_eval(monkeypatch):
    seen = {}

    class FakePool:
        def __init__(self, max_workers):
            seen["max_workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def submit(self, fn, i):
            from concurrent.futures import Future

            f = Future()
            f.set_result(fn(i))
            return f

    class FakeLLMPool:
        def __init__(self, **kw): ...
        def lane(self, i): return object()
        def close(self): ...

    monkeypatch.setattr(swarm, "ThreadPoolExecutor", FakePool)
    monkeypatch.setattr(swarm, "run_one", lambda task, lane, log=print: {"target": task.target, "status": "done"})
    monkeypatch.setattr("revel8_agent.llm_client.LLMPool", FakeLLMPool)

    tasks = [swarm.Task(target=t, scenario="eval") for t in ("a", "b", "c")]
    swarm.run_swarm(tasks, ["k1", "k2", "k3"], max_parallel=3, log=lambda *_: None)
    assert seen["max_workers"] == 1

    swarm.run_swarm([swarm.Task(target=t) for t in ("a", "b")], ["k1", "k2"], max_parallel=2, log=lambda *_: None)
    assert seen["max_workers"] == 2


# 2. no dossier leak across people sharing an id -----------------------------------------------------------------

@pytest.mark.parametrize(
    ("prev_name", "prev_company", "merged"),
    [
        ("Tom Muller", "Acme", True),
        ("  tom MULLER ", "ACME ", True),
        ("Tom Muller", "Other Corp", False),
        ("Tim Other", "Acme", False),
    ],
)
def test_live_dossier_merges_only_same_person(tmp_path, monkeypatch, prev_name, prev_company, merged):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "dossiers").mkdir()
    prev = _dossier(prev_name, prev_company, _fact("f1", "PRACTICE-ONLY quote"))
    (tmp_path / "dossiers" / "tom.json").write_text(prev.model_dump_json(), encoding="utf-8")

    new = _dossier("Tom Muller", "Acme", _fact("f1", "fresh quote"))

    class FakePool:
        def __init__(self, **kw): ...
        def lane(self, i): return None
        def close(self): ...

    monkeypatch.setattr(research, "LLMPool", FakePool)
    monkeypatch.setattr(research, "research", lambda t, pool, **kw: (new, {}))
    monkeypatch.setattr(research, "rank_hooks", lambda *a, **k: [])
    monkeypatch.setenv("RESEARCH_ACCUMULATE", "1")

    dossier, _ = research.live_dossier(Target("tom", "Tom Muller", "CTO", "Acme"), log=lambda *_: None)
    quotes = {f.verbatim_quote for f in dossier.facts}
    assert ("PRACTICE-ONLY quote" in quotes) is merged


# 3. multi-word company root tokens are blocked -----------------------------------------------------------------

@pytest.mark.parametrize("host", ["muster.de", "www.versicherung.de", "musterversicherungag.de", "mail.muster-x.com"])
def test_company_root_tokens_block_domains(host):
    d = _dossier("A B", "Muster Versicherung AG", _fact("f1", "q", url=f"https://{host}/about"))
    assert org_domains_from_dossier(d)


def test_legal_suffix_and_short_tokens_ignored():
    d = _dossier("A B", "Muster Versicherung AG", _fact("f1", "q", url="https://agency.de/"))
    assert not org_domains_from_dossier(d)
