"""Public-text reference using path-weighted expansion, without engine imports.

The probe policy completes an identifying affine basis. It is not claimed to
minimize the number of probes. Terminal predictions are posterior modes over
all models consistent with the public local observations.
"""

import re


class Choices:
    def __init__(self, label, width, modulus, observation, active=1):
        self.label, self.width, self.modulus = label, width, modulus
        self.observation, self.entries = observation, ()
        if active == 0:
            self.entries = ((1, 1, 0),)
        else:
            self.search(1, 1, 0)
        if self.entries == ():
            raise ValueError("public evidence has no compatible rule")

    def compatible(self, coefficients, offset=0):
        event = re.search(r"^Observation " + self.label + r" ([0-9]{1,2}) ([0-9]{1,2}) = ([0-9]{1,2})$", self.observation[offset:], re.MULTILINE)
        if event is None:
            return 1
        x, y, observed = tuple(map(int, event.groups()))
        a, b, c = coefficients
        if (a * x + b * y + c) % self.modulus != observed:
            return 0
        return self.compatible(coefficients, offset + event.end())

    def search(self, a, b, c):
        if a > self.width:
            return
        if b > self.width:
            return self.search(a + 1, 1, 0)
        if c == self.width:
            return self.search(a, b + 1, 0)
        if self.compatible((a, b, c)) == 1:
            self.entries += ((a, b, c),)
        return self.search(a, b, c + 1)


class PublicSolver:
    def __init__(self, mode="full"):
        if mode != "full" and mode != "shallow":
            raise ValueError("unknown composition policy")
        self.mode = mode

    def missing_basis(self, position=0, basis=0):
        if position == self.operators:
            return None
        if basis == 3:
            return self.missing_basis(position + 1, 0)
        label = "ABC"[position]
        left, right = ((0, 0), (1, 0), (0, 1))[basis]
        if re.search(r"^Observation " + label + f" {left} {right} = [0-9]+$", self.observation, re.MULTILINE) is None:
            return f"probe {label} {left} {right}"
        return self.missing_basis(position, basis + 1)

    def evaluate(self, program, rules, modulus):
        self.program, self.rules, self.modulus = program, rules, modulus
        self.parse_nodes = 0
        end, contribution, first_leaf = self.expand(0, 1, 0)
        if program[end:] != "":
            raise ValueError("trailing expression text")
        return contribution % modulus

    def expand(self, position, weight, depth):
        self.parse_nodes += 1
        if depth > 6 or self.parse_nodes > 255:
            raise ValueError("expression exceeds reference bounds")
        literal = re.match(r"[0-9]{1,2}", self.program[position:])
        if literal is not None:
            value = int(literal.group(0))
            if value >= self.modulus:
                raise ValueError("invalid leaf residue")
            return (position + literal.end(), weight * value, value)
        label = self.program[position:position + 1]
        if label != "A" and label != "B" and label != "C":
            raise ValueError("unknown operator")
        if self.program[position + 1:position + 2] != "(":
            raise ValueError("missing opening delimiter")
        a, b, c = self.rules["ABC".index(label)]
        end_left, left, first_leaf = self.expand(position + 2, weight * a, depth + 1)
        if self.program[end_left:end_left + 1] != ",":
            raise ValueError("missing child delimiter")
        end_right, right, other_leaf = self.expand(end_left + 1, weight * b, depth + 1)
        if self.program[end_right:end_right + 1] != ")":
            raise ValueError("missing closing delimiter")
        if self.mode == "shallow" and depth > 0:
            return (end_right + 1, weight * first_leaf, first_leaf)
        return (end_right + 1, weight * c + left + right, first_leaf)

    def enumerate_models(self, position, chosen):
        if position == 3:
            return self.accumulate(chosen, 0)
        return self.enumerate_choices(position, chosen, self.choices[position].entries)

    def enumerate_choices(self, position, chosen, candidates):
        if candidates == ():
            return
        self.enumerate_models(position + 1, chosen + (candidates[0],))
        return self.enumerate_choices(position, chosen, candidates[1:])

    def accumulate(self, rules, position):
        if position == 3:
            return
        value = self.evaluate(self.targets[position], rules, self.modulus)
        counts = self.counts[position]
        counts = counts[:value] + (counts[value] + 1,) + counts[value + 1:]
        self.counts = self.counts[:position] + (counts,) + self.counts[position + 1:]
        return self.accumulate(rules, position + 1)

    def certificate(self, position=0):
        if position == self.operators:
            return ()
        return self.choices[position].entries[0] + self.certificate(position + 1)

    def act(self, observation):
        self.observation = observation
        header = re.search(r"Modulus=(7|11); Operators=([1-3]); Width=([23]); Remaining=([0-9])\.", observation)
        if header is None:
            raise ValueError("missing public recursive-program contract")
        self.modulus, self.operators, self.width, remaining = tuple(map(int, header.groups()))
        query = self.missing_basis()
        if remaining > 0 and query is not None:
            return query
        first = re.search(r"^Target 0: ([ABC0-9(),]+)$", observation, re.MULTILINE)
        second = re.search(r"^Target 1: ([ABC0-9(),]+)$", observation, re.MULTILINE)
        third = re.search(r"^Target 2: ([ABC0-9(),]+)$", observation, re.MULTILINE)
        if first is None or second is None or third is None:
            raise ValueError("missing public targets")
        self.targets = (first.group(1), second.group(1), third.group(1))
        self.choices = (
            Choices("A", self.width, self.modulus, observation),
            Choices("B", self.width, self.modulus, observation, 1 if self.operators >= 2 else 0),
            Choices("C", self.width, self.modulus, observation, 1 if self.operators >= 3 else 0),
        )
        self.counts = ((0,) * self.modulus, (0,) * self.modulus, (0,) * self.modulus)
        self.enumerate_models(0, ())
        a, b, c = self.counts
        return f"answer {a.index(max(a))} {b.index(max(b))} {c.index(max(c))} model " + " ".join(map(str, self.certificate()))


class ShallowSolver(PublicSolver):
    """Learns local rules, then collapses each internal child to its first leaf."""

    def __init__(self):
        super().__init__("shallow")


class ZeroSolver:
    def act(self, observation):
        count = re.search(r"Operators=([1-3]);", observation)
        if count is None:
            raise ValueError("missing operator count")
        return "answer 0 0 0 model" + " 1 1 0" * int(count.group(1))
