"""Presentation-only Server transition defaults; no remote commands or storage."""
NEUTRAL_SERVER_PALETTE = {
    "body_base": "#20252c", "page": "#e9edf2", "heading": "#f4f6f9",
    "panel1": "#20252c", "surface2": "#303740", "border": "#697684",
    "accent": "#abc7e8", "accent_text": "#abc7e8", "muted": "#bdc5cf",
}


def connection_text(origin: str, profile: str, *, initial: bool) -> str:
    if initial:
        return f"Connecting to {origin}…\nServer data stays separate from Local profile {profile}."
    return "Loading Server page…"
