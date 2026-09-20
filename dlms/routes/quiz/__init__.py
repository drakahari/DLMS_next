"""Quiz lifecycle and classic-authoring Blueprint."""

from flask import Blueprint

from .authoring import register_authoring_routes
from .bundles import register_bundle_routes
from .dependencies import (
    QuizAuthoringDependencies,
    QuizBundleDependencies,
    QuizEditorDependencies,
    QuizLibraryDependencies,
)
from .editor import register_editor_routes
from .library import register_library_routes


def create_quiz_blueprint(
    library_dependencies: QuizLibraryDependencies,
    editor_dependencies: QuizEditorDependencies,
    authoring_dependencies: QuizAuthoringDependencies,
    bundle_dependencies: QuizBundleDependencies,
) -> Blueprint:
    """Create the complete classic Quiz route family."""
    blueprint = Blueprint("quiz", __name__)
    register_library_routes(blueprint, library_dependencies)
    register_editor_routes(blueprint, editor_dependencies)
    register_authoring_routes(blueprint, authoring_dependencies)
    register_bundle_routes(blueprint, bundle_dependencies)
    return blueprint


__all__ = [
    "QuizAuthoringDependencies",
    "QuizBundleDependencies",
    "QuizEditorDependencies",
    "QuizLibraryDependencies",
    "create_quiz_blueprint",
]
