"""Authored regression specifications; no execution has been performed here."""

from fractions import Fraction
from io import StringIO
from unittest import TestCase

from arena.recursive_programs.game import ProgramDiscovery
from arena.recursive_programs.reference import Choices, PublicSolver, ShallowSolver
from arena.recursive_programs.semantics import Node, Posterior, Rule, RulePool, TreeFactory
from arena.recursive_programs.session import Replay, Session, Trial


class HandDerivedComposition(TestCase):
    def test_nested_reduction_and_path_expansion_agree_on_manual_value(self):
        # A(1,2)=5; B(3,4)=4; A(5,4)=1 modulo seven.
        left = Node("A", Node("leaf", value=1), Node("leaf", value=2))
        right = Node("B", Node("leaf", value=3), Node("leaf", value=4))
        tree = Node("A", left, right)
        self.assertEqual(tree.reduce((Rule(2, 1, 1), Rule(1, 2, 0), Rule(1, 1, 0)), 7), 1)
        self.assertEqual(PublicSolver().evaluate(tree.render(), ((2, 1, 1), (1, 2, 0), (1, 1, 0)), 7), 1)

    def test_same_leaves_and_operator_counts_different_composition(self):
        first = "A(A(1,2),B(3,4))"
        second = "A(B(3,4),A(1,2))"
        rules = ((2, 1, 1), (1, 2, 0), (1, 1, 0))
        self.assertEqual(PublicSolver().evaluate(first, rules, 7), 1)
        self.assertEqual(PublicSolver().evaluate(second, rules, 7), 0)

    def test_shallow_rule_knowledge_does_not_solve_nested_composition(self):
        rules = ((2, 1, 1), (1, 2, 0), (1, 1, 0))
        self.assertEqual(ShallowSolver().evaluate("A(A(1,2),B(3,4))", rules, 7), 6)
        self.assertEqual(PublicSolver().evaluate("A(A(1,2),B(3,4))", rules, 7), 1)

    def test_associative_flattening_is_a_valid_control(self):
        rules = ((1, 1, 0), (1, 1, 0), (1, 1, 0))
        self.assertEqual(PublicSolver().evaluate("A(A(1,2),A(3,4))", rules, 7), 3)
        self.assertEqual(PublicSolver().evaluate("A(1,A(2,A(3,4)))", rules, 7), 3)

    def test_repeated_subtree_has_distinct_expanded_and_unique_size(self):
        leaf = Node("leaf", value=1)
        first = Node("A", leaf, leaf)
        second = Node("A", first, first)
        third = Node("A", second, second)
        # x -> 3x+1 modulo seven: 1 -> 4 -> 6 -> 5.
        self.assertEqual(third.reduce((Rule(2, 1, 1), Rule(1, 1, 0), Rule(1, 1, 0)), 7), 5)
        self.assertEqual(third.depth, 3)
        self.assertEqual(third.nodes, 15)
        self.assertEqual(third.distinct_subtrees(), 4)

    def test_reference_rejects_trailing_or_incomplete_expressions(self):
        with self.assertRaises(ValueError):
            PublicSolver().evaluate("A(1,2)junk", ((1, 1, 0), (1, 1, 0), (1, 1, 0)), 7)
        with self.assertRaises(ValueError):
            PublicSolver().evaluate("A(1,2", ((1, 1, 0), (1, 1, 0), (1, 1, 0)), 7)


