"""Runtime checks for the existing bounded control mechanism.

These tests exercise explicit speaker/listener models and a supplied Bayesian
credibility update. They do not establish arbitrary procedure modification,
objective-disclosure ablations, text transport, replay, or OP037 profile ablations.
Expected fractions and action sequences are independently specified fixtures.
"""

from fractions import Fraction
from unittest import TestCase

from arena.epistemic_control.game import ControlGame
from arena.epistemic_control.planning import Belief, ControlPlan
from arena.epistemic_control.semantics import Defender, Semantics


class EpistemicControlOPValidation(TestCase):
    def test_OP008_depth_changes_defender_decision_at_fixed_truth(self):
        context = Semantics("5/7", (3, 1), 1, "1/4")
        shallow = Defender(1, "1/2", "1")
        deep = Defender(2, "1/2", "1")
        self.assertEqual(context.listener(1, "1", 0), Fraction(135, 259))
        self.assertEqual(context.listener(2, "1", 0), Fraction(3995, 8183))
        self.assertEqual(shallow.choose(context, 0), 0)
        self.assertEqual(deep.choose(context, 0), 1)
        self.assertEqual(shallow.loss(0, 0), Fraction(0))
        self.assertEqual(deep.loss(1, 0), Fraction(1))

    def test_OP011_speaker_selection_changes_interpretation_of_same_true_message(self):
        ordinary = Semantics("5/7", (3, 1), 1, "0")
        duplicated = Semantics("5/7", (3, 1, 1), 1, "0")
        defender = Defender(1, "1/2", "1")
        self.assertEqual(ordinary.listener(0, "1", 0), Fraction(5, 7))
        self.assertEqual(duplicated.listener(0, "1", 0), Fraction(5, 7))
        self.assertEqual(ordinary.listener(1, "1", 0), Fraction(25, 49))
        self.assertEqual(duplicated.listener(1, "1", 0), Fraction(25, 63))
        self.assertEqual(defender.choose(ordinary, 0), 0)
        self.assertEqual(defender.choose(duplicated, 0), 1)

    def test_OP010_OP033_complete_truthful_teaching_changes_target_decision(self):
        game = ControlGame(depth=1, breadth=1, horizon=2, selected_profile=1)
        self.assertEqual(game.actual.choose(game.target, 0), 0)
        self.assertEqual(game.step("teach 0 1"), "defender procedure 0")
        self.assertEqual(game.actual.credibility, Fraction(25, 38))
        self.assertEqual(game.actual.choose(game.target, 0), 0)
        self.assertEqual(game.step("teach 0 1"), "defender procedure 0")
        self.assertEqual(game.actual.credibility, Fraction(625, 794))
        self.assertEqual(game.actual.choose(game.target, 0), 1)
        self.assertEqual(game.remaining, 0)
        result = game.step("attack 0 1/2 1/2 0")
        self.assertEqual(game.stage, "done")
        self.assertEqual(game.actions, ("teach 0 1", "teach 0 1", "attack 0 1/2 1/2 0"))
        self.assertEqual(game.trace, (("teach 0 1", 0), ("teach 0 1", 0), ("attack 0 1/2 1/2 0", 1)))
        self.assertEqual(result.count(("target_defender_loss", "1")), 1)
        self.assertEqual(result.count(("target_expected_loss", "1/2")), 1)
        self.assertEqual(result.count(("interaction_cost", "1/25")), 1)
        self.assertEqual(result.count(("net_attack_payoff", "24/25")), 1)
        self.assertEqual(result.count(("procedure_brier", "1/2")), 1)
        self.assertEqual(result.count(("procedure_forecast_excess", "0")), 1)
        self.assertEqual(result.count(("fixed_message_learning_effect", "1")), 1)
        self.assertEqual(result.count(("remaining_profile_candidates", "2")), 1)
        self.assertEqual(result.count(("teaches", "2")), 1)

    def test_OP033_frozen_feedback_does_not_change_target_decision(self):
        game = ControlGame(depth=1, breadth=1, horizon=2, selected_profile=1, learning="frozen")
        original = game.actual
        self.assertEqual(game.step("teach 0 1"), "defender procedure 0")
        self.assertEqual(game.step("teach 0 1"), "defender procedure 0")
        self.assertIs(game.actual, original)
        self.assertEqual(game.actual.credibility, Fraction(1, 2))
        result = game.step("attack 0 1 0 0")
        self.assertEqual(result.count(("target_defender_loss", "0")), 1)
        self.assertEqual(result.count(("fixed_message_learning_effect", "0")), 1)
        self.assertEqual(result.count(("net_attack_payoff", "-1/25")), 1)
        self.assertEqual(result.count(("procedure_forecast_excess", "0")), 1)

    def test_OP008_OP010_probe_filters_hidden_profiles_without_teaching(self):
        game = ControlGame(depth=1, breadth=2, horizon=1, selected_profile=2)
        original = game.actual
        self.assertEqual(game.belief.size(), 4)
        self.assertEqual(game.step("probe 0 0"), "defender procedure 0")
        self.assertIs(game.actual, original)
        self.assertEqual(game.actual.credibility, Fraction(1, 2))
        self.assertEqual(game.belief.signature(), (
            (0, 0, Fraction(1, 2), Fraction(1, 2), Fraction(1, 2)),
            (2, 1, Fraction(1, 2), Fraction(1, 2), Fraction(1, 2)),
        ))
        self.assertEqual(game.probes, 1)
        self.assertEqual(game.teaches, 0)
        result = game.step("attack 0 1 0 0")
        self.assertEqual(result.count(("target_defender_loss", "0")), 1)
        self.assertEqual(result.count(("remaining_profile_candidates", "2")), 1)

    def test_OP033_planner_values_two_step_teaching_beyond_one_step(self):
        context = Semantics("2/3", (3, 1), 1, "1/4")
        belief = Belief(((0, Defender(1, "1/2", "1/2"), Fraction(1)),))
        plan = ControlPlan((context,), (0,), context, 0, "1/50", "adaptive")
        self.assertEqual(plan.choose(belief, 0), (("attack", 0, 0), Fraction(0)))
        self.assertEqual(plan.choose(belief, 1), (("attack", 0, 0), Fraction(0)))
        self.assertEqual(plan.choose(belief, 2), (("teach", 0, 1), Fraction(24, 25)))
        self.assertEqual(plan.action_value(belief, 2, ("probe", 0, 1)), Fraction(-1, 50))
        frozen = ControlPlan((context,), (0,), context, 0, "1/50", "frozen")
        self.assertEqual(frozen.choose(belief, 2), (("attack", 0, 0), Fraction(0)))

    def test_OP074_budget_stop_and_post_terminal_rejection(self):
        game = ControlGame(depth=0, breadth=1, horizon=0)
        with self.assertRaises(ValueError):
            game.step("probe 0 0")
        with self.assertRaises(ValueError):
            game.step("teach 0 1")
        self.assertEqual(game.remaining, 0)
        self.assertEqual(game.actions, ())
        self.assertEqual(game.reference_action(), "attack 0 1 0 0")
        result = game.step("attack 0 1 0 0")
        self.assertEqual(result.count(("target_defender_loss", "0")), 1)
        self.assertEqual(game.stage, "done")
        with self.assertRaises(ValueError):
            game.step("attack 0 1 0 0")

    def test_OP074_invalid_actions_preserve_open_state(self):
        game = ControlGame(depth=0, breadth=1, horizon=1, menu="exclusive")
        original = game.actual
        signature = game.belief.signature()
        with self.assertRaises(ValueError):
            game.step("teach 0 1")
        with self.assertRaises(ValueError):
            game.step("attack 1 1 0 0")
        with self.assertRaises(ValueError):
            game.step("probe 0 3")
        with self.assertRaises(ValueError):
            game.step("attack 0 1/0 0 0")
        with self.assertRaises(ValueError):
            game.step("attack 0 1 1 0")
        with self.assertRaises(ValueError):
            game.step("attack 0 NaN 0 0")
        with self.assertRaises(ValueError):
            game.step("attack 0 1 0 0 trailing")
        self.assertIs(game.actual, original)
        self.assertEqual(game.belief.signature(), signature)
        self.assertEqual(game.stage, "open")
        self.assertEqual(game.actions, ())
        self.assertEqual(game.trace, ())
        self.assertEqual(game.remaining, 1)
        self.assertEqual(game.spent, Fraction(0))

    def test_OP074_seed_identity_and_hidden_profile_information_boundary(self):
        original = ControlGame(semantic_seed=0, world_seed=29, depth=1, breadth=2, horizon=0)
        repeated = ControlGame(semantic_seed=0, world_seed=29, depth=1, breadth=2, horizon=0)
        alternative = ControlGame(semantic_seed=0, world_seed=31, depth=1, breadth=2, horizon=0)
        rotated = ControlGame(semantic_seed=1, world_seed=29, depth=1, breadth=2, horizon=0)
        self.assertEqual(original.profile_id, repeated.profile_id)
        self.assertEqual(original.actual.row(), repeated.actual.row())
        self.assertEqual(original.semantic_id, repeated.semantic_id)
        self.assertEqual(original.view(), repeated.view())
        self.assertEqual(original.semantic_id, alternative.semantic_id)
        self.assertEqual(original.view(), alternative.view())
        self.assertNotEqual(original.semantic_id, rotated.semantic_id)
        self.assertEqual(original.target.masks, (3, 1))
        self.assertEqual(rotated.target.masks, (1, 3))
        hidden_a = ControlGame(depth=1, breadth=1, horizon=0, selected_profile=0)
        hidden_b = ControlGame(depth=1, breadth=1, horizon=0, selected_profile=1)
        self.assertEqual(hidden_a.semantic_id, hidden_b.semantic_id)
        self.assertEqual(hidden_a.view(), hidden_b.view())

    def test_OP074_wrong_forecast_is_penalized_without_changing_attack_payoff(self):
        calibrated = ControlGame(depth=0, breadth=1, horizon=0)
        wrong = ControlGame(depth=0, breadth=1, horizon=0)
        good_result = calibrated.step("attack 0 1 0 0")
        bad_result = wrong.step("attack 0 0 1 0")
        self.assertEqual(good_result.count(("procedure_forecast_excess", "0")), 1)
        self.assertEqual(bad_result.count(("procedure_forecast_excess", "2")), 1)
        self.assertEqual(good_result.count(("procedure_brier", "0")), 1)
        self.assertEqual(bad_result.count(("procedure_brier", "2")), 1)
        self.assertEqual(good_result.count(("net_attack_payoff", "0")), 1)
        self.assertEqual(bad_result.count(("net_attack_payoff", "0")), 1)
