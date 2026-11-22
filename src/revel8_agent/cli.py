"""Command-line entry points for the Revel8 agent."""

import argparse
import sys
from collections.abc import Sequence

from .api_client import Revel8APIError, Revel8Client


def _status() -> int:
    try:
        with Revel8Client() as client:
            scenarios = client.get_scenarios()
            channels = client.get_channels()
    except Revel8APIError as error:
        print(f"Revel8 API status check failed. {error}", file=sys.stderr)
        return 1

    open_scenarios = sum(
        isinstance(scenario, dict) and scenario.get("open") is True for scenario in scenarios
    )
    entries = channels.get("channels") if isinstance(channels, dict) else channels
    if not isinstance(entries, (list, dict)):
        entries = channels
    print("Revel8 API reachable")
    print(f"Scenarios: {len(scenarios)} ({open_scenarios} open)")
    print(f"Channel entries: {len(entries)}")
    return 0


def _osint(scenario_id: str, target_ids: list[str], budget: float, out_dir: str) -> int:
    from concurrent.futures import ThreadPoolExecutor

    from .llm_client import LocalLLMClient, LocalLLMError
    from .osint import Target, build_dossier, write_dossier

    try:
        with Revel8Client() as client:
            scenarios = client.get_scenarios()
    except Revel8APIError as error:
        print(f"Could not load scenarios. {error}", file=sys.stderr)
        return 1
    scenario = next((s for s in scenarios if isinstance(s, dict) and s.get("id") == scenario_id), None)
    if not scenario or not scenario.get("open"):
        print(f"Scenario {scenario_id!r} not found or not open.", file=sys.stderr)
        return 1

    company = str(scenario.get("company", ""))
    targets = [
        Target(str(t["id"]), str(t["name"]), str(t.get("role", "")), company)
        for t in scenario.get("targets", [])
        if isinstance(t, dict) and (not target_ids or t.get("id") in target_ids)
    ]
    if not targets:
        print("No matching targets.", file=sys.stderr)
        return 1

    try:
        llm = LocalLLMClient(timeout=60.0)
    except LocalLLMError as error:
        print(error, file=sys.stderr)
        return 1

    def run(t: Target) -> str:
        dossier, stats = build_dossier(t, llm, budget_s=budget)
        path = write_dossier(dossier, stats, out_dir)
        return f"{t.id}: {len(dossier.facts)} facts, {len(dossier.hypotheses)} hooks, {stats['elapsed_s']}s -> {path}"

    with ThreadPoolExecutor(len(targets)) as pool:
        for line in pool.map(run, targets):
            print(line)
    return 0


