"""Identify a hidden recursive defender and shape its later decision procedure.

Provenance: dialogue opportunities OP008, OP010, OP011, OP033, OP037, OP074.
All messages are literally true. The attacker selects observations that can
alter a supplied learner's source-objective belief and commit/verify choices.
"""

from fractions import Fraction
from hashlib import sha256
from random import Random
import re

from .semantics import Defender, Semantics
from .planning import Belief, ControlPlan


class ControlGame:
    def __init__(self, semantic_seed=0, world_seed=0, depth=2, breadth=2, horizon=2, menu="asymmetric", power=1, learning="adaptive", prior="2/3", credibility="1/2", target_world=0, interaction_cost="1/50", selected_profile=None):
        if re.fullmatch(r"[0-9]{1,8}", str(semantic_seed)) is None or re.fullmatch(r"[0-9]{1,8}", str(world_seed)) is None:
            raise ValueError("unsigned seeds below 100000000 required")
        if re.fullmatch(r"[0-3]", str(depth)) is None or re.fullmatch(r"[12]", str(breadth)) is None or re.fullmatch(r"[0-3]", str(horizon)) is None:
            raise ValueError("depth 0..3, breadth 1..2, horizon 0..3 required")
        if re.fullmatch(r"[12]", str(power)) is None or re.fullmatch(r"[01]", str(target_world)) is None:
            raise ValueError("power 1..2 and target world 0..1 required")
        if learning != "adaptive" and learning != "frozen":
            raise ValueError("learning must be adaptive or frozen")
        self.semantic_seed, self.world_seed = int(semantic_seed), int(world_seed)
        self.depth, self.breadth, self.horizon = int(depth), int(breadth), int(horizon)
        self.power, self.target_world = int(power), int(target_world)
        if self.depth > 1 and self.horizon > 2:
            raise ValueError("depth above one supports horizon at most two")
        if self.depth > 2 and self.power > 1:
            raise ValueError("depth three supports selection power one")
        self.prior, self.credibility = Fraction(prior), Fraction(credibility)
        self.interaction_cost = Fraction(interaction_cost)
        if self.prior <= 0 or self.prior >= 1 or self.credibility <= 0 or self.credibility >= 1:
            raise ValueError("interior prior and credibility required")
        if self.prior.denominator > 12 or self.credibility.denominator > 12 or self.interaction_cost < 0 or self.interaction_cost > 1:
            raise ValueError("prior/credibility denominators at most twelve and interaction cost in [0,1] required")
        self.menu, self.learning = menu, learning
        if menu == "asymmetric":
            masks = (3, 1)
        elif menu == "symmetric":
            masks = (3, 1, 2)
        elif menu == "redundant":
            masks = (3, 1, 1, 2)
        elif menu == "exclusive":
            masks = (1, 2)
        else:
            raise ValueError("unknown message-menu topology")
        rotation = self.semantic_seed % (masks.count(1) + masks.count(2) + masks.count(3))
        masks = masks[rotation:] + masks[:rotation]
        self.target = Semantics(self.prior, masks, self.power, "1/4")
        diagnostic_prior = Fraction(5, 7) if self.prior != Fraction(5, 7) else Fraction(3, 4)
        self.contexts = (self.target, Semantics(1 - self.prior, (3, 2), self.power, "1/4"), Semantics(diagnostic_prior, (3, 1), self.power, "1/4"))
        self.worlds = (0, 1, 0)
        self.initial_records = self.catalogue(0)
        self.belief = Belief(self.initial_records)
        count = (self.depth + 1) * self.breadth
        if selected_profile is None:
            chosen = Random(f"recursive-defender-v1:{self.world_seed}").randrange(count)
        else:
            if re.fullmatch(r"[0-7]", str(selected_profile)) is None or int(selected_profile) >= count:
                raise ValueError("selected profile outside the declared catalogue")
            chosen = int(selected_profile)
        self.profile_id, self.actual = self.initial_records[chosen][:2]
        self.initial_actual = self.actual
        self.plan = ControlPlan(self.contexts, self.worlds, self.target, self.target_world, self.interaction_cost, learning)
        self.remaining, self.spent = self.horizon, Fraction(0)
        self.stage, self.result = "open", None
        self.actions, self.trace, self.regrets = (), (), ()
        self.probes, self.teaches = 0, 0
        canonical = ("epistemic-control/1", self.context_rows(), self.profile_rows(), self.horizon, self.target_world, learning, str(self.interaction_cost))
        self.semantic_id = sha256(repr(canonical).encode("utf8")).hexdigest()

    def catalogue(self, position):
        if position == (self.depth + 1) * self.breadth:
            return ()
        depth = position // self.breadth
        cost = Fraction(1, 2) if position % self.breadth == 0 else Fraction(1, 4)
        defender = Defender(depth, cost, self.credibility)
        return ((position, defender, Fraction(1)),) + self.catalogue(position + 1)

    def profile_rows(self, records=None):
        if records is None:
            records = self.initial_records
        if records == ():
            return ()
        identifier, defender, weight = records[0]
        return ((identifier, defender.row()),) + self.profile_rows(records[1:])

    def context_rows(self, position=0):
        if self.contexts[position:] == ():
            return ()
        context = self.contexts[position]
        return ((position, str(context.prior), context.masks, context.power, str(context.floor), self.worlds[position]),) + self.context_rows(position + 1)

    def view(self):
        return ("Identify a hidden defender procedure and influence its target decision using literally true messages.\n"
                "Worlds: 0=A, 1=B. Mask 1 means true only in A; 2 only in B; 3 in both. Message IDs are positions in each mask tuple.\n"
                f"Cases (ID, prior_A, masks, power, floor, audited_world): {self.context_rows()!r}\n"
                f"Target uses case 0; its world, known to you, is {self.target_world}.\n"
                f"Profiles (ID, (depth, verification_cost, initial_credibility)): {self.profile_rows()!r}. Initial profile prior is uniform.\n"
                "L0 conditions the world prior on literal truth. At depth d>=1, a cooperative source selects among true messages with weights floor+L[d-1](true world|message)^power; an adversarial source uses floor+(1-L[d-1](true world|message))^power. Normalize within each world; all-zero weights fall back to uniform true messages.\n"
                "Ld conditions on credibility*S_cooperative[d]+(1-credibility)*S_adversarial[d]. Every nested listener uses the same current credibility.\n"
                "The defender commits to MAP (A on a tie), or buys perfect verification when its cost is strictly below MAP error risk. Procedures: 0=commit A, 1=commit B, 2=verify then answer correctly.\n"
                "A probe uses a disposable copy of the current defender; it returns only the selected procedure and changes no source belief. Teaching uses the live defender, returns its selected procedure, then supplies the case's true world as independent feedback.\n"
                "After teaching, source-objective odds are multiplied by S_cooperative[max(1,d)](message|audited world)/S_adversarial[max(1,d)](message|audited world), evaluated at the old credibility. The model assumes a stationary source objective and does not anticipate a teaching campaign.\n"
                f"Learning={self.learning}; Remaining={self.remaining}; Interaction_cost={self.interaction_cost}. In the frozen arm teaching supplies feedback but leaves credibility unchanged.\n"
                "Actions: probe CASE MESSAGE; teach CASE MESSAGE; attack MESSAGE p_commit_A p_commit_B p_verify. Every selected message must be true in the corresponding known world. Forecasts are exact fractions summing to one.\n"
                "Maximize target wrong-answer loss (one unit) plus target verification cost, minus your probe/teaching expenditure. Calibration loss is not rewarded.\n"
                f"History: {self.trace!r}\n")

    def step(self, raw):
        if self.stage != "open":
            raise ValueError("episode closed")
        match = re.fullmatch(r"(probe|teach) ([0-2]) ([0-3])", raw)
        if match is not None:
            mode, case, message = match.groups()
            case, message = int(case), int(message)
            action = (mode, case, message)
            self.plan.validate(action, self.remaining)
            regret = self.plan.value(self.belief, self.remaining) - self.plan.action_value(self.belief, self.remaining, action)
            context, world = self.contexts[case], self.worlds[case]
            response = self.actual.choose(context, message)
            update = self.learning if mode == "teach" else "frozen"
            next_belief = self.belief.condition(context, message, response, world, update)
            next_actual = self.actual.learn(context, message, world) if update == "adaptive" else self.actual
            self.belief, self.actual = next_belief, next_actual
            self.remaining -= 1
            self.spent += self.interaction_cost
            self.regrets += (regret,)
            self.probes += 1 if mode == "probe" else 0
            self.teaches += 1 if mode == "teach" else 0
            self.actions += (raw,)
            self.trace += ((raw, response),)
            return f"defender procedure {response}"
        match = re.fullmatch(r"attack ([0-3]) ([0-9]{1,6}(?:/[1-9][0-9]{0,5})?) ([0-9]{1,6}(?:/[1-9][0-9]{0,5})?) ([0-9]{1,6}(?:/[1-9][0-9]{0,5})?)", raw)
        if match is None:
            raise ValueError("invalid control action grammar")
        message, a, b, v = match.groups()
        message, a, b, v = int(message), Fraction(a), Fraction(b), Fraction(v)
        if a + b + v != 1 or max(a, b, v) > 1:
            raise ValueError("procedure probabilities must sum to one")
        action = ("attack", 0, message)
        self.plan.validate(action, self.remaining)
        expected = self.plan.action_value(self.belief, self.remaining, action)
        immediate = self.plan.best(self.plan.targets(self.belief))[1]
        future = self.plan.value(self.belief, self.remaining)
        target_a, target_b, target_v = self.belief.responses(self.target, message)
        response = self.actual.choose(self.target, message)
        frozen_response = self.initial_actual.choose(self.target, message)
        loss = self.actual.loss(response, self.target_world)
        frozen_loss = self.initial_actual.loss(frozen_response, self.target_world)
        brier = a * a + b * b + v * v - 2 * (a, b, v)[response] + 1
        excess = (a - target_a) ** 2 + (b - target_b) ** 2 + (v - target_v) ** 2
        self.result = (
            ("target_defender_loss", str(loss)),
            ("target_expected_loss", str(expected)),
            ("interaction_cost", str(self.spent)),
            ("net_attack_payoff", str(loss - self.spent)),
            ("interaction_regrets", tuple(map(str, self.regrets))),
            ("terminal_control_regret", str(immediate - expected)),
            ("missed_intervention_value", str(future - immediate)),
            ("procedure_brier", str(brier)),
            ("procedure_forecast_excess", str(excess)),
            ("target_procedure", str(response)),
            ("frozen_state_procedure", str(frozen_response)),
            ("fixed_message_learning_effect", str(loss - frozen_loss)),
            ("remaining_profile_candidates", str(self.belief.size())),
            ("realized_depth", str(self.actual.depth)),
            ("probes", str(self.probes)),
            ("teaches", str(self.teaches)),
        )
        self.actions += (raw,)
        self.trace += ((raw, response),)
        self.stage = "done"
        return self.result

    def reference_action(self):
        action, value = self.plan.choose(self.belief, self.remaining)
        mode, case, message = action
        if mode == "attack":
            probabilities = self.belief.responses(self.target, message)
            return f"attack {message} " + " ".join(map(str, probabilities))
        return f"{mode} {case} {message}"
