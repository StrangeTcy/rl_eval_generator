"""Judge-facing wrapper for the controlled deception attribution family."""
from __future__ import annotations

try:
    from shared import deception_game
except ImportError:
    import deception_game


def build_instance(mode, mechanism, incentive, visibility, scenario, seed):
    return deception_game.build_detection(mode, mechanism, incentive, visibility, scenario, seed)