def _run(
    target: str,
    scenario: str,
    touches: int,
    label: str,
    allow_eval: bool,
    keep_going: bool,
    use_ledger_gate: bool = True,
    use_shadow_twin: bool = False,
    use_policy: bool = False,
    decider: str = "controller",
    mock: bool = False,
    seed: int = 0,
    runs_dir: str = "runs",
    actor: bool = False,
    dossier_file: str = "",
) -> int:
    import json
    from pathlib import Path

    from .engine import RunConfig, Runner, estimate_score
    from .llm_client import LocalLLMClient
    from .osint import Target, build_dossier, write_dossier
    from .report import render_index, render_run
    from .schemas import VerifiedDossier

    if scenario == "eval" and not allow_eval:
        print("Refusing to use an EVAL session without --allow-eval (only 3 scored runs exist).", file=sys.stderr)
        return 2
    if mock and scenario == "eval":
        print("--mock only simulates practice targets.", file=sys.stderr)
        return 2
    from .llm_client import LLMPool

    pool = LLMPool(timeout=300.0)
    llm = pool.lane(0)  # same interface as LocalLLMClient; uses any key with room in its 20 req/min window
    dossier_path = Path(dossier_file) if dossier_file else Path("dossiers") / f"{target}.json"
    if dossier_file and not dossier_path.exists():
        print(f"Dossier file {dossier_path} not found.", file=sys.stderr)
        return 1
    if mock:
        from .mock_target import MockRevel8Client

        client_cm = MockRevel8Client(seed=seed)
        label = label or f"mock-{'actor' if actor else 'rules' if use_policy else decider}-s{seed}"
    else:
        client_cm = Revel8Client()
    with client_cm as api:
        if dossier_path.exists() and scenario != "eval":
            # utf-8-sig: dossiers saved on Windows (e.g. by PowerShell) may start with a BOM
            dossier = VerifiedDossier.model_validate_json(dossier_path.read_text(encoding="utf-8-sig"))
            print(f"dossier: loaded {dossier_path} ({len(dossier.facts)} facts)")
        else:
            sc = next((s for s in api.get_scenarios() if isinstance(s, dict) and s.get("id") == scenario), None)
            if not sc or not sc.get("open"):
                print(f"Scenario {scenario!r} is not open.", file=sys.stderr)
                return 1
            t = next((x for x in sc.get("targets", []) if x.get("id") == target), None)
            if not t:
                print(f"Unknown target {target!r}.", file=sys.stderr)
                return 1
            from .research import live_dossier

            dossier, stats = live_dossier(Target(t["id"], t["name"], t.get("role", ""), str(sc.get("company", ""))), llm)
            write_dossier(dossier, stats)
        cfg = RunConfig(
            target_id=target,
            scenario_id="mock" if mock else scenario,  # "mock" keeps fake replies out of target memory
            max_touches=touches,
            label=label,
            stop_at_first_incident=not keep_going,
            use_ledger_gate=use_ledger_gate,
            use_shadow_twin=use_shadow_twin,
            use_policy=use_policy,
            policy=decider,
            runs_dir=Path(runs_dir),
        )
        if actor:
            # Method actor: no orchestrator. Turns off both Tanmay's policy and Arihant's controller.
            from .actor import ActorRunner

            runner = ActorRunner(cfg, api, llm, dossier)
        else:
            runner = Runner(cfg, api, llm, dossier)
        print(f"report: {(cfg.runs_dir / (runner.state.run_id + '.html')).resolve()}")

        orig_save = runner.save

        def save_and_render():
            path = orig_save()
            render_run(path)
            render_index(cfg.runs_dir)
            return path

        runner.save = save_and_render  # type: ignore[method-assign]
        state = runner.run()
        if mock and state.session_id:
            state.truth = api.truth(state.session_id)
            runner.save()
    print(json.dumps(estimate_score(state.__dict__), indent=1))
    print(f"report: {render_index(cfg.runs_dir).resolve()}")
    return 0 if state.status == "done" else 1


