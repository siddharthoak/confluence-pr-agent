"""Local git operations against a cloned working copy of the target repo."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


class GitCommandError(RuntimeError):
    def __init__(self, command: list[str], returncode: int, output: str) -> None:
        self.command = command
        self.returncode = returncode
        self.output = output
        super().__init__(f"git command failed ({returncode}): {' '.join(command)}\n{output}")


async def _run(*args: str, cwd: Path | None = None) -> str:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    output = stdout.decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise GitCommandError(list(args), process.returncode, output)
    return output


class GitClient:
    """Wraps the `git` CLI. Requires `git` to be on PATH."""

    def __init__(self, github_token: str) -> None:
        self._token = github_token

    def _authenticated_url(self, owner_repo: str) -> str:
        return f"https://x-access-token:{self._token}@github.com/{owner_repo}.git"

    async def clone(self, owner_repo: str, dest: Path, base_branch: str) -> None:
        if dest.exists():
            shutil.rmtree(dest)  # avoid stale state from a prior pipeline run
        await _run(
            "git",
            "clone",
            "--branch",
            base_branch,
            "--depth",
            "50",
            self._authenticated_url(owner_repo),
            str(dest),
        )

    async def create_branch(self, repo_dir: Path, branch_name: str) -> None:
        await _run("git", "checkout", "-b", branch_name, cwd=repo_dir)

    async def has_changes(self, repo_dir: Path) -> bool:
        output = await _run("git", "status", "--porcelain", cwd=repo_dir)
        return bool(output.strip())

    async def changed_files(self, repo_dir: Path) -> list[str]:
        output = await _run("git", "status", "--porcelain", cwd=repo_dir)
        files = []
        for line in output.splitlines():
            if line.strip():
                files.append(line[3:].strip())
        return files

    async def diff(self, repo_dir: Path) -> str:
        """Full unified diff of everything the change engine did, staged and
        unstaged, tracked and new -- used by the LLM judge review gate. Runs
        `git add -A` first (same as commit_all, and harmless to repeat)
        because an unstaged `git diff` alone omits the *content* of new
        (untracked) files, which is exactly what a from-scratch change is
        made of.
        """
        await _run("git", "add", "-A", cwd=repo_dir)
        return await _run("git", "diff", "--cached", cwd=repo_dir)

    async def commit_all(self, repo_dir: Path, message: str) -> None:
        await _run("git", "add", "-A", cwd=repo_dir)
        await _run(
            "git",
            "-c",
            "user.name=confluence-pr-agent",
            "-c",
            "user.email=confluence-pr-agent@users.noreply.github.com",
            "commit",
            "-m",
            message,
            cwd=repo_dir,
        )

    async def push(self, repo_dir: Path, branch_name: str) -> None:
        await _run("git", "push", "-u", "origin", branch_name, cwd=repo_dir)
