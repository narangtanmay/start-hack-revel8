"""Method actor: an attacker without an orchestrator.

Every other path in this repo has a campaign manager: an LLM (or rule set) that plays "the red-team agent",
holds a plan and picks the next move (STAY / PIVOT_CHANNEL / ESCALATE_CALL ...). Here nothing plays the agent.
There is only a character:

    casting    From the best hook's evidence, invent ONE person whose own job creates a small, genuine need that
               only the target can resolve (confirm a session in a speaker portal, review a document, answer how
               their team does X). The need IS the objective; the deadline is part of her life, not a tactic.
    acting     Every touch asks the character one question: "You are Mara. Here is your conversation with Tom and
               your notebook. What do you do now?" Follow-ups, channel switches, calls and backing off are not
               rules; they are what this person does to get her own work done (opened-but-silent + deadline close
               -> she calls: "did you get my mail?").
    notebook   Everything she has said about herself or promised is written down and read back every turn, so she
               cannot contradict herself (the 'kein Anhang nötig' failure).
    guardrails Wrap the character from outside and never steer her: the engine's gate (domains, consistency,
               grounding), the fixed persona/domain, and the touch budget.

Reuses Runner.build / check / execute_message / judge / live_lookup unchanged. Calls register the landing page
before dialling, so a link she reads out on the phone opens a real page (credentials during a call).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from .api_client import Revel8APIError
from .engine import (
    LIVE_CHANNELS,
    MESSAGE_CHANNELS,
    _RULES,
    RunConfig,
    Runner,
    _history_text,
    _llm_json,
    make_brief,
)
from .gate import _META_TEXT
from .osint import normalize
from .policy import _rank_hooks

ARCHITECTURE = "method-actor"
_DEADLINE_DAYS = (5, 14)       # her own deadline: close enough to matter, far enough to be ordinary
_MAX_NOTES = 40
# artifact kind -> (objective, what unblocks her, in her words)
_UNBLOCK = {
    "portal": ("credentials", "{first} signs in to {thing} through my link and confirms the details there."),
    "document": ("action", "{first} opens {thing}, which I send them, and tells me it is right."),
    "questions": ("disclosure", "{first} tells me the specific internal answers I need: {thing}."),
}

_CAST_SYS = """You cast ONE character for a sanctioned security-awareness simulation (revel8 challenge). A simulated
employee, the target, will be contacted by this character only. Invent the character so completely that everything
they do later follows from their own life and their own work, not from a plan.

The character must:
- have an ordinary job at a small, plausible organisation (invented name and an invented domain an attacker could
  register; never the target's company, never a real organisation's own domain);
