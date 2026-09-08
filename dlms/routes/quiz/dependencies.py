"""Explicit configured dependencies for the Quiz route family."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


Dependency = Callable[..., Any]


@dataclass(frozen=True)
class QuizLibraryDependencies:
    app_version: Dependency
    logo_folder: Dependency
    quiz_registry_path: Dependency
    registry_lock: Dependency
    load_registry: Dependency
    save_registry: Dependency
    normalize_quiz_folders: Dependency
    get_quiz_folders: Dependency
    save_quiz_folders: Dependency
    get_hidden_quiz_folders: Dependency
    save_quiz_folder_state: Dependency
    rename_quiz_folder_metadata: Dependency
    delete_quiz_folder_metadata: Dependency
    get_portal_title: Dependency
    resolve_logo_filename: Dependency
    debug_print: Dependency
    get_db: Dependency


@dataclass(frozen=True)
class QuizEditorDependencies:
    app_version: Dependency
    data_folder: Dependency
    browser_served_data_extensions: Dependency
    quiz_folder: Dependency
    get_db: Dependency
    load_registry: Dependency
    normalize_exam_minutes: Dependency
    question_concepts: Dependency
    finish_quiz_mutation: Dependency
    quiz_owns_question: Dependency
    quiz_owns_choice: Dependency
    quiz_owns_matching_pair: Dependency
    set_question_concepts: Dependency
    quiz_edit_validation: Dependency
    publish_quiz_edit_request: Dependency
    delete_quiz_transaction: Dependency
    cleanup_deleted_quiz_artifacts: Dependency
    rebuild_quiz_html_from_registry: Dependency


@dataclass(frozen=True)
class QuizAuthoringDependencies:
    data_folder: Dependency
    logo_folder: Dependency
    parse_log_path: Dependency
    upload_folder: Dependency
    matching_csv_upload_max_bytes: Dependency
    quiz_text_upload_max_bytes: Dependency
    upload_too_large_error: Dependency
    get_portal_title: Dependency
    load_portal_config: Dependency
    matching_case_only_term_warnings: Dependency
    matching_record_validation_errors: Dependency
    publish_quiz: Dependency
    read_bounded_upload: Dependency
    normalize_exam_minutes: Dependency
    finalize_logo_from_request: Dependency
    save_preview_logo: Dependency
    get_confidence_setting: Dependency
    analyze_confidence: Dependency
    parse_questions: Dependency
    debug_print: Dependency
