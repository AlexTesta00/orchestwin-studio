"""Proposal task identifiers shared with the isolated model-serving environment."""

SOURCE_TASKS = frozenset({"web-source", "web-repair", "jvm-source", "jvm-repair"})
TASKS = frozenset(
    {
        "team",
        "personas",
        "user-twins",
        "twin-chat",
        "user-twin-evaluation",
        "requirements",
        "design",
        "brief-dialogue",
    }
)
