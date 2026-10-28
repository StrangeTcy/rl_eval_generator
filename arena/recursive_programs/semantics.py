"""Trusted recursive reduction and exact finite model accounting."""

from fractions import Fraction
from random import Random


class Rule:
    def __init__(self, a, b, c):
        self.a, self.b, self.c = a, b, c

    def apply(self, left, right, modulus):
        return (self.a * left + self.b * right + self.c) % modulus

    def coefficients(self):
        return (self.a, self.b, self.c)


class Node:
    def __init__(self, label, left=None, right=None, value=0):
        self.label, self.left, self.right, self.value = label, left, right, value
        if label == "leaf":
            self.depth, self.nodes = 0, 1
        else:
            self.depth = 1 + max(left.depth, right.depth)
            self.nodes = 1 + left.nodes + right.nodes

    def reduce(self, rules, modulus):
        if self.label == "leaf":
            return self.value
        index = ("A", "B", "C").index(self.label)
        return rules[index].apply(self.left.reduce(rules, modulus), self.right.reduce(rules, modulus), modulus)

    def render(self):
        if self.label == "leaf":
            return str(self.value)
        return f"{self.label}({self.left.render()},{self.right.render()})"

    def signatures(self):
        if self.label == "leaf":
            return (self.render(),)
        return (self.render(),) + self.left.signatures() + self.right.signatures()

    def distinct_subtrees(self, remaining=None, seen=()):
        if remaining is None:
            remaining = self.signatures()
        if remaining == ():
            return 0
        head, tail = remaining[0], remaining[1:]
        if seen.count(head) != 0:
            return self.distinct_subtrees(tail, seen)
        return 1 + self.distinct_subtrees(tail, seen + (head,))


class TreeFactory:
    def __init__(self, seed, operators, modulus):
        self.rng = Random(seed)
        self.operators, self.modulus = operators, modulus

    def make(self, depth, shape, sharing, root_label=None):
        if depth == 0:
            return Node("leaf", value=self.rng.randrange(self.modulus))
        label = ("A", "B", "C")[self.rng.randrange(self.operators)] if root_label is None else root_label
        if shape == "chain":
            child = self.make(depth - 1, shape, sharing)
            leaf = self.make(0, shape, sharing)
            if self.rng.randrange(2) == 0:
                return Node(label, child, leaf)
            return Node(label, leaf, child)
        left = self.make(depth - 1, shape, sharing)
        right = left if sharing == "repeated" else self.make(depth - 1, shape, sharing)
        return Node(label, left, right)


class RulePool:
    def __init__(self, operator, width, modulus, observations, active=1):
        self.operator, self.width, self.modulus = operator, width, modulus
        self.observations = observations
        self.entries, self.count = (), 0
        if active == 0:
            self.entries, self.count = (Rule(1, 1, 0),), 1
        else:
            self.scan(1, 1, 0)
        if self.count == 0:
            raise ValueError("observations contradict the declared rule family")

    def agrees(self, rule, observations):
        if observations == ():
            return 1
        operator, left, right, outcome = observations[0]
        if operator == self.operator and rule.apply(left, right, self.modulus) != outcome:
            return 0
        return self.agrees(rule, observations[1:])

    def scan(self, a, b, c):
        if a > self.width:
            return
        if b > self.width:
            return self.scan(a + 1, 1, 0)
        if c == self.width:
            return self.scan(a, b + 1, 0)
        candidate = Rule(a, b, c)
        if self.agrees(candidate, self.observations) == 1:
            self.entries += (candidate,)
            self.count += 1
        return self.scan(a, b, c + 1)


class Histogram:
    def __init__(self, modulus):
        self.counts = (0,) * modulus

    def add(self, value):
        self.counts = self.counts[:value] + (self.counts[value] + 1,) + self.counts[value + 1:]

    def expected_loss(self, prediction, total):
        return 1 - Fraction(self.counts[prediction], total)

    def risk(self, total):
        return 1 - Fraction(max(self.counts), total)


class Posterior:
    """Uniform finite grammar posterior; local probes factor by operator."""

    def __init__(self, operators, width, modulus, observations, targets):
        self.modulus, self.targets = modulus, targets
        self.pools = (
            RulePool("A", width, modulus, observations),
            RulePool("B", width, modulus, observations, 1 if operators >= 2 else 0),
            RulePool("C", width, modulus, observations, 1 if operators >= 3 else 0),
        )
        self.total = self.pools[0].count * self.pools[1].count * self.pools[2].count
        self.histograms = (Histogram(modulus), Histogram(modulus), Histogram(modulus), Histogram(modulus), Histogram(modulus), Histogram(modulus))
        self.walk(0, ())

    def walk(self, position, rules):
        if position == 3:
            return self.record(rules, 0)
        return self.branches(position, rules, self.pools[position].entries)

    def branches(self, position, rules, remaining):
        if remaining == ():
            return
        self.walk(position + 1, rules + (remaining[0],))
        return self.branches(position, rules, remaining[1:])

    def record(self, rules, position):
        if position == 6:
            return
        self.histograms[position].add(self.targets[position].reduce(rules, self.modulus))
        return self.record(rules, position + 1)

    def losses(self, predictions, offset=0, position=0):
        if position == 3:
            return (Fraction(0), Fraction(0))
        histogram = self.histograms[offset + position]
        expected, risk = self.losses(predictions, offset, position + 1)
        return (expected + histogram.expected_loss(predictions[position], self.total), risk + histogram.risk(self.total))
