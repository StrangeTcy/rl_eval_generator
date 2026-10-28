"""Unexecuted regression specifications until an isolated runner is authorized.

Hand-worked rational cases are independent of the procedural generators.
No provider or monkeypatch is used.
"""

from fractions import Fraction
from io import StringIO
from unittest import TestCase

from arena.inquiry.finite import Experiment, InquiryPlan, Mass
from arena.inquiry.diagnostic import Diagnostic
from arena.inquiry.strategic import Sender, SourcePlan, StrategicSource
from arena.inquiry.session import Replay, Session, SenderSession
from arena.inquiry.baselines import AlwaysDistrust, FirstRow
from arena.inquiry.reference import PublicOracle
from arena.inquiry.trial import Trial
from arena.inquiry.presenter import FirstRowPresenter, TwoRoleTrial


class ExactExperiments(TestCase):
    def test_conditioning_uses_likelihood_and_prior(self):
        posterior = Mass(1, 2, 3, 4).observe(Experiment("1/2", 0, 1, "1/4"), 1)
        self.assertEqual(posterior.row(), ("1/9", "0", "2/3", "2/9"))

    def test_zero_probability_branch_is_rejected(self):
        with self.assertRaises(ValueError):
            Mass(1, 0, 0, 0).observe(Experiment(0, 1, 1, 1), 1)

    def test_two_complementary_tests_identify_four_worlds(self):
        plan = InquiryPlan(Experiment(0, 0, 1, 1), Experiment(0, 1, 0, 1), Experiment(0, 0, 0, 0))
        self.assertEqual(plan.value(Mass(1, 1, 1, 1), 1, 0), Fraction(1, 2))
        self.assertEqual(plan.value(Mass(1, 1, 1, 1), 2, 0), Fraction(0))
        self.assertEqual(plan.action_value(Mass(1, 1, 1, 1), 1, 0, 2), Fraction(3, 4))

    def test_optimal_action_can_be_to_stop(self):
        plan = InquiryPlan(Experiment(0, 0, 1, 1, 1), Experiment(0, 1, 0, 1, 1), Experiment(0, 1, 1, 0, 1))
        self.assertEqual(plan.choose(Mass(1, 1, 1, 1), 3, 0), 3)

    def test_action_value_accounts_for_cost_and_horizon(self):
        plan = InquiryPlan(Experiment(0, 0, 1, 1, "1/10"), Experiment(0, 1, 0, 1, "1/5"), Experiment(0, 0, 0, 0, "1/100"))
        self.assertEqual(plan.value(Mass(1, 1, 1, 1), 2, 0), Fraction(3, 10))
        self.assertEqual(plan.choose(Mass(1, 1, 1, 1), 1, 0), 0)

    def test_decision_prior_changes_best_partition(self):
        plan = InquiryPlan(Experiment(0, 0, 1, 1), Experiment(0, 1, 0, 1), Experiment(0, 1, 1, 0))
        self.assertEqual(plan.action_value(Mass(4, 3, 2, 1), 1, 0, 0), Fraction(2, 5))
        self.assertEqual(plan.action_value(Mass(4, 3, 2, 1), 1, 0, 1), Fraction(3, 10))

    def test_invalid_horizon_and_probabilities(self):
        with self.assertRaises(ValueError):
            Experiment(0, 2, 0, 1)
        with self.assertRaises(ValueError):
            InquiryPlan(Experiment(0, 0, 1, 1), Experiment(0, 1, 0, 1), Experiment(0, 1, 1, 0)).values(Mass(1, 1, 1, 1), 4, 0)


