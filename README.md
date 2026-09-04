# agent-cost-bench

**How much does the same model cost across different coding CLIs? Which model delivers the best quality for your actual codebase?** agent-cost-bench answers both questions in a single run.

Bring any model, any CLI, and any use case — a real GitHub repo with your own verification tests — and agent-cost-bench will measure cost, quality, and latency side by side. Checkout a video of how to run this repo [here of how to compare development agents.](https://www.youtube.com/watch?v=rFoeg-cXhWs)

## What you can do

| Question | Mode | Example |
|----------|------|---------|
| How does Sonnet 4.6 compare in Kiro vs Claude Code vs Copilot vs Codex? | `cli-compare` | Compare USD cost, latency, and pass rate for the same tasks |
| How do Opus, Sonnet, and other models stack up inside the Kiro CLI? | `model-compare` | Compare quality scores + cost across models |
| Does GPT-5.5 through Codex beat Sonnet 4.6 through Kiro on *my* brownfield repo? | `cli-compare` | Clone your repo into the task workspace; verify with your own tests |

The framework is designed to be flexible:

- **Any CLI** — Kiro, Claude Code, GitHub Copilot, Cursor, OpenAI Codex, Antigravity, Devin - Currently supported CLI's.
- **Any model** — Anthropic (Claude), OpenAI (o-series, GPT-5.x) or anything your CLI exposes.
- **Any use case** — greenfield tasks included out of the box, or bring your own GitHub repo (public or private). The framework clones it, hands it to the model, and verifies the result.
- **Multiple verification options** — pytest, Docker containers, custom scorers, or LLM-judge rubrics. Pick the one that fits; no verification code is required for rubric-graded tasks.

Cost is always reported two ways: USD and native units (credits / AI Credits / tokens).

## Prerequisites

- **Python 3.10+**
- **The coding CLI(s) you want to benchmark**, installed and logged in:
  - `cli-compare`: the CLIs you list as runners (e.g. `kiro-cli`, `claude`, `copilot`, `agent`, `codex`, `agy`, `devin`)
  - `model-compare`: the Kiro CLI
- **Docker** — only if you run the multi-language tasks (C#/.NET, Java,
  TypeScript, Terraform, Helm). Build images once with `./tasks/docker/build-images.sh`.
  Alternatively, set `CONTAINER_RUNTIME=finch` to use [Finch](https://github.com/runfinch/finch)
  instead of Docker (default is `docker`). When using Finch, set `workspace_base`
  in your config to a path under your home directory (e.g. `~/bench-workspaces`)
  since Finch on macOS can only mount volumes from the home directory.

> **Cost warning:** Each CLI you benchmark requires your own active subscription or license (Kiro, Claude Code, GitHub Copilot, Cursor, OpenAI Codex, Devin, etc.). Running benchmarks consumes credits, tokens, or premium requests against your account. A full run across all tasks can use significant resources. Start with a small subset (`task_ids:`) to estimate cost before running the full suite.
> **Note:** Checkout a video of how to run this repo [here of how to compare development agents.](https://www.youtube.com/watch?v=rFoeg-cXhWs)

## Install

```bash
git clone <repo link>
cd sample-agent-cost-bench
pip install -e .            # installs the `agent-cost-bench` command
pip install -e ".[dev]"     # optional: dev/test extras
```

## Quick start

### Step 1: Copy an example config

Example configs are provided as templates. **Copy them and fill in your specific details** — never edit the `*.example.yaml` files directly (they serve as reference).

```bash
# For CLI comparison (Kiro vs Claude Code vs Copilot vs Cursor vs Codex vs Devin):
cp config.cli-compare.example.yaml config.cli-compare.yaml

# For model comparison (multiple models inside the Kiro CLI):
cp config.model-compare.example.yaml config.model-compare.yaml
```

Then edit your copy with your specific paths, model IDs, and pricing rates (see below).

### Step 2: Set up authentication

Each CLI reads its API key from standard environment variables. Set these in your shell before running:

```bash
export KIRO_API_KEY=...          # Kiro (or use `kiro-cli login`)
export ANTHROPIC_API_KEY=...     # Claude Code (or use `claude login`)
export GITHUB_TOKEN=...          # Copilot (or use `copilot auth login`)
export CURSOR_API_KEY=...        # Cursor (or use `cursor login`)
export OPENAI_API_KEY=...        # Codex (or use `codex auth login`)
# Antigravity: use `agy login`
# Devin: use `devin auth login` (no env-var equivalent)
```

The harness inherits the parent shell's environment, so all CLIs pick up their keys automatically — no per-runner `env:` block needed.

### Step 3: Configure pricing

Pricing rates are volatile and change over time. Check each vendor's current pricing page before running. The example configs include inline comments with rates that were current at the time of writing, but **you are responsible for verifying these match your subscription tier and current published rates**.

#### Pricing reference (verify before use)

| CLI | Pricing config | Reference |
|-----|----------------|-----------|
| **Kiro** | `usd_per_credit: 0.04` | Credits consumed fractionally per task; check your plan's credit value |
| **Claude Code** | No pricing config needed — reports `total_cost_usd` directly | Direct API billing; cost reported in CLI JSON output |
| **GitHub Copilot** | No pricing config needed — cost derived from AI-credit (AIU) telemetry in the JSON output, 1 AIU = $0.01 USD |
| **Cursor** | Token-level rates (see below) | [cursor.com/docs/models-and-pricing](https://cursor.com/docs/models-and-pricing) |
| **OpenAI Codex** | Token-level rates (see below) | [platform.openai.com/docs/pricing](https://platform.openai.com/docs/pricing) |
| **Antigravity** | Token-level rates (see below) | Verify the per-token rates for your chosen `agy` model |
| **Devin** | Token-level rates (see below) | `devin models list` prints per-MTok rates per model slug |

#### Token-level pricing (Cursor, Codex, and Devin)

These CLIs report raw token counts; the harness computes cost using rates you supply. Example for Cursor with Opus 4.8:

```yaml
pricing:
  usd_per_input_token:        0.000005     # $5.00  / 1M (fresh input)
  usd_per_cache_write_token:  0.00000625   # $6.25  / 1M (cache write)
  usd_per_cached_input_token: 0.0000005    # $0.50  / 1M (cache read)
  usd_per_output_token:       0.000025     # $25.00 / 1M
```

Example for Codex with GPT-5.5:

```yaml
pricing:
  usd_per_input_token:        0.000005     # $5.00  / 1M
  usd_per_cached_input_token: 0.0000005    # $0.50  / 1M
  usd_per_output_token:       0.000030     # $30.00 / 1M
```

> **Important:** These rates change. Always cross-reference with the vendor's pricing page. Different models have different rates — update the pricing block when you change `model_id`.

#### Cost source auto-detection

The harness automatically detects how to read cost from each CLI based on its binary name

### cli-compare — same tasks, different CLIs

*"How much does Sonnet 4.6 cost through Kiro vs Claude Code vs Copilot? How does Opus 4.8 compare across all four CLIs plus Cursor?"*

```bash
agent-cost-bench cli-compare run config.cli-compare.yaml
```

The example config defines runners for Kiro, Claude Code, Copilot, Cursor, Antigravity, and Devin. Cost is auto-detected from the binary name — you provide the CLI path, model ID, and pricing rates:

```yaml
runners:
  - name: kiro
    display_name: "Kiro (claude-opus-4.8)"
    cli_path: kiro-cli
    model_id: claude-opus-4.8
    pricing:
      usd_per_credit: 0.04
    cli_base_args: [chat, --no-interactive, --trust-all-tools,
                    "--model={model}", "--effort={effort}"]

  - name: claude-code
    display_name: "Claude Code (claude-opus-4.8)"
    cli_path: claude
    model_id: us.anthropic.claude-opus-4-8
    cli_base_args: ["-p", "{prompt}", "--output-format", "json",
                    "--model", "{model}", "--dangerously-skip-permissions",
                    "--effort", "{effort}"]

  - name: copilot
    display_name: "GitHub Copilot (claude-opus-4.8)"
    cli_path: copilot
    model_id: claude-opus-4.8
    pricing:
      usd_per_premium_request: 0.04
    cli_base_args: ["-p", "{prompt}", "--model", "{model}",
                    "--allow-all-tools", "--output-format", "json",
                    "--effort", "{effort}"]

  - name: cursor
    display_name: "Cursor (claude-opus-4.8)"
    cli_path: agent
    model_id: claude-opus-4-8
    pricing:
      usd_per_input_token:        0.000005
      usd_per_cache_write_token:  0.00000625
      usd_per_cached_input_token: 0.0000005
      usd_per_output_token:       0.000025
    cli_base_args: ["-p", "{prompt}", "--trust", "--yolo",
                    "--output-format", "json", "--model", "{model}"]

  - name: devin
    display_name: "Devin (claude-opus-4.8)"
    cli_path: devin
    model_id: claude-opus-4-8
    pricing:
      usd_per_input_token:        0.000005
      usd_per_cached_input_token: 0.0000005
      usd_per_output_token:       0.000025
      devin_export_file: devin-usage.json
    cli_base_args: ["-p", "{prompt}", "--model", "{model}",
                    "--export", "devin-usage.json"]
```

> **Note:** Cursor, Devin, and Antigravity encode effort/thinking level as part of the model slug (e.g., `claude-opus-4-8-high`, `gemini-3.8-flash-high`), not as a separate flag. The harness auto-appends the task's effort level to the `model_id` unless you bake it in yourself. This is what keeps a cross-CLI run fair — every runner ends up on the same model at the same reasoning effort even though they spell it differently.

#### Antigravity specifics

The Antigravity CLI (`agy`) reports cost from `agy -p "<prompt>" --output-format json`, which prints a single JSON object with a `usage` block (`input_tokens`, `output_tokens`, `thinking_tokens`, `cache_read_tokens`). Cost is computed per-token like Cursor/Codex: `input_tokens × input_rate + cache_read_tokens × cached_rate + output_tokens × output_rate`. `thinking_tokens` is a subset of `output_tokens` and is reported but not billed separately.

Like Cursor and Devin, Antigravity bakes the reasoning effort **into the model slug** rather than taking a separate `--effort` flag. `agy models` lists ids such as `gemini-3.8-flash-high` / `-medium` / `-low`, `gemini-3.1-pro-high` / `-low`, and `gpt-oss-120b-medium`. So the runner passes only `--model`, and you either set `model_id` to a full slug that already carries the effort, or set it to the base slug (`gemini-3.8-flash`) and let the harness append the task's effort (`-high`/`-medium`/`-low`) — the same mechanism used for Cursor and Devin, which keeps a cross-CLI run fair.

```yaml
- name: antigravity
  display_name: "Antigravity (gemini-3.8-flash)"
  cli_path: agy
  model_id: gemini-3.8-flash   # base slug; harness appends the effort (-high/…)
  cost_source: antigravity_json
  pricing:
    usd_per_input_token:  0.00000075   # $0.75 / 1M (fresh input)
    usd_per_output_token: 0.00000375   # $3.75 / 1M
    # usd_per_cached_input_token:       # add from the Gemini API pricing page
  cli_base_args: ["-p", "{prompt}", "--output-format", "json",
                  "--model", "{model}", "--add-dir", "{workspace}",
                  "--print-timeout", "30m",
                  "--dangerously-skip-permissions"]
```

The rates above are Gemini 3.8 Flash's introductory pricing ($0.75/1M input, $3.75/1M output) from [Google's announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/). Content was rephrased for compliance with licensing restrictions.

> **Caveat:** These are introductory rates and may change — verify against the current Gemini API pricing page before trusting cost numbers, and update the block whenever you change `model_id`. The announcement publishes no cache-read rate, so `usd_per_cached_input_token` is left unset and cache reads fall back to the full input rate; supply it from the API pricing page (Gemini cached input is typically 25% of the input rate) to avoid overstating cost in agentic runs where most prompt tokens are cache hits.

Two `agy`-specific flags in the block above are **not optional** for the benchmark — leaving either out produces a failing run that looks like a model failure:

- **`--add-dir {workspace}`** — `agy` ignores the process working directory and writes generated files into its own managed scratch dir (`~/.gemini/antigravity-cli/...`) unless the run workspace is passed as an **absolute** path via `--add-dir`. The harness substitutes `{workspace}` with the run's absolute workspace path so files land where the verifier looks. A relative `.` does **not** work — `agy` resolves it against its scratch dir, not cwd. Without this, verification finds no code and scores 0%.
- **`--print-timeout 30m`** — `agy`'s print mode aborts itself after **5 minutes** by default and returns `{"status":"ERROR","error":"timeout waiting for response"}` with a partial or empty result. Large tasks need longer, so raise it to comfortably exceed the harness `timeout_minutes`. This is `agy`'s own timeout, independent of the harness timeout. Symptom when too low: a truncated result and a low pass rate from partial files.

**Tips for running Antigravity:**

- **Log in first** with `agy login`, and confirm your account can use the model you set — run `agy models` and copy an exact id (base slug like `gemini-3.8-flash`, or a full slug like `gemini-3.8-flash-high`).
- **Expect slower wall-clock times.** In practice Gemini 3.8 Flash spent several minutes on the larger multi-file tasks. Budget headroom in both `--print-timeout` and the harness `timeout_minutes`.
- **Sanity-check the result status** in the run log's `RESPONSE` block: it should read `"status":"SUCCESS"`, not `"status":"ERROR"`. An `ABNORMAL EXIT ... exit 1` line for the antigravity target means `agy` returned a non-success result — read the `error` field to see why. Two common ones:
  - `"timeout waiting for response"` → the print timeout was hit; raise `--print-timeout`.
  - `"Individual quota reached. Please upgrade your subscription..."` → your Antigravity account hit its usage quota (the message includes when it resets). This is an account limit, not a config problem — the run will score 0% until the quota resets or you upgrade. Watch for this when running several large tasks in a row.
- **If the pass rate is unexpectedly 0%**, first read the `RESPONSE` status/error (quota or timeout above), then check where files landed. If the response's `file://` links point under `~/.gemini/antigravity-cli/` instead of the run workspace, `--add-dir {workspace}` is missing or was passed as a relative path.
- **Cost is derived from token counts, not a billed dollar figure** (`agy` reports no `total_cost_usd`), so accuracy depends entirely on the per-token rates you configure. Update them whenever you change `model_id`.

#### Devin specifics

Devin has no JSON output mode, so cost comes from the ATIF conversation export written by `--export <file>`. The path is relative to the CLI's working directory (the run's workspace), and `pricing.devin_export_file` must match the `--export` filename so the parser can find it.

`devin models list` publishes only input and output rates (`--format json` exposes the same `cost_summary` string and nothing more), so **you must supply `usd_per_cached_input_token` yourself** — use the underlying provider's published cache-read price. This matters more than it looks: `total_prompt_tokens` is inclusive of `total_cached_tokens`, and cache reads are typically ~90% of prompt tokens in an agentic run. Omitting the rate makes the parser fall back to the full input price and overstates Devin's cost by roughly 5x, which would make a CLI comparison meaningless.

Devin's non-interactive mode **silently rejects any tool call that would need approval**, which would fail every task. Rather than hand it a blanket auto-approve flag, the harness copies a scoped permission policy into each workspace as `.devin/config.json`:

```yaml
devin_permissions_file: tasks/devin/config.json   # default
```

The shipped policy allows workspace reads/writes plus an explicit allowlist of build and test commands (`python`, `pytest`, `npm`, `go`, `cargo`, `make`, `git`, common POSIX utilities, …) and **denies** credential paths (`~/.ssh`, `~/.aws`, `**/.env`, `**/*.pem`), config-directory writes, and `sudo` / `ssh` / `git push` / `gh` / `aws`. Deny rules win over allow rules. If your tasks need a command that isn't listed, add an `Exec(<command>)` entry — an unlisted command is rejected, not prompted. Set `devin_permissions_file: ""` to skip the copy entirely.

The policy allows the shell, which makes that deny list a speed bump rather than a boundary: `bash -c "<denied command>"` still runs, because the inner command is only an argument. Containment comes from the disposable per-run workspace, not from the policy — do not run the suite against a `workspace_base` holding anything you care about. Denying the shell was tried and rejected: an allowlist cannot be both airtight and complete across a heterogeneous task suite, and the gaps scored as model failures rather than policy failures. For the same reason `curl`/`wget` are **allowed** — denying them bought nothing once the shell was permitted, while the other runners already have network access under `--trust-all-tools` / `--dangerously-skip-permissions`, so the deny only manufactured a capability gap in the runner being measured. Egress restriction, if you want it, belongs at the sandbox or network layer and must apply to every runner equally. `tasks/devin/config.json` documents the full reasoning and the CLI's exact matching semantics.

Print mode cannot display Devin's interactive workspace-trust prompt and aborts in an untrusted directory. Trust is inherited by child directories, so run `devin` once interactively in your `workspace_base` and approve it — every per-run workspace created underneath is then trusted, and no flag is needed. Prefer this to `--respect-workspace-trust false`, which turns the check off for the whole run; add the flag only where nobody can approve interactively, such as CI.

> Do **not** point Devin's `--config` flag at a file you intend to commit: the CLI writes session state (including your `org_id`) back into it.

### model-compare — same CLI, different models

*"Which model gives the best quality inside the Kiro CLI?"*

```bash
agent-cost-bench model-compare run config.model-compare.yaml
```

```yaml
models:
  - claude-opus-4.8
  - claude-sonnet-4.6
  - deepseek-3.2
pricing: { usd_per_credit: 0.04 }
judge_model: claude-opus-4.8    # grades rubric + spec quality tasks
modes: ["vibe"]                 # or ["vibe", "spec-driven"]
```

### Bring your own repo

Any task can reference a GitHub repository. The framework clones it (cached across models), places it in the workspace, and the model works against your real code:

```yaml
# task.yaml
id: fix-my-auth-bug
mode: vibe
prompt: "Fix the failing test in tests/test_auth.py"
effort: medium            # low / medium / high — per-task, based on complexity
repo:
  url: https://github.com/my-org/my-service.git
  ref: a1b2c3d4e5f6...   # pin to a commit SHA for reproducibility
  token_env: GITHUB_TOKEN # for private repos
verify:
  runner: pytest
  deps: [pytest, httpx]
```

### Effort level

Set `effort` in each task's `task.yaml` to control how much reasoning the model applies:

```yaml
# Simple formatting task — low reasoning is fine
effort: low

# Complex multi-file refactor — give the model time to think
effort: high
```

Valid values: `low`, `medium`, `high` (default: `high`). A run-level fallback (`effort:` in the main config) still works for backward compatibility — per-task settings override it.

### Useful commands

```bash
agent-cost-bench cli-compare validate config.cli-compare.example.yaml        # check setup
agent-cost-bench model-compare list-tasks config.model-compare.example.yaml  # see tasks
agent-cost-bench report results/<run_id>.json                                # rebuild HTML
agent-cost-bench new-task my-task                                            # scaffold (rubric)
agent-cost-bench new-task my-task --with-tests                               # scaffold (pytest)
```

Reports (HTML + JSON) are written to `results/` and open automatically.

## Included tasks

Tasks live under `tasks/`. Two types:

- **vibe** — a single prompt; the model produces code that is verified. Run by both modes.
- **spec-driven** — full spec workflow (requirements → design → tasks → implementation). Model-compare only.

| Task | Type | Domain | What it tests |
|------|------|--------|---------------|
| `rest-api` | vibe | Python / FastAPI | Greenfield: CRUD Todo REST API |
| `dashboard` | vibe | Python + HTML/JS | Greenfield: full-stack Todo dashboard |
| `log-analyzer-cli` | vibe | Python | Greenfield: parse access logs into JSON |
| `note-cli` | vibe | Python | Greenfield: note-taking CLI (rubric graded) |
| `dockerize-flask` | vibe | Docker | Brownfield: add Dockerfile + compose |
| `terraform-s3` | vibe | Terraform / AWS | Provision a secure S3 bucket |
| `terraform-serverless-spa` | vibe | Terraform / AWS | Serverless SPA stack |
| `helm-chart` | vibe | Helm / K8s | Production-ready Helm chart |
| `harden-k8s` | vibe | Kubernetes | Brownfield: security-harden manifests |
| `dotnet-invoicing` | vibe | C#/.NET (Docker) | Brownfield: fix invoice-pricing bugs |
| `java-ratelimiter` | vibe | Java (Docker) | Brownfield: fix rate-limiter bugs |
| `typescript-circuit-breaker` | vibe | TypeScript (Docker) | Brownfield: fix circuit-breaker bugs |
| `bedrock-sentiment` | vibe | AWS / Python | Migrate Comprehend → Bedrock (rubric graded) |
| `geotrack-duplicate-device` | vibe | Vue.js / AWS | Prevent duplicate IoT device assignment (rubric) |
| `event-sourcing-cqrs` | vibe | Python (stdlib) | Greenfield high-complexity: event-sourcing/CQRS bank system (7 files, 32 tests) |
| `multitenant-rbac-api` | vibe | Python / FastAPI | Greenfield high-complexity: multi-tenant RBAC document API (7 files, 30 tests) |
| `multitenant-workflow-engine` | vibe | Python / FastAPI | Greenfield high-complexity: workflow state machine + SLA tracking (9 files, 38 tests) |
| `distributed-task-processor` | vibe | Python / FastAPI | Greenfield high-complexity: plugin task processor + event bus (12 files, 52 tests) |
| `ecommerce-order-saga` | vibe | Python / FastAPI | Greenfield high-complexity: order saga with compensation (15 files, 66 tests) |
| `ml-pipeline-orchestrator` | vibe | Python / FastAPI | Greenfield high-complexity: ML pipeline orchestrator + registry (14 files, 64 tests) |
| `platform-as-a-service` | vibe | Python / FastAPI | Greenfield high-complexity: multi-tenant PaaS backend (16 files, 72 tests) |
| `auth-feature` | spec-driven | Python | JWT auth: login, logout, refresh |

Select tasks with `task_ids:` in your config. Omit it to run everything.

> Rubric-graded tasks need `judge_model`. Docker tasks need Docker + prebuilt images.
> The seven high-complexity tasks (`event-sourcing-cqrs` through `platform-as-a-service`) are greenfield multi-file applications (7-16 files, 30-72 pytest scenarios each) that stress multi-file architecture and cross-cutting concerns; they take ~5-22 min per run versus under 2 min for the single-file tasks.

## How verification works

After a model finishes a task, the framework scores its output. Four options — pick what fits your task:

### 1. Python tests (`verify: { runner: pytest }`)

Put test files in the task's `verify/` folder (the model never sees them). List pip dependencies under `deps`. The framework handles the venv.

```yaml
verify:
  runner: pytest
  deps: ["fastapi==0.104.1", "httpx==0.27.2", "pytest==9.0.3"]
```

### 2. Custom scorer (`verify: { runner: local }`)

Write `verify/score.py` to inspect the workspace and print a graduated score.

```yaml
verify:
  runner: local
  deps: ["python-hcl2==4.3.5"]
  score: verify/score.py
```

### 3. Docker (`verify: { image: ... }`)

For non-Python tasks. Tests run in a prebuilt image — no local toolchain needed.

```yaml
verify:
  image: agent-cost-bench-node:20
  parser: vitest-json
  workdir: src
  tests_subdir: verify/tests
  test_cmd: 'vitest run --reporter=json --outputFile="$RESULTS_DIR/vitest.json"'
```

### 4. LLM judge rubric (`quality.rubric`)

No verification code needed. List plain-English criteria and the judge grades each one.

```yaml
quality:
  rubric:
    - "notes_cli.py is created in the workspace"
    - "'add <text>' appends the note as a new line to notes.txt"
    - "'search' is case-insensitive"
```

### Partial credit

Any verifier can report a graduated score (0.0–1.0):

```
AGENT_COST_BENCH_RESULT: {"score": 0.7, "checkpoints": {...}, "summary": "..."}
```

### Pass threshold

`functional_pass_threshold` in `task.yaml` sets the score needed for a PASS (default: 0.99). Lower it for rubric tasks that rarely need perfection.

## Supported CLIs and cost detection

| Binary name | What it reads |
|-------------|---------------|
| `kiro` / `kiro-cli` | `Credits: X • Time: Ys` telemetry line |
| `claude` | `--output-format json` → `total_cost_usd` |
| `copilot` | `--output-format json` JSONL + `~/.copilot/session-state/` `totalNanoAiu` |
| `codex` | `codex exec --json` → `turn.completed` token counts |
| `cursor` / `agent` | `-p --output-format json` → `usage` object with token counts |
| `agy` / `antigravity` | `-p --output-format json` → `usage` object with token counts |
| `devin` | `--export <file>` ATIF conversation export → `final_metrics` token counts |
| Any + per-token pricing | Custom regex with `(?P<input>...)` / `(?P<output>...)` groups |


## Run the test suite

```bash
pytest    # unit + integration; uses a MockCLI, no network or real CLI needed
```

## Troubleshooting

- **Spec runs hang** — native spec mode needs a TTY. The harness uses PTY by default (`spec_use_pty: true`). If your CLI reads from stdin, set `spec_prompt_via_stdin: true`.
- **Docker task fails** — run `agent-cost-bench <mode> validate <config>` to check images; build missing ones with `./tasks/docker/build-images.sh`.
- **Offline restore fails** — allow network for verification: `AGENT_COST_BENCH_VERIFY_NETWORK=bridge agent-cost-bench <mode> run <config>`.
