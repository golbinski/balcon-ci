# BalconCI — Specification

> Agentic code review and analysis system for GitHub Enterprise, distributed via git subtree from a central `balcon-ci` repository.

---

## 1. Overview

BalconCI is a multi-agent pipeline that runs inside GitHub Actions. It performs agentic code review on pull requests and periodic codebase analysis, using GitHub itself (PR comments, issues) as its memory and state store. All workflows end with a human taking responsibility — no auto-merge, ever.

---

## 2. Pipeline modes

| Mode | Trigger | Description |
|---|---|---|
| `review` | PR label `balcon-ci:review` or comment `/balcon-ci review` | Read-only review. Agents post comments on the PR. No code changes. |
| `review+fix` | PR label `balcon-ci:review+fix` or comment `/balcon-ci fix` | Review plus agent-authored commits pushed to the existing PR branch. Developer opts in explicitly. |
| `scan` | Cron schedule or `workflow_dispatch` | Periodic repo-wide analysis via codebase embeddings. Can open new PRs or GitHub issues. |

Human-raised PRs are never modified without explicit opt-in (`review+fix` mode). The `scan` mode is the only mode that opens new PRs autonomously.

---

## 3. Agents

Agents have fixed **roles** (internal contract identifiers) and configurable **names** (how they appear in logs and GitHub comments).

| Role | Default name | Responsibility |
|---|---|---|
| `scanner` | Statler | Finds potential issues in code |
| `verifier` | Waldorf | Challenges scanner findings, eliminates hallucinations |
| `triage` | Sam | Routes each finding: auto-fix, human issue, or skip |
| `fixer` | Fozzie | Attempts automated fixes within defined blast radius |
| `reviewer` | Kermit | Reviews fixer output, iterates, marks PR ready for human |

### Pipeline composition per mode

```
review:        scanner → verifier → triage → reviewer (read-only, no fixer)
review+fix:    scanner → verifier → triage → fixer → reviewer (commits to PR branch)
scan:          scanner → verifier → triage → fixer → reviewer (may open new PR or issue)
```

---

## 4. Instruction layers

Four layers are merged at runtime, from most general to most specific:

```
1. Harness defaults          lives in balcon-ci repo, applies everywhere
2. Agent role prompts        lives in balcon-ci repo, defines each agent's job and output schema
3. Repo-specific config      lives in .github/balcon-ci.yml, owned by repo team
4. Project guidelines        referenced from balcon-ci.yml, injected as agent context
```

Repo teams only ever write layers 3 and 4.

---

## 5. Configuration — `.github/balcon-ci.yml`

```yaml
agents:

  scanner:
    name: statler
    instructions:
      - .github/balcon-ci/statler-instructions.md
    context:
      - docs/cpp-coding-standards.md
      - docs/fix-protocol-reference.md
    min_severity: medium

  verifier:
    name: waldorf
    instructions:
      - .github/balcon-ci/waldorf-instructions.md
    context:
      - docs/cpp-coding-standards.md
    confidence_threshold: 0.75

  triage:
    name: sam
    instructions:
      - .github/balcon-ci/sam-instructions.md
    context:
      - docs/security-escalation-policy.md
    always_escalate:
      - "race condition"
      - "security vulnerability"
      - "protocol field ordering"

  fixer:
    name: fozzie
    instructions:
      - .github/balcon-ci/fozzie-instructions.md
    context:
      - docs/approved-refactoring-patterns.md
    eligible_categories:
      - "missing null check"
      - "unused variable"
      - "missing RAII wrapper for simple cases"
    max_files_changed: 3
    max_lines_changed: 50

  reviewer:
    name: kermit
    instructions:
      - .github/balcon-ci/kermit-instructions.md
    context:
      - docs/cpp-coding-standards.md
    max_iterations: 3

codebase:
  scanning:
    queries:
      - "raw owning pointers stored as class members without RAII wrapper"
      - "FIX message handlers missing tag 35 validation"
      - "shared mutable state accessed without lock"
    exclude_paths:
      - "third_party/**"
      - "**/*.generated.cpp"
```

### Config field reference

**Per-agent fields**

| Field | Required | Description |
|---|---|---|
| `name` | no | Display name in GitHub comments and logs. Defaults to role name. |
| `instructions` | no | Paths to files that shape how the agent behaves. Injected into system prompt. |
| `context` | no | Paths to reference documents the agent should know. Injected as knowledge alongside the payload. |

**Scanner-specific**

| Field | Description |
|---|---|
| `min_severity` | Minimum severity to report: `low`, `medium`, `high`, `critical` |

**Verifier-specific**

| Field | Description |
|---|---|
| `confidence_threshold` | Minimum confidence (0.0–1.0) to pass a finding. Below this → escalate to human. |

**Triage-specific**

| Field | Description |
|---|---|
| `always_escalate` | List of category patterns that always route to human, regardless of confidence. Matched semantically. |

**Fixer-specific**

