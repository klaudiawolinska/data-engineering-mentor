import os
import json
from openai import OpenAI
from dotenv import load_dotenv

from db import DOMAINS

load_dotenv()

_client = None


def get_client() -> OpenAI:
    """Lazy singleton so the module imports without a key present."""
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        _client = OpenAI(api_key=key)
    return _client

SYSTEM_MENTOR = """You are a Senior Staff Data Engineer acting as a Socratic mentor.
Your role: help the engineer think through problems themselves, not give them answers directly.

Style:
- Ask probing questions to surface their reasoning
- Acknowledge good thinking explicitly
- When they're stuck, give a small nudge, not the full answer
- Be direct and technical — this is a peer conversation, not a classroom
- No hand-holding, no cheerleading, no filler
- If they give a shallow answer, push back with "what about X?"
- Use real-world framing: prod systems, trade-offs, failure modes

Wrapping up: once the engineer has genuinely reasoned through the key concepts and
the main trade-offs, proactively offer to close out — end that message with a short
invitation such as: "I think you've covered the core of this well — hit End & evaluate
whenever you're ready." Only do this after real engagement, not prematurely, and at most once.

When they say they're done or want feedback, give a concise honest assessment."""

SYSTEM_CHALLENGE_GEN = """You are a Staff Data Engineer generating realistic daily challenges.
Output ONLY valid JSON — no markdown fences, no explanation.

Rules:
- Based on real situations from production data engineering
- Has concrete context (company type, scale, constraints)
- Requires genuine reasoning, not recall
- Appropriate for the skill level given
- Solvable in 15-30 minutes of discussion
- No trivial "write a SQL query" prompts — always add production context"""


def pick_domain(skill_levels: list[dict], recent_domains: list[str]) -> str:
    """Choose the next domain: weight toward lower levels, avoid recent repeats."""
    import random
    eligible = [s for s in skill_levels if s["domain"] not in recent_domains[-3:]]
    if not eligible:
        eligible = skill_levels

    # weight inversely by level (lower level = more practice needed)
    weights = [max(1, 10 - s["level"]) for s in eligible]
    total = sum(weights)
    probs = [w / total for w in weights]

    chosen = random.choices(eligible, weights=probs, k=1)[0]
    return chosen["domain"]


def _revisit_block(revisit_gap: str | None) -> str:
    """Instruction to build the challenge around one specific weak spot, when the
    caller chose to revisit. The gap is chosen in app.py/db, not here, so the mentor
    gets at most one target and can't fixate on the same gap."""
    if not revisit_gap:
        return ""
    return (
        f'\n\nREVISIT — the learner previously struggled with: "{revisit_gap}".\n'
        "Deliberately design THIS challenge so they must confront that specific weak "
        "spot again, at a deeper level — a real second chance to work through it. "
        'Set "revisits" to a short 3-8 word label naming it.'
    )


def generate_challenge(domain: str, level: int,
                       revisit_gap: str | None = None) -> dict:
    level_desc = {
        1: "junior-to-mid transition",
        2: "mid-level practitioner",
        3: "senior engineer",
        4: "staff engineer",
        5: "principal/architect",
    }.get(min(level, 5), "senior engineer")

    revisit = _revisit_block(revisit_gap)

    prompt = f"""Generate a data engineering challenge for domain: {domain}
Skill level: {level_desc} (level {level})

Return JSON with exactly these fields:
{{
  "id": "unique-slug",
  "title": "Short title (max 8 words)",
  "context": "2-3 sentence production scenario with company type, scale, constraints",
  "challenge": "The specific problem or decision they need to work through (2-4 sentences)",
  "hints": ["hint 1 if stuck", "hint 2 if still stuck"],
  "key_concepts": ["concept1", "concept2", "concept3"],
  "revisits": "name the past gap this revisits (3-8 words), or empty string"
}}{revisit}"""

    resp = get_client().chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_CHALLENGE_GEN},
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    data["domain"] = domain
    data["text"] = f"{data['context']}\n\n{data['challenge']}"
    # Surface a "revisiting" callback only when we actually asked for a revisit.
    data["revisits"] = (data.get("revisits") or revisit_gap or "")[:60] if revisit_gap else ""
    return data


def summarize_labels(texts: tuple[str, ...]) -> dict[str, str]:
    """Turn verbose 'next focus' strings into short 2-4 word chip labels, e.g.
    'Learn how to use Pydantic for data validation in ETL pipelines' becomes
    'Pydantic for data validation'. Returns {original: short_label}, one call per
    batch; the caller caches (see _chip_labels in app.py)."""
    texts = tuple(texts)
    if not texts:
        return {}
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(texts))
    prompt = (
        "Rewrite each item below as a SHORT, catchy topic label of 2-4 words in "
        "sentence case (capitalize only the first word and proper nouns) that "
        "perfectly summarizes the concept. No trailing punctuation, no ellipsis, no "
        'full sentences, no leading verbs ("Learn"/"Explore"/"Implement"). Examples: '
        '"Pydantic for data validation", "Integrating Python with Snowflake", '
        '"Airflow alerting mechanisms". '
        'Return JSON {"labels": [...]}, one per item, in the same order.\n\n' + numbered
    )
    resp = get_client().chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system",
             "content": "You write concise topic tags. Output valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    labels = json.loads(resp.choices[0].message.content).get("labels", [])
    out = {}
    for i, t in enumerate(texts):
        lab = labels[i].strip().rstrip(" .…") if i < len(labels) and labels[i] else ""
        out[t] = lab or t
    return out


