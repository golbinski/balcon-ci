"""
Token budget gate for BalconCI pipeline runs.

Usage:
    gate = CostGate(budget=500_000)
    gate.charge(tokens_used)   # raises BudgetExceeded if over budget
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_BUDGET = 500_000


class BudgetExceeded(Exception):
    """Raised when a pipeline run exceeds its token budget."""

    def __init__(self, used: int, budget: int) -> None:
        self.used = used
        self.budget = budget
        super().__init__(f"Token budget exceeded: used {used:,} of {budget:,} tokens")


class CostGate:
    def __init__(self, budget: int | None = None) -> None:
        if budget is None:
            budget = int(os.environ.get("BALCON_TOKEN_BUDGET", DEFAULT_BUDGET))
        self._budget = budget
        self._used = 0

    @property
    def used(self) -> int:
        return self._used

    @property
    def budget(self) -> int:
        return self._budget

    def remaining(self) -> int:
        return max(0, self._budget - self._used)

    def charge(self, tokens: int) -> None:
        """Add *tokens* to the running total. Raises BudgetExceeded if over budget."""
        self._used += tokens
        logger.debug("Token usage: %d / %d", self._used, self._budget)
        if self._used > self._budget:
            raise BudgetExceeded(self._used, self._budget)
