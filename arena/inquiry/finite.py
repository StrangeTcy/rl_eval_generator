"""Four-state exact experiment calculus, shared by two distinct game mechanisms.

The trusted engine owns these objects. Agents receive rendered observations only.
No sampled hidden state participates in an ex ante action value.
"""

from fractions import Fraction


class Experiment:
    def __init__(self, a, b, c, d, cost="0"):
        self.a, self.b, self.c, self.d = Fraction(a), Fraction(b), Fraction(c), Fraction(d)
        self.cost = Fraction(cost)
        if min(self.a, self.b, self.c, self.d, self.cost) < 0:
            raise ValueError("negative probability or cost")
        if max(self.a, self.b, self.c, self.d, self.cost) > 1:
            raise ValueError("probability or cost exceeds one")

    def row(self):
        return (str(self.a), str(self.b), str(self.c), str(self.d), str(self.cost))


class Mass:
    def __init__(self, a, b, c, d):
        a, b, c, d = Fraction(a), Fraction(b), Fraction(c), Fraction(d)
        total = a + b + c + d
        if min(a, b, c, d) < 0 or total <= 0:
            raise ValueError("nonnegative mass with positive total required")
        self.a, self.b, self.c, self.d = a / total, b / total, c / total, d / total

    def row(self):
        return (str(self.a), str(self.b), str(self.c), str(self.d))

    def probability(self, experiment, outcome):
        if outcome == 1:
            return self.a * experiment.a + self.b * experiment.b + self.c * experiment.c + self.d * experiment.d
        if outcome == 0:
            return 1 - self.probability(experiment, 1)
        raise ValueError("outcome must be zero or one")

    def observe(self, experiment, outcome):
        if outcome == 1:
            return Mass(self.a * experiment.a, self.b * experiment.b, self.c * experiment.c, self.d * experiment.d)
        if outcome == 0:
            return Mass(self.a * (1 - experiment.a), self.b * (1 - experiment.b), self.c * (1 - experiment.c), self.d * (1 - experiment.d))
        raise ValueError("outcome must be zero or one")

    def risk(self, objective="world"):
        if objective == "world":
            return 1 - max(self.a, self.b, self.c, self.d)
        if objective == "sender":
            return min(self.a + self.b, self.c + self.d)
        raise ValueError("unknown decision objective")


class InquiryPlan:
    """Finite-horizon Bayes risk, including the option to stop and all test costs."""

    def __init__(self, first, second, third):
        self.experiments = (first, second, third)

    def branch(self, mass, experiment, outcome, remaining, used):
        weight = mass.probability(experiment, outcome)
        if weight == 0:
            return Fraction(0)
        return weight * self.value(mass.observe(experiment, outcome), remaining, used)

    def action_value(self, mass, remaining, used, action):
        if action == 3:
            return mass.risk()
        if action < 0 or action > 2:
            raise ValueError("unknown test")
        if remaining <= 0 or used & (1 << action):
            return Fraction(10)
        experiment = self.experiments[action]
        next_used = used | (1 << action)
        return experiment.cost + self.branch(mass, experiment, 0, remaining - 1, next_used) + self.branch(mass, experiment, 1, remaining - 1, next_used)

    def values(self, mass, remaining, used):
        if remaining < 0 or remaining > 3 or used < 0 or used > 7:
            raise ValueError("invalid finite inquiry state")
        return (self.action_value(mass, remaining, used, 0), self.action_value(mass, remaining, used, 1), self.action_value(mass, remaining, used, 2), mass.risk())

    def value(self, mass, remaining, used):
        return min(self.values(mass, remaining, used))

    def choose(self, mass, remaining, used):
        values = self.values(mass, remaining, used)
        # Prefer stopping on a tie; extra observations are not free evidence of skill.
        if values[3] == min(values):
            return 3
        return values.index(min(values))