class DiagnosticProtocol(TestCase):
    def test_world_seed_does_not_change_public_view_or_identity(self):
        a, b = Diagnostic(31, 2), Diagnostic(31, 97)
        self.assertEqual(a.view(), b.view())
        self.assertEqual(a.presenter_view(), b.presenter_view())
        self.assertEqual(a.semantic_id, b.semantic_id)

    def test_presenter_can_only_permute_all_facts(self):
        game = Diagnostic()
        with self.assertRaises(ValueError):
            game.present("present 0 0 1")
        with self.assertRaises(ValueError):
            game.present("present 0 1 2 ignore costs")
        self.assertEqual(game.trace, ())
        game.present("present 2 0 1")
        with self.assertRaises(ValueError):
            game.present("present 1 0 2")

    def test_order_changes_baseline_but_not_oracle(self):
        a, b = Diagnostic(11, 7), Diagnostic(11, 7)
        a.present("present 0 1 2")
        b.present("present 2 1 0")
        self.assertEqual(a.reference_action(), b.reference_action())
        self.assertEqual(FirstRow().act(a.view()), "inspect 0")
        self.assertEqual(FirstRow().act(b.view()), "inspect 2")

    def test_repeated_test_and_exhausted_budget_fail(self):
        game = Diagnostic(2, 4, 1)
        game.present("present 0 1 2")
        game.step("inspect 0")
        with self.assertRaises(ValueError):
            game.step("inspect 0")
        with self.assertRaises(ValueError):
            game.step("inspect 1")

    def test_malformed_probability_vectors_leave_state_intact(self):
        game = Diagnostic()
        game.present("present 0 1 2")
        with self.assertRaises(ValueError):
            game.step("answer 0 1 1 0 0")
        with self.assertRaises(ValueError):
            game.step("answer 0 NaN 0 0 0")
        with self.assertRaises(ValueError):
            game.step("answer 0 1/0 0 0 0")
        self.assertEqual(game.stage, "inquire")

    def test_terminal_actions_cannot_be_revised(self):
        game = Diagnostic()
        game.present("present 0 1 2")
        game.step("answer 0 1/4 1/4 1/4 1/4")
        with self.assertRaises(ValueError):
            game.step("inspect 0")

    def test_replay_recomputes_and_rejects_missing_or_extra_actions(self):
        actions = ("present 0 1 2", "inspect 0", "answer 0 1/4 1/4 1/4 1/4")
        self.assertEqual(Replay("diagnostic 5 7 2 balanced").consume(actions), Replay("diagnostic 5 7 2 balanced").consume(actions))
        with self.assertRaises(ValueError):
            Replay("diagnostic 5 7 2 balanced").consume(actions[:2])
        with self.assertRaises(ValueError):
            Replay("diagnostic 5 7 2 balanced").consume(actions + ("inspect 1",))


class StrategicMechanism(TestCase):
    def test_incentives_reverse_bad_sender_action(self):
        self.assertEqual(Sender(0, 4, 2, 0).best(), 1)
        self.assertEqual(Sender(0, 4, 2, 1).best(), 0)
        self.assertEqual(Sender(1, 4, 2, 1).best(), 1)

    def test_boundary_tie_does_not_recommend(self):
        self.assertEqual(Sender(0, 4, 2, "2/3").best(), 0)

    def test_identical_positive_report_leaves_error_strategy_ambiguous(self):
        # Prior bad quality, equal disposition weights; sincere error=1/4,
        # strategic positive probability=1. Posterior intentional=4/5.
        posterior = Mass(1, 0, 1, 0).observe(Experiment("1/4", "3/4", 1, 1), 1)
        self.assertEqual(posterior.row(), ("1/5", "0", "4/5", "0"))

    def test_protocol_change_identifies_different_causes(self):
        prior = Mass(1, 0, 1, 0)
        low = Experiment("1/4", "3/4", 1, 1)
        high = Experiment("1/4", "3/4", 0, 1)
        self.assertEqual(prior.observe(low, 1).observe(high, 1).row(), ("1", "0", "0", "0"))
        self.assertEqual(prior.observe(low, 1).observe(high, 0).row(), ("3/19", "0", "16/19", "0"))

    def test_truthful_certificate_preserves_policy_but_changes_truth_semantics(self):
        a = StrategicSource(0, 7, 2, "disclosed", "assertion")
        b = StrategicSource(0, 7, 2, "disclosed", "certificate")
        self.assertEqual(a.step("protocol 0"), b.step("protocol 0"))
        self.assertEqual(a.mass.row(), b.mass.row())
        self.assertEqual(b.event_probabilities()[4], Fraction(0))

    def test_blind_protocol_does_not_change_sender_likelihood(self):
        game = StrategicSource(8, 9, 2, "blind")
        self.assertEqual(game.plan.experiments[0].c, game.plan.experiments[2].c)
        disclosed = StrategicSource(8, 9, 2, "disclosed")
        self.assertEqual(disclosed.plan.experiments[0].c, Fraction(1))
        self.assertEqual(disclosed.plan.experiments[2].c, Fraction(0))

    def test_public_view_has_no_hidden_seed_dependence(self):
        self.assertEqual(StrategicSource(17, 2).view(), StrategicSource(17, 92).view())

    def test_recovery_is_once_after_report(self):
        game = StrategicSource(1, 1)
        with self.assertRaises(ValueError):
            game.step("reveal")
        game.step("protocol 0")
        game.step("reveal")
        self.assertEqual(game.mass.a + game.mass.c, Fraction(1 - game.quality))
        with self.assertRaises(ValueError):
            game.step("reveal")

    def test_noise_zero_is_an_accurate_sincere_control(self):
        game = StrategicSource(0, 0, noise="0")
        self.assertEqual(game.plan.experiments[0].a, Fraction(0))
        self.assertEqual(game.plan.experiments[0].b, Fraction(1))

    def test_incorrect_sender_policy_loses_utility(self):
        self.assertEqual(Sender(0, 4, 2, 1).grade("report 1"), (("deployment_regret", "2"), ("expected_utility", "-2"), ("channel", "assertion")))

    def test_always_distrust_does_not_get_a_free_pass(self):
        game = StrategicSource()
        game.step(AlwaysDistrust().act(game.view()))
        self.assertEqual(game.event_probabilities()[2], Fraction(0))
        self.assertEqual(str(game.result).count("('intent_brier', '1')"), 1)
        self.assertEqual(str(game.result).count("('disposition_decision_regret', '1/3')"), 1)
        self.assertEqual(str(game.result).count("('protocol_cost', '0')"), 1)


