"""Independent rational reference for finite recursive communication.

Only Fraction is imported. World/message joint weights are expanded afresh;
neither the production semantics nor its caches or update methods are reused.
This is an exhaustive mathematical reference, not evidence about model strategy.
"""

from fractions import Fraction


class ReferenceSemantics:
    def __init__(self, prior="5/7", masks=(3, 1), power=1, floor="0"):
        self.prior = Fraction(prior)
        self.masks = masks
        self.floor = Fraction(floor)
        if self.prior <= 0 or self.prior >= 1 or self.floor < 0:
            raise ValueError("interior prior and nonnegative selection floor required")
        if str(power) != "1" and str(power) != "2" and str(power) != "3":
            raise ValueError("power must be one, two, or three")
        self.power = int(power)
        self.validate_masks(masks)
        if sum(self.support(0)) == 0 or sum(self.support(1)) == 0:
            raise ValueError("each world requires a truthful available message")

    def validate_masks(self, remaining):
        if remaining == ():
            return
        if remaining[0] != 1 and remaining[0] != 2 and remaining[0] != 3:
            raise ValueError("truth masks must be one, two, or three")
        return self.validate_masks(remaining[1:])

    def support(self, world, position=0):
        if self.masks[position:] == ():
            return ()
        weight = Fraction(1) if self.masks[position] & (1 << world) else Fraction(0)
        return (weight,) + self.support(world, position + 1)

    def normalize(self, weights, total):
        if weights == ():
            return ()
        return (weights[0] / total,) + self.normalize(weights[1:], total)

    def preference_weights(self, depth, credibility, goal, world, position=0):
        if self.masks[position:] == ():
            return ()
        if self.masks[position] & (1 << world):
            a, b = self.joint(depth - 1, credibility, position)
            if a + b == 0:
                raise ValueError("undefined listener at zero-probability message")
            desired = (a, b)[world] if goal == "cooperative" else (b, a)[world]
            weight = self.floor + (desired / (a + b)) ** self.power
        else:
            weight = Fraction(0)
        return (weight,) + self.preference_weights(depth, credibility, goal, world, position + 1)

    def source(self, depth, credibility, goal, world):
        if depth < 1 or depth > 6 or world < 0 or world > 1:
            raise ValueError("source depth or world outside finite domain")
        if goal != "cooperative" and goal != "adversarial":
            raise ValueError("unknown source objective")
        credibility = Fraction(credibility)
        if credibility < 0 or credibility > 1:
            raise ValueError("credibility outside unit interval")
        weights = self.preference_weights(depth, credibility, goal, world)
        total = sum(weights)
        if total == 0:
            weights = self.support(world)
            total = sum(weights)
        return self.normalize(weights, total)

    def joint(self, depth, credibility, message):
        if depth == 0:
            a = self.prior if self.masks[message] & 1 else Fraction(0)
            b = 1 - self.prior if self.masks[message] & 2 else Fraction(0)
            return (a, b)
        cooperative_a = self.source(depth, credibility, "cooperative", 0)[message]
        adversarial_a = self.source(depth, credibility, "adversarial", 0)[message]
        cooperative_b = self.source(depth, credibility, "cooperative", 1)[message]
        adversarial_b = self.source(depth, credibility, "adversarial", 1)[message]
        a = self.prior * (credibility * cooperative_a + (1 - credibility) * adversarial_a)
        b = (1 - self.prior) * (credibility * cooperative_b + (1 - credibility) * adversarial_b)
        return (a, b)

    def listener(self, depth, credibility, message):
        if depth < 0 or depth > 6 or message < 0 or self.masks[message:] == ():
            raise ValueError("listener depth or message outside finite domain")
        credibility = Fraction(credibility)
        if credibility < 0 or credibility > 1:
            raise ValueError("credibility outside unit interval")
        a, b = self.joint(depth, credibility, message)
        if a + b == 0:
            raise ValueError("cannot condition on zero-probability message")
        return a / (a + b)

    def credibility_after(self, depth, credibility, message, world):
        credibility = Fraction(credibility)
        cooperative = self.source(max(1, depth), credibility, "cooperative", world)[message]
        adversarial = self.source(max(1, depth), credibility, "adversarial", world)[message]
        a = credibility * cooperative
        b = (1 - credibility) * adversarial
        if a + b == 0:
            raise ValueError("cannot update from zero-probability feedback")
        return a / (a + b)
