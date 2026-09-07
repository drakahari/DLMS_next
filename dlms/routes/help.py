"""Help and documentation routes."""

from flask import Blueprint, current_app, send_from_directory


HELP_TOPIC_FILES = {
    "getting-started": "help-getting-started.html",
    "quizzes": "help-quizzes.html",
    "build-quiz": "help-build-quiz.html",
    "smart-pdf": "help-smart-pdf.html",
    "study-packs": "help-study-packs.html",
    "study-modules": "help-study-modules.html",
    "content-management": "help-content-management.html",
    "history-analytics": "help-history-analytics.html",
    "learning-intelligence": "help-learning-intelligence.html",
    "anki": "help-anki.html",
    "settings": "help-settings.html",
    "maintenance": "help-maintenance.html",
    "troubleshooting": "help-troubleshooting.html",
}


def create_help_blueprint() -> Blueprint:
    """Create the Help and documentation Blueprint."""
    blueprint = Blueprint("help", __name__)

    @blueprint.get("/help/")
    def help_index():
        return send_from_directory("static", "help.html")

    @blueprint.get("/help/about")
    def help_about():
        return send_from_directory("static", "about.html")

    @blueprint.get("/help/quiz-help")
    def help_quiz():
        return send_from_directory("static", "quiz-help.html")

    @blueprint.get("/help/advanced-features")
    def help_advanced():
        return send_from_directory("static", "advanced-features.html")

    @blueprint.get("/help/<topic>")
    def help_topic(topic):
        filename = HELP_TOPIC_FILES.get(str(topic or "").strip().lower())
        if not filename:
            return "Help topic not found", 404
        return send_from_directory("static", filename)

    @blueprint.get("/regex-help")
    @blueprint.get("/regex-help/")
    def regex_help():
        return send_from_directory(current_app.static_folder, "regex-help.html")

    return blueprint