class Transport(TestCase):
    def test_controller_initialization_is_not_echoed(self):
        source = StringIO("diagnostic 1 938275 1 balanced\npresent 0 1 2\nanswer 0 1/4 1/4 1/4 1/4\n")
        sink = StringIO()
        Session(source, sink).run()
        self.assertEqual(sink.getvalue().count("938275"), 0)
        self.assertEqual(sink.getvalue().count('"episode_result"'), 1)

    def test_eof_is_unscored(self):
        sink = StringIO()
        Session(StringIO("source 1 1 2 blind certificate\n"), sink).run()
        self.assertEqual(sink.getvalue().count("incomplete_episode: unscored"), 1)

    def test_deployment_port(self):
        sink = StringIO()
        SenderSession(1, 4, 2, 1, "certificate").run(StringIO("report 1\n"), sink)
        self.assertEqual(sink.getvalue().count('"deployment_regret", "0"'), 1)


class IndependentReference(TestCase):
    def test_diagnostic_reference_uses_only_rendered_observations(self):
        trial = Trial("diagnostic 13 29 3 balanced", PublicOracle(), "present 2 1 0")
        trial.run()
        self.assertEqual(trial.status, "scored")
        self.assertEqual(sum(trial.controller.game.regrets), Fraction(0))
        self.assertEqual(trial.controller.game.result, Replay("diagnostic 13 29 3 balanced").consume(trial.actions)[1])
        self.assertEqual(str(trial.controller.game.result).count("('forecast_excess', '0')"), 1)

    def test_skewed_prior_and_short_budget(self):
        trial = Trial("diagnostic 24 3 1 skewed", PublicOracle(), "present 1 0 2")
        trial.run()
        self.assertEqual(trial.status, "scored")
        self.assertEqual(sum(trial.controller.game.regrets), Fraction(0))
        self.assertEqual(str(trial.controller.game.result).count("('forecast_excess', '0')"), 1)

    def test_source_reference_derives_response_law_from_payoffs(self):
        trial = Trial("source 11 27 3 disclosed assertion", PublicOracle())
        trial.run()
        self.assertEqual(trial.status, "scored")
        self.assertEqual(sum(trial.controller.game.regrets), Fraction(0))
        self.assertEqual(str(trial.controller.game.result).count("('forecast_excess', ('0', '0', '0', '0', '0'))"), 1)
        self.assertEqual(str(trial.controller.game.result).count("('disposition_decision_regret', '0')"), 1)

    def test_blind_truthful_source_reference(self):
        trial = Trial("source 23 19 2 blind certificate", PublicOracle())
        trial.run()
        self.assertEqual(trial.status, "scored")
        self.assertEqual(sum(trial.controller.game.regrets), Fraction(0))
        self.assertEqual(str(trial.controller.game.result).count("('forecast_excess', ('0', '0', '0', '0', '0'))"), 1)

    def test_public_reference_updates_after_recovery(self):
        game = StrategicSource(2, 3, 1, "disclosed", "certificate")
        game.step("protocol 0")
        game.step("reveal")
        action = PublicOracle().act(game.view())
        self.assertEqual(action, game.reference_action())
        game.step(action)
        self.assertEqual(str(game.result).count("('forecast_excess', ('0', '0', '0', '0', '0'))"), 1)

    def test_two_role_permutation_cannot_change_semantic_case(self):
        help_trial = TwoRoleTrial("diagnostic 13 29 1 balanced", FirstRowPresenter("helpful"), FirstRow())
        adversarial_trial = TwoRoleTrial("diagnostic 13 29 1 balanced", FirstRowPresenter("adversarial"), FirstRow())
        help_trial.run()
        adversarial_trial.run()
        self.assertEqual(help_trial.trial.controller.game.semantic_id, adversarial_trial.trial.controller.game.semantic_id)
        self.assertGreaterEqual(sum(adversarial_trial.trial.controller.game.regrets), sum(help_trial.trial.controller.game.regrets))

    def test_extra_probe_after_source_terminal_is_rejected(self):
        game = StrategicSource()
        game.step("answer 1/3 2/3 0 0 0")
        with self.assertRaises(ValueError):
            game.step("protocol 0")
