from db import get_streak, get_recent_sessions, get_skill_levels, grant_achievement

ACHIEVEMENTS = {
    "first_session": {
        "title": "First Contact",
        "desc": "Completed your first session",
        "icon": "⚡",
    },
    "streak_3": {
        "title": "Consistent",
        "desc": "3-day streak",
        "icon": "🔥",
    },
    "streak_7": {
        "title": "Weekly Discipline",
        "desc": "7-day streak",
        "icon": "🔥",
    },
    "streak_30": {
        "title": "Committed",
        "desc": "30-day streak",
        "icon": "🔥",
    },
    "score_9": {
        "title": "Sharp",
        "desc": "Scored 9+ on a session",
        "icon": "✦",
    },
    "score_10": {
        "title": "Flawless",
        "desc": "Perfect score on a session",
        "icon": "✦",
    },
    "five_domains": {
        "title": "Breadth",
        "desc": "Practiced 5 different domains",
        "icon": "◈",
    },
    "ten_sessions": {
        "title": "10 Deep",
        "desc": "Completed 10 sessions",
        "icon": "◈",
    },
    "level_3_any": {
        "title": "Expert Emerging",
        "desc": "Reached level 3 in any domain",
        "icon": "▲",
    },
    "sql_master": {
        "title": "Query Master",
        "desc": "Reached level 5 in SQL",
        "icon": "▲",
    },
}


def check_and_grant(user_id: int, score: int = None) -> list[str]:
    """Check all conditions and return list of newly unlocked achievement keys."""
    newly_unlocked = []

    sessions = get_recent_sessions(user_id, limit=100)
    completed = [s for s in sessions if s["completed"]]
    streak = get_streak(user_id)
    skills = get_skill_levels(user_id)

    checks = {
        "first_session": len(completed) >= 1,
        "streak_3": streak.get("current_streak", 0) >= 3,
        "streak_7": streak.get("current_streak", 0) >= 7,
        "streak_30": streak.get("current_streak", 0) >= 30,
        "score_9": score is not None and score >= 9,
        "score_10": score is not None and score == 10,
        "five_domains": len({s["domain"] for s in completed}) >= 5,
        "ten_sessions": len(completed) >= 10,
        "level_3_any": any(s["level"] >= 3 for s in skills),
        "sql_master": next((s["level"] for s in skills if s["domain"] == "SQL"), 0) >= 5,
    }

    for key, condition in checks.items():
        if condition:
            if grant_achievement(user_id, key):
                newly_unlocked.append(key)

    return newly_unlocked