| Field | Description |
|---|---|
| `eligible_categories` | Categories the fixer is permitted to attempt. Matched semantically against finding category. |
| `max_files_changed` | Hard blast radius limit. Exceeding this downgrades fix attempt to a GitHub issue. |
| `max_lines_changed` | Hard blast radius limit. Same behaviour. |

**Reviewer-specific**

| Field | Description |
|---|---|
| `max_iterations` | Maximum fixer/reviewer feedback cycles before marking PR as needing human review. |

**Codebase scanning**

| Field | Description |
|---|---|
| `codebase.scanning.queries` | Natural language queries run against the arborist-mcp embedding index. |
| `codebase.scanning.exclude_paths` | Glob patterns excluded from scanning. |

---

## 6. Schemas

### 6.1 Finding

The atomic unit produced by the scanner and mutated by each subsequent agent.

```typescript
interface Finding {
  // Core — set by scanner, immutable after creation
  id: string;                  // stable hash of file + line_start + snippet
  source: "diff" | "arborist"; // how the finding was discovered
  location: {
    file: string;              // repo-relative path
    line_start: number;
    line_end: number;
    snippet: string;           // verbatim quoted code, never generated — required
  };
  category: string;            // free-form text description of the problem type
  severity: "low" | "medium" | "high" | "critical";
  reasoning: string;           // scanner's natural language explanation
  confidence: number;          // 0.0–1.0, scanner's self-assessed certainty

  // Added by verifier
  verified?: boolean;
  confidence_adjusted?: number;
  rejection_reason?: string;   // present only if verified = false

  // Added by triage
  decision?: "auto_fix" | "human_issue" | "skip";
  escalation_reason?: string;  // present when decision = "human_issue"

  // Added by fixer
  fix_attempted?: boolean;
  fix_result?: "success" | "partial" | "failed";
  files_changed?: string[];
  lines_changed?: number;
  fix_summary?: string;

  // Added by reviewer
  review_result?: "approved" | "changes_requested";
  review_iterations?: number;
  review_feedback?: string;
  github_ref?: string;         // URL to GitHub comment, issue, or PR
}
```

**Validation rules enforced by the harness before passing to each agent:**

- `snippet` must be non-empty
- `location.file` must exist in the repo at the current HEAD
- `location.line_start` must be a valid line number in that file
- `confidence` must be in range [0.0, 1.0]
- Any finding failing these checks is dropped before reaching the verifier

### 6.2 Scanner output

```typescript
interface ScannerOutput {
  result: "success" | "circuit_break";
  findings: Finding[];
  scan_metadata: {
    source: "diff" | "arborist";
    files_scanned: string[];
    queries_used?: string[];   // arborist mode only
    token_usage: number;
  };
  reasoning: string;
}
```

### 6.3 Verifier output

```typescript
interface VerifierOutput {
  result: "success" | "needs_human" | "circuit_break";
  findings: Finding[];         // mutated: verified/rejected fields populated
  evidence_checks: {
    finding_id: string;
    file_exists: boolean;
    line_exists: boolean;
    snippet_matches: boolean;
    passed: boolean;
  }[];
  reasoning: string;
}
```

### 6.4 Triage output

```typescript
interface TriageOutput {
  result: "success" | "circuit_break";
  findings: Finding[];         // mutated: decision field populated
  reasoning: string;
}
```

### 6.5 Fixer output

```typescript
interface FixerOutput {
  result: "success" | "partial" | "failed" | "circuit_break";
  findings: Finding[];         // mutated: fix fields populated
  reasoning: string;
}
```

### 6.6 Reviewer output

```typescript
interface ReviewerOutput {
  result: "approved" | "changes_requested" | "needs_human" | "circuit_break";
  findings: Finding[];         // mutated: review fields populated
  feedback?: string;           // present when result = "changes_requested"
  reasoning: string;
}
```

---

## 7. State and memory

GitHub is the state store. No external database required.

| Scope | Storage | Contents |
|---|---|---|
| Within a pipeline run | Python process memory | Finding objects flowing between agents |
| PR review state | PR comment thread | Agent outputs, findings, feedback, iteration history |
| Scan findings | GitHub Issues | Full finding detail, audit trail in issue comments |
| Auto-fix state | PR description + comments | What Fozzie attempted, Kermit's review iterations |

All GitHub comments posted by agents are signed with the agent name (e.g. "Waldorf rejected 3 of Statler's findings").

---

## 8. Safety constraints

- **Never auto-merge.** All pipelines end with a human-ready PR or issue.
- **Blast radius limits.** Fixer is hard-stopped if `max_files_changed` or `max_lines_changed` is exceeded. Finding is downgraded to a GitHub issue instead.
- **Confidence gate.** Findings below `confidence_threshold` are escalated to human before triage.
- **Semantic escalation.** `always_escalate` categories bypass the fixer entirely regardless of confidence.
- **Iteration cap.** Fixer/reviewer loop is capped at `max_iterations`. Exceeding cap marks PR as needing human review.
- **Schema validation.** Harness validates every agent output before passing to the next agent. Invalid output triggers circuit break.
- **Evidence requirement.** Every finding must carry a verbatim snippet. Snippet is cross-checked against actual file content. No snippet = finding dropped.
- **Opt-in for code changes.** Human-raised PRs are only modified in `review+fix` mode, which requires explicit developer opt-in via label or comment command.

