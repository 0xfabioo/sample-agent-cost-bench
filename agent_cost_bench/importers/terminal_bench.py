"""
Terminal-Bench importer (2.x / Harbor layout, with 1.x fallback).

Harbor task layout (Terminal-Bench 2.x)::

    <task>/
      task.toml            # version, [metadata], [verifier], [agent], [environment]
      instruction.md       # the natural-language task the agent must complete
      environment/         # Dockerfile / docker-compose.yaml (or docker_image in toml)
      solution/solve.sh    # oracle solution (not used for grading)
      tests/test.sh        # authoritative tests; writes reward to /logs/verifier/reward.txt

Terminal-Bench 1.x layout (fallback)::

    <task>/
      task.yaml            # instruction nested inside, plus docker/timeout config
      run-tests.sh         # authoritative tests
      docker-compose.yaml / Dockerfile

We emit a native ``vibe`` task whose Docker ``verify:`` block runs the task's own
test script inside the task's environment image and scores from the reward file
(``reward-file`` parser). See :mod:`agent_cost_bench.importers.base` for the
bridging rationale.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from .base import ImportedTask, ImportError_, copy_tree_into, dump_task_yaml, read_toml

# Container paths used by the generated verify block. $TESTS_RO / $BUILD /
# $RESULTS_DIR are provided by the generic Docker verify runner.
_APP_DIR = "/app"  # where Harbor tasks conventionally expect the working tree
# Terminal-Bench test scripts reference their tests by the ABSOLUTE path /tests
# (e.g. `pytest /tests/test_outputs.py`, `cp /tests/test.py /app/test.py`). TB's
# own harness mounts the tests there, so we must stage a writable copy at /tests
# too — not only under /app/tests — or those scripts collect 0 tests and score 0.
_TESTS_DIR = "/tests"

# ---------------------------------------------------------------------------
# Harness-compatible task allowlist
# ---------------------------------------------------------------------------
#
# Many Terminal-Bench tasks assume the agent runs INSIDE the task container and
# mutates its environment (install a package, build a binary into
# /usr/local/bin, start a service). This framework runs the agent on the HOST
# and only copies its produced files into a fresh container for grading, so
# those tasks can never pass here regardless of the model — a harness
# limitation, not a model result. Running the full 89-task suite therefore
# produces many misleading "failures".
#
# This is the set of tasks EMPIRICALLY CONFIRMED to grade correctly under the
# host-agent model (i.e. pure file-producing tasks whose hidden tests check the
# model's output files, not a mutated environment). It is used as the DEFAULT
# task set when a `terminal-bench` task source is configured without an explicit
# `tasks:` filter, so a default run is meaningful rather than dominated by
# ungradeable tasks.
#
# HOW TO GROW THIS LIST (deliberately empirical, not guessed):
#   Add a task's source name here only after a real run shows it grading
#   correctly under this harness — i.e. it reaches a genuine pass/fail from its
#   own hidden tests (model quality decides the score), NOT a harness error such
#   as "binary not installed", "module not found", "no /app", or a service that
#   never came up. A confirmed model FAILURE still means the task is gradeable
#   and belongs here; only harness-incompatible tasks stay out.
#
# Entries are Terminal-Bench SOURCE task names (no `terminal-bench-` prefix).
_TERMINAL_BENCH_SUPPORTED: tuple[str, ...] = (
    # Confirmed gradeable from runs on 2026-09-09/10 (reached real hidden-test
    # verdicts under the host-agent model): the task's own test suite collected
    # and ran its tests against the model's OUTPUT — the score reflects model
    # quality, not a harness/env failure. A confirmed model FAIL still qualifies
    # (the task grades correctly); only env-mutation tasks (install a package,
    # build a binary into a system path, need a running service) are excluded.
    "break-filter-js-from-html",   # passed (Kiro)
    "circuit-fibsqrt",             # passed (Kiro)
    "code-from-image",             # passed (Kiro)
    "count-dataset-tokens",        # passed (Kiro)
    "cancel-async-tasks",          # tests ran (collected 6) — real verdict
    "write-compressor",            # tests ran — real verdict
    "bn-fit-modify",               # tests ran (collected 9), failed on missing
                                   #   output file — real verdict on model output
    "constraints-scheduling",      # tests ran (collected 3) — real verdict
    "chess-best-move",             # tests ran, failed on wrong moves — real verdict
)


def terminal_bench_supported_tasks() -> tuple[str, ...]:
    """Return the empirically-confirmed harness-compatible Terminal-Bench task
    names (used as the default `tasks:` filter when none is given)."""
    return _TERMINAL_BENCH_SUPPORTED


def is_terminal_bench_task(task_dir: Path) -> bool:
    if not task_dir.is_dir():
        return False
    if (task_dir / "task.toml").is_file():
        return True
    # 1.x: a task.yaml with an embedded instruction/description + a test script.
    if (task_dir / "task.yaml").is_file() and (
        (task_dir / "run-tests.sh").is_file() or (task_dir / "tests").is_dir()
    ):
        return True
    return False


def _load_instruction(task_dir: Path, toml_meta: dict) -> str:
    inst = task_dir / "instruction.md"
    if inst.is_file():
        return inst.read_text(encoding="utf-8").strip()
    # 1.x fallback: instruction embedded in task.yaml.
    ty = task_dir / "task.yaml"
    if ty.is_file():
        raw = yaml.safe_load(ty.read_text(encoding="utf-8")) or {}
        for key in ("instruction", "description", "prompt", "task"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, list) and val and isinstance(val[0], dict):
                # Some 1.x tasks used a list of {key, instruction} descriptions.
                for item in val:
                    if isinstance(item.get("instruction"), str):
                        return item["instruction"].strip()
    raise ImportError_(
        f"{task_dir.name}: no instruction found (expected instruction.md or an "
        f"'instruction'/'description' field in task.yaml)"
    )


def _resolve_image(task_dir: Path, toml_meta: dict) -> tuple[str | None, bool, list[str]]:
    """Return (image, has_buildable_dockerfile, warnings).

    Prefer an explicit prebuilt image. Otherwise, if the task ships a Dockerfile,
    derive a local image tag AND signal that the framework can build it from the
    copied ``verify/environment/`` context (auto-build at run time)."""
    warnings: list[str] = []
    env = toml_meta.get("environment", {}) if isinstance(toml_meta, dict) else {}
    image = env.get("docker_image") if isinstance(env, dict) else None
    if image:
        return str(image), False, warnings

    env_dir = task_dir / "environment"
    dockerfile = None
    for cand in (env_dir / "Dockerfile", task_dir / "Dockerfile"):
        if cand.is_file():
            dockerfile = cand
            break
    if dockerfile is not None:
        # A local tag the framework builds from the copied Dockerfile on demand.
        tag = f"tb-{task_dir.name.lower()}:imported"
        return tag, True, warnings

    warnings.append(
        "no docker_image and no Dockerfile found — verification will fail until an "
        "image is provided. Set [environment].docker_image in the source task.toml."
    )
    return None, False, warnings


def _timeouts(toml_meta: dict) -> tuple[int, int | None]:
    """Return (task_timeout_minutes, verify_timeout_seconds)."""
    agent = toml_meta.get("agent", {}) if isinstance(toml_meta, dict) else {}
    verifier = toml_meta.get("verifier", {}) if isinstance(toml_meta, dict) else {}
    agent_sec = agent.get("timeout_sec") if isinstance(agent, dict) else None
    verify_sec = verifier.get("timeout_sec") if isinstance(verifier, dict) else None
    task_minutes = 15
    if isinstance(agent_sec, (int, float)) and agent_sec > 0:
        task_minutes = max(1, int(round(agent_sec / 60.0)))
    vt = int(verify_sec) if isinstance(verify_sec, (int, float)) and verify_sec > 0 else None
    return task_minutes, vt


def _test_script_relpath(task_dir: Path) -> str:
    """Path (relative to the copied verify/tests dir) of the test entrypoint."""
    if (task_dir / "tests" / "test.sh").is_file():
        return "test.sh"
    if (task_dir / "run-tests.sh").is_file():
        return "run-tests.sh"
    if (task_dir / "tests" / "run-tests.sh").is_file():
        return "run-tests.sh"
    raise ImportError_(
        f"{task_dir.name}: no test script found (expected tests/test.sh or run-tests.sh)"
    )


def convert_terminal_bench_task(source_dir: Path, dest_dir: Path, native_id: str) -> ImportedTask:
    if not is_terminal_bench_task(source_dir):
        raise ImportError_(
            f"{source_dir.name}: not a Terminal-Bench task (no task.toml / task.yaml+tests)"
        )

    toml_meta: dict = {}
    toml_path = source_dir / "task.toml"
    if toml_path.is_file():
        try:
            toml_meta = read_toml(toml_path)
        except Exception as e:
            raise ImportError_(f"{source_dir.name}: could not parse task.toml: {e}") from e

    instruction = _load_instruction(source_dir, toml_meta)
    image, buildable, warnings = _resolve_image(source_dir, toml_meta)
    task_minutes, verify_timeout = _timeouts(toml_meta)
    test_rel = _test_script_relpath(source_dir)

    # --- copy the authoritative tests into verify/tests (mounted ro at $TESTS_RO) ---
    tests_src = source_dir / "tests"
    dest_tests = dest_dir / "verify" / "tests"
    if tests_src.is_dir():
        copy_tree_into(tests_src, dest_tests)
    else:
        # 1.x: a bare run-tests.sh at the task root.
        dest_tests.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_dir / "run-tests.sh", dest_tests / "run-tests.sh")

    # Copy the environment (Dockerfile etc.) so the operator can build the image.
    env_src = source_dir / "environment"
    if env_src.is_dir():
        copy_tree_into(env_src, dest_dir / "verify" / "environment")
    elif (source_dir / "Dockerfile").is_file():
        (dest_dir / "verify" / "environment").mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_dir / "Dockerfile", dest_dir / "verify" / "environment" / "Dockerfile")

    # Keep the oracle solution for reference (not used in grading).
    sol_src = source_dir / "solution"
    if sol_src.is_dir():
        copy_tree_into(sol_src, dest_dir / "reference")

    # --- seed the task's INPUT files into an inputs/ fixture ---
    # TB tasks reference their inputs by absolute container paths (e.g.
    # /app/decomp.c, /app/data.txt) that the environment/Dockerfile COPYs into
    # the image's WORKDIR. This framework runs the agent on the host where /app
    # doesn't exist, so without these files the model can't read its inputs and
    # flails (e.g. a full `find /`). We parse the Dockerfile's COPY lines and
    # copy exactly those source files into inputs/, which setup seeds into the
    # workspace. Parsing COPY (rather than copying all of environment/) avoids
    # leaking non-inputs like a reference-solution source file.
    seeded_inputs = _seed_dockerfile_inputs(source_dir, dest_dir)

    # --- build the prompt (instruction + a placement contract for src/) ---
    prompt = _build_prompt(instruction, seeded_inputs=seeded_inputs)

    # --- setup steps: place the model's src/ at the container working dir, then
    #     stage the authoritative tests where the test script expects them. ---
    setup = [
        f'mkdir -p "{_APP_DIR}" "{_TESTS_DIR}"',
        # The generic runner pre-copies workspace/src to $BUILD/src.
        f'cp -r "$BUILD/src/." "{_APP_DIR}/" 2>/dev/null || true',
        # Stage the authoritative tests at BOTH the absolute /tests path (which
        # TB scripts reference directly, e.g. `pytest /tests/test_outputs.py`)
        # and under /app/tests (for scripts that use a relative path). $TESTS_RO
        # is read-only, so we copy to writable locations the scripts can use.
        f'cp -r "$TESTS_RO/." "{_TESTS_DIR}/" 2>/dev/null || true',
        f'cp -r "$TESTS_RO/." "{_APP_DIR}/tests/" 2>/dev/null || cp -r "$TESTS_RO/." "{_APP_DIR}/"',
    ]
    # test_cmd: run the task's own test script ONCE, publish reward.
    # Resolve the script path first (prefer /tests, then /app/tests, then /app)
    # and run exactly that — chaining with `||` would wrongly re-run the suite at
    # another path on a genuine test failure and mask the real exit code. Harbor
    # scripts write /logs/verifier/reward.txt; TB 1.x rely on the exit code, so
    # we honor an explicit reward file if present else synthesize one, then copy
    # it to $RESULTS_DIR.
    test_cmd = (
        f'cd "{_APP_DIR}"; mkdir -p /logs/verifier; '
        f'for p in "{_TESTS_DIR}/{test_rel}" "{_APP_DIR}/tests/{test_rel}" "{_APP_DIR}/{test_rel}"; do '
        f'  if [ -f "$p" ]; then ts="$p"; break; fi; '
        f'done; '
        f'bash "${{ts:-{_TESTS_DIR}/{test_rel}}}" 2>&1; '
        f'ec=$?; '
        f'if [ ! -s /logs/verifier/reward.txt ]; then '
        f'  if [ $ec -eq 0 ]; then echo 1 > /logs/verifier/reward.txt; '
        f'  else echo 0 > /logs/verifier/reward.txt; fi; fi; '
        f'cp /logs/verifier/reward.txt "$RESULTS_DIR/reward.txt" 2>/dev/null || true; '
        f'exit $ec'
    )

    verify_block: dict = {
        "image": image,
        "parser": "reward-file",
        "workdir": "",
        "tests_subdir": "verify/tests",
        "setup": setup,
        "test_cmd": test_cmd,
        # Terminal-Bench test scripts routinely install their own dependencies at
        # verify time (apt-get, `uv`/pip from PyPI, downloading `uv` from
        # astral.sh, etc.), so the verify container needs outbound network. TB's
        # own harness grades with network available; "none" here makes essentially
        # every task fail setup and score 0. Use a networked default and let the
        # AGENT_COST_BENCH_VERIFY_NETWORK env var override per-run if needed.
        "network": "bridge",
    }
    # When the task ships a Dockerfile (no prebuilt image), point the framework
    # at the copied build context so it can build the image on demand.
    if buildable:
        verify_block["build_context"] = "verify/environment"
    if verify_timeout:
        verify_block["timeout_seconds"] = verify_timeout

    description = _first_line(instruction)
    task_yaml = {
        "id": native_id,
        "mode": "vibe",
        "description": description,
        "timeout_minutes": task_minutes,
        # Partial credit: Harbor rewards can be graduated, so don't require 1.0.
        "functional_pass_threshold": 0.99,
        "prompt": prompt,
        "verify": verify_block,
    }

    _write_task_yaml(dest_dir / "task.yaml", task_yaml, source="Terminal-Bench", warnings=warnings)
    return ImportedTask(
        source_id=source_dir.name, native_id=native_id, dest_dir=dest_dir,
        image=image, warnings=warnings,
    )


def _parse_dockerfile_copy_sources(dockerfile_text: str) -> list[str]:
    """Return the build-context source paths named in a Dockerfile's COPY/ADD
    instructions.

    A ``COPY a b /dest`` line copies build-context files ``a`` and ``b`` into the
    image; the LAST token is the destination and the rest are sources. We:
      * handle line continuations (``\\``),
      * skip ``COPY --from=<stage> …`` (those copy from another build stage, not
        the build context, so there's no local file to seed),
      * drop flags like ``--chown=…`` / ``--chmod=…``,
      * ignore glob/URL sources we can't resolve to a single local file.
    Only the source tokens are returned (destinations are irrelevant on the host).
    """
    # Join continuation lines.
    joined = re.sub(r"\\\s*\n", " ", dockerfile_text)
    sources: list[str] = []
    for line in joined.splitlines():
        s = line.strip()
        if not re.match(r"^(COPY|ADD)\b", s, re.I):
            continue
        tokens = s.split()[1:]  # drop COPY/ADD
        # Skip --from=<stage> copies (not build-context files) and strip flags.
        if any(t.lower().startswith("--from=") for t in tokens):
            continue
        tokens = [t for t in tokens if not t.startswith("--")]
        if len(tokens) < 2:
            continue
        # Last token is the destination; the rest are sources.
        for src in tokens[:-1]:
            # Skip remote sources and obvious globs we can't map to one file.
            if src.startswith(("http://", "https://")) or any(c in src for c in "*?["):
                continue
            sources.append(src)
    return sources


def _seed_dockerfile_inputs(source_dir: Path, dest_dir: Path) -> list[str]:
    """Copy the task's input files (named in the environment Dockerfile's COPY
    lines) into ``dest_dir/inputs/``. Returns the list of seeded file names.

    These are the files the task expects to read at its working dir (``/app``).
    Seeding only the COPY'd sources — not all of ``environment/`` — avoids
    leaking non-inputs (e.g. a reference-solution source that is present in the
    context but never COPYed into the image).
    """
    env_dir = source_dir / "environment"
    dockerfile = env_dir / "Dockerfile"
    if not dockerfile.is_file():
        dockerfile = source_dir / "Dockerfile"
        env_dir = source_dir
    if not dockerfile.is_file():
        return []

    try:
        text = dockerfile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    seeded: list[str] = []
    inputs_dir = dest_dir / "inputs"
    for src in _parse_dockerfile_copy_sources(text):
        # Resolve the source relative to the build context (environment/). Guard
        # against path traversal escaping the context dir.
        candidate = (env_dir / src).resolve()
        try:
            candidate.relative_to(env_dir.resolve())
        except ValueError:
            continue
        if not candidate.is_file():
            continue  # skip directories / missing (kept simple: file inputs only)
        inputs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, inputs_dir / candidate.name)
        seeded.append(candidate.name)
    return seeded


def _build_prompt(instruction: str, *, seeded_inputs: list[str] | None = None) -> str:
    prompt = (
        f"{instruction}\n\n"
        "---\n"
        "Working agreement for this benchmark: place ALL files you create or "
        "modify to solve the task under a top-level `src/` directory in the "
        "workspace. Your solution in `src/` is copied into the task's container "
        "and graded by its own hidden test suite, so the layout inside `src/` "
        "must match what the task expects at its working directory."
    )
    if seeded_inputs:
        files = ", ".join(f"`{n}`" for n in seeded_inputs)
        prompt += (
            "\n\n"
            "The task refers to input files by absolute paths under `/app` (e.g. "
            "`/app/decomp.c`). In this environment there is no `/app`: those input "
            f"files ({files}) have already been placed in your workspace directory "
            "(your current working directory). Read them from there — do NOT search "
            "the filesystem for them. Treat `/app` in the instruction as your "
            "workspace root, and put your solution under `src/` as above."
        )
    return prompt


def _first_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:200]
    return "Imported Terminal-Bench task"


def _write_task_yaml(path: Path, data: dict, *, source: str, warnings: list[str]) -> None:
    header = [f"# Imported from a {source} task by agent-cost-bench.", "#"]
    for w in warnings:
        header.append(f"# WARNING: {w}")
    if warnings:
        header.append("#")
    body = dump_task_yaml(data)
    path.write_text("\n".join(header) + "\n" + body, encoding="utf-8")
