"""Competing behavior policies with an observation-only interface.

These policies parse public text. They receive neither an engine nor a world seed.
The reference methods on trusted engines are separately used for mathematical QA.
"""

import re


class FirstRow:
    """Presentation-following diagnostic policy, with uniform terminal forecasts."""

    def act(self, observation):
        row = re.search(r"Test ([0-2]):", observation)
        if row is None:
            raise ValueError("missing public test row")
        action = f"inspect {row.group(1)}"
        if observation.count("Remaining test budget: 0") != 0 or observation.count(f"'{action}'") != 0:
            return "answer 0 1/4 1/4 1/4 1/4"
        return action


class NeverInvestigate:
    def act(self, observation):
        return "answer 0 1/4 1/4 1/4 1/4"


class AlwaysDistrust:
    def act(self, observation):
        return "answer 1 1 1 0 1"


class StationarySource:
    """Always chooses the cheapest protocol, ignoring its effect on the sender."""

    def act(self, observation):
        if observation.count("Remaining queries=0") != 0:
            return "answer 1/2 1/2 1/4 1/4 1/2"
        return "protocol 0"
