"""OP-indexed checks for bounded inquiry behavior, with independent expectations.

These tests exercise supplied finite models. They do not establish hypothesis
suppression, unknown-noise learning, general subset selection, or model ability.
"""

from fractions import Fraction
from io import StringIO
from unittest import TestCase

from arena.inquiry.baselines import AlwaysDistrust, FirstRow
from arena.inquiry.diagnostic import Diagnostic
from arena.inquiry.finite import Experiment, InquiryPlan, Mass
from arena.inquiry.presenter import FirstRowPresenter, TwoRoleTrial
from arena.inquiry.reference import PublicOracle
from arena.inquiry.session import Replay, Session
from arena.inquiry.strategic import StrategicSource


class InquiryOPValidation(TestCase):
    def test_OP015_OP035_OP039_query_order_keeps_all_supplied_hypotheses(self):
        neutral = Diagnostic(11, 7, 2)
        changed = Diagnostic(11, 7, 2)
        neutral.present("present 0 1 2")
        changed.present("present 2 1 0")
        self.assertEqual(FirstRow().act(neutral.view()), "inspect 0")
        self.assertEqual(FirstRow().act(changed.view()), "inspect 2")
        self.assertEqual(PublicOracle().act(neutral.view()), PublicOracle().act(changed.view()))
        self.assertEqual(neutral.semantic_id, changed.semantic_id)
        self.assertEqual(neutral.initial.row(), changed.initial.row())
        self.assertEqual(neutral.view().count("H0, H1, H2, or H3"), 1)
        self.assertEqual(changed.view().count("H0, H1, H2, or H3"), 1)
        self.assertEqual(changed.view().count("Test 0:"), 1)
        self.assertEqual(changed.view().count("Test 1:"), 1)
        self.assertEqual(changed.view().count("Test 2:"), 1)

    def test_OP025_OP045_two_observations_identify_world_and_replay(self):
        game = Diagnostic(0, 7, 2)
        game.present("present 0 1 2")
        self.assertEqual(game.trace, ("present 0 1 2",))
        first = game.step("inspect 0")
        second = game.step("inspect 1")
        # The public fixed partitions encode the high and low bit respectively.
        decision = 2 * int(first[-1]) + int(second[-1])
        forecast = ("1 0 0 0", "0 1 0 0", "0 0 1 0", "0 0 0 1")[decision]
        answer = f"answer {decision} {forecast}"
        with self.assertRaises(ValueError):
            game.step("inspect 2")
        result = game.step(answer)
        loss, brier, excess, cost, regrets, stopping, decision_regret = result
        self.assertEqual(loss, ("terminal_loss", "0"))
        self.assertEqual(brier, ("brier", "0"))
        self.assertEqual(excess, ("forecast_excess", "0"))
        self.assertEqual(stopping, ("stop_regret", "0"))
        self.assertEqual(decision_regret, ("decision_regret", "0"))
        self.assertEqual(game.stage, "done")
        actions = ("present 0 1 2", "inspect 0", "inspect 1", answer)
        trace, replayed = Replay("diagnostic 0 7 2 balanced").consume(actions)
        self.assertEqual(replayed, result)
        self.assertEqual(trace, ("present 0 1 2", ("inspect 0", int(first[-1])), ("inspect 1", int(second[-1])), answer))
        with self.assertRaises(ValueError):
            Replay("diagnostic 0 7 2 balanced").consume(actions[:-1])
        with self.assertRaises(ValueError):
            Replay("diagnostic 0 7 2 balanced").consume(actions + ("inspect 2",))

    def test_OP028_OP040_OP059_presenter_changes_first_row_cost(self):
        helpful = TwoRoleTrial("diagnostic 13 29 1 balanced", FirstRowPresenter("helpful"), FirstRow())
        adversarial = TwoRoleTrial("diagnostic 13 29 1 balanced", FirstRowPresenter("adversarial"), FirstRow())
        helpful.run()
        adversarial.run()
        self.assertEqual(helpful.trial.status, "scored")
        self.assertEqual(adversarial.trial.status, "scored")
        self.assertEqual(helpful.trial.controller.game.semantic_id, adversarial.trial.controller.game.semantic_id)
        self.assertGreater(sum(adversarial.trial.controller.game.regrets), sum(helpful.trial.controller.game.regrets))
        self.assertEqual(helpful.trial.invalid, ())
        self.assertEqual(adversarial.trial.invalid, ())
        # This contrast supplies the first-row opponent; no unknown profile is learned.
        self.assertEqual(helpful.trial.controller.game.initial.row(), adversarial.trial.controller.game.initial.row())

    def test_OP043_horizon_can_reverse_stop_into_complementary_queries(self):
        plan = InquiryPlan(Experiment(0, 0, 1, 1, "3/10"), Experiment(0, 1, 0, 1, "3/10"), Experiment(0, 0, 0, 0, 1))
        prior = Mass(1, 1, 1, 1)
        # A single test costs 3/10 and leaves error 1/2: worse than stopping at 3/4.
        # Two complementary tests cost 3/5 and eliminate decision error.
        self.assertEqual(plan.value(prior, 1, 0), Fraction(3, 4))
        self.assertEqual(plan.choose(prior, 1, 0), 3)
        self.assertEqual(plan.value(prior, 2, 0), Fraction(3, 5))
        self.assertEqual(plan.choose(prior, 2, 0), 0)

    def test_OP005_OP010_OP020_disclosed_audit_changes_response_law(self):
        disclosed = StrategicSource(0, 7, 1, "disclosed")
        blind = StrategicSource(0, 7, 1, "blind")
        self.assertEqual(disclosed.initial.row(), ("4/9", "2/9", "2/9", "1/9"))
        low, middle, high = disclosed.plan.experiments
        blind_low, blind_middle, blind_high = blind.plan.experiments
        self.assertEqual(low.c, Fraction(1))
        self.assertEqual(high.c, Fraction(0))
        self.assertEqual(blind_high.c, Fraction(1))
        # Enumerated prior: low-audit positive mass is 11/18; high-audit is 7/18.
        self.assertEqual(disclosed.initial.probability(low, 1), Fraction(11, 18))
        self.assertEqual(disclosed.initial.probability(high, 1), Fraction(7, 18))
        self.assertEqual(blind.initial.probability(blind_high, 1), Fraction(11, 18))

    def test_OP007_OP023_OP075_certificate_keeps_evidence_but_changes_truth(self):
        assertion = StrategicSource(0, 7, 1, "blind", "assertion")
        certificate = StrategicSource(0, 7, 1, "blind", "certificate")
        report = assertion.step("protocol 0")
        self.assertEqual(certificate.step("protocol 0"), report)
        report_id = int(report[-1])
        expected = ((Fraction(0), Fraction(6, 7), Fraction(0), Fraction(0), Fraction(0)), (Fraction(6, 11), Fraction(6, 11), Fraction(4, 11), Fraction(2, 11), Fraction(6, 11)))[report_id]
        strategic, bad, intentional, error, falsehood = expected
        self.assertEqual(assertion.event_probabilities(), expected)
        self.assertEqual(certificate.event_probabilities(), (strategic, bad, intentional, error, Fraction(0)))
        self.assertEqual(assertion.mass.row(), certificate.mass.row())
        assertion.step("answer " + " ".join(map(str, expected)))
        certificate.step("answer " + " ".join(map(str, (strategic, bad, intentional, error, Fraction(0)))))
        self.assertEqual(assertion.stage, "done")
        self.assertEqual(certificate.stage, "done")
        self.assertEqual(str(assertion.result).count("('forecast_excess', ('0', '0', '0', '0', '0'))"), 1)
        self.assertEqual(str(certificate.result).count("('literal_falsehood_brier', '0')"), 1)

    def test_OP018_supplied_noise_changes_source_posterior(self):
        noisy = StrategicSource(0, 7, 1, noise="1/4")
        accurate = StrategicSource(0, 7, 1, noise="0")
        noisy_low, noisy_middle, noisy_high = noisy.plan.experiments
        accurate_low, accurate_middle, accurate_high = accurate.plan.experiments
        self.assertEqual(noisy.initial.observe(noisy_low, 1).row(), ("2/11", "3/11", "4/11", "2/11"))
        self.assertEqual(accurate.initial.observe(accurate_low, 1).row(), ("0", "2/5", "2/5", "1/5"))
        # Noise is supplied in the task; it is not inferred from an unknown model class.
        self.assertEqual(noisy.view().count("error probability 1/4"), 1)
        self.assertEqual(accurate.view().count("error probability 0"), 1)

    def test_OP034_OP052_reveal_updates_quality_without_certifying_intent(self):
        game = StrategicSource(0, 7, 1, "blind", "certificate")
        report = int(game.step("protocol 0")[-1])
        remaining = game.remaining
        quality = int(game.step("reveal")[-1])
        # Rows are (report=0/quality=0), (0/1), (1/0), (1/1).
        expected = (("0", "1", "0", "0", "0"), ("0", "0", "0", "0", "0"), ("2/3", "1", "2/3", "1/3", "0"), ("2/5", "0", "0", "0", "0"))[2 * report + quality]
        self.assertEqual(tuple(map(str, game.event_probabilities())), expected)
        self.assertEqual(game.remaining, remaining)
        self.assertEqual(game.trace.count(("reveal", quality)), 1)
        with self.assertRaises(ValueError):
            game.step("reveal")
        game.step("answer " + " ".join(expected))
        self.assertEqual(game.stage, "done")
        self.assertEqual(str(game.result).count("('recovery_arm', '1')"), 1)
        self.assertEqual(str(game.result).count("('forecast_excess', ('0', '0', '0', '0', '0'))"), 1)

    def test_OP038_OP055_OP074_uncertain_forecast_beats_false_certainty_in_expectation(self):
        calibrated = StrategicSource(0, 7, 1)
        distrust = StrategicSource(0, 7, 1)
        calibrated.step("answer 1/3 2/3 0 0 0")
        distrust.step(AlwaysDistrust().act(distrust.view()))
        self.assertEqual(str(calibrated.result).count("('forecast_excess', ('0', '0', '0', '0', '0'))"), 1)
        self.assertEqual(str(distrust.result).count("('forecast_excess', ('4/9', '1/9', '1', '0', '1'))"), 1)
        self.assertEqual(str(calibrated.result).count("('protocol_cost', '0')"), 1)
        self.assertEqual(str(calibrated.result).count("('disposition_decision_regret', '0')"), 1)
        self.assertEqual(str(distrust.result).count("('disposition_decision_regret', '1/3')"), 1)
        self.assertEqual(str(distrust.result).count("('intent_brier', '1')"), 1)

    def test_OP053_semantic_identity_ignores_hidden_seed_and_preserves_contract(self):
        first = Diagnostic(11, 7, 1)
        other_world = Diagnostic(11, 987654, 1)
        other_budget = Diagnostic(11, 7, 2)
        self.assertEqual(first.view(), other_world.view())
        self.assertEqual(first.semantic_id, other_world.semantic_id)
        self.assertNotEqual(first.semantic_id, other_budget.semantic_id)
        assertion = StrategicSource(0, 7, 1, "blind", "assertion")
        other_source_world = StrategicSource(0, 987654, 1, "blind", "assertion")
        certificate = StrategicSource(0, 7, 1, "blind", "certificate")
        self.assertEqual(assertion.view(), other_source_world.view())
        self.assertEqual(assertion.semantic_id, other_source_world.semantic_id)
        self.assertNotEqual(assertion.semantic_id, certificate.semantic_id)

    def test_OP054_invalid_source_actions_preserve_state_and_budget(self):
        game = StrategicSource(0, 7, 1)
        prior = game.mass.row()
        with self.assertRaises(ValueError):
            game.step("protocol 9")
        with self.assertRaises(ValueError):
            game.step("answer NaN 0 0 0 0")
        with self.assertRaises(ValueError):
            game.step("answer 1/0 0 0 0 0")
        with self.assertRaises(ValueError):
            game.step("answer 2 0 0 0 0")
        with self.assertRaises(ValueError):
            game.step("reveal")
        self.assertEqual(game.mass.row(), prior)
        self.assertEqual(game.remaining, 1)
        self.assertEqual(game.trace, ())
        game.step("protocol 0")
        with self.assertRaises(ValueError):
            game.step("protocol 0")
        self.assertEqual(game.remaining, 0)

    def test_OP054_bounded_transport_remains_unscored_after_invalid_responses(self):
        sink = StringIO()
        source = StringIO("source 0 987654 1 blind certificate\n" + "nonsense\n" * 12)
        Session(source, sink).run()
        self.assertEqual(sink.getvalue().count("invalid_action:"), 12)
        self.assertEqual(sink.getvalue().count("response limit reached; unscored"), 1)
        self.assertEqual(sink.getvalue().count("episode_result"), 0)
        self.assertEqual(sink.getvalue().count("987654"), 0)

    def test_OP045_source_replay_reconstructs_reports_and_scores(self):
        game = StrategicSource(0, 7, 1, "blind", "certificate")
        report = game.step("protocol 0")
        expected = ("answer 0 6/7 0 0 0", "answer 6/11 6/11 4/11 2/11 0")[int(report[-1])]
        result = game.step(expected)
        actions = ("protocol 0", expected)
        trace, replayed = Replay("source 0 7 1 blind certificate").consume(actions)
        self.assertEqual(trace, (("protocol 0", int(report[-1])), expected))
        self.assertEqual(replayed, result)
        self.assertEqual(str(replayed).count("('forecast_excess', ('0', '0', '0', '0', '0'))"), 1)
        self.assertEqual(str(replayed).count("('protocol_cost', '1/100')"), 1)
        self.assertEqual(Replay("source 0 7 1 blind certificate").consume(actions), (trace, result))
        with self.assertRaises(ValueError):
            Replay("source 0 7 1 blind certificate").consume(actions + ("reveal",))
