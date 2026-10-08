"""Experiment-only selector for instances that distinguish two predictors.

This helper records disagreement only. It does not establish that either
predictor is correct and must not be used as an equilibrium oracle or scorer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

Game = TypeVar("Game")


def discriminating_instances(
    instances: list[Game],
    predictor_a: Callable[[Game], object],
    predictor_b: Callable[[Game], object],
) -> list[Game]:
    """Return input games for which the two supplied predictors disagree."""
    return [game for game in instances if predictor_a(game) != predictor_b(game)]


__all__ = ["discriminating_instances"]