class RuleIdentification(TestCase):
    def test_three_basis_observations_identify_local_rule(self):
        observations = (("A", 0, 0, 1), ("A", 1, 0, 3), ("A", 0, 1, 2))
        pool = RulePool("A", 3, 7, observations)
        self.assertEqual(pool.count, 1)
        self.assertEqual(pool.entries[0].coefficients(), (2, 1, 1))

    def test_candidate_repertoire_scales_cubically_per_operator(self):
        self.assertEqual(RulePool("A", 2, 7, ()).count, 8)
        self.assertEqual(RulePool("A", 3, 7, ()).count, 27)

    def test_conflicting_observations_are_rejected(self):
        with self.assertRaises(ValueError):
            RulePool("A", 2, 7, (("A", 0, 0, 0), ("A", 0, 0, 1)))

    def test_local_offset_can_be_known_while_recursive_result_is_ambiguous(self):
        inner = Node("A", Node("leaf", value=0), Node("leaf", value=0))
        tree = Node("A", inner, inner)
        posterior = Posterior(1, 2, 7, (("A", 0, 0, 1),), (tree,) * 6)
        # Remaining rules give a+b+1: 3,4,4,5. The modal answer still has error 1/2.
        self.assertEqual(posterior.total, 4)
        self.assertEqual(posterior.histograms[0].counts, (0, 0, 0, 1, 2, 1, 0))
        self.assertEqual(posterior.histograms[0].risk(4), Fraction(1, 2))

    def test_independent_candidate_filter_uses_only_public_observations(self):
        public = "Observation A 0 0 = 1\nObservation A 1 0 = 3\nObservation A 0 1 = 2\n"
        self.assertEqual(Choices("A", 3, 7, public).entries, ((2, 1, 1),))

    def test_observation_only_solver_finds_manual_recursive_answers(self):
        public = (
            "Modulus=7; Operators=2; Width=2; Remaining=0.\n"
            "Target 0: A(A(1,2),B(3,4))\n"
            "Target 1: A(B(3,4),A(1,2))\n"
            "Target 2: B(A(1,2),A(3,4))\n"
            "Observation A 0 0 = 1\nObservation A 1 0 = 3\nObservation A 0 1 = 2\n"
            "Observation B 0 0 = 0\nObservation B 1 0 = 1\nObservation B 0 1 = 2\n"
        )
        self.assertEqual(PublicSolver().act(public), "answer 1 0 6 model 2 1 1 1 2 0")


class StructuralAxes(TestCase):
    def test_chain_and_balanced_branching_scale_differently(self):
        chain = TreeFactory("axis", 2, 7).make(5, "chain", "distinct")
        balanced = TreeFactory("axis", 2, 7).make(5, "balanced", "distinct")
        self.assertEqual((chain.depth, chain.nodes), (5, 11))
        self.assertEqual((balanced.depth, balanced.nodes), (5, 63))

    def test_repetition_exposes_a_compression_control(self):
        tree = TreeFactory("repeat", 3, 11).make(5, "balanced", "repeated")
        self.assertEqual(tree.nodes, 63)
        self.assertEqual(tree.distinct_subtrees(), 6)

    def test_transfer_programs_are_one_level_deeper(self):
        game = ProgramDiscovery(9, 21, 4)
        self.assertEqual((game.targets[0].depth, game.targets[1].depth, game.targets[2].depth), (4, 4, 4))
        self.assertEqual((game.transfer[0].depth, game.transfer[1].depth, game.transfer[2].depth), (5, 5, 5))

    def test_every_active_operator_appears_in_a_public_target(self):
        game = ProgramDiscovery(9, 21, 2, 3)
        self.assertEqual((game.targets[0].label, game.targets[1].label, game.targets[2].label), ("A", "B", "C"))

    def test_no_evidence_public_view_is_independent_of_private_rule_seed(self):
        first, second = ProgramDiscovery(9, 21), ProgramDiscovery(9, 99)
        self.assertEqual(first.view(), second.view())
        self.assertEqual(first.semantic_id, second.semantic_id)

    def test_free_demonstrations_do_not_consume_paid_queries(self):
        game = ProgramDiscovery(9, 21, demonstrations=2)
        self.assertEqual(game.has_probe("A", 0, 0, game.observations), 1)
        self.assertEqual(game.has_probe("A", 1, 0, game.observations), 1)
        self.assertEqual(game.remaining, 6)
        self.assertEqual(game.spent, 0)

    def test_invalid_or_inapplicable_axes_are_rejected(self):
        with self.assertRaises(ValueError):
            ProgramDiscovery(depth=6)
        with self.assertRaises(ValueError):
            ProgramDiscovery(operators=4)
        with self.assertRaises(ValueError):
            ProgramDiscovery(shape="chain", sharing="repeated")


