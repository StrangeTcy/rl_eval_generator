"""Constrained two-role presentation trial, separate from private-type deployment."""

from .reference import PublicOracle
from .session import Session
from .trial import Trial


class FirstRowPresenter:
    """Construct a permutation against the declared first-row target model.

The objective is first-query regret, not realized hidden-world accuracy.
This is a positive control for a specified opponent, not a learned attacker.
"""

    def __init__(self, goal="adversarial"):
        if goal != "adversarial" and goal != "helpful":
            raise ValueError("unknown presenter goal")
        self.goal = goal

    def act(self, public_observation):
        oracle = PublicOracle()
        oracle.act(public_observation)
        costs = oracle.action_costs[:3]
        target = max(costs) if self.goal == "adversarial" else min(costs)
        action = costs.index(target)
        order = ((0, 1, 2), (1, 0, 2), (2, 0, 1))[action]
        return "present " + " ".join(map(str, order))


class TwoRoleTrial:
    def __init__(self, configuration, presenter, investigator):
        if not configuration.startswith("diagnostic "):
            raise ValueError("presentation trials require a diagnostic game")
        controller = Session()
        controller.start(configuration)
        # Only text crosses each role boundary; controller configuration is private.
        self.presentation = presenter.act(controller.game.presenter_view())
        self.trial = Trial(configuration, investigator, self.presentation)

    def run(self):
        return self.trial.run()
