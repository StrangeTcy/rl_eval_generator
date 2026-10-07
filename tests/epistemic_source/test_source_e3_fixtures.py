"""CS008 source E3 fixtures: design and result accepted by the user.

Both original source fixtures remain separate from CS007 implementation tests.
"""
import unittest
from fractions import Fraction

from silence import update_on_silence


class SourceE3FixtureTests(unittest.TestCase):
    def assert_exact_posterior(self, posterior, expected):
        self.assertEqual(posterior, expected)
        for world, probability in posterior.items():
            with self.subTest(world=world):
                self.assertIs(type(probability), Fraction)

    def test_silence_rules_out_worlds_where_protocol_mandates_speech(self):
        # Original source fixture and assertions.
        prior = {'w1': Fraction(1, 2), 'w2': Fraction(1, 2)}
        original_prior = dict(prior)
        protocol = {'agent_x': lambda w: w == 'w1'}
        post = update_on_silence(prior, protocol)
        self.assertEqual(post['w1'], Fraction(0))
        self.assertEqual(post['w2'], Fraction(1))
        # Added full mapping, exact type and input-preservation checks.
        self.assert_exact_posterior(post, {'w1': Fraction(0), 'w2': Fraction(1)})
        self.assertEqual(prior, original_prior)

    def test_silence_is_uninformative_when_protocol_never_fires(self):
        # Original asymmetric fixture catches unconditional world elimination.
        prior = {'w1': Fraction(1, 3), 'w2': Fraction(2, 3)}
        original_prior = dict(prior)
        protocol = {'agent_x': lambda w: False}
        post = update_on_silence(prior, protocol)
        self.assertEqual(post, prior)
        # Compare against a pre-call snapshot as well: mutating prior and output
        # together must not make the source equality assertion pass spuriously.
        self.assert_exact_posterior(post, original_prior)
        self.assertEqual(prior, original_prior)

    def test_reversing_firing_condition_reverses_excluded_world(self):
        # Added counterfixture: same world names/prior, opposite firing condition.
        prior = {'w1': Fraction(1, 2), 'w2': Fraction(1, 2)}
        original_prior = dict(prior)
        protocol = {'agent_x': lambda w: w == 'w2'}
        post = update_on_silence(prior, protocol)
        self.assert_exact_posterior(post, {'w1': Fraction(1), 'w2': Fraction(0)})
        self.assertEqual(prior, original_prior)


if __name__ == '__main__':
    unittest.main()
