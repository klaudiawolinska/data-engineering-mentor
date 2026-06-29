import json
import hashlib
import colorsys
import random
import streamlit as st
from datetime import date

import db
import ai
from achievements import check_and_grant, ACHIEVEMENTS

st.set_page_config(
    page_title="DE Mentor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Theme / CSS

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

/* Base typography */
html, body, [class*="css"], .stMarkdown, p, span, div, label, input, textarea, button {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}
h1, h2, h3, h4 {
    font-family: 'Poppins', sans-serif !important;
    font-weight: 800 !important;
    letter-spacing: -0.02em !important;
    color: #15161A !important;
}

.stApp { background: #FFFFFF; }

/* Primary buttons -> violet */
.stButton > button[kind="primary"] {
    background: #7C3AED;
    color: #FFFFFF;
    font-family: 'Poppins', sans-serif;
    font-weight: 700;
    border: none;
    border-radius: 12px;
    padding: 0.55rem 1.1rem;
    box-shadow: 0 4px 14px rgba(124,58,237,0.28);
    transition: all .15s ease;
}
.stButton > button[kind="primary"]:hover {
    background: #6D28D9;
    color: #FFFFFF;
    transform: translateY(-1px);
    box-shadow: 0 6px 20px rgba(124,58,237,0.40);
}

/* Secondary buttons -> soft pill */
.stButton > button[kind="secondary"] {
    background: #F5F3FA;
    color: #15161A;
    border: 1.5px solid #E6ECF5;
    border-radius: 12px;
    font-weight: 600;
    transition: all .15s ease;
}
.stButton > button[kind="secondary"]:hover {
    border-color: #7C3AED;
    color: #7C3AED;
    background: #FFFFFF;
}

/* Inputs */
.stTextInput input, .stChatInput textarea { border-radius: 10px !important; }
[data-baseweb="select"] > div { border-radius: 10px !important; }

/* Metrics -> pastel card */
[data-testid="stMetric"] {
    background: #F5F3FA;
    border: 1px solid #EAF0F8;
    border-radius: 14px;
    padding: 12px 16px;
}
[data-testid="stMetricValue"] { font-family: 'Poppins', sans-serif; font-weight: 700; }

/* Alerts / expanders / chat -> rounded */
[data-testid="stAlert"], .stAlert { border-radius: 14px; }
[data-testid="stExpander"] { border-radius: 12px; border: 1px solid #EAF0F8; }
[data-testid="stChatMessage"] { border-radius: 14px; }

/* Sidebar */
[data-testid="stSidebar"] { background: #FBFCFE; border-right: 1px solid #EEF2F7; }
[data-testid="stSidebar"] h2 { font-size: 1.15rem; }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

# Init

db.init_db()


def init_state():
    defaults = {
        "user_id": None,
        "user_name": None,
        "session_id": None,
        "challenge": None,
        "messages": [],
        "session_done": False,
        "assessment": None,
        "new_achievements": [],
        "force_new": False,  # force the generator even if today is already done
        "view": "home",  # home | session | history | skills
        "last_revisit": None,  # last weak spot revisited, to avoid back-to-back repeats
        "rematch_bonus": 0,  # bonus XP from the most recent cleared rematch
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


# Helpers

def xp_for_score(score: int) -> int:
    # A non-answer (0–2) earns nothing; real contributions scale with the score.
    return 0 if score < 3 else score * 10


def level_label(level: int) -> str:
    labels = {1: "Novice", 2: "Practitioner", 3: "Expert", 4: "Staff", 5: "Principal"}
    return labels.get(min(level, 5), "Principal")


@st.cache_data(show_spinner=False)
def _chip_labels(texts: tuple) -> dict:
    """Map each weak-spot text to a short chip label via the LLM, cached by the set
    of texts so it runs once per distinct set rather than on every rerun."""
    return ai.summarize_labels(texts)


def domain_color(domain: str) -> str:
    """A stable, distinct color per domain, hashed from its name into the red-green
    and purple-pink hue ranges (skipping blues) so nothing reads as blue."""
    h = int(hashlib.md5(domain.encode()).hexdigest(), 16)
    arcs = [(0, 165), (285, 345)]
    span = sum(hi - lo for lo, hi in arcs)
    x = h % span
    hue = arcs[0][0]
    for lo, hi in arcs:
        if x < hi - lo:
            hue = lo + x
            break
        x -= (hi - lo)
    sat = 0.60 + ((h >> 8) % 18) / 100.0      # 0.60–0.77
    light = 0.52 + ((h >> 16) % 10) / 100.0   # 0.52–0.61
    r, g, b = colorsys.hls_to_rgb(hue / 360.0, light, sat)
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


# Sidebar

with st.sidebar:
    st.markdown("## ⚡ Data Engineering Mentor")

    if not st.session_state.user_id:
        # A form so pressing Enter in the field submits, same as clicking Start.
        with st.form("login_form", clear_on_submit=False, border=False):
            st.markdown("**Who are you?**")
            name = st.text_input("Your name", placeholder="e.g. Alex", label_visibility="collapsed")
            submitted = st.form_submit_button("Start", use_container_width=True, type="primary")
        if submitted and name.strip():
            uid = db.get_or_create_user(name.strip())
            st.session_state.user_id = uid
            st.session_state.user_name = name.strip()
            st.rerun()
    else:
        uid = st.session_state.user_id
        streak = db.get_streak(uid)
        current = streak.get("current_streak", 0)
        longest = streak.get("longest_streak", 0)

        st.markdown(f"**{st.session_state.user_name}**")

        col1, col2 = st.columns(2)
        col1.metric("Streak", f"{current}d")
        col2.metric("Best", f"{longest}d")

        st.divider()

        nav_items = [
            ("🏠 Home", "home"),
            ("💬 Session", "session"),
            ("◈  Skills", "skills"),
            ("◎  History", "history"),
        ]
        for label, view in nav_items:
            is_active = st.session_state.view == view
            if st.button(
                label,
                use_container_width=True,
                type="primary" if is_active else "secondary",
                key=f"nav_{view}",
            ):
                st.session_state.view = view
                st.rerun()

        st.divider()

        unlocked = db.get_achievements(uid)
        if unlocked:
            st.markdown("**Achievements**")
            for key in unlocked[-5:]:
                a = ACHIEVEMENTS.get(key, {})
                st.markdown(f"{a.get('icon','◎')} {a.get('title','')}")

        st.divider()
        if st.button("🔁 Switch user", key="logout", use_container_width=True, type="secondary"):
            # Clear identity + any in-progress session, then return to the login screen.
            for k in ("user_id", "user_name", "session_id", "challenge", "messages",
                      "session_done", "assessment", "new_achievements", "force_new",
                      "suggested_domain", "domain_choice", "last_revisit",
                      "rematch_bonus", "challenge_mode", "rematch_pick"):
                st.session_state.pop(k, None)
            st.session_state.view = "home"
            st.rerun()


# Require login

if not st.session_state.user_id:
    hero = """
<div style="max-width:1000px;">
  <div style="font-family:'Poppins',sans-serif;font-weight:800;font-size:3.2rem;
              line-height:1.06;letter-spacing:-0.03em;color:#15161A;">
    Data Engineering
    <span style="position:relative;white-space:nowrap;">Mentor<svg width="100%" height="16"
        viewBox="0 0 320 16" preserveAspectRatio="none"
        style="position:absolute;left:0;bottom:-9px;overflow:visible;">
        <path d="M5 10 C 90 3, 200 3, 315 8" stroke="#7C3AED" stroke-width="7"
              fill="none" stroke-linecap="round"/></svg></span>
  </div>
  <p style="font-size:1.12rem;color:#3A4049;max-width:680px;margin-top:24px;line-height:1.55;">
    A daily practice environment for data engineers at every level.
    <strong>Not a course. Not a tutorial. A sparring partner</strong> that hands you
    realistic challenges and pushes your thinking.
  </p>
</div>
"""
    features = [
        ("#E5F6ED", "#C3EAD5", "⚡", "Daily Challenge",
         "Realistic scenarios, sized to your level."),
        ("#FDF3D6", "#F8E5A6", "💬", "Socratic Mentor",
         "An AI mentor that asks, nudges and pushes back — never hands you the answer."),
        ("#FCE0EE", "#F6C6DF", "◈", "Skill Tree",
         f"Progress across {len(ai.DOMAINS)} domains. Tracks real depth, not clicks."),
        ("#EDE7FB", "#DDD2F6", "🔥", "Streaks",
         "Show up daily. Build the habit and keep the streak alive."),
    ]
    cards = "".join(
        f'<div style="background:{bg};border-radius:18px;padding:20px;">'
        f'<div style="width:46px;height:46px;border-radius:50%;background:{circle};'
        f'display:flex;align-items:center;justify-content:center;font-size:22px;">{icon}</div>'
        f'<div style="font-family:Poppins,sans-serif;font-weight:700;font-size:1.05rem;'
        f'color:#15161A;margin-top:14px;">{title}</div>'
        f'<div style="font-size:0.86rem;color:#41474F;margin-top:6px;line-height:1.45;">{desc}</div>'
        f'</div>'
        for bg, circle, icon, title, desc in features
    )
    grid = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));'
        f'gap:16px;margin-top:34px;max-width:1000px;">{cards}</div>'
    )
    footer = (
        '<p style="margin-top:30px;color:#7C3AED;font-weight:600;font-size:1rem;">'
        '→ Enter your name in the sidebar to begin.</p>'
    )
    st.markdown(hero + grid + footer, unsafe_allow_html=True)
    st.stop()

uid = st.session_state.user_id
view = st.session_state.view


# New achievement toast

if st.session_state.new_achievements:
    for key in st.session_state.new_achievements:
        a = ACHIEVEMENTS.get(key, {})
        st.toast(f"{a.get('icon','')} **{a.get('title','')}** — {a.get('desc','')}",
                 icon=":material/military_tech:")
    st.session_state.new_achievements = []


# Home view

if view == "home":
    today_session = db.get_today_session(uid)
    force_new = st.session_state.force_new

    if today_session and today_session["completed"] and not force_new:
        # Already done today
        assessment = json.loads(today_session["assessment"]) if today_session["assessment"] else {}
        st.markdown(f"## Today's session — complete")
        st.markdown(f"**{today_session['domain']} · {today_session['challenge_title']}**")

        col1, col2, col3 = st.columns(3)
        col1.metric("Score", f"{today_session['score']}/10")
        col2.metric("Verdict", assessment.get("verdict", "—").title())
        col3.metric("XP earned", f"+{xp_for_score(today_session['score'])}")

        if assessment.get("summary"):
            st.info(assessment["summary"])

        if assessment.get("next_focus"):
            st.markdown(f"**Next focus:** {assessment['next_focus']}")

        if st.button("Practice another topic today", type="secondary"):
            st.session_state.force_new = True
            st.rerun()

    elif today_session and not today_session["completed"] and not force_new:
        # Resume
        st.markdown(f"## Resume today's session")
        st.markdown(f"**{today_session['domain']} · {today_session['challenge_title']}**")
        st.caption(today_session["challenge_text"])

        if st.button("Continue session →", type="primary", use_container_width=True):
            st.session_state.session_id = today_session["id"]
            # Rehydrate the full challenge from stored JSON so resume keeps
            # key_concepts, hints and revisits. Fall back to the flat columns for
            # sessions saved before challenge_json existed.
            cj = today_session.get("challenge_json")
            if cj:
                st.session_state.challenge = json.loads(cj)
            else:
                st.session_state.challenge = {
                    "id": today_session["challenge_id"],
                    "title": today_session["challenge_title"],
                    "text": today_session["challenge_text"],
                    "domain": today_session["domain"],
                    "key_concepts": [],
                }
            msgs = json.loads(today_session["messages"]) if today_session["messages"] else []
            st.session_state.messages = msgs
            st.session_state.view = "session"
            st.rerun()

    else:
        # Fresh start
        st.markdown("## Ready for today's challenge?")

        skills = db.get_skill_levels(uid)
        recent = db.get_recent_sessions(uid, limit=5)
        recent_domains = [s["domain"] for s in recent]

        # pick_domain() is random, so compute it once and keep it stable across
        # reruns; otherwise Generate re-rolls and starts a different domain than shown.
        if st.session_state.get("suggested_domain") is None:
            st.session_state.suggested_domain = ai.pick_domain(skills, recent_domains)
        suggested_domain = st.session_state.suggested_domain

        st.markdown(f"**Suggested domain:** `{suggested_domain}`")

        all_domains = sorted(ai.DOMAINS)
        choice = st.selectbox(
            "Domain",
            options=all_domains,
            index=all_domains.index(suggested_domain),
            key="domain_choice",  # persists your selection across reruns
            label_visibility="collapsed",
        )

        # Rematch: fresh by default, or revisit one past weak spot. The gap is picked
        # here in code, not in the prompt, so the mentor can't fixate on one gap.
        weak_spots = db.get_weak_spots(uid)
        revisit_gap = None
        if weak_spots:
            n = len(weak_spots)
            st.caption(f"⚔️ Unfinished business · {n} weak spot{'s' if n != 1 else ''} "
                       "from recent sessions")
            FRESH, REMATCH = "🎯 Fresh challenge", "⚔️ Rematch a weak spot"
            mode = st.radio(
                "Challenge type",
                [FRESH, REMATCH],
                horizontal=True,
                label_visibility="collapsed",
                key="challenge_mode",
            )
            if mode == REMATCH:
                RANDOM = "🎲 Surprise me"
                selected = st.session_state.get("rematch_pick")
                # Short chip labels from the LLM (cached); full text shown on hover via
                # the button help tooltip, which st.pills can't do per option.
                label_map = {}
                try:
                    label_map = _chip_labels(tuple(w["label"] for w in weak_spots))
                except Exception:
                    pass  # fall back to the full text on the chips
                cols = None
                for i, w in enumerate(weak_spots):
                    if i % 2 == 0:
                        cols = st.columns(2)
                    full = w["label"]
                    if cols[i % 2].button(
                        label_map.get(full, full),
                        help=full,
                        key=f"ws_{i}",
                        use_container_width=True,
                        type="primary" if full == selected else "secondary",
                    ):
                        st.session_state.rematch_pick = full
                        st.rerun()
                if st.button(RANDOM, help="Pick one of your weak spots at random",
                             key="ws_random", use_container_width=True,
                             type="primary" if selected == RANDOM else "secondary"):
                    st.session_state.rematch_pick = RANDOM
                    st.rerun()

                if selected and selected != RANDOM:
                    revisit_gap = selected
                else:
                    # Random, avoiding an immediate repeat when there's a choice.
                    pool = [w["label"] for w in weak_spots
                            if w["label"] != st.session_state.last_revisit] \
                        or [w["label"] for w in weak_spots]
                    revisit_gap = random.choice(pool)

        if st.button("Generate challenge →", type="primary", use_container_width=True):
            with st.spinner("Generating your challenge..."):
                skill_row = next((s for s in skills if s["domain"] == choice), {"level": 1})
                challenge = ai.generate_challenge(choice, skill_row["level"], revisit_gap)
                session_id = db.save_session(uid, choice, challenge)
                st.session_state.challenge = challenge
                st.session_state.session_id = session_id
                st.session_state.messages = []
                st.session_state.session_done = False
                st.session_state.assessment = None
                st.session_state.force_new = False
                st.session_state.rematch_bonus = 0
                if revisit_gap:
                    st.session_state.last_revisit = revisit_gap
                st.session_state.suggested_domain = None   # fresh suggestion next visit
                st.session_state.pop("domain_choice", None)
                st.session_state.pop("challenge_mode", None)
                st.session_state.pop("rematch_pick", None)
                st.session_state.view = "session"
            st.rerun()

    # Recent sessions preview
    recent = db.get_recent_sessions(uid, limit=5)
    done = [s for s in recent if s["completed"]]
    if done:
        st.divider()
        st.markdown("#### Recent sessions")
        for s in done[:3]:
            col1, col2, col3 = st.columns([3, 1, 1])
            col1.markdown(f"**{s['domain']}** · {s['challenge_title']}")
            col2.markdown(f"`{s['score']}/10`")
            col3.markdown(f"`{s['date']}`")


# Session view

elif view == "session":
    if st.button("← Home", key="session_back", type="secondary"):
        st.session_state.view = "home"
        st.rerun()

    if not st.session_state.challenge:
        st.info("No active session — head back home to start one.")
        st.stop()

    challenge = st.session_state.challenge

    # Header
    domain_c = domain_color(challenge["domain"])
    st.markdown(
        f'<span style="background:{domain_c}22;color:{domain_c};'
        f'padding:2px 10px;border-radius:4px;font-size:13px;font-weight:600;">'
        f'{challenge["domain"]}</span>',
        unsafe_allow_html=True,
    )
    st.markdown(f"### {challenge['title']}")
    if challenge.get("revisits"):
        st.markdown(
            f'<div style="font-size:13px;color:#06D6A0;margin-top:-8px;">'
            f'↩ Revisiting <strong>{challenge["revisits"]}</strong> '
            f'— a gap from a recent session</div>',
            unsafe_allow_html=True,
        )

    # Challenge text
    with st.expander("Challenge", expanded=not st.session_state.messages):
        st.markdown(challenge["text"])

    # Session toolbar (hybrid end mechanic)
    if not st.session_state.session_done:
        n_exchanges = sum(1 for m in st.session_state.messages if m["role"] == "user")
        t1, t2, _ = st.columns([1, 1.4, 3])
        with t1:
            if st.button("💡 Hint", key="hint_btn", use_container_width=True):
                with st.spinner("Thinking of a nudge..."):
                    nudge = ai.hint(st.session_state.messages, challenge)
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"💡 **Hint:** {nudge}"}
                )
                db.update_session_messages(st.session_state.session_id, st.session_state.messages)
                st.rerun()
        with t2:
            if st.button("✓ End & evaluate", key="end_btn", type="primary",
                         use_container_width=True, disabled=n_exchanges < 1,
                         help="Evaluation unlocks after your first reply."):
                with st.spinner("Assessing your session..."):
                    # Grade against the learner's current level in this domain so the bar
                    # matches the challenge, instead of defaulting everyone to "senior".
                    skills = db.get_skill_levels(uid)
                    level = next((s["level"] for s in skills
                                  if s["domain"] == challenge["domain"]), 1)
                    result = ai.assess_session(st.session_state.messages, challenge, level)
                    score = result.get("score", 5)
                    xp = xp_for_score(score)
                    # Clearing a rematch (a deliberate revisit) with a pass earns bonus XP.
                    is_rematch = bool(challenge.get("revisits"))
                    bonus = 20 if is_rematch and score >= 7 else 0
                    db.complete_session(
                        st.session_state.session_id, json.dumps(result), score
                    )
                    db.update_skill(uid, challenge["domain"], xp + bonus)
                    db.update_streak(uid)
                    new_ach = check_and_grant(uid, score)
                    db.backup_db()  # snapshot the fully-final state (score, XP, streak, achievements)
                    st.session_state.assessment = result
                    st.session_state.session_done = True
                    st.session_state.new_achievements = new_ach
                    st.session_state.rematch_bonus = bonus
                st.rerun()

        # Guidance sits below the buttons.
        if n_exchanges < 1:
            st.caption("Share your approach below to begin.")
        else:
            plural = "s" if n_exchanges != 1 else ""
            st.caption(f"{n_exchanges} exchange{plural} · end whenever you're ready; "
                       "the mentor will also flag when you've covered enough.")

    st.divider()

    # Assessment result
    if st.session_state.session_done and st.session_state.assessment:
        result = st.session_state.assessment
        st.markdown("## Session complete")

        col1, col2, col3 = st.columns(3)
        col1.metric("Score", f"{result['score']}/10")
        col2.metric("Verdict", result.get("verdict", "—").title())
        col3.metric("XP", f"+{xp_for_score(result['score'])}")

        if st.session_state.get("rematch_bonus"):
            st.success(
                f"⚔️ Rematch cleared — +{st.session_state.rematch_bonus} bonus XP "
                f"into {challenge['domain']}!"
            )

        if result.get("summary"):
            st.info(result["summary"])

        substance = result.get("substance") or []
        gaps = result.get("gaps") or []

        if substance:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**✓ What actually counted**")
                for s in substance:
                    st.markdown(f"- {s}")
            with c2:
                if gaps:
                    st.markdown("**Where to go deeper**")
                    for g in gaps:
                        st.markdown(f"- {g}")
        else:
            st.warning(
                "**Nothing here counted as real substance.** You mostly restated the "
                "challenge instead of proposing concrete techniques, commands, or trade-offs "
                "— so it scored as a non-answer. What a strong answer would have covered:"
            )
            for g in gaps:
                st.markdown(f"- {g}")

        if result.get("next_focus"):
            st.markdown(f"**Next focus:** {result['next_focus']}")

        st.divider()

    # Chat history
    for msg in st.session_state.messages:
        role = msg["role"]
        with st.chat_message(role):
            st.markdown(msg["content"])

    # Empty state: a new learner reads the challenge up top and can miss the chat
    # box pinned at the bottom. A mentor "welcome" bubble makes the input below it
    # the natural next step. Display-only — nothing is saved to messages.
    if not st.session_state.messages and not st.session_state.session_done:
        with st.chat_message("assistant"):
            st.markdown(
                "👋 **Ready when you are.** Share your initial approach to this "
                "challenge in the box below — even a rough plan — and we'll dig in "
                "together."
            )

    # Input
    if not st.session_state.session_done:
        placeholder = (
            "Start by sharing your initial approach to this challenge..."
            if not st.session_state.messages
            else "Continue the discussion..."
        )
        if user_input := st.chat_input(placeholder):
            st.session_state.messages.append({"role": "user", "content": user_input})
            db.update_session_messages(st.session_state.session_id, st.session_state.messages)

            with st.chat_message("user"):
                st.markdown(user_input)

            with st.chat_message("assistant"):
                with st.spinner(""):
                    reply = ai.chat(st.session_state.messages, challenge)
                st.markdown(reply)

            st.session_state.messages.append({"role": "assistant", "content": reply})
            db.update_session_messages(st.session_state.session_id, st.session_state.messages)
            st.rerun()
    else:
        if st.button("Start a new session", type="primary"):
            st.session_state.challenge = None
            st.session_state.session_id = None
            st.session_state.messages = []
            st.session_state.session_done = False
            st.session_state.assessment = None
            st.session_state.rematch_bonus = 0
            st.session_state.view = "home"
            st.rerun()


