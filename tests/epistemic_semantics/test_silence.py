"""CS007 implementation checks; CS008 source fixtures remain separate."""
import unittest
from fractions import Fraction as F
from unittest.mock import patch

from shared.epistemic_semantics import silence
from shared.epistemic_semantics.event_bayes import SpecError
from shared.epistemic_semantics.supplied_policy import SuppliedPolicyInstance


class SilenceTests(unittest.TestCase):
    def test_no_agent_announces(self):
        result = silence.silence_event_likelihood('w', {'a': lambda w: False, 'b': lambda w: False})
        self.assertEqual(result, F(1))
        self.assertIs(type(result), F)

    def test_any_agent_announcing_precludes_silence(self):
        for a, b in [(False, True), (True, False), (True, True)]:
            result = silence.silence_event_likelihood('w', {'a': lambda w: a, 'b': lambda w: b})
            self.assertEqual(result, F(0))
            self.assertIs(type(result), F)

    def test_every_rule_evaluated_even_after_true(self):
        called = []
        def rule(agent, decision):
            def evaluate(world):
                called.append((agent, world))
                return decision
            return evaluate
        silence.silence_event_likelihood('w', {'a': rule('a', True), 'b': rule('b', False)})
        self.assertEqual(called, [('a', 'w'), ('b', 'w')])

    def test_non_boolean_results_rejected_even_after_true(self):
        for invalid in [0, 1, F(1, 2), F(0), 'yes', None]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(SpecError):
                    silence.silence_event_likelihood('w', {'a': lambda w: True, 'b': lambda w: invalid})

    def test_empty_protocol_has_unit_likelihood_and_preserves_prior(self):
        prior = {'w1': F(1, 3), 'w2': F(2, 3)}
        self.assertEqual(silence.silence_event_likelihood('w1', {}), F(1))
        self.assertEqual(silence.update_on_silence(prior, {}), prior)

    def test_normalized_complementary_rows_and_exact_posterior(self):
        prior = {'w1': F(1, 6), 'w2': F(1, 3), 'w3': F(1, 2)}
        seen = []
        def capture(**kwargs):
            instance = SuppliedPolicyInstance(**kwargs)
            seen.append(instance)
            return instance
        with patch.object(silence, 'SuppliedPolicyInstance', side_effect=capture):
            result = silence.update_on_silence(prior, {'a': lambda w: w == 'w3'})
        self.assertEqual(result, {'w1': F(1, 3), 'w2': F(2, 3), 'w3': F(0)})
        self.assertTrue(all(type(value) is F for value in result.values()))
        self.assertEqual(dict(seen[0].policy['w3']), {'silence': F(0), 'announcement': F(1)})
        for row in seen[0].policy.values():
            self.assertEqual(set(row), {'silence', 'announcement'})
            self.assertEqual(sum(row.values()), F(1))
        self.assertEqual(prior, {'w1': F(1, 6), 'w2': F(1, 3), 'w3': F(1, 2)})

    def test_impossible_silence_rejected_at_update_not_construction(self):
        constructed = []
        def capture(**kwargs):
            instance = SuppliedPolicyInstance(**kwargs)
            constructed.append(instance)
            return instance
        with patch.object(silence, 'SuppliedPolicyInstance', side_effect=capture):
            with self.assertRaisesRegex(SpecError, 'Zero-probability event'):
                silence.update_on_silence({'w': F(1)}, {'a': lambda w: True})
        self.assertEqual(len(constructed), 1)

    def test_silence_possible_only_at_zero_prior_world_is_impossible_evidence(self):
        with self.assertRaisesRegex(SpecError, 'Zero-probability event'):
            silence.update_on_silence({'w1': F(1), 'w2': F(0)}, {'a': lambda w: w == 'w1'})

    def test_invalid_prior_rejected_by_accepted_validator(self):
        for prior in [{}, {'w': F(1, 2)}, {'w': 1.0}]:
            with self.subTest(prior=prior):
                with self.assertRaises(SpecError): silence.update_on_silence(prior, {})


if __name__ == '__main__':
    unittest.main()
