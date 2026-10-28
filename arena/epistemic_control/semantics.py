"""Finite recursive speaker/listener models and an explicit adaptive defender.

Depth is epistemic: a source predicts a lower-depth listener, and a listener
conditions on the source's resulting message-selection policy. It is unrelated
to the recursion used by an implementation to traverse a search tree.
"""

from fractions import Fraction


class Semantics:
    def __init__(self, prior="5/7", masks=(3, 1), power=1, floor="0"):
        self.prior, self.floor = Fraction(prior), Fraction(floor)
        if self.prior <= 0 or self.prior >= 1 or self.floor < 0:
            raise ValueError("interior prior and nonnegative selection floor required")
        if str(power) != "1" and str(power) != "2" and str(power) != "3":
            raise ValueError("power must be one, two, or three")
        if masks == () or masks[4:] != ():
            raise ValueError("one to four message masks required")
        self.masks, self.power = masks, int(power)
        self.validate_masks(masks)
        if sum(self.support(0)) == 0 or sum(self.support(1)) == 0:
            raise ValueError("each world requires a truthful available message")
        self.source_keys, self.source_values = (), ()
        self.listener_keys, self.listener_values = (), ()

    def validate_masks(self, remaining):
        if remaining == ():
            return
        if remaining[0] != 1 and remaining[0] != 2 and remaining[0] != 3:
            raise ValueError("truth masks must be one, two, or three")
        return self.validate_masks(remaining[1:])

    def support(self, world, position=0):
        if self.masks[position:] == ():
            return ()
        value = Fraction(1) if self.masks[position] & (1 << world) else Fraction(0)
        return (value,) + self.support(world, position + 1)

    def weights(self, depth, credibility, goal, world, position=0):
        if self.masks[position:] == ():
            return ()
        weight = Fraction(0)
        if self.masks[position] & (1 << world):
            p = self.listener(depth - 1, credibility, position)
            correct = p if world == 0 else 1 - p
            desired = correct if goal == "cooperative" else 1 - correct
            weight = self.floor + desired ** self.power
        return (weight,) + self.weights(depth, credibility, goal, world, position + 1)

    def normalize(self, weights, total):
        if weights == ():
            return ()
        return (weights[0] / total,) + self.normalize(weights[1:], total)

    def source(self, depth, credibility, goal, world):
        if depth < 1 or depth > 6 or (world != 0 and world != 1):
            raise ValueError("source depth or world outside finite domain")
        if goal != "cooperative" and goal != "adversarial":
            raise ValueError("unknown source objective")
        credibility = Fraction(credibility)
        if credibility < 0 or credibility > 1:
            raise ValueError("credibility outside unit interval")
        key = (depth, credibility, goal, world)
        if self.source_keys.count(key) != 0:
            return self.source_values[self.source_keys.index(key)]
        weights = self.weights(depth, credibility, goal, world)
        total = sum(weights)
        if total == 0:
            weights = self.support(world)
            total = sum(weights)
        result = self.normalize(weights, total)
        self.source_keys += (key,)
        self.source_values += (result,)
        return result

    def listener(self, depth, credibility, message):
        if depth < 0 or depth > 6 or message < 0 or self.masks[message:] == ():
            raise ValueError("listener depth or message outside finite domain")
        credibility = Fraction(credibility)
        if credibility < 0 or credibility > 1:
            raise ValueError("credibility outside unit interval")
        key = (depth, credibility, message)
        if self.listener_keys.count(key) != 0:
            return self.listener_values[self.listener_keys.index(key)]
        if depth == 0:
            a = self.prior if self.masks[message] & 1 else Fraction(0)
            b = 1 - self.prior if self.masks[message] & 2 else Fraction(0)
        else:
            ca = self.source(depth, credibility, "cooperative", 0)[message]
            aa = self.source(depth, credibility, "adversarial", 0)[message]
            cb = self.source(depth, credibility, "cooperative", 1)[message]
            ab = self.source(depth, credibility, "adversarial", 1)[message]
            a = self.prior * (credibility * ca + (1 - credibility) * aa)
            b = (1 - self.prior) * (credibility * cb + (1 - credibility) * ab)
        if a + b == 0:
            raise ValueError("cannot condition on zero-probability message")
        result = a / (a + b)
        self.listener_keys += (key,)
        self.listener_values += (result,)
        return result

    def credibility_after(self, depth, credibility, message, world):
        credibility = Fraction(credibility)
        cooperative = self.source(max(1, depth), credibility, "cooperative", world)[message]
        adversarial = self.source(max(1, depth), credibility, "adversarial", world)[message]
        a, b = credibility * cooperative, (1 - credibility) * adversarial
        if a + b == 0:
            raise ValueError("cannot update from zero-probability feedback")
        return a / (a + b)


class Defender:
    """A supplied procedure family with explicit source-belief learning.

Actions 0 and 1 commit to A and B. Action 2 purchases a perfect verification.
The learning method returns a new state; probing an old state cannot alter it.
"""

    def __init__(self, depth=1, cost="1/2", credibility="1/2"):
        if depth < 0 or depth > 6:
            raise ValueError("defender depth outside finite domain")
        self.depth, self.cost, self.credibility = depth, Fraction(cost), Fraction(credibility)
        if self.cost < 0 or self.cost > 1 or self.credibility < 0 or self.credibility > 1:
            raise ValueError("invalid defender cost or source belief")

    def choose(self, context, message):
        p = context.listener(self.depth, self.credibility, message)
        if self.cost < min(p, 1 - p):
            return 2
        return 0 if p >= Fraction(1, 2) else 1

    def loss(self, action, world):
        if action == 2:
            return self.cost
        if action == 0 or action == 1:
            return Fraction(0) if action == world else Fraction(1)
        raise ValueError("unknown defender procedure")

    def learn(self, context, message, world):
        credibility = context.credibility_after(self.depth, self.credibility, message, world)
        return Defender(self.depth, self.cost, credibility)

    def row(self):
        return (self.depth, str(self.cost), str(self.credibility))
