"""Exact belief-state planning over hidden defender procedures.

The planning horizon counts probes and teaching interactions. The model depth
inside each defender is a separate, epistemic axis. Only public observations
condition this belief state; the realized controller profile is never consulted.
"""

from fractions import Fraction


class Belief:
    def __init__(self, records):
        total = self.total(records)
        if total <= 0:
            raise ValueError("empty or impossible procedure belief")
        self.records = self.normalize(records, total)

    def total(self, records):
        if records == ():
            return Fraction(0)
        if records[0][2] < 0:
            raise ValueError("negative procedure weight")
        return records[0][2] + self.total(records[1:])

    def normalize(self, records, total):
        if records == ():
            return ()
        identifier, defender, weight = records[0]
        if weight == 0:
            return self.normalize(records[1:], total)
        return ((identifier, defender, weight / total),) + self.normalize(records[1:], total)

    def size(self, records=None):
        if records is None:
            records = self.records
        if records == ():
            return 0
        return 1 + self.size(records[1:])

    def signature(self, records=None):
        if records is None:
            records = self.records
        if records == ():
            return ()
        identifier, defender, weight = records[0]
        return ((identifier, defender.depth, defender.cost, defender.credibility, weight),) + self.signature(records[1:])

    def responses(self, context, message, records=None):
        if records is None:
            records = self.records
        if records == ():
            return (Fraction(0), Fraction(0), Fraction(0))
        identifier, defender, weight = records[0]
        a, b, v = self.responses(context, message, records[1:])
        action = defender.choose(context, message)
        return (a + (weight if action == 0 else 0), b + (weight if action == 1 else 0), v + (weight if action == 2 else 0))

    def expected_loss(self, context, message, world, records=None):
        if records is None:
            records = self.records
        if records == ():
            return Fraction(0)
        identifier, defender, weight = records[0]
        loss = defender.loss(defender.choose(context, message), world)
        return weight * loss + self.expected_loss(context, message, world, records[1:])

    def survivors(self, context, message, response, world, learning, records):
        if records == ():
            return ()
        identifier, defender, weight = records[0]
        tail = self.survivors(context, message, response, world, learning, records[1:])
        if defender.choose(context, message) != response:
            return tail
        if learning == "adaptive":
            defender = defender.learn(context, message, world)
        return ((identifier, defender, weight),) + tail

    def condition(self, context, message, response, world, learning="frozen"):
        return Belief(self.survivors(context, message, response, world, learning, self.records))


class ControlPlan:
    def __init__(self, contexts, worlds, target, target_world, interaction_cost="1/50", learning="adaptive"):
        self.contexts, self.worlds = contexts, worlds
        self.target, self.target_world = target, target_world
        self.interaction_cost, self.learning = Fraction(interaction_cost), learning
        self.keys, self.cached_values = (), ()

    def validate(self, action, remaining):
        mode, case, message = action
        if mode == "attack":
            context, world = self.target, self.target_world
            if case != 0:
                raise ValueError("target has no calibration case index")
        elif mode == "probe" or mode == "teach":
            if remaining <= 0:
                raise ValueError("interaction budget exhausted")
            if case < 0 or self.contexts[case:] == ():
                raise ValueError("unknown calibration case")
            context, world = self.contexts[case], self.worlds[case]
        else:
            raise ValueError("unknown control action")
        if message < 0 or context.masks[message:] == ():
            raise ValueError("unknown message")
        if context.masks[message] & (1 << world) == 0:
            raise ValueError("message is false in the disclosed world")

    def targets(self, belief, message=0):
        if self.target.masks[message:] == ():
            return ()
        tail = self.targets(belief, message + 1)
        if self.target.masks[message] & (1 << self.target_world) == 0:
            return tail
        action = ("attack", 0, message)
        return ((action, belief.expected_loss(self.target, message, self.target_world)),) + tail

    def branch(self, belief, remaining, mode, case, message, response, probability):
        if probability == 0:
            return Fraction(0)
        learning = self.learning if mode == "teach" else "frozen"
        next_belief = belief.condition(self.contexts[case], message, response, self.worlds[case], learning)
        return probability * self.value(next_belief, remaining - 1)

    def action_value(self, belief, remaining, action):
        self.validate(action, remaining)
        mode, case, message = action
        if mode == "attack":
            return belief.expected_loss(self.target, message, self.target_world)
        a, b, v = belief.responses(self.contexts[case], message)
        return (-self.interaction_cost
                + self.branch(belief, remaining, mode, case, message, 0, a)
                + self.branch(belief, remaining, mode, case, message, 1, b)
                + self.branch(belief, remaining, mode, case, message, 2, v))

    def interactions(self, belief, remaining, case=0, message=0):
        if remaining == 0 or self.contexts[case:] == ():
            return ()
        context = self.contexts[case]
        if context.masks[message:] == ():
            return self.interactions(belief, remaining, case + 1, 0)
        tail = self.interactions(belief, remaining, case, message + 1)
        if context.masks[message] & (1 << self.worlds[case]) == 0:
            return tail
        probe, teach = ("probe", case, message), ("teach", case, message)
        return ((probe, self.action_value(belief, remaining, probe)), (teach, self.action_value(belief, remaining, teach))) + tail

    def best(self, choices):
        if choices[1:] == ():
            return choices[0]
        following = self.best(choices[1:])
        # Earlier actions win exact ties. Terminal choices precede interactions.
        return choices[0] if choices[0][1] >= following[1] else following

    def choose(self, belief, remaining):
        if remaining < 0 or remaining > 3:
            raise ValueError("control horizon outside finite domain")
        key = (belief.signature(), remaining)
        if self.keys.count(key) != 0:
            return self.cached_values[self.keys.index(key)]
        choices = self.targets(belief) + self.interactions(belief, remaining)
        result = self.best(choices)
        self.keys += (key,)
        self.cached_values += (result,)
        return result

    def value(self, belief, remaining):
        return self.choose(belief, remaining)[1]
