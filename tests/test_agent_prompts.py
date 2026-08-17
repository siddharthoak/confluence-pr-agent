"""agent/prompts.py::build_repo_context -- in particular the out-of-scope
repo flagging that lets a scope-mismatched BRD (e.g. labeled repo-api only
for a change that also needs repo-ui) surface that gap in the agent's own
summary instead of silently doing a partial job.
"""

from __future__ import annotations

from pathlib import Path

from confluence_pr_agent.agent.prompts import build_repo_context
from confluence_pr_agent.models import RepoTarget


def _repo_dirs(workspace: Path, *repos: str) -> dict[str, Path]:
    return {repo: workspace / repo.split("/")[-1] for repo in repos}


def test_build_repo_context_without_out_of_scope_has_no_gap_warning():
    workspace = Path("/work/page-1-v1")
    in_scope = [RepoTarget("org/api", "main", "pytest", "repo-api")]
    context = build_repo_context(in_scope, _repo_dirs(workspace, "org/api"), workspace)

    assert "org/api" in context
    assert "NOT checked out" not in context
    assert "Next steps" not in context


def test_build_repo_context_lists_out_of_scope_repos_and_labels():
    workspace = Path("/work/page-1-v1")
    in_scope = [RepoTarget("org/api", "main", "pytest", "repo-api")]
    out_of_scope = [
        RepoTarget("org/ui", "main", "pytest", "repo-ui"),
        RepoTarget("org/db", "main", "pytest", "repo-db"),
    ]
    context = build_repo_context(in_scope, _repo_dirs(workspace, "org/api"), workspace, out_of_scope)

    assert "org/ui (routing label `repo-ui`)" in context
    assert "org/db (routing label `repo-db`)" in context
    assert "do not guess at their contents or invent a change" in context
    assert "Next steps" in context
    assert "name the exact routing label" in context
    assert "re-run the pipeline" in context
    assert "won't be picked up" in context  # the label-only-edit gotcha itself


def test_build_repo_context_empty_out_of_scope_list_is_same_as_none():
    workspace = Path("/work/page-1-v1")
    in_scope = [RepoTarget("org/api", "main", "pytest", "repo-api")]
    with_none = build_repo_context(in_scope, _repo_dirs(workspace, "org/api"), workspace, None)
    with_empty = build_repo_context(in_scope, _repo_dirs(workspace, "org/api"), workspace, [])

    assert with_none == with_empty