---

## 9. LLM abstraction

BalconCI uses a thin wrapper over official provider SDKs rather than a third-party abstraction library. The wrapper exposes a single `.complete(messages, model)` interface. Provider is selected per-deployment via the `BALCON_LLM_PROVIDER` environment variable.

| `BALCON_LLM_PROVIDER` | SDK used | Required env vars |
|---|---|---|
| `anthropic` (default) | `anthropic` | `ANTHROPIC_API_KEY` |
| `bedrock` | `anthropic[bedrock]` (Anthropic Claude on AWS Bedrock only) | `AWS_REGION` (default `us-east-1`); AWS credentials via IAM role or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` |

The model is selected via `BALCON_MODEL` (default: `claude-sonnet-4-6`). For Bedrock, use the Bedrock model ID format, e.g. `anthropic.claude-3-5-sonnet-20241022-v2:0`.

`anthropic[bedrock]` is an optional install extra (`pip install ".[bedrock]"`); the base install only requires the core `anthropic` package.

---

## 10. Codebase retrieval

Arborist-mcp is used for `scan` mode to retrieve semantically relevant code chunks rather than scanning the full repository sequentially. Queries defined in `codebase.scanning.queries` are run against the embedding index at pipeline start. Scanner agents receive retrieved chunks, not raw file dumps.

---

## 11. Workflow distribution

BalconCI workflow definitions live in a standalone `balcon-ci` repository and are distributed to codebase repos via git subtree. Per-repo configuration (`.github/balcon-ci.yml`) and agent instruction/context files remain in each repo and are read at runtime.

---

## 12. Harness implementation

**Language**: Python 3.11+. Installable as `balcon-ci` package via `pyproject.toml`.

**CLI**: Click-based entrypoint — `balcon-ci review --pr N`, `balcon-ci review-fix --pr N`, `balcon-ci scan`.

**Package layout**:

```
harness/
├── __main__.py        # Click CLI
├── config.py          # load_config(), load_file_content()
├── llm.py             # LLMClient wrapper
├── cost_gate.py       # CostGate, BudgetExceeded
├── schemas.py         # Pydantic v2 models (Finding, *Output, *Config)
├── validation.py      # validate_findings() — harness pre-agent checks
├── github.py          # GitHubClient (PyGitHub)
├── pipeline.py        # run_review / run_review_fix / run_scan
└── agents/
    ├── base.py        # BaseAgent — 4-layer prompt, LLM call, JSON parse, CircuitBreak
    ├── scanner.py
    ├── verifier.py
    ├── triage.py
    ├── fixer.py
    └── reviewer.py
prompts/               # Markdown system prompt templates, one per role
.github/workflows/     # Three workflow files, one per pipeline mode
```

**Cost gate**: `CostGate` tracks cumulative token usage per pipeline run. Configured via `BALCON_TOKEN_BUDGET` env var (default 500,000 tokens). Exceeding the budget raises `BudgetExceeded`, which the pipeline catches and converts to a circuit break.

**Dry-run mode**: Set `BALCON_DRY_RUN=1`. All GitHub writes (comments, commits, issues, PRs) are suppressed; a Markdown summary is written to `$GITHUB_STEP_SUMMARY` instead (visible as the GitHub Actions Job Summary). The `balcon-scan.yml` workflow exposes a `dry_run` input on `workflow_dispatch`.

**GitHub Actions workflows**:

| File | Trigger |
|---|---|
| `balcon-review.yml` | PR label `balcon-ci:review` or comment `/balcon-ci review` |
| `balcon-review-fix.yml` | PR label `balcon-ci:review+fix` or comment `/balcon-ci fix` |
| `balcon-scan.yml` | Weekly cron (`0 2 * * 1`) or `workflow_dispatch` |

**Environment variables** (all workflows):

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | yes | — | GitHub Actions token |
| `ANTHROPIC_API_KEY` | provider-dependent | — | Required when `BALCON_LLM_PROVIDER=anthropic` |
| `BALCON_LLM_PROVIDER` | no | `anthropic` | LLM provider (`anthropic` or `bedrock`) |
| `BALCON_MODEL` | no | `claude-sonnet-4-6` | Model ID (provider-specific) |
| `BALCON_TOKEN_BUDGET` | no | `500000` | Token budget per run |
| `BALCON_DRY_RUN` | no | `0` | Set to `1` to suppress GitHub writes |

**Agent role prompts**: One Markdown file per role in `prompts/`. Injected as layer 2 of the four-layer instruction stack by `BaseAgent`. Contain the output JSON schema and anti-hallucination constraints for each role.