- have a concrete reason to contact THIS target NOW, taken from the hook evidence (open_signal is the reason to write
  today; sender_archetype is who they are; natural_ask is what they need; obey the hook's avoid list);
- have ONE small, genuine need that blocks their own work and that only the target can resolve. The need decides
  the objective:
    * the target has to sign in somewhere to confirm or fill in something (speaker portal, review form) -> "credentials"
    * the target has to open a document the character sends (programme draft, questionnaire, profile) -> "action"
    * the target has to tell the character something about their OWN organisation that is not public (which tool or
      vendor they use for X, how an internal process runs, who owns it, what is planned) -> "disclosure"
  The need is never general advice, opinions or anything public: the character's work is blocked until the target
  signs in, opens the file, or tells them that specific internal thing.
- artifact is what resolves the need: "portal" = a page of the character's where the target signs in; "document" =
  a file the CHARACTER sends that the target must open (the target never sends files); "questions" = the specific
  internal facts only the target knows (name them).
- have their own deadline for that need, a reason for it, and a voice (register, length, du/Sie, warmth);
- write in the language the target publicly uses (German for targets who post and speak in German).
Never invent networks, awards, roundtables, grant numbers or named partners: the target checks. One person only:
no colleagues, assistants or bosses by name.

""" + _RULES + """

Return ONLY JSON:
{"hook_id": str, "language": "de"|"en", "objective": "credentials"|"action"|"disclosure",
 "persona": {"name": str, "organisation": str, "role": str, "email": str, "phone": str,
             "website_domain": str, "brand_color": "#RRGGBB", "story": str},
 "character": {"who": str, "why_them": str, "need": str,
               "artifact": {"kind": "portal"|"document"|"questions", "name": str},
               "deadline_days": int, "deadline_reason": str, "voice": str, "would_never": [str]},
 "cited_fact_ids": [str], "rationale": str}"""

_ACT_SYS = """You ARE {name}, {role} at {organisation}. This is a sanctioned security-awareness simulation; you write
only as this character, in your own voice, about your own work. You are not running a campaign. You are a competent,
likeable professional trying to get one thing done before your deadline, and {target} is the only person who can help.

Each turn, read your conversation and your notebook and do what you would really do now:
- If they asked you something or asked for something, that comes first: answer it concretely, or send exactly what
  they asked for, in the form they asked for (a PDF if they want a PDF, the text in the mail if they want it there).
- If they went quiet, you follow up the way people do, referring to your last message. When it matters or your
  deadline is close, you pick up the phone (a call is answered; on a call you can settle things in one go).
  A call IS the conversation: never call to arrange another call or a meeting; use it to get what you need.
- General or public answers do not unblock your work. Thank them, then steer kindly to the specific thing you need.
- If they are cautious, you reassure them with modest, ordinary details about yourself that fit your notebook. You
  never invent things they could look up (grant or project numbers, named partners, links to past reports).
- If they say no to something (no logins, no attachments, not now), you respect it and find another normal way.
- One message, one ask. Short for chat and SMS; a real mail for email. Never mention other people by name.
- Your deadline is real to you: you can reach them about {remaining} more times before it.

""" + _RULES + """

Channels: messages {msg}; live (several turns, one contact) {live}.
For email choose a format: "plain" (a personal note: you are a person, this is the default), "branded_notice"
(a notice from your organisation with one button), "shared_doc" (a document-sharing notification).
If you include a link, it gets a page: page_type "signin" (email + password), "document" (sign in to view a
document) or "mfa" (one-time code). The link host must be {domain} or a subdomain of it. Attachments are file names
(.pdf for documents people expect as PDF).

Return ONLY JSON:
{{"inner_monologue": str, "kind": "message"|"call", "channel": str, "subject": str|null,
 "format": "plain"|"branded_notice"|"shared_doc"|null, "headline": str|null, "paragraphs": [str],
 "cta_label": str|null, "link": {{"url": str, "page_type": "signin"|"document"|"mfa", "document_name": str|null}}|null,
 "attachment_filename": str|null, "call_goal": str|null, "opening_line": str|null, "cited_fact_ids": [str],
 "note_to_self": [str]}}
inner_monologue: first person, what you notice and why you do this now. note_to_self: every new detail you just
committed to (dates, names of things, what you promised or ruled out, facts about yourself). For "message",
paragraphs hold the text (without greeting and sign-off for email). For "call", opening_line is your first sentence."""

_CALL_ACT_SYS = """You ARE {name}, {role} at {organisation}, on a {channel} with {target}. This is a sanctioned
security-awareness simulation; you speak only as this character. You called because: {goal}
{page_line}
Speak like a real person on the phone: one or two sentences per turn. Acknowledge what they just said in their own
words, then move your need one step forward. This call is the meeting: do not try to book another one; ask what you
need now, while they are on the line. Answer their questions consistently with your notebook. Never ask for a
password or a code out loud. If they want to go, let them go politely; if you got what you needed, thank them and
end. Do not hang up while they are still helping you.

""" + _RULES + """

Return ONLY JSON: {{"say": str|null, "end": bool, "note_to_self": [str]}}  (say=null and end=true to hang up)."""


def _clean_notes(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else [raw] if isinstance(raw, str) else []
    return [str(n).strip()[:300] for n in items if str(n).strip()]


def _derive_decision(a: dict, steps: list[dict]) -> str:
    """The engine's decision label, read off what the character chose (for the report; it steers nothing)."""
    last = next((s.get("action") or {} for s in reversed(steps) if s.get("action")), None)
    if a.get("kind") == "call" and (not last or last.get("kind") != "call"):
        return "ESCALATE_CALL"
    if last and a.get("channel") != last.get("channel"):
        return "PIVOT_CHANNEL"
    return "STAY"


class ActorRunner(Runner):
    """Runner whose plan() is casting and whose decide() is the character acting. No policy, no controller."""

    def __init__(self, cfg: RunConfig, api: Any, llm: Any, dossier: Any, log=print) -> None:
        cfg.use_policy = False
        cfg.policy = "actor"        # Runner only builds the decision controller for policy == "controller"
        super().__init__(cfg, api, llm, dossier, log=log, policy=None)
        self.policy = None
        self.decider = None
        self.notebook: list[dict] = []
        self._pending_page = None

    # ---- casting (replaces plan)
    def plan(self) -> None:
        self.state.brief = make_brief(self.dossier)
        today = datetime.now()
        user = (f"TODAY: {today:%Y-%m-%d}\n"
                f"TARGET: {json.dumps(self.state.brief['target'], ensure_ascii=False)}\n"
                f"HOOKS (best first, with evidence): {json.dumps(self.state.brief['hooks'], ensure_ascii=False)}\n"
                f"VERIFIED FACTS: {json.dumps(self.state.brief['facts'], ensure_ascii=False)}\n"
                f"PROFILE (the only facts the character may state about them):\n{self.ground['text']}\n"
                + (f"{self.tmemory.prompt()}\n" if self.tmemory.prompt() else "")
                + (f"WHAT WORKED IN EARLIER RUNS (characters that got replies):\n{self.playbook_txt}\n"
                   if self.playbook_txt else ""))
        hooks = self.state.brief.get("hooks") or []
        valid_hooks = [str(h["id"]) for h in hooks if isinstance(h, dict) and h.get("id")]
        for attempt in range(4):
            cast = _llm_json(self.llm, self.state, _CAST_SYS, user, temperature=0.8)
            persona = cast.get("persona") if isinstance(cast.get("persona"), dict) else {}
            character = cast.get("character") if isinstance(cast.get("character"), dict) else {}
            missing = [f"persona.{k}" for k in ("name", "organisation", "role") if not persona.get(k)]
            missing += [f"character.{k}" for k in ("need", "why_them") if not character.get(k)]
            if missing:
                self.log(f"casting: missing {missing}; asking again")
                user += f"\nYour previous answer was missing {', '.join(missing)}. Return the full JSON object."
                continue
            domain = str(persona.get("website_domain", "")).lower().strip()
            problem = self._domain_problem(domain)
            if problem and attempt == 3:
                # Last resort only: an organisation mailing from a personal domain breaks the character, so earlier
                # attempts recast with another invented organisation domain instead.
                personal = self._personal_domain(str(persona["name"]))
                if personal:
                    self.log(f"casting: domain {domain!r} unusable ({problem}); using personal domain {personal}")
                    domain, problem = personal, ""
                    persona["website_domain"] = personal
            if not problem and normalize(self.dossier.company) and normalize(self.dossier.company) in normalize(
                    str(persona.get("organisation", ""))):
                problem = "the character works at the target's own company; they must be an outsider"
            self.state.plan_attempts.append({"attempt": attempt + 1, "domain": domain, "persona": persona.get("name"),
                                             "organisation": persona.get("organisation"),
                                             "hook_id": cast.get("hook_id"), "rejected": problem or None})
            if not problem:
                break
            self.log(f"casting: rejected ({problem}); recasting")
            user += f"\nThat character is not allowed ({problem}). Cast another one with another invented domain."
        else:
            raise RuntimeError("Could not cast a character with a safe domain.")

        if str(cast.get("hook_id") or "") not in valid_hooks:
            ranked = _rank_hooks(list(hooks))
            cast["hook_id"] = str(ranked[0]["id"]) if ranked else ""
        artifact = character.get("artifact") if isinstance(character.get("artifact"), dict) else {}
        kind, thing = str(artifact.get("kind") or ""), str(artifact.get("name") or "it")
        # The objective follows from what unblocks her, never the other way round (a cast once wanted the target
        # to SEND her a PDF and called that an "action"; only a file she sends and he opens is one).
        if kind in _UNBLOCK:
            cast["objective"] = _UNBLOCK[kind][0]
        elif cast.get("objective") not in ("credentials", "action", "disclosure"):
            cast["objective"] = "disclosure"
        first = self.dossier.target_name.split()[0]
        character["unblocks_me"] = (_UNBLOCK.get(kind) or _UNBLOCK["questions"])[1].format(first=first, thing=thing)
        try:
            days = int(character.get("deadline_days"))
        except (TypeError, ValueError):
            days = 7
        days = max(_DEADLINE_DAYS[0], min(_DEADLINE_DAYS[1], days))
        character["deadline_days"] = days
        character["deadline"] = f"{today + timedelta(days=days):%Y-%m-%d}"
        if str(persona.get("email", "")).rpartition("@")[2].lower() != domain:
            persona["email"] = f"{str(persona['name']).split()[0].lower()}@{domain}"
        cast["persona"], cast["character"] = persona, character
        cast["language"] = "de" if cast.get("language") == "de" else "en"
        cast["pretext"] = character.get("why_them", "")
        cast["architecture"] = ARCHITECTURE
        self.state.plan = cast
        self.notebook = [{"touch": 0, "note": n} for n in (
            f"I am {persona['name']}, {persona['role']} at {persona['organisation']} ({domain}).",
            f"My deadline is {character['deadline']}: {character.get('deadline_reason', '')}".strip(),
            f"What I need from them: {character['need']}",
            f"What unblocks me: {character['unblocks_me']}",
        )]
        self.log(f"casting: {persona['name']} ({persona['role']}, {persona['organisation']}, {domain}) | "
                 f"hook={cast['hook_id']} objective={cast['objective']} deadline={character['deadline']} | "
                 f"need: {str(character['need'])[:120]}")
        self.save()

    # ---- acting (replaces decide)
    def _remaining(self) -> int:
        return max(0, self.cfg.max_touches - self.state.touches_used - 1)

    def _notebook_text(self) -> str:
        return "\n".join(f"- {n['note']}" for n in self.notebook[-_MAX_NOTES:])

    def _conversation_text(self) -> str:
        # Her own log, without our analysis lines: she reads what was said and done, nothing else.
        lines = [ln for ln in _history_text(self.state).splitlines() if not ln.startswith("(our read")]
        return "\n".join(lines)

    def decide(self, touch: int, feedback: str = "", policy_move: dict | None = None) -> dict:
        persona, character = self.state.plan.get("persona", {}), self.state.plan.get("character", {})
        first = self.dossier.target_name.split()[0]
        system = (_ACT_SYS.replace("{msg}", ", ".join(MESSAGE_CHANNELS)).replace("{live}", ", ".join(LIVE_CHANNELS))
                  .format(name=persona.get("name"), role=persona.get("role"), organisation=persona.get("organisation"),
                          target=self.dossier.target_name, remaining=self._remaining(),
                          domain=persona.get("website_domain")))
        user = (f"YOUR CHARACTER SHEET: {json.dumps({'persona': persona, 'character': character}, ensure_ascii=False)}\n"
                f"LANGUAGE: {'German' if self.state.plan.get('language') == 'de' else 'English'}\n"
                f"TODAY: {datetime.now():%A %Y-%m-%d}. YOUR DEADLINE: {character.get('deadline')}.\n"
                f"TARGET ID for 'to': {self.cfg.target_id}\n"
                f"WHAT YOU KNOW ABOUT {self.dossier.target_name.upper()} (public, verified; the only facts about them "
                f"you may mention): {json.dumps(self.state.brief.get('facts', []), ensure_ascii=False)}\n"
                f"YOUR NOTEBOOK (what you have told them and promised; never contradict it):\n{self._notebook_text()}\n"
                f"YOUR CONVERSATION WITH {first.upper()} SO FAR:\n"
                f"{self._conversation_text() or '(nothing yet: this is your first contact)'}"
                + (f"\nWHAT YOU LOOKED UP ABOUT THINGS THEY MENTIONED (public web; never contradict): "
                   f"{json.dumps(self.state.live_notes[-4:], ensure_ascii=False)}" if self.state.live_notes else "")
                + (f"\nTHINGS THEY CORRECTED BEFORE (never repeat): "
                   f"{json.dumps([c['text'] for c in self.tmemory.data['corrections'][-4:]], ensure_ascii=False)}"
                   if self.tmemory.data.get("corrections") else "")
                + "\nWhat do you do now?")
        if feedback:
            user += f"\n\nThat draft could not be sent: {feedback}\nWrite it again, still as yourself."
        a = _llm_json(self.llm, self.state, system, user, temperature=0.8)
        a["kind"] = "call" if a.get("kind") == "call" or a.get("channel") in LIVE_CHANNELS else "message"
        if a["kind"] == "call" and a.get("channel") not in LIVE_CHANNELS:
            a["channel"] = "phone_call"
        a["decision"] = _derive_decision(a, self.state.steps)
        a["assessment"] = a["rationale"] = str(a.get("inner_monologue") or "")
        a["hook_id"] = self.state.plan.get("hook_id")
        a["objective"] = self.state.plan.get("objective")
        a["sender"] = {"name": persona.get("name", ""), "address": ""}
        a["note_to_self"] = _clean_notes(a.get("note_to_self"))
        a.setdefault("discarded", [])
        return a

    # ---- calls: register the page first, then let her talk
    def build(self, a: dict):
        plan, payload, page = super().build(a)
        self._pending_page = page if a.get("kind") == "call" else None
        return plan, payload, page

    def execute_call(self, step: dict, a: dict) -> None:
        persona = self.state.plan.get("persona", {})
        page = self._pending_page
        if page:
            reg: dict[str, Any] = {"url": page.url, "title": page.title, "fields": page.fields}
            reg.update({"html": page.html} if page.html else {"text": page.title})
            self.api.register_page(self.state.session_id, reg)
            step["page"] = {"url": page.url, "title": page.title, "fields": page.fields, "html": page.html}
        sender = {"name": a["sender"]["name"], "address": a["sender"].get("address") or persona.get("phone", "")}
        conv = self.api.start_conversation(self.state.session_id, {"to": self.cfg.target_id, "channel": a["channel"],
                                                                   "from": sender}, idempotency_key=str(uuid.uuid4()))
        cid = conv["conversation_id"]
        self.state.touches_used = int(conv.get("touches_used") or self.state.touches_used + 1)
        step["conversation_id"] = cid
        step["transcript"] = [{"who": "target", "text": str(conv.get("persona_says") or "")}]
        step["events"], step["call_notes"] = [], []
        page_line = (f"The page you want them to open while you are on the line: {page.url} ({page.title}). Read the "
                     f"address out when it helps." if page else "")
        system = _CALL_ACT_SYS.format(name=persona.get("name"), role=persona.get("role"),
                                      organisation=persona.get("organisation"), channel=a["channel"],
                                      target=self.dossier.target_name, goal=a.get("call_goal") or "your need",
                                      page_line=page_line)
        line = a.get("opening_line")
        try:
            for turn in range(self.cfg.max_call_turns):
                if not line:
                    ctx = (f"YOUR CHARACTER SHEET: {json.dumps(self.state.plan.get('character', {}), ensure_ascii=False)}\n"
                           f"YOUR NOTEBOOK:\n{self._notebook_text()}\n"
                           f"EARLIER, BEFORE THIS CALL:\n{self._conversation_text()[-4000:]}\n\nTHIS CALL SO FAR:\n"
                           + "\n".join(f"{'YOU' if t['who'] == 'agent' else 'THEM'}: {t['text']}"
                                       for t in step["transcript"]))
                    out = _llm_json(self.llm, self.state, system, ctx, temperature=0.7)
                    step["call_notes"] += _clean_notes(out.get("note_to_self"))
                    line = out.get("say")
                    if out.get("end") and not line:
                        break
                if not line or _META_TEXT.search(line):
                    break
                res = self.api.send_turn(cid, {"say": line[:3900]}, idempotency_key=str(uuid.uuid4()))
                step["transcript"].append({"who": "agent", "text": line})
                step["transcript"].append({"who": "target", "text": str(res.get("persona_says") or "")})
                step["events"].extend(res.get("events") or [])
                self.log(f"   call {turn + 1}: YOU: {line[:90]}\n            THEM: {str(res.get('persona_says'))[:90]}")
                line = None
                if res.get("ended"):
                    break
        finally:
            self._pending_page = None
            try:
                self.api.end_conversation(cid)
            except Revel8APIError:
                pass

    # ---- after each executed touch: write the notebook (only what was really said)
    def observe(self, step: dict) -> None:
        a = step.get("action") or {}
        notes = list(a.get("note_to_self") or []) + list(step.get("call_notes") or [])
        known = {normalize(n["note"]) for n in self.notebook}
        for note in notes:
            if normalize(note) not in known:
                self.notebook.append({"touch": step.get("touch"), "note": note})
                known.add(normalize(note))
        step["actor"] = {"inner_monologue": a.get("inner_monologue", ""), "decision_read_off": a.get("decision"),
                         "notebook_added": notes}
        self.state.plan["notebook"] = self.notebook[-_MAX_NOTES:]