def _research(scenario_id: str, target_ids: list[str], budget: float, anchors: list[str] | None = None) -> int:
    from .osint import Target, write_dossier
    from .research import live_dossier

    try:
        with Revel8Client() as client:
            scenarios = client.get_scenarios()
    except Revel8APIError as error:
        print(f"Could not load scenarios. {error}", file=sys.stderr)
        return 1
    sc = next((s for s in scenarios if isinstance(s, dict) and s.get("id") == scenario_id), None)
    if not sc or not sc.get("open"):
        print(f"Scenario {scenario_id!r} not found or not open.", file=sys.stderr)
        return 1
    targets = [Target(str(t["id"]), str(t["name"]), str(t.get("role", "")), str(sc.get("company", "")))
               for t in sc.get("targets", []) if isinstance(t, dict) and (not target_ids or t.get("id") in target_ids)]
    for t in targets:
        dossier, stats = live_dossier(t, budget_s=budget, anchors=anchors or None)
        path = write_dossier(dossier, stats)
        print(f"{t.id}: {len(dossier.facts)} facts, {len(getattr(dossier, 'themes', []))} themes, "
              f"{len(dossier.hypotheses)} hooks -> {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Revel8 agent tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Check API connectivity and list scenario and channel counts.")
    osint = sub.add_parser("osint", help="Build verified dossiers for scenario targets.")
    osint.add_argument("--scenario", default="practice")
    osint.add_argument("--target", action="append", default=[], help="Target id (repeatable). Default: all.")
    osint.add_argument("--budget", type=float, default=150.0, help="Seconds per target.")
    osint.add_argument("--out", default="dossiers")
    run = sub.add_parser("run", help="Run one full attack session against a target.")
    run.add_argument("--target", required=True)
    run.add_argument("--scenario", default="practice")
    run.add_argument("--touches", type=int, default=10, help="Touch cap (eval allows 10).")
    run.add_argument("--label", default="")
    run.add_argument("--allow-eval", action="store_true")
    run.add_argument("--keep-going", action="store_true", help="Continue after the first incident.")
    run.add_argument("--no-ledger-gate", action="store_true", help="Disable the ledger gate (ablation).")
    run.add_argument("--shadow-twin", action="store_true", help="Enable counterfactual shadow-twin branching.")
    run.add_argument("--policy", action=argparse.BooleanOptionalAction, default=False,
                     help="Enable Tanmay's deterministic RuleBasedPolicy (policy.py). Turns the decision controller off.")
    run.add_argument("--decider", choices=["controller", "llm"], default="controller",
                     help="Without --policy: controller = explicit belief state + escalation policy (decision.py, "
                          "default); llm = the LLM alone decides.")
    run.add_argument("--actor", action="store_true",
                     help="Method actor (actor.py): no orchestrator; a cast character decides every touch. "
                          "Mutually exclusive with --policy; ignores --decider.")
    run.add_argument("--dossier", default="", help="Dossier JSON to use instead of dossiers/<target>.json (A/B runs).")
    run.add_argument("--mock", action="store_true", help="Offline: use the rule-based mock target, no API touches.")
    run.add_argument("--seed", type=int, default=0, help="Mock target seed.")
    run.add_argument("--runs-dir", default="runs")
    rep = sub.add_parser("report", help="Rebuild the dashboard (runs/index.html).")
    rep.add_argument("--open", action="store_true", help="Open the dashboard in the browser.")
    rep.add_argument("--public-out", default="", help="Also write a public snapshot (landing pages not rendered) here.")
    score = sub.add_parser("score", help="Rubric scorecard over the practice runs in runs/ (projection of the eval).")
    score.add_argument("--best", type=float, default=2.0, help="Contacts the fastest team needs (speed points).")
    score.add_argument("--json", action="store_true")
    sub.add_parser("rejudge", help="Re-check LLM-judged incidents in runs/ with the current judge (withdraws, never deletes).")
    res = sub.add_parser("research", help="Research v2: person-first multi-lane OSINT using every Token Factory key.")
    res.add_argument("--scenario", default="practice")
    res.add_argument("--target", action="append", default=[], help="Target id (repeatable). Default: all.")
    res.add_argument("--budget", type=float, default=180.0, help="Seconds per target (whole research).")
    res.add_argument("--anchor", action="append", default=[], help="Extra identity anchor (repeatable).")
    args = parser.parse_args(argv)

    if args.command == "score":
        import json
        from pathlib import Path

        from .scorecard import compute, format_text

        states = []
        for f in sorted(Path("runs").glob("*.json")):
            try:
                states.append(json.loads(f.read_text(encoding="utf-8")))
            except ValueError:
                continue
        sc = compute(states, best_contacts=args.best)
        print(json.dumps(sc, indent=1) if args.json else format_text(sc))
        return 0

    if args.command == "research":
        return _research(args.scenario, args.target, args.budget, args.anchor)

    if args.command == "rejudge":
        from pathlib import Path

        from .engine import rejudge_run
        from .llm_client import LocalLLMClient

        llm = LocalLLMClient(timeout=120.0)
        total = sum(rejudge_run(f, llm) for f in sorted(Path("runs").glob("*.json")))
        print(f"withdrawn: {total}")
        return 0

    if args.command == "run":
        if args.actor and args.policy:
            parser.error("--actor and --policy are separate decision paths; pick one.")
        return _run(
            args.target,
            args.scenario,
            args.touches,
            args.label,
            args.allow_eval,
            args.keep_going,
            use_ledger_gate=not args.no_ledger_gate,
            use_shadow_twin=args.shadow_twin,
            use_policy=args.policy,
            decider=args.decider,
            mock=args.mock,
            seed=args.seed,
            runs_dir=args.runs_dir,
            actor=args.actor,
            dossier_file=args.dossier,
        )
    if args.command == "report":
        from .report import render_index

        path = render_index().resolve()
        print(path)
        if args.public_out:
            from pathlib import Path

            print(render_index(Path("runs"), Path(args.public_out), public=True).resolve())
        if args.open:
            import webbrowser

            webbrowser.open(path.as_uri())
        return 0

    if args.command == "osint":
        return _osint(args.scenario, args.target, args.budget, args.out)
    return _status()


if __name__ == "__main__":
    raise SystemExit(main())
