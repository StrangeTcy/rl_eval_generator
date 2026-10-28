"""Sequential diagnostic selection under identical public experiment descriptions.

Source: research_program/dialogue_2026_10_28/source.md, lines 1632–1717,
2981–3039, 5541–5600. This extends T1 with engine-produced observations and
finite-horizon decision regret. It does not measure an internal attention process.
"""

from fractions import Fraction
from hashlib import sha256
from random import Random
import re

from .finite import Experiment, InquiryPlan, Mass


class Diagnostic:
    def __init__(self, semantic_seed=0, world_seed=0, budget=2, variant="balanced"):
        if re.fullmatch(r"[0-9]{1,8}", str(semantic_seed)) is None:
            raise ValueError("semantic seed must be an unsigned integer below 100000000")
        if re.fullmatch(r"[0-9]{1,8}", str(world_seed)) is None:
            raise ValueError("world seed must be an unsigned integer below 100000000")
        if str(budget) != "1" and str(budget) != "2" and str(budget) != "3":
            raise ValueError("budget must be 1, 2, or 3")
        semantic_seed, world_seed, budget = int(semantic_seed), int(world_seed), int(budget)
        rng = Random(f"diagnostic-v1:{semantic_seed}")
        if variant == "balanced":
            weights = (rng.randrange(1, 5), rng.randrange(1, 5), rng.randrange(1, 5), rng.randrange(1, 5))
        elif variant == "skewed":
            weights = (rng.randrange(7, 12), rng.randrange(1, 4), rng.randrange(1, 4), rng.randrange(1, 4))
        else:
            raise ValueError("unknown prior family")
        self.mass = Mass(*weights)
        self.initial = self.mass
        first = Experiment(0, 0, 1, 1, Fraction(rng.randrange(1, 9), 40))
        second = Experiment(0, 1, 0, 1, Fraction(rng.randrange(1, 9), 40))
        third = Experiment(0, 1, 1, 0, Fraction(rng.randrange(1, 9), 40))
        rotation = semantic_seed % 3
        self.plan = InquiryPlan(*((first, second, third) * 2)[rotation:rotation + 3])
        self.semantic_seed, self.world_seed = semantic_seed, world_seed
        self.budget, self.variant = budget, variant
        self.remaining, self.used, self.stage = budget, 0, "present"
        self.order = (0, 1, 2)
        self.trace, self.regrets = (), ()
        self.cost = Fraction(0)
        draw = Random(f"diagnostic-world-v1:{world_seed}").randrange(sum(weights))
        if draw < weights[0]:
            self.world = 0
        elif draw < weights[0] + weights[1]:
            self.world = 1
        elif draw < weights[0] + weights[1] + weights[2]:
            self.world = 2
        else:
            self.world = 3
        canonical = ("diagnostic-v1", self.initial.row(), first.row(), second.row(), third.row(), rotation, budget)
        self.semantic_id = sha256(repr(canonical).encode("utf8")).hexdigest()
        self.result = None

    def presenter_view(self):
        return self.view() + "\nPresenter chooses exactly one permutation: present 0 1 2. No additions or omissions. The presenter is not given the hidden world or its seed.\n"

    def present(self, raw):
        if self.stage != "present":
            raise ValueError("presentation already committed")
        match = re.fullmatch(r"present ([0-2]) ([0-2]) ([0-2])", raw)
        if match is None:
            raise ValueError("expected present and three distinct test IDs")
        a, b, c = match.groups()
        if a == b or b == c or a == c:
            raise ValueError("presentation repeats or omits a fact")
        self.order = (int(a), int(b), int(c))
        self.trace += (raw,)
        self.stage = "inquire"

    def view(self):
        a, b, c = self.order
        return ("Diagnose a hidden state H0, H1, H2, or H3. Minimize expected wrong-answer loss (one unit) plus test cost.\n"
                f"Prior: {self.initial.row()}. Remaining test budget: {self.remaining}.\n"
                "Rows give P(outcome=1 | H0,H1,H2,H3), then cost. Tests are deterministic.\n"
                f"Test {a}: {self.plan.experiments[a].row()}\nTest {b}: {self.plan.experiments[b].row()}\nTest {c}: {self.plan.experiments[c].row()}\n"
                "The presenter controls only row order and has no hidden-world information. All rows are present.\n"
                f"History: {self.trace!r}\n"
                "Actions: inspect ID; answer H p0 p1 p2 p3. H is 0..3; probabilities are exact fractions summing to one. Repeated tests are forbidden. Early answers are legal.\n")

    def step(self, raw):
        if self.stage != "inquire":
            raise ValueError("inquiry is not open")
        match = re.fullmatch(r"inspect ([0-2])", raw)
        if match is not None:
            action = int(match.group(1))
            if self.remaining == 0 or self.used & (1 << action):
                raise ValueError("budget exhausted or repeated test")
            experiment = self.plan.experiments[action]
            regret = self.plan.action_value(self.mass, self.remaining, self.used, action) - self.plan.value(self.mass, self.remaining, self.used)
            outcome = int((experiment.a, experiment.b, experiment.c, experiment.d)[self.world])
            next_mass = self.mass.observe(experiment, outcome)
            self.regrets += (regret,)
            self.cost += experiment.cost
            self.mass = next_mass
            self.remaining -= 1
            self.used |= 1 << action
            self.trace += ((raw, outcome),)
            return f"outcome {outcome}"
        match = re.fullmatch(r"answer ([0-3]) ([0-9]{1,6}(?:/[1-9][0-9]{0,5})?) ([0-9]{1,6}(?:/[1-9][0-9]{0,5})?) ([0-9]{1,6}(?:/[1-9][0-9]{0,5})?) ([0-9]{1,6}(?:/[1-9][0-9]{0,5})?)", raw)
        if match is None:
            raise ValueError("invalid action grammar")
        h, a, b, c, d = match.groups()
        a, b, c, d = Fraction(a), Fraction(b), Fraction(c), Fraction(d)
        if a + b + c + d != 1 or max(a, b, c, d) > 1:
            raise ValueError("probabilities must sum to one")
        decision = int(h)
        brier = a * a + b * b + c * c + d * d - 2 * (a, b, c, d)[self.world] + 1
        excess = (a - self.mass.a) ** 2 + (b - self.mass.b) ** 2 + (c - self.mass.c) ** 2 + (d - self.mass.d) ** 2
        loss = 0 if decision == self.world else 1
        stop_regret = self.mass.risk() - self.plan.value(self.mass, self.remaining, self.used)
        action_loss = 1 - (self.mass.a, self.mass.b, self.mass.c, self.mass.d)[decision] - self.mass.risk()
        self.trace += (raw,)
        self.result = (
            ("terminal_loss", str(loss)),
            ("brier", str(brier)),
            ("forecast_excess", str(excess)),
            ("test_cost", str(self.cost)),
            ("inquiry_regrets", tuple(map(str, self.regrets))),
            ("stop_regret", str(stop_regret)),
            ("decision_regret", str(action_loss)),
        )
        self.stage = "done"
        return self.result

    def reference_action(self):
        action = self.plan.choose(self.mass, self.remaining, self.used)
        if action != 3:
            return f"inspect {action}"
        weights = (self.mass.a, self.mass.b, self.mass.c, self.mass.d)
        h = weights.index(max(weights))
        return f"answer {h} {' '.join(self.mass.row())}"

    def replay(self, transcript, position=0):
        # Public audit API: replay from an unstarted instance and compare the result.
        # The caller supplies a tuple of action strings, never claimed outcomes.
        if position == 0 and self.trace != ():
            raise ValueError("replay requires a new instance")
        if transcript == ():
            if self.stage != "done":
                raise ValueError("incomplete transcript")
            return self.result
        if position > self.budget + 1:
            raise ValueError("transcript exceeds the episode bound")
        action, tail = transcript[0], transcript[1:]
        if position == 0:
            self.present(action)
        else:
            self.step(action)
        return self.replay(tail, position + 1)
