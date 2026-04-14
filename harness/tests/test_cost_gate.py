"""Tests for harness/cost_gate.py — token budget tracking."""

import pytest

from harness.cost_gate import BudgetExceeded, CostGate


class TestCostGate:
    def test_initial_state(self):
        gate = CostGate(budget=1000)
        assert gate.used == 0
        assert gate.budget == 1000
        assert gate.remaining() == 1000

    def test_charge_accumulates(self):
        gate = CostGate(budget=1000)
        gate.charge(300)
        gate.charge(200)
        assert gate.used == 500
        assert gate.remaining() == 500

    def test_charge_exactly_at_budget_does_not_raise(self):
        gate = CostGate(budget=100)
        gate.charge(100)
        assert gate.used == 100
        assert gate.remaining() == 0

    def test_charge_exceeds_budget_raises(self):
        gate = CostGate(budget=100)
        with pytest.raises(BudgetExceeded) as exc_info:
            gate.charge(101)
        assert exc_info.value.used == 101
        assert exc_info.value.budget == 100

    def test_incremental_charges_cross_budget_raises(self):
        gate = CostGate(budget=100)
        gate.charge(90)
        with pytest.raises(BudgetExceeded):
            gate.charge(20)

    def test_budget_exceeded_message_contains_counts(self):
        gate = CostGate(budget=50)
        with pytest.raises(BudgetExceeded, match="75") as exc_info:
            gate.charge(75)
        assert "50" in str(exc_info.value)

    def test_remaining_never_goes_negative(self):
        gate = CostGate(budget=10)
        try:
            gate.charge(999)
        except BudgetExceeded:
            pass
        assert gate.remaining() == 0

    def test_zero_charge_does_not_raise(self):
        gate = CostGate(budget=100)
        gate.charge(0)
        assert gate.used == 0

    def test_env_var_sets_budget(self, monkeypatch):
        monkeypatch.setenv("BALCON_TOKEN_BUDGET", "42")
        gate = CostGate()
        assert gate.budget == 42

    def test_explicit_budget_overrides_env_var(self, monkeypatch):
        monkeypatch.setenv("BALCON_TOKEN_BUDGET", "42")
        gate = CostGate(budget=999)
        assert gate.budget == 999