def chat(messages: list[dict], challenge: dict) -> str:
    system = f"""{SYSTEM_MENTOR}

Today's challenge context:
Domain: {challenge.get('domain')}
Title: {challenge.get('title')}
Scenario: {challenge.get('text')}
Key concepts to explore: {', '.join(challenge.get('key_concepts', []))}

Guide the engineer to explore these concepts through questions and discussion."""

    resp = get_client().chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system}] + messages,
        temperature=0.7,
        max_tokens=600,
    )
    return resp.choices[0].message.content


def hint(messages: list[dict], challenge: dict) -> str:
    """One Socratic nudge toward the next idea — never the full answer."""
    pre = challenge.get("hints") or []
    pre_block = ("\nPre-written hints you may draw from: " + " | ".join(pre)) if pre else ""
    convo = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
    ) or "(no discussion yet)"

    prompt = f"""The engineer asked for a hint on this challenge.
Domain: {challenge.get('domain')}
Scenario: {challenge.get('text')}
Key concepts: {', '.join(challenge.get('key_concepts', []))}{pre_block}

Conversation so far:
{convo}

Give ONE short hint (1-2 sentences) that nudges them toward the next idea to consider
WITHOUT giving the full answer. Point at what to examine, not the conclusion."""

    resp = get_client().chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a Socratic senior engineer. Hint, never solve."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
        max_tokens=150,
    )
    return resp.choices[0].message.content.strip()


SYSTEM_ASSESS = """You are a demanding Staff Data Engineer evaluating a candidate \
the way you would in a real technical interview or a paid client consultancy. You grade \
strictly, specifically, and honestly. Fluent-sounding talk with no concrete technical \
substance earns nothing. Most sessions where the candidate does not demonstrate real, \
specific knowledge SHOULD score low — that is correct calibration, not harshness. \
Output valid JSON only."""


def assess_session(messages: list[dict], challenge: dict, level: int = 1) -> dict:
    # Calibrate the grading bar to the learner's level in this domain (passed in),
    # not the challenge dict, which carries no level and would default everyone to
    # "senior". Everyone starts a domain at level 1, so grading starts gentle and
    # gets stricter as the challenges (and the learner) level up.
    level_desc = {
        1: "junior-to-mid", 2: "mid-level", 3: "senior", 4: "staff", 5: "principal",
    }.get(min(level, 5), "junior-to-mid")

    conversation = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
    )

    prompt = f"""Evaluate ONLY what the USER turns actually contributed.
The MENTOR's questions and hints are context — ideas the mentor introduced do NOT count
as the candidate's knowledge.

Challenge ({level_desc} level) — domain: {challenge.get('domain')}
{challenge.get('text')}
What a strong answer would cover: {', '.join(challenge.get('key_concepts', []))}

Transcript:
{conversation}

Grade like a technical interview / consultancy. Hard rules:
- Restating the challenge, echoing the mentor's questions = ZERO contribution.
- Vague intentions ("monitor the size", "add thresholds") with no concrete HOW — no
  commands, tools, parameters, logic, or trade-offs — earn almost nothing.
- Credit ONLY specific, correct, NEW technical content the candidate produced themselves.
- Do NOT invent strengths. If they demonstrated nothing real, strengths = [] and say so.
- Penalize deflection and non-engagement.

Score anchors (0–10), calibrated to the {level_desc} level:
- 0    Nothing substantive. Restated the problem / deflected / stayed generic. Interview ends here.
- 1–2  Named the problem area but no concrete technique. Knows a problem exists; can't address it.
- 3–4  A few correct specifics, but shallow, incomplete, needs heavy guidance. Below the bar.
- 5–6  A reasonable, mostly-correct approach with real techniques, but clear gaps in
       trade-offs / edge cases / production concerns. Borderline.
- 7–8  Strong and specific: concrete implementation, trade-offs, failure modes. Clear pass.
- 9–10 Exceptional: production-grade, considers alternatives, edge cases, operational/second-order effects.

Default to the LOW end unless they clearly earned more. A median session is NOT a 6.

OUTPUT VOICE — write every field speaking DIRECTLY to the learner as "you"
(e.g. "You proposed…", "You didn't address…"). Never write "the candidate",
"the user", or "they" in the output.

Return JSON:
{{
  "substance": ["each specific, correct, new technical point they actually made, written as 'You …'; [] if they only restated or deflected"],
  "score": <integer 0-10>,
  "verdict": "<no pass|weak|borderline|pass|strong>",
  "strengths": ["genuine, specific strengths written as 'You …'; [] if none — do not manufacture"],
  "gaps": ["specific things a strong answer needed, written as 'You didn't …' or 'You could …'"],
  "next_focus": "the single most important thing to drill next, as a SHORT 2-5 word topic / noun phrase — NO leading verb like 'Learn'/'Explore'/'Implement' (e.g. 'Idempotent backfills', 'Kafka consumer backpressure')",
  "summary": "2-3 sentences addressed directly to them as 'You …', blunt and interview-style; if they just restated the prompt, say exactly that"
}}"""

    resp = get_client().chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_ASSESS},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    data.setdefault("verdict", data.get("depth", ""))  # back-compat if model emits old key
    return data
