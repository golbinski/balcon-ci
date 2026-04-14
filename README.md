# BalconCI

Agentic code review and analysis pipeline for GitHub Actions. A multi-agent system that reviews pull requests, verifies findings, triages issues, and optionally commits automated fixes — all within a configurable blast radius, with a human always in the loop at the end.

---

## Table of contents

- [How it works](#how-it-works)
- [Pipeline modes](#pipeline-modes)
- [Agents](#agents)
- [Getting started](#getting-started)
  - [1. Add caller workflows to your repository](#1-add-caller-workflows-to-your-repository)
  - [2. Add secrets and variables](#2-add-secrets-and-variables)
  - [3. Create your configuration file](#3-create-your-configuration-file)
- [Configuration reference](#configuration-reference)
  - [Agent fields](#agent-fields)
  - [Scanner](#scanner)
  - [Verifier](#verifier)
  - [Triage](#triage)
  - [Fixer](#fixer)
  - [Reviewer](#reviewer)
  - [Codebase scanning](#codebase-scanning)
- [LLM providers](#llm-providers)
  - [Anthropic (direct)](#anthropic-direct)
  - [Amazon Bedrock](#amazon-bedrock)
- [Environment variables](#environment-variables)
- [Dry-run mode](#dry-run-mode)
- [Safety constraints](#safety-constraints)
- [Instruction and context files](#instruction-and-context-files)
- [Local development](#local-development)
- [Contributing](#contributing)

---

## How it works

BalconCI runs inside GitHub Actions. When triggered, it assembles a pipeline of specialised agents and passes a shared list of `Finding` objects through them. Each agent annotates the findings with its own output (verified status, triage decision, fix result, review verdict). GitHub itself is the state store — no external database required.

```
PR diff / codebase chunks
         │
         ▼
    ┌─────────┐
    │ Scanner │  Statler — finds potential issues
    └────┬────┘
         │ validate
         ▼
    ┌──────────┐
    │ Verifier │  Waldorf — challenges findings, eliminates hallucinations
    └────┬─────┘
         │ validate
         ▼
    ┌────────┐
    │ Triage │  Sam — routes each finding: auto_fix / human_issue / skip
    └────┬───┘
         │ validate
         ▼
    ┌───────┐          (review+fix and scan modes only)
    │ Fixer │  Fozzie — attempts automated fixes within blast radius
    └────┬──┘
         │
         ▼
    ┌──────────┐
    │ Reviewer │  Kermit — reviews output, iterates, marks ready for human
    └──────────┘
         │
         ▼
    PR comments / GitHub issues / fix commits
    (human takes responsibility — no auto-merge, ever)
```

---

## Pipeline modes

| Mode | Trigger | What happens |
|---|---|---|
| `review` | PR label `balcon-ci:review` or comment `/balcon-ci review` | Read-only. Agents post findings as PR comments. No code changes. |
| `review+fix` | PR label `balcon-ci:review+fix` or comment `/balcon-ci fix` | Review plus agent-authored commits pushed to the PR branch. Requires explicit developer opt-in. |
| `scan` | Cron schedule or `workflow_dispatch` | Repo-wide analysis via codebase embeddings (arborist-mcp). Can open GitHub issues or new fix PRs. |

Human-raised PRs are never modified without explicit opt-in (`review+fix`). Only `scan` mode opens PRs autonomously.

---

## Agents

| Role | Default name | Responsibility |
|---|---|---|
| `scanner` | Statler | Finds potential issues in the diff or semantic code chunks |
| `verifier` | Waldorf | Challenges scanner findings, cross-checks evidence, adjusts confidence |
| `triage` | Sam | Routes each finding: `auto_fix`, `human_issue`, or `skip` |
| `fixer` | Fozzie | Attempts automated fixes within configured blast radius |
| `reviewer` | Kermit | Reviews fixer output, iterates up to `max_iterations`, marks PR ready for human |

Agent names are configurable — they appear in GitHub comments and workflow logs.

---

## Getting started

### 1. Add caller workflows to your repository

BalconCI exposes three [reusable workflows](https://docs.github.com/en/actions/sharing-automations/reusing-workflows). You do not copy or subtree any code — consuming repos simply call the centralised workflows by reference. The harness is installed at runtime directly from the `balcon-ci` repository.

Copy the example caller files from [`examples/`](examples/) into `.github/workflows/` in your repository and replace `your-org` with your GitHub organisation name:

| Example file | Copy to | Purpose |
|---|---|---|
| [`examples/review.yml`](examples/review.yml) | `.github/workflows/balcon-review.yml` | Read-only PR review |
| [`examples/review-fix.yml`](examples/review-fix.yml) | `.github/workflows/balcon-review-fix.yml` | PR review with automated fix commits |
| [`examples/scan.yml`](examples/scan.yml) | `.github/workflows/balcon-scan.yml` | Periodic codebase scan |

Add only the modes you want to use. The trigger conditions (label, comment, cron) live entirely in your caller workflow — you are free to customise them.

To pin to a specific release instead of `main`, set `harness_ref` in the caller:

```yaml
uses: your-org/balcon-ci/.github/workflows/balcon-review.yml@v1.0.0
with:
  harness_ref: v1.0.0
```

### 2. Add secrets and variables

In your repository's **Settings → Secrets and variables → Actions**:

| Name | Type | When required |
|---|---|---|
| `ANTHROPIC_API_KEY` | Secret | When using `BALCON_LLM_PROVIDER=anthropic` (default) |
| `BALCON_TOKEN_BUDGET` | Variable | Optional — overrides the default 500,000 token budget |
| `BALCON_MODEL` | Variable | Optional — overrides the default model |

AWS credentials for Bedrock are supplied via an IAM role attached to the Actions runner — no secrets needed.

### 3. Create your configuration file

Create `.github/balcon-ci.yml` in your repository. All fields are optional — BalconCI works with defaults, but you will get better results by providing project-specific context and instructions.

```yaml
agents:

  scanner:
    name: statler
    instructions:
      - .github/balcon-ci/statler-instructions.md
    context:
      - docs/coding-standards.md
    min_severity: medium

  verifier:
    name: waldorf
    confidence_threshold: 0.75

  triage:
    name: sam
    always_escalate:
      - "race condition"
      - "security vulnerability"

  fixer:
    name: fozzie
    eligible_categories:
      - "missing null check"
      - "unused variable"
    max_files_changed: 3
    max_lines_changed: 50

  reviewer:
    name: kermit
    max_iterations: 3

codebase:
  scanning:
    queries:
      - "raw owning pointers stored as class members without RAII wrapper"
      - "shared mutable state accessed without lock"
    exclude_paths:
      - "third_party/**"
      - "**/*.generated.cpp"
```

---

## Configuration reference

### Agent fields

These fields apply to every agent:

| Field | Required | Description |
|---|---|---|
| `name` | no | Display name in GitHub comments and logs. Defaults to role name. |
| `instructions` | no | Repo-relative paths to Markdown files that shape how the agent behaves. Injected into the system prompt. |
| `context` | no | Repo-relative paths to reference documents the agent should know (standards, specs, policies). Injected as knowledge alongside the payload. |

### Scanner

| Field | Default | Description |
|---|---|---|
| `min_severity` | `low` | Minimum severity to report: `low`, `medium`, `high`, `critical`. |

### Verifier

| Field | Default | Description |
|---|---|---|
| `confidence_threshold` | `0.5` | Minimum confidence (0.0–1.0) to pass a finding without escalation. |

### Triage

| Field | Default | Description |
|---|---|---|
| `always_escalate` | `[]` | List of category patterns that always route to `human_issue`, regardless of confidence. Matched semantically. |

### Fixer

| Field | Default | Description |
|---|---|---|
| `eligible_categories` | `[]` | Categories the fixer is permitted to attempt. Matched semantically. If empty, all `auto_fix` findings are eligible. |
| `max_files_changed` | `5` | Hard blast radius limit. Exceeding this downgrades the fix to a GitHub issue. |
| `max_lines_changed` | `100` | Hard blast radius limit. Same behaviour. |

### Reviewer

| Field | Default | Description |
|---|---|---|
| `max_iterations` | `3` | Maximum fixer/reviewer feedback cycles. Exceeding this marks the PR as needing human review. |

### Codebase scanning

| Field | Description |
|---|---|
| `codebase.scanning.queries` | Natural language queries run against the arborist-mcp embedding index in `scan` mode. |
| `codebase.scanning.exclude_paths` | Glob patterns excluded from scanning (e.g. `third_party/**`). |

---

## LLM providers

### Anthropic (direct)

The default. Uses the `anthropic` Python SDK directly.

```bash
BALCON_LLM_PROVIDER=anthropic          # default, can be omitted
BALCON_MODEL=claude-sonnet-4-6         # default
ANTHROPIC_API_KEY=sk-ant-...
```

### Amazon Bedrock

Routes through AWS Bedrock using the `anthropic[bedrock]` SDK extra. Supports Anthropic Claude models on Bedrock only. Authentication is via the Actions runner's IAM role — no API key secret required.

```bash
BALCON_LLM_PROVIDER=bedrock
BALCON_MODEL=anthropic.claude-3-5-sonnet-20241022-v2:0
AWS_REGION=us-east-1                   # default
```

Install with the Bedrock extra when using this provider:

```bash
pip install ".[bedrock]"
```

In your workflow, replace `pip install .` with `pip install ".[bedrock]"`.

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | yes | — | Supplied automatically by GitHub Actions |
| `ANTHROPIC_API_KEY` | provider-dependent | — | Required when `BALCON_LLM_PROVIDER=anthropic` |
| `BALCON_LLM_PROVIDER` | no | `anthropic` | LLM provider: `anthropic` or `bedrock` |
| `BALCON_MODEL` | no | `claude-sonnet-4-6` | Model ID (format depends on provider) |
| `BALCON_TOKEN_BUDGET` | no | `500000` | Maximum tokens per pipeline run. Exceeding this triggers a circuit break. |
| `BALCON_DRY_RUN` | no | `0` | Set to `1` to suppress all GitHub writes and output to Job Summary instead. |

---

## Dry-run mode

Set `BALCON_DRY_RUN=1` to run the full pipeline without writing anything to GitHub. All output — findings, agent reasoning, what actions would have been taken — is written to the GitHub Actions [Job Summary](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/workflow-commands-for-github-actions#adding-a-job-summary) instead.

The `balcon-scan.yml` workflow exposes this as a `workflow_dispatch` input, so you can trigger a dry-run scan manually from the Actions UI without any environment variable changes.

Dry-run is useful for:
- Validating your `.github/balcon-ci.yml` configuration before going live
- Estimating token usage and costs
- Testing new agent instructions without risk of posting noise to PRs

---

## Safety constraints

BalconCI is designed so that a misconfigured or misbehaving agent cannot cause unrecoverable damage:

- **No auto-merge.** All pipelines end with a human-ready PR or issue. The reviewer marks the PR ready; a human merges.
- **Opt-in for code changes.** Human-raised PRs are only modified in `review+fix` mode, which requires an explicit label or comment from the developer.
- **Blast radius limits.** The fixer is hard-stopped if `max_files_changed` or `max_lines_changed` is exceeded. The finding is opened as a GitHub issue instead.
- **Confidence gate.** Findings below `confidence_threshold` are escalated to human before triage.
- **Semantic escalation.** `always_escalate` categories bypass the fixer entirely.
- **Iteration cap.** The fixer/reviewer loop is capped at `max_iterations`. Exceeding the cap marks the PR as needing human review.
- **Schema validation.** The harness validates every agent output before passing it to the next agent. Invalid output triggers a circuit break, which posts a failure comment and exits cleanly.
- **Evidence requirement.** Every finding must carry a verbatim code snippet. The snippet is cross-checked against the actual file content. No snippet means the finding is dropped.
- **Token budget.** A configurable token budget per run prevents runaway costs. Exceeding it triggers a circuit break.

---

## Instruction and context files

The system prompt for each agent is assembled from four layers, in order from most general to most specific:

```
1. Harness defaults         built-in, applies to all agents everywhere
2. Role prompt              built-in, defines the agent's job and output schema
3. Agent instructions       your files, listed under agents.<role>.instructions
4. Agent context            your files, listed under agents.<role>.context
```

You only write layers 3 and 4. They are read from your repository at runtime and injected into the system prompt on each invocation.

**Instructions** (layer 3) shape *how* the agent behaves — think of them as role-specific standing orders for your codebase.

**Context** (layer 4) is reference material the agent should know — coding standards, protocol specs, security policies.

Example layout:

```
.github/
  balcon-ci.yml
  balcon-ci/
    statler-instructions.md   # scanner behaviour for this repo
    waldorf-instructions.md
    sam-instructions.md
    fozzie-instructions.md
    kermit-instructions.md
docs/
  cpp-coding-standards.md     # injected as context for scanner and verifier
  security-escalation-policy.md
```

---

## Local development

```bash
# Clone
git clone https://github.com/your-org/balcon-ci.git
cd balcon-ci

# Install in editable mode with dev tools
pip install -e ".[dev]"        # includes ruff + pytest
pip install -e ".[dev,bedrock]" # also include Bedrock SDK

# Lint and format
ruff check harness/
ruff format harness/

# Run tests
pytest

# Run a dry-run review against a real PR
export GITHUB_TOKEN=...
export ANTHROPIC_API_KEY=...
export GITHUB_REPOSITORY=your-org/your-repo
export BALCON_DRY_RUN=1
balcon-ci review --pr 42
```

## Contributing

The CI workflow (`.github/workflows/ci.yml`) runs on every push and pull request:

- `ruff check` — linting (pycodestyle, pyflakes, isort, pylint subset, pyupgrade)
- `ruff format --check` — formatting

All contributions must pass both checks before merging. To fix issues locally:

```bash
ruff check --fix harness/   # auto-fix safe issues
ruff format harness/         # auto-format
```
