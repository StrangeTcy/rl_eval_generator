"""OP-scoped runtime checks for the existing bounded affine-rule environment."""

from io import StringIO
from unittest import TestCase

from arena.recursive_programs.game import ProgramDiscovery
from arena.recursive_programs.reference import PublicSolver
from arena.recursive_programs.semantics import RulePool
from arena.recursive_programs.session import Replay, Session, Trial


class RecursiveProgramOpportunityValidation(TestCase):
    def test_OP019_OP070_text_session_identifies_rules_and_scores_compositions(self):
        # Two free basis examples leave exactly b unknown per operator.
        # One remaining basis probe per operator identifies the affine rules;
        # the independent path-expansion solver then predicts the compositions.
        configuration = "recursive 41 17 4 2 3 2 balanced distinct 2 11"
        reference = Trial(configuration, PublicSolver())
        reference.run()
        self.assertEqual(reference.status, "scored")
        self.assertEqual(reference.controller.game.actions[:2], ("probe A 0 1", "probe B 0 1"))
        sink = StringIO()
        session = Session(StringIO(configuration + "\n" + "\n".join(reference.controller.game.actions) + "\n"), sink)
        session.run()
        self.assertEqual(session.game.stage, "done")
        self.assertEqual((session.game.spent, session.game.remaining, session.remaining_lines), (2, 0, 21))
        self.assertEqual(session.game.result.count(("prediction_loss", "0")), 1)
        self.assertEqual(session.game.result.count(("prediction_regret", "0")), 1)
        self.assertEqual(session.game.result.count(("candidate_grammars", "1")), 1)
        self.assertEqual(session.game.result.count(("certificate_transfer_loss", "0")), 1)
        self.assertEqual(sink.getvalue().count('"recursive_result"'), 1)
        self.assertEqual(sink.getvalue().count("configuration_error"), 0)
        self.assertEqual(sink.getvalue().count("invalid_action"), 0)

    def test_OP019_early_stopping_preserves_unspent_budget_and_ambiguity(self):
        game = ProgramDiscovery(41, 17, 2, 1, 2, 3)
        game.step("answer 0 0 0 model 1 1 0")
        # A supplied width-two family has 2 * 2 * 2 possibilities before evidence.
        self.assertEqual(game.stage, "done")
        self.assertEqual((game.remaining, game.spent, game.observations), (3, 0, ()))
        self.assertEqual(game.result.count(("candidate_grammars", "8")), 1)
        self.assertEqual(game.result.count(("identified_from_evidence", "0")), 1)
        with self.assertRaisesRegex(ValueError, "episode closed"):
            game.step("probe A 0 0")
        self.assertEqual((game.remaining, game.spent, game.observations), (3, 0, ()))

    def test_OP019_malformed_and_repeated_queries_do_not_consume_evidence_budget(self):
        game = ProgramDiscovery(41, 17, 2, 1, 2, 2)
        initial_view = game.view()
        with self.assertRaises(ValueError):
            game.step("probe A A(0,1) 0")
        with self.assertRaises(ValueError):
            game.step("probe B 0 0")
        with self.assertRaises(ValueError):
            game.step("probe A 7 0")
        self.assertEqual((game.view(), game.remaining, game.spent, game.actions), (initial_view, 2, 0, ()))
        game.step("probe A 0 0")
        observed_view, observations = game.view(), game.observations
        # Alternate numeral spelling cannot buy the same evidence twice.
        with self.assertRaisesRegex(ValueError, "repeated input"):
            game.step("probe A 00 0")
        self.assertEqual((game.view(), game.observations, game.remaining, game.spent), (observed_view, observations, 1, 1))
        game.step("probe A 1 0")
        exhausted_view = game.view()
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            game.step("probe A 0 1")
        self.assertEqual((game.view(), game.remaining, game.spent), (exhausted_view, 0, 2))

    def test_OP070_correct_targets_do_not_prove_consistent_rule_certificate(self):
        game = ProgramDiscovery(41, 17, 3, 1, 2, 1, demonstrations=2)
        game.step("probe A 0 1")
        answer, first, second, third, model, a, b, c = tuple(PublicSolver().act(game.view()).split())
        alternate_a = 2 if a == "1" else 1
        game.step(f"{answer} {first} {second} {third} {model} {alternate_a} {b} {c}")
        # The basis uniquely determines a. Replacing it necessarily contradicts
        # observed evidence, even though independently computed targets are right.
        self.assertEqual(game.result.count(("prediction_loss", "0")), 1)
        self.assertEqual(game.result.count(("prediction_regret", "0")), 1)
        self.assertEqual(game.result.count(("candidate_grammars", "1")), 1)
        self.assertEqual(game.result.count(("certificate_consistent", "0")), 1)

    def test_OP070_nonlinear_observations_are_outside_the_supplied_rule_family(self):
        # x squared at 0, 1, 2 is 0, 1, 4 modulo seven. An affine rule that
        # matches the first two must instead return 2 at the third input.
        with self.assertRaisesRegex(ValueError, "contradict the declared rule family"):
            RulePool("A", 3, 7, (("A", 0, 0, 0), ("A", 1, 0, 1), ("A", 2, 0, 4)))

    def test_OP045_OP053_seeded_truth_actions_and_scores_reproduce_through_replay(self):
        configuration = "recursive 41 17 3 2 2 6 balanced distinct 0 7"
        first, second = Trial(configuration, PublicSolver()), Trial(configuration, PublicSolver())
        first_record, second_record = first.run(), second.run()
        self.assertEqual(first_record, second_record)
        self.assertEqual(first.controller.game.semantic_id, second.controller.game.semantic_id)
        self.assertEqual(first.controller.game.rules[0].coefficients(), second.controller.game.rules[0].coefficients())
        self.assertEqual(first.controller.game.rules[1].coefficients(), second.controller.game.rules[1].coefficients())
        self.assertEqual(Replay(configuration).consume(first.controller.game.actions), (first.controller.game.observations, first.controller.game.result))
        with self.assertRaises(ValueError):
            Replay(configuration).consume(first.controller.game.actions[:-1])
        with self.assertRaises(ValueError):
            Replay(configuration).consume(first.controller.game.actions + ("answer 0 0 0 model 1 1 0 1 1 0",))

    def test_OP053_private_rule_seed_is_not_public_identity_or_truth_evidence(self):
        first, second = ProgramDiscovery(41, 17), ProgramDiscovery(41, 18)
        self.assertEqual(first.view(), second.view())
        self.assertEqual(first.semantic_id, second.semantic_id)
        self.assertEqual((first.observations, second.observations), ((), ()))
        changed_targets = ProgramDiscovery(42, 17)
        self.assertNotEqual(first.semantic_id, changed_targets.semantic_id)
        self.assertNotEqual(first.view(), changed_targets.view())

    def test_OP019_OP045_invalid_transport_actions_reach_unscored_response_limit(self):
        configuration = "recursive 41 17 2 1 2 2 balanced distinct 0 7"
        sink = StringIO()
        session = Session(StringIO(configuration + "\n" + "probe A A(0,1) 0\n" * 24), sink)
        session.run()
        self.assertEqual(session.remaining_lines, 0)
        self.assertEqual((session.game.stage, session.game.remaining, session.game.spent), ("open", 2, 0))
        self.assertEqual((session.game.actions, session.game.observations, session.game.result), ((), (), None))
        self.assertEqual(sink.getvalue().count("invalid_action:"), 24)
        self.assertEqual(sink.getvalue().count("response_limit: unscored"), 1)
        self.assertEqual(sink.getvalue().count('"recursive_result"'), 0)
