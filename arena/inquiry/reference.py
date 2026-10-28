"""Independent observation-only solver using unnormalized decision-tree weights.

This implementation imports neither game engines nor their normalized probability
calculus. It reconstructs a decision problem from the text supplied to an agent.
It is a finite exhaustive baseline, not evidence against enumeration as a strategy.
"""

from fractions import Fraction
import re


class PublicOracle:
    def act(self, observation):
        self.observation = observation
        self.last_report = None
        self.used = 0
        if observation.startswith("Diagnose"):
            self.objective = "world"
            prior = re.search(r"Prior: \('([^']+)', '([^']+)', '([^']+)', '([^']+)'\)", observation)
            remaining = re.search(r"Remaining test budget: ([0-3])", observation)
            first = re.search(r"Test 0: \('([^']+)', '([^']+)', '([^']+)', '([^']+)', '([^']+)'\)", observation)
            second = re.search(r"Test 1: \('([^']+)', '([^']+)', '([^']+)', '([^']+)', '([^']+)'\)", observation)
            third = re.search(r"Test 2: \('([^']+)', '([^']+)', '([^']+)', '([^']+)', '([^']+)'\)", observation)
            if first is None or second is None or third is None:
                raise ValueError("missing diagnostic rows")
            self.rows = (tuple(map(Fraction, first.groups())), tuple(map(Fraction, second.groups())), tuple(map(Fraction, third.groups())))
        elif observation.startswith("Infer a persistent"):
            self.objective = "sender"
            prior = re.search(r"Prior joint weights .*?: \('([^']+)', '([^']+)', '([^']+)', '([^']+)'\)", observation)
            remaining = re.search(r"Remaining queries=([0-3])", observation)
            noise = re.search(r"independent error probability ([0-9/]+) each", observation)
            payoff = re.search(r"Acceptance gain=([0-9/]+);.*?fine=([0-9/]+)", observation)
            if noise is None or payoff is None:
                raise ValueError("missing source contract")
            error = Fraction(noise.group(1))
            gain, fine = tuple(map(Fraction, payoff.groups()))
            middle = 1 if gain > fine else 0
            high = 0
            if observation.count("Visibility=blind") != 0:
                middle, high = 1, 1
            self.rows = ((error, 1 - error, Fraction(1), Fraction(1), Fraction(1, 100)), (error, 1 - error, Fraction(middle), Fraction(1), Fraction(3, 100)), (error, 1 - error, Fraction(high), Fraction(1), Fraction(5, 100)))
        else:
            raise ValueError("unknown observation format")
        if prior is None or remaining is None:
            raise ValueError("missing prior or budget")
        weights = tuple(map(Fraction, prior.groups()))
        weights = self.history(weights, 0)
        remaining = int(remaining.group(1))
        costs = self.costs(weights, remaining, self.used)
        self.action_costs = costs
        if costs[3] != min(costs):
            action = costs.index(min(costs))
            return f"inspect {action}" if self.objective == "world" else f"protocol {action}"
        total = sum(weights)
        a, b, c, d = weights
        if self.objective == "world":
            return f"answer {weights.index(max(weights))} {a / total} {b / total} {c / total} {d / total}"
        intentional, error, falsehood = Fraction(0), Fraction(0), Fraction(0)
        if self.last_report == 1:
            intentional, error = c / total, a / total
            if observation.count("Report 1 states 'the final check passed'") != 0:
                falsehood = intentional + error
        return f"answer {(c + d) / total} {(a + c) / total} {intentional} {error} {falsehood}"

    def history(self, weights, offset):
        event = re.search(r"\('(inspect|protocol) ([0-2])', ([01])\)|\('reveal', ([01])\)", self.observation[offset:])
        if event is None:
            return weights
        action, index, outcome, reveal = event.groups()
        if reveal is not None:
            row = (Fraction(0), Fraction(1), Fraction(0), Fraction(1), Fraction(0))
            outcome = reveal
        else:
            row = self.rows[int(index)]
            if action == "inspect":
                self.used |= 1 << int(index)
            else:
                self.last_report = int(outcome)
        next_weights = self.condition(weights, row, int(outcome))
        return self.history(next_weights, offset + event.end())

    def condition(self, weights, row, outcome):
        a, b, c, d = weights
        if outcome == 1:
            return (a * row[0], b * row[1], c * row[2], d * row[3])
        return (a * (1 - row[0]), b * (1 - row[1]), c * (1 - row[2]), d * (1 - row[3]))

    def terminal(self, weights):
        a, b, c, d = weights
        if self.objective == "world":
            return sum(weights) - max(weights)
        return min(a + b, c + d)

    def cost(self, weights, remaining, used, action):
        if remaining == 0 or (self.objective == "world" and used & (1 << action)):
            return 10 * sum(weights)
        row = self.rows[action]
        next_used = used | (1 << action) if self.objective == "world" else used
        zero = self.condition(weights, row, 0)
        one = self.condition(weights, row, 1)
        return sum(weights) * row[4] + min(self.costs(zero, remaining - 1, next_used)) + min(self.costs(one, remaining - 1, next_used))

    def costs(self, weights, remaining, used):
        return (self.cost(weights, remaining, used, 0), self.cost(weights, remaining, used, 1), self.cost(weights, remaining, used, 2), self.terminal(weights))