# Skills view

elif view == "skills":
    st.markdown("## Skill Tree")
    skills = db.get_skill_levels(uid)

    # Sort by level desc, then alpha
    skills_sorted = sorted(skills, key=lambda s: (-s["level"], s["domain"]))

    cols = st.columns(3)
    for i, skill in enumerate(skills_sorted):
        col = cols[i % 3]
        domain = skill["domain"]
        level = skill["level"]
        xp = skill["xp"]
        xp_in_level = xp % 100
        color = domain_color(domain)

        with col:
            st.markdown(
                f'<div style="border:1px solid {color}33;border-radius:14px;'
                f'padding:14px 18px;margin-bottom:14px;background:{color}12;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                f'<span style="font-family:Poppins,sans-serif;font-weight:700;font-size:14px;'
                f'color:#15161A;">{domain}</span>'
                f'<span style="color:{color};font-size:12px;font-weight:700;">'
                f'L{level} · {level_label(level)}</span></div>'
                f'<div style="background:#EAEEF4;border-radius:6px;height:6px;margin-top:10px;">'
                f'<div style="background:{color};width:{xp_in_level}%;height:6px;border-radius:6px;"></div>'
                f'</div>'
                f'<div style="font-size:11px;color:#8A909A;margin-top:6px;">{xp} XP total</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.divider()
    st.markdown("## Achievements")
    unlocked_keys = set(db.get_achievements(uid))
    ach_cols = st.columns(3)
    for i, (key, ach) in enumerate(ACHIEVEMENTS.items()):
        col = ach_cols[i % 3]
        if key in unlocked_keys:
            col.markdown(
                f'<div style="border:1px solid #E6ECF5;border-radius:14px;'
                f'padding:12px 16px;margin-bottom:12px;background:#FBFCFE;">'
                f'<span style="font-size:18px;">{ach["icon"]}</span> '
                f'<strong style="font-family:Poppins,sans-serif;color:#15161A;">{ach["title"]}</strong><br>'
                f'<span style="font-size:12px;color:#6B7280;">{ach["desc"]}</span></div>',
                unsafe_allow_html=True,
            )
        else:
            col.markdown(
                f'<div style="border:1px dashed #DCE2EA;border-radius:14px;'
                f'padding:12px 16px;margin-bottom:12px;background:#FAFBFD;opacity:0.7;">'
                f'<span style="font-size:18px;filter:grayscale(1);">🔒</span> '
                f'<strong style="color:#9AA1AC;">Locked</strong><br>'
                f'<span style="font-size:12px;color:#A6ACB6;">{ach["desc"]}</span></div>',
                unsafe_allow_html=True,
            )


# History view

elif view == "history":
    st.markdown("## Session History")
    sessions = db.get_recent_sessions(uid, limit=30)

    if not sessions:
        st.info("No sessions yet. Complete your first challenge to see history.")
        st.stop()

    for s in sessions:
        completed = bool(s["completed"])
        score = s.get("score") or 0
        assessment = json.loads(s["assessment"]) if s.get("assessment") else {}
        color = domain_color(s["domain"])

        with st.expander(
            f"{'✓' if completed else '○'} {s['date']} · {s['domain']} · {s['challenge_title']}"
            + (f" · {score}/10" if completed else " · in progress")
        ):
            st.markdown(f"**Challenge:** {s['challenge_text']}")

            if completed and assessment:
                col1, col2 = st.columns(2)
                col1.metric("Score", f"{score}/10")
                col2.metric("Verdict", assessment.get("verdict", "—").title())
                if assessment.get("summary"):
                    st.caption(assessment["summary"])
