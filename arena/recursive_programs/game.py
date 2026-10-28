"""Infer hidden local rules, evaluate nested programs, and submit a transferable model."""

from fractions import Fraction
from hashlib import sha256
from random import Random
import re

from .semantics import Posterior, Rule, TreeFactory


class ProgramDiscovery:
    def __init__(self, semantic_seed=0, world_seed=0, depth=3, operators=2, width=2, budget=6, shape="balanced", sharing="distinct", demonstrations=0, modulus=7):
        if re.fullmatch(r"[0-9]{1,8}", str(semantic_seed)) is None or re.fullmatch(r"[0-9]{1,8}", str(world_seed)) is None:
            raise ValueError("unsigned seeds below 100000000 required")
        if re.fullmatch(r"[2-5]", str(depth)) is None or re.fullmatch(r"[1-3]", str(operators)) is None:
            raise ValueError("depth 2..5 and operator count 1..3 required")
        if re.fullmatch(r"[23]", str(width)) is None or re.fullmatch(r"[0-9]", str(budget)) is None:
            raise ValueError("width 2 or 3 and query budget 0..9 required")
        if re.fullmatch(r"[0-2]", str(demonstrations)) is None or (str(modulus) != "7" and str(modulus) != "11"):
            raise ValueError("demonstrations 0..2 and modulus 7 or 11 required")
        if shape != "chain" and shape != "balanced":
            raise ValueError("unknown tree shape")
        if sharing != "distinct" and sharing != "repeated":
            raise ValueError("unknown subtree condition")
        if sharing == "repeated" and shape != "balanced":
            raise ValueError("repeated subtrees require balanced branching")
        semantic_seed, world_seed = int(semantic_seed), int(world_seed)
        self.depth, self.operators, self.width = int(depth), int(operators), int(width)
        self.remaining, self.budget = int(budget), int(budget)
        self.demonstrations, self.modulus = int(demonstrations), int(modulus)
        self.shape, self.sharing = shape, sharing
        self.stage, self.result, self.spent = "open", None, 0
        self.actions, self.observations = (), ()
        public = TreeFactory(f"recursive-public-v1:{semantic_seed}", self.operators, self.modulus)
        private = TreeFactory(f"recursive-transfer-v1:{semantic_seed}", self.operators, self.modulus)
        labels = ("A", "B", "C")
        self.targets = (public.make(self.depth, shape, sharing, labels[0]), public.make(self.depth, shape, sharing, labels[1 % self.operators]), public.make(self.depth, shape, sharing, labels[2 % self.operators]))
        self.transfer = (private.make(self.depth + 1, shape, sharing, labels[0]), private.make(self.depth + 1, shape, sharing, labels[1 % self.operators]), private.make(self.depth + 1, shape, sharing, labels[2 % self.operators]))
        secret = Random(f"recursive-rule-v1:{world_seed}")
        self.rules = self.draw_rules(secret, 0)
        self.demonstrate(0, 0)
        canonical = ("recursive-programs/1", self.depth, self.operators, self.width, self.budget, shape, sharing, self.demonstrations, self.modulus, self.targets[0].render(), self.targets[1].render(), self.targets[2].render())
        self.semantic_id = sha256(repr(canonical).encode("utf8")).hexdigest()

    def draw_rules(self, rng, position):
        if position == 3:
            return ()
        if position >= self.operators:
            rule = Rule(1, 1, 0)
        else:
            rule = Rule(rng.randrange(1, self.width + 1), rng.randrange(1, self.width + 1), rng.randrange(self.width))
        return (rule,) + self.draw_rules(rng, position + 1)

    def demonstrate(self, operator, basis):
        if operator == self.operators:
            return
        if basis == self.demonstrations:
            return self.demonstrate(operator + 1, 0)
        left, right = ((0, 0), (1, 0), (0, 1))[basis]
        label = ("A", "B", "C")[operator]
        outcome = self.rules[operator].apply(left, right, self.modulus)
        self.observations += ((label, left, right, outcome),)
        return self.demonstrate(operator, basis + 1)

    def observation_text(self, observations):
        if observations == ():
            return ""
        label, left, right, value = observations[0]
        return f"Observation {label} {left} {right} = {value}\n" + self.observation_text(observations[1:])

    def view(self):
        labels = "ABC"[:self.operators]
        return ("Recursive rule discovery. Infer local operator rules and predict nested programs.\n"
                f"Modulus={self.modulus}; Operators={self.operators}; Width={self.width}; Remaining={self.remaining}.\n"
                f"Active labels={labels}. Each label has a fixed hidden rule (a*left+b*right+c) modulo the modulus.\n"
                f"Independently for each label, a and b are uniform integers 1..{self.width}; c is uniform 0..{self.width - 1}.\n"
                "Every leaf is a literal residue. The same local rule applies at every nesting level.\n"
                f"Target 0: {self.targets[0].render()}\nTarget 1: {self.targets[1].render()}\nTarget 2: {self.targets[2].render()}\n"
                + self.observation_text(self.observations)
                + "Actions: probe LABEL LEFT RIGHT, with literal residues only; no nested probes or repeated inputs.\n"
                "Finish: answer V0 V1 V2 model aA bA cA [aB bB cB] [aC bC cC], with exactly one coefficient triple per active label.\n"
                "Predictions and the submitted model are scored separately. A model can remain uncertain under insufficient evidence.\n"
                "Your model is also evaluated on three unseen programs one level deeper; those programs cannot be probed.\n")

    def has_probe(self, label, left, right, observations):
        if observations == ():
            return 0
        old_label, old_left, old_right, outcome = observations[0]
        if label == old_label and left == old_left and right == old_right:
            return 1
        return self.has_probe(label, left, right, observations[1:])

    def parse_rules(self, coefficients, position=0):
        if position == 3:
            return ()
        if position >= self.operators:
            return (Rule(1, 1, 0),) + self.parse_rules(coefficients, position + 1)
        a, b, c = tuple(map(int, coefficients[3 * position:3 * position + 3]))
        if min(a, b) < 1 or max(a, b) > self.width or c < 0 or c >= self.width:
            raise ValueError("model coefficients outside the declared family")
        return (Rule(a, b, c),) + self.parse_rules(coefficients, position + 1)

    def consistent(self, rules, observations):
        if observations == ():
            return 1
        label, left, right, outcome = observations[0]
        if rules[("A", "B", "C").index(label)].apply(left, right, self.modulus) != outcome:
            return 0
        return self.consistent(rules, observations[1:])

    def errors(self, predictions, targets, rules, position=0):
        if position == 3:
            return 0
        error = 0 if predictions[position] == targets[position].reduce(rules, self.modulus) else 1
        return error + self.errors(predictions, targets, rules, position + 1)

    def nonassociative_operators(self, position=0):
        if position == self.operators:
            return 0
        rule = self.rules[position]
        count = 1 if rule.a != 1 or rule.b != 1 else 0
        return count + self.nonassociative_operators(position + 1)

    def step(self, raw):
        if self.stage != "open":
            raise ValueError("episode closed")
        probe = re.fullmatch(r"probe ([ABC]) ([0-9]{1,2}) ([0-9]{1,2})", raw)
        if probe is not None:
            label, left, right = probe.groups()
            operator, left, right = ("A", "B", "C").index(label), int(left), int(right)
            if operator >= self.operators or max(left, right) >= self.modulus:
                raise ValueError("inactive label or invalid residue")
            if self.remaining == 0 or self.has_probe(label, left, right, self.observations) == 1:
                raise ValueError("query budget exhausted or repeated input")
            outcome = self.rules[operator].apply(left, right, self.modulus)
            self.observations += ((label, left, right, outcome),)
            self.actions += (raw,)
            self.remaining -= 1
            self.spent += 1
            return f"Observation {label} {left} {right} = {outcome}"
        answer = re.fullmatch(r"answer ([0-9]{1,2}) ([0-9]{1,2}) ([0-9]{1,2}) model" + r" ([1-3]) ([1-3]) ([0-2])" * self.operators, raw)
        if answer is None:
            raise ValueError("invalid answer grammar")
        values = tuple(map(int, answer.groups()[:3]))
        if max(values) >= self.modulus:
            raise ValueError("prediction outside the residue space")
        model = self.parse_rules(answer.groups()[3:])
        posterior = Posterior(self.operators, self.width, self.modulus, self.observations, self.targets + self.transfer)
        expected, risk = posterior.losses(values)
        transfer_values = (self.transfer[0].reduce(model, self.modulus), self.transfer[1].reduce(model, self.modulus), self.transfer[2].reduce(model, self.modulus))
        transfer_expected, transfer_risk = posterior.losses(transfer_values, 3)
        self.result = (
            ("prediction_loss", str(Fraction(self.errors(values, self.targets, self.rules), 3))),
            ("prediction_expected_loss", str(expected / 3)),
            ("prediction_bayes_risk", str(risk / 3)),
            ("prediction_regret", str((expected - risk) / 3)),
            ("certificate_consistent", str(self.consistent(model, self.observations))),
            ("candidate_grammars", str(posterior.total)),
            ("identified_from_evidence", str(1 if posterior.total == 1 else 0)),
            ("composition_errors_given_certificate", str(self.errors(values, self.targets, model))),
            ("certificate_transfer_loss", str(Fraction(self.errors(transfer_values, self.transfer, self.rules), 3))),
            ("certificate_transfer_excess_vs_marginal_oracle", str((transfer_expected - transfer_risk) / 3)),
            ("queries", str(self.spent)),
            ("public_depth", str(self.depth)),
            ("public_node_counts", (self.targets[0].nodes, self.targets[1].nodes, self.targets[2].nodes)),
            ("public_distinct_subtrees", (self.targets[0].distinct_subtrees(), self.targets[1].distinct_subtrees(), self.targets[2].distinct_subtrees())),
            ("nonassociative_operators", str(self.nonassociative_operators())),
        )
        self.actions += (raw,)
        self.stage = "done"
        return self.result