class ProtocolAndEndToEndSpecifications(TestCase):
    def test_nested_probe_and_invalid_residue_cannot_reveal_target(self):
        game = ProgramDiscovery()
        with self.assertRaises(ValueError):
            game.step("probe A A(0,1) 0")
        with self.assertRaises(ValueError):
            game.step("probe A 7 0")
        self.assertEqual(game.actions, ())
        self.assertEqual(game.observations, ())

    def test_repeated_or_exhausted_probe_is_rejected(self):
        game = ProgramDiscovery(budget=1)
        game.step("probe A 0 0")
        with self.assertRaises(ValueError):
            game.step("probe A 0 0")
        with self.assertRaises(ValueError):
            game.step("probe A 1 0")

    def test_invalid_model_does_not_close_episode(self):
        game = ProgramDiscovery(operators=1)
        with self.assertRaises(ValueError):
            game.step("answer 0 0 0 model 3 1 0")
        with self.assertRaises(ValueError):
            game.step("answer 0 0 0 model 1 1 0 extra")
        self.assertEqual(game.stage, "open")

    def test_complete_identification_supports_direct_and_unseen_compositions(self):
        trial = Trial("recursive 13 29 3 2 2 6 balanced distinct 0 7", PublicSolver())
        trial.run()
        self.assertEqual(trial.status, "scored")
        self.assertEqual(trial.controller.game.result.count(("prediction_loss", "0")), 1)
        self.assertEqual(trial.controller.game.result.count(("prediction_regret", "0")), 1)
        self.assertEqual(trial.controller.game.result.count(("certificate_transfer_loss", "0")), 1)
        self.assertEqual(trial.controller.game.result.count(("identified_from_evidence", "1")), 1)

    def test_larger_repertoire_and_three_operators_have_an_identifying_basis(self):
        trial = Trial("recursive 17 91 4 3 3 9 balanced distinct 0 11", PublicSolver())
        trial.run()
        self.assertEqual(trial.status, "scored")
        self.assertEqual(trial.controller.game.result.count(("candidate_grammars", "1")), 1)
        self.assertEqual(trial.controller.game.result.count(("queries", "9")), 1)
        self.assertEqual(trial.controller.game.result.count(("composition_errors_given_certificate", "0")), 1)

    def test_free_basis_examples_reduce_queries_needed_for_chain_transfer(self):
        trial = Trial("recursive 5 8 5 1 3 1 chain distinct 2 7", PublicSolver())
        trial.run()
        self.assertEqual(trial.status, "scored")
        self.assertEqual(trial.controller.game.result.count(("queries", "1")), 1)
        self.assertEqual(trial.controller.game.result.count(("certificate_transfer_loss", "0")), 1)

    def test_short_budget_reports_ambiguity_and_separates_bayes_regret(self):
        trial = Trial("recursive 3 11 2 1 2 0 balanced repeated 0 7", PublicSolver())
        trial.run()
        self.assertEqual(trial.controller.game.result.count(("candidate_grammars", "8")), 1)
        self.assertEqual(trial.controller.game.result.count(("identified_from_evidence", "0")), 1)
        self.assertEqual(trial.controller.game.result.count(("prediction_regret", "0")), 1)

    def test_replay_reconstructs_and_rejects_incomplete_or_appended_actions(self):
        configuration = "recursive 3 11 2 1 2 3 balanced repeated 0 7"
        trial = Trial(configuration, PublicSolver())
        trial.run()
        actions = trial.controller.game.actions
        self.assertEqual(Replay(configuration).consume(actions), (trial.controller.game.observations, trial.controller.game.result))
        with self.assertRaises(ValueError):
            Replay(configuration).consume(actions[:-1])
        with self.assertRaises(ValueError):
            Replay(configuration).consume(actions + ("probe A 2 2",))

    def test_closed_episode_cannot_accept_more_queries(self):
        game = ProgramDiscovery(0, 0, 2, 1, 2, 0)
        game.step("answer 0 0 0 model 1 1 0")
        with self.assertRaises(ValueError):
            game.step("probe A 0 0")

    def test_transport_eof_is_unscored(self):
        sink = StringIO()
        Session(StringIO("recursive 3 11 2 1 2 0 balanced repeated 0 7\n"), sink).run()
        self.assertEqual(sink.getvalue().count("incomplete_episode: unscored"), 1)

    def test_controller_rule_seed_is_not_echoed(self):
        sink = StringIO()
        source = StringIO("recursive 3 982734 2 1 2 0 balanced repeated 0 7\nanswer 0 0 0 model 1 1 0\n")
        Session(source, sink).run()
        self.assertEqual(sink.getvalue().count("982734"), 0)
        self.assertEqual(sink.getvalue().count('"recursive_result"'), 1)
