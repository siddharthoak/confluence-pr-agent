"""Best-effort test-command detection from a repo's root file listing.

Used by the /ui/config repeating repo-config editor to pre-fill a sensible
default (see ui/routes.py's detect_test_command_route) instead of leaving
the field blank or wrong, which only ever surfaces as a real pipeline run
failing at the test-gate step. Detect-and-prefill in the UI, not re-detect
on every pipeline run -- see the multi-repo plan's reasoning: a value the
user can see and override stays predictable, silently re-guessing it fresh
every run does not.

Order matters -- first match wins, for a repo that happens to carry more
than one marker (e.g. a Python backend with a small bundled npm tool).
"""

from __future__ import annotations

_MARKERS: list[tuple[str, str]] = [
    ("pom.xml", "mvn test"),
    ("build.gradle", "./gradlew test"),
    ("build.gradle.kts", "./gradlew test"),
    ("go.mod", "go test ./..."),
    ("Cargo.toml", "cargo test"),
    ("package.json", "npm test"),
    ("pyproject.toml", "pytest"),
    ("requirements.txt", "pytest"),
    ("setup.py", "pytest"),
    ("Gemfile", "bundle exec rspec"),
]


def detect_test_command(root_files: list[str]) -> str | None:
    names = set(root_files)
    for marker, command in _MARKERS:
        if marker in names:
            return command
    return None
