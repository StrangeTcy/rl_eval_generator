from __future__ import annotations
try:
    from shared import deception_game
except ImportError:
    import deception_game


def build_instance(signal_type, incentive, scenario, seed):
    return deception_game.build_signal(signal_type, incentive, scenario, seed)
