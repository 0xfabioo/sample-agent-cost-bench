"""Tests for the on-demand Docker image builder (no real daemon required)."""

from __future__ import annotations

from agent_cost_bench.verify import docker_build as db


def test_ensure_image_returns_ok_when_already_present(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "resolve_docker_env", lambda image: {"present": True})
    # Should short-circuit before touching the daemon or the context.
    res = db.ensure_image("some/image:tag", tmp_path)
    assert res.ok is True and res.built is False
    assert "present" in res.detail


def test_ensure_image_no_daemon(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "resolve_docker_env", lambda image: None)
    monkeypatch.setattr(db, "docker_available", lambda: False)
    res = db.ensure_image("some/image:tag", tmp_path)
    assert res.ok is False and res.built is False
    assert "not reachable" in res.detail


def test_ensure_image_missing_dockerfile(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "resolve_docker_env", lambda image: None)
    monkeypatch.setattr(db, "docker_available", lambda: True)
    res = db.ensure_image("some/image:tag", tmp_path)  # empty context, no Dockerfile
    assert res.ok is False and res.built is False
    assert "no Dockerfile" in res.detail


def test_ensure_image_builds_and_succeeds(monkeypatch, tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    # Missing before, present after (simulate a successful build).
    calls = {"n": 0}

    def fake_resolve(image):
        calls["n"] += 1
        return None if calls["n"] == 1 else {"present": True}

    monkeypatch.setattr(db, "resolve_docker_env", fake_resolve)
    monkeypatch.setattr(db, "docker_available", lambda: True)

    class _Proc:
        returncode = 0
        stdout = "built"
        stderr = ""

    monkeypatch.setattr(db.subprocess, "run", lambda *a, **k: _Proc())
    logged = []
    res = db.ensure_image("some/image:tag", tmp_path, log=logged.append)
    assert res.ok is True and res.built is True
    assert any("building image" in m for m in logged)


def test_ensure_image_build_failure(monkeypatch, tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    monkeypatch.setattr(db, "resolve_docker_env", lambda image: None)
    monkeypatch.setattr(db, "docker_available", lambda: True)

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "step 3 failed: boom"

    monkeypatch.setattr(db.subprocess, "run", lambda *a, **k: _Proc())
    res = db.ensure_image("some/image:tag", tmp_path)
    assert res.ok is False and res.built is True
    assert "build failed" in res.detail
