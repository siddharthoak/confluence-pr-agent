from __future__ import annotations

import sys

from confluence_pr_agent.testing.test_runner import run_tests


async def test_run_tests_installs_requirements_before_running_command(tmp_path):
    (tmp_path / "requirements.txt").write_text("")  # empty on purpose: install should still run, just do nothing
    (tmp_path / "test_something.py").write_text("def test_ok():\n    assert True\n")

    result = await run_tests(tmp_path, f"{sys.executable} -m pytest -q")

    assert result.passed is True
    assert "pip install -r requirements.txt" in result.output


async def test_run_tests_skips_install_when_no_requirements_file(tmp_path):
    (tmp_path / "test_something.py").write_text("def test_ok():\n    assert True\n")

    result = await run_tests(tmp_path, f"{sys.executable} -m pytest -q")

    assert result.passed is True
    assert "pip install" not in result.output


async def test_run_tests_reports_failure_and_includes_output(tmp_path):
    (tmp_path / "test_something.py").write_text("def test_fail():\n    assert False, 'boom'\n")

    result = await run_tests(tmp_path, f"{sys.executable} -m pytest -q")

    assert result.passed is False
    assert "boom" in result.output
