"""
BaseAgent — shared scaffolding for all five BalconCI agent roles.

Responsibilities:
  1. Build the four-layer system prompt (harness default → role prompt →
     agent instructions → agent context)
  2. Call the LLM via LLMClient and charge the CostGate
  3. Parse the JSON response into the role-specific output Pydantic model
  4. Raise CircuitBreak on parse failure

Subclasses set:
  role            str          internal identifier
  default_name    str          display name when config.name is absent
  output_schema   type         the Pydantic model to parse LLM output into
  prompt_file     str          filename inside prompts/ directory
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from harness.cost_gate import CostGate
from harness.llm import LLMClient
from harness.schemas import AgentConfig

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Harness-level default injected at the top of every agent's system prompt.
_HARNESS_DEFAULT = """\
You are part of BalconCI, an automated code-review pipeline running inside GitHub Actions.

Rules that apply to ALL agents in this pipeline:
- Output ONLY valid JSON that conforms exactly to the schema specified in your role prompt.
- Never fabricate code snippets. Every `snippet` field must be verbatim code copied from the diff or file provided to you.
- Never auto-merge changes or take any irreversible action beyond what your role permits.
- If you are uncertain about something, express it in the `reasoning` field rather than guessing.
- When in doubt, escalate to human rather than auto-fix.
"""

# Directory containing role prompt Markdown files.
_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class CircuitBreak(Exception):
    """Raised when an agent produces output that cannot be parsed."""

    def __init__(self, agent_name: str, reason: str, raw: str = "") -> None:
        self.agent_name = agent_name
        self.reason = reason
        self.raw = raw
        super().__init__(f"{agent_name} circuit break: {reason}")


class BaseAgent:
    role: str = ""
    default_name: str = ""
    output_schema: type[BaseModel] = BaseModel
    prompt_file: str = ""

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        gate: CostGate,
        repo_root: Path | None = None,
    ) -> None:
        self._config = config
        self._llm = llm
        self._gate = gate
        self._repo_root = repo_root or Path(".")
        self.name = config.name or self.default_name

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, payload: dict[str, Any]) -> BaseModel:
        """Build prompt, call LLM, validate output. Returns typed output model."""
        system = self._build_system_prompt()
        messages = self._build_messages(payload)

        logger.info("[%s] calling LLM", self.name)
        raw, tokens = self._llm.complete(messages, system=system)
        self._gate.charge(tokens)

        return self._parse_output(raw)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        parts = [_HARNESS_DEFAULT]

        # Layer 2: role prompt from prompts/<role>.md
        role_prompt = self._load_role_prompt()
        if role_prompt:
            parts.append(role_prompt)

        # Layer 3: per-repo agent instructions
        if self._config.instructions:
            from harness.config import load_file_content  # noqa: PLC0415

            instructions = load_file_content(self._repo_root, self._config.instructions)
            if instructions:
                parts.append(f"## Agent instructions\n\n{instructions}")

        # Layer 4: per-repo context documents
        if self._config.context:
            from harness.config import load_file_content  # noqa: PLC0415

            context = load_file_content(self._repo_root, self._config.context)
            if context:
                parts.append(f"## Reference context\n\n{context}")

        return "\n\n---\n\n".join(parts)

    def _load_role_prompt(self) -> str:
        fname = self.prompt_file or f"{self.role}.md"
        path = _PROMPTS_DIR / fname
        if path.exists():
            return path.read_text()
        logger.warning("Role prompt not found: %s", path)
        return ""

    def _build_messages(self, payload: dict[str, Any]) -> list[dict]:
        return [{"role": "user", "content": json.dumps(payload, indent=2)}]

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def _parse_output(self, raw: str) -> BaseModel:
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # drop first and last fence lines
            inner = lines[1:] if lines[0].startswith("```") else lines
            if inner and inner[-1].strip() == "```":
                inner = inner[:-1]
            text = "\n".join(inner).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CircuitBreak(self.name, f"JSON parse error: {exc}", raw) from exc

        try:
            return self.output_schema.model_validate(data)
        except ValidationError as exc:
            raise CircuitBreak(self.name, f"Schema validation error: {exc}", raw) from exc
