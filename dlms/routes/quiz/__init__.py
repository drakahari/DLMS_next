"""Quiz lifecycle and classic-authoring Blueprint."""

from flask import Blueprint

from .authoring import register_authoring_routes
from .dependencies import (
    QuizAuthoringDependencies,
    QuizEditorDependencies,
    QuizLibraryDependencies,
)
from .editor import register_editor_routes
from .library import register_library_routes


def create_quiz_blueprint(
    library_dependencies: QuizLibraryDependencies,
    editor_dependencies: QuizEditorDependencies,
    authoring_dependencies: QuizAuthoringDependencies,
) -> Blueprint:
    """Create the complete classic Quiz route family."""
    blueprint = Blueprint("quiz", __name__)
    register_library_routes(blueprint, library_dependencies)
    register_editor_routes(blueprint, editor_dependencies)
    register_authoring_routes(blueprint, authoring_dependencies)
    return blueprint


__all__ = [
    "QuizAuthoringDependencies",
    "QuizEditorDependencies",
    "QuizLibraryDependencies",
    "create_quiz_blueprint",
]
