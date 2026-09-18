"""Tests for runtime-dependency preflight (skipping tasks whose verifier needs a
runtime nothing provides). Detection is fully STATIC — it reads the task's test
files, test.sh, and verify/environment/Dockerfile — so these tests need no
Docker daemon and no mocking of it."""

from __future__ import annotations

from agent_cost_bench.models import TaskConfig, VerifySpec
import agent_cost_bench.preflight as pf


def _task(tmp_path, tid, test_py, image="img/x:1", test_sh="", dockerfile=""):
    """Build a minimal imported-style task fixture.

    Optionally writes a test.sh and a verify/environment/Dockerfile so the
    static install-detection can be exercised.
    """
    tdir = tmp_path / tid
    tests = tdir / "verify" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_outputs.py").write_text(test_py)
    if test_sh:
        (tests / "test.sh").write_text(test_sh)
    if dockerfile:
        env = tdir / "verify" / "environment"
        env.mkdir(parents=True)
        (env / "Dockerfile").write_text(dockerfile)
    t = TaskConfig(
        id=tid,
        prompt="p",
        verify=VerifySpec(
            image=image, parser="reward-file", test_cmd="bash test.sh",
            tests_subdir="verify/tests",
        ),
    )
    t.task_dir = tdir
    return t


def test_scan_detects_subprocess_runtime(tmp_path):
    t = _task(tmp_path, "r-task",
              'import subprocess\nsubprocess.run(["Rscript", "x.R"], check=True)\n')
    assert pf._scan_required_runtimes(t) == {"Rscript"}


def test_scan_ignores_python_and_harness_tools(tmp_path):
    t = _task(tmp_path, "py-task",
              'import subprocess\nsubprocess.run(["python3", "x.py"])\n'
              'subprocess.run(["uvx", "pytest"])\n')
    assert pf._scan_required_runtimes(t) == set()


def test_report_flags_missing_runtime(tmp_path):
    # Vanilla Dockerfile that does NOT install R -> flagged.
    t = _task(tmp_path, "r-task",
              'import subprocess\nsubprocess.run(["Rscript", "x.R"])\n',
              dockerfile="FROM ubuntu:24.04\nWORKDIR /app\n")
    rep = pf.unsupported_runtime_report([t])
    assert "r-task" in rep
    assert rep["r-task"]["missing"] == [("Rscript", "R")]


def test_report_ok_when_dockerfile_installs_runtime(tmp_path):
    # Dockerfile apt-installs r-base -> runtime present at verify time -> not flagged.
    t = _task(tmp_path, "r-ok",
              'import subprocess\nsubprocess.run(["Rscript", "x.R"])\n',
              dockerfile="FROM ubuntu:24.04\nRUN apt-get update && apt-get install -y r-base\n")
    assert pf.unsupported_runtime_report([t]) == {}


def test_report_ok_when_test_script_installs_runtime(tmp_path):
    # Even with a vanilla Dockerfile, test.sh installs r-base -> not flagged.
    t = _task(tmp_path, "r-selfinstall",
              'import subprocess\nsubprocess.run(["Rscript", "x.R"])\n',
              test_sh="apt-get install -y r-base\nRscript x.R\n",
              dockerfile="FROM ubuntu:24.04\n")
    assert pf.unsupported_runtime_report([t]) == {}


def test_report_ok_when_no_external_runtime(tmp_path):
    # Only python3 (always present) -> nothing to flag.
    t = _task(tmp_path, "py-ok",
              'import subprocess\nsubprocess.run(["python3", "x.py"])\n',
              dockerfile="FROM python:3.13-slim\n")
    assert pf.unsupported_runtime_report([t]) == {}


def test_report_no_pull_no_docker_needed(tmp_path, monkeypatch):
    """Detection must not shell out to docker at all (fully static)."""
    import subprocess as _sp

    def _boom(*a, **k):
        raise AssertionError("docker/subprocess must not be invoked during detection")

    monkeypatch.setattr(_sp, "run", _boom)
    t = _task(tmp_path, "r-task",
              'import subprocess\nsubprocess.run(["Rscript", "x.R"])\n',
              dockerfile="FROM ubuntu:24.04\n")
    rep = pf.unsupported_runtime_report([t])
    assert "r-task" in rep
