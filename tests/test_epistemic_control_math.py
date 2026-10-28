"""Authored exact fixtures; no test execution occurred during this work.

The rational answers below were derived by hand before either implementation
was run. Production/reference agreement supplements, rather than replaces, them.
"""

from fractions import Fraction
from unittest import TestCase

from arena.epistemic_control.semantics import Semantics
from arena.epistemic_control.reference_semantics import ReferenceSemantics


class RecursiveCommunicationMath(TestCase):
    def test_literal_truth_conditioning(self):
        game = Semantics("5/7", (3, 1), 1, "0")
        self.assertEqual(game.listener(0, "1", 0), Fraction(5, 7))
        self.assertEqual(game.listener(0, "1", 1), Fraction(1))

    def test_recursive_selection_has_independent_exact_fractions(self):
        game = Semantics("5/7", (3, 1), 1, "0")
        self.assertEqual(game.source(1, "1", "cooperative", 0), (Fraction(5, 12), Fraction(7, 12)))
        self.assertEqual(game.listener(1, "1", 0), Fraction(25, 49))
        self.assertEqual(game.listener(2, "1", 0), Fraction(125, 273))
        self.assertEqual(game.listener(3, "1", 0), Fraction(625, 1421))

    def test_depth_changes_map_decision_and_is_not_parity(self):
        game = Semantics("5/7", (3, 1), 1, "0")
        self.assertGreater(game.listener(0, "1", 0), Fraction(1, 2))
        self.assertGreater(game.listener(1, "1", 0), Fraction(1, 2))
        self.assertLess(game.listener(2, "1", 0), Fraction(1, 2))
        self.assertLess(game.listener(3, "1", 0), Fraction(1, 2))
        different_prior = Semantics("3/4", (3, 1), 1, "0")
        self.assertEqual(different_prior.listener(3, "1", 0), Fraction(81, 160))
        self.assertGreater(different_prior.listener(3, "1", 0), Fraction(1, 2))

    def test_positive_floor_preserves_depth_sensitive_case(self):
        game = Semantics("5/7", (3, 1), 1, "1/4")
        self.assertEqual(game.listener(1, "1", 0), Fraction(135, 259))
        self.assertEqual(game.listener(2, "1", 0), Fraction(3995, 8183))

    def test_topology_changes_selection_law_not_just_word_order(self):
        duplicated = Semantics("5/7", (3, 1, 1), 1, "0")
        self.assertEqual(duplicated.listener(1, "1", 0), Fraction(25, 63))
        self.assertNotEqual(duplicated.listener(1, "1", 0), Fraction(25, 49))

    def test_source_objectives_overlap_under_positive_floor(self):
        game = Semantics("2/3", (3, 1), 1, "1/4")
        self.assertEqual(game.source(1, "1/2", "cooperative", 0), (Fraction(11, 26), Fraction(15, 26)))
        self.assertEqual(game.source(1, "1/2", "adversarial", 0), (Fraction(7, 10), Fraction(3, 10)))
        self.assertEqual(game.source(1, "1/2", "cooperative", 1), (Fraction(1), Fraction(0)))
        self.assertEqual(game.source(1, "1/2", "adversarial", 1), (Fraction(1), Fraction(0)))

    def test_uniform_truthful_fallback_for_zero_preference(self):
        game = Semantics("2/3", (1, 2), 1, "0")
        self.assertEqual(game.source(1, "1/2", "adversarial", 0), (Fraction(1), Fraction(0)))
        self.assertEqual(game.source(1, "1/2", "adversarial", 1), (Fraction(0), Fraction(1)))

    def test_reference_expansion_reproduces_hand_fixture(self):
        reference = ReferenceSemantics("5/7", (3, 1), 1, "0")
        self.assertEqual(reference.listener(1, "1", 0), Fraction(25, 49))
        self.assertEqual(reference.listener(2, "1", 0), Fraction(125, 273))
        self.assertEqual(reference.listener(3, "1", 0), Fraction(625, 1421))

    def test_reference_agreement_with_distinct_menu_power_and_prior(self):
        production = Semantics("3/5", (3, 1, 2), 2, "1/4")
        reference = ReferenceSemantics("3/5", (3, 1, 2), 2, "1/4")
        self.assertEqual(production.listener(3, "2/3", 0), reference.listener(3, "2/3", 0))
        self.assertEqual(production.source(3, "2/3", "adversarial", 0), reference.source(3, "2/3", "adversarial", 0))
        self.assertEqual(sum(production.source(3, "2/3", "cooperative", 1)), Fraction(1))

    def test_true_message_can_be_impossible_under_a_pragmatic_model(self):
        reference = ReferenceSemantics("5/7", (3, 1), 1, "0")
        with self.assertRaises(ValueError):
            reference.listener(1, "0", 1)


class TeachingMath(TestCase):
    def test_audited_truthful_teaching_updates_objective_belief(self):
        reference = ReferenceSemantics("2/3", (3, 1), 1, "1/4")
        first = reference.credibility_after(1, "1/2", 1, 0)
        second = reference.credibility_after(1, first, 1, 0)
        self.assertEqual(first, Fraction(25, 38))
        self.assertEqual(second, Fraction(625, 794))

    def test_two_teaches_change_final_decision_one_does_not(self):
        game = Semantics("2/3", (3, 1), 1, "1/4")
        initial = game.listener(1, "1/2", 0)
        one_teach = game.listener(1, "25/38", 0)
        two_teaches = game.listener(1, "625/794", 0)
        self.assertEqual(initial, Fraction(73, 138))
        self.assertEqual(one_teach, Fraction(1279, 2514))
        self.assertEqual(two_teaches, Fraction(24877, 50682))
        self.assertGreater(initial, Fraction(1, 2))
        self.assertGreater(one_teach, Fraction(1, 2))
        self.assertLess(two_teaches, Fraction(1, 2))

    def test_ambiguous_teaching_reduces_credibility(self):
        reference = ReferenceSemantics("2/3", (3, 1), 1, "1/4")
        self.assertEqual(reference.credibility_after(1, "1/2", 0, 0), Fraction(55, 146))
        self.assertLess(reference.credibility_after(1, "1/2", 0, 0), Fraction(1, 2))
