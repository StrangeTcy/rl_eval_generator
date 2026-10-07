"""CS004: preserve and repair Sonnet E1 test fixtures (critique lines 340–363).

Design choices approved: 1B, 2B, 3C, 4A. Result accepted by the user.
These tests exercise accepted CS003; no production/proposal implementation changes.
"""
import unittest
from fractions import Fraction

from supplied_policy import (
    SuppliedPolicyInstance, StrictSuppliedPolicyInstance, bayes_update,
    validate_dist,
)


class SourceE1FixtureTests(unittest.TestCase):
    def test_original_impossible_event_fixture_rejected_at_construction(self):
        # Original source values retained: w2's row sums to zero.
        prior = {'w1': Fraction(1, 2), 'w2': Fraction(1, 2)}
        policy = {'w1': {'o': Fraction(1)}, 'w2': {'o': Fraction(0)}}
        for contract in ('sparse', 'strict'):
            with self.subTest(contract=contract):
                with self.assertRaisesRegex(ValueError, r'policy\[w2\]'):
                    if contract == 'sparse':
                        SuppliedPolicyInstance(prior, policy, 'not_o')
                    else:
                        StrictSuppliedPolicyInstance(prior, policy, 'not_o', ('o', 'not_o'))

    def test_original_exact_posterior_fixture_rejected_at_construction(self):
        # Original source values retained: neither policy row is normalized.
        prior = {'w1': Fraction(1, 3), 'w2': Fraction(2, 3)}
        policy = {'w1': {'o': Fraction(1, 2)}, 'w2': {'o': Fraction(1, 4)}}
        for contract in ('sparse', 'strict'):
            with self.subTest(contract=contract):
                with self.assertRaisesRegex(ValueError, r'policy\[w1\]'):
                    if contract == 'sparse':
                        SuppliedPolicyInstance(prior, policy, 'o')
                    else:
                        StrictSuppliedPolicyInstance(prior, policy, 'o', ('o',))
        # Construction stops at w1; independently expose w2's malformed row too.
        for world, row in policy.items():
            with self.subTest(row=world):
                with self.assertRaises(ValueError):
                    validate_dist(row, label=f'policy[{world}]')

    def test_zero_likelihood_observation_is_rejected_not_silently_renormalized_sparse(self):
        prior = {'w1': Fraction(1, 2), 'w2': Fraction(1, 2)}
        policy = {'w1': {'o': Fraction(1)}, 'w2': {'other': Fraction(1)}}
        # Construction is deliberately OUTSIDE assertRaises: it must succeed.
        instance = SuppliedPolicyInstance(prior, policy, 'not_o')
        with self.assertRaisesRegex(ValueError, 'Zero-probability event observed'):
            bayes_update(instance)

    def test_zero_likelihood_observation_is_rejected_not_silently_renormalized_strict(self):
        prior = {'w1': Fraction(1, 2), 'w2': Fraction(1, 2)}
        policy = {
            'w1': {'o': Fraction(1), 'other': Fraction(0), 'not_o': Fraction(0)},
            'w2': {'o': Fraction(0), 'other': Fraction(1), 'not_o': Fraction(0)},
        }
        instance = StrictSuppliedPolicyInstance(prior, policy, 'not_o', ('o', 'other', 'not_o'))
        with self.assertRaisesRegex(ValueError, 'Zero-probability event observed'):
            bayes_update(instance)

    def _posterior_instance(self, prior, contract):
        # Add complementary outcomes without changing either source P(o | world).
        policy = {
            'w1': {'o': Fraction(1, 2), 'other': Fraction(1, 2)},
            'w2': {'o': Fraction(1, 4), 'other': Fraction(3, 4)},
        }
        if contract == 'sparse':
            return SuppliedPolicyInstance(prior, policy, 'o')
        return StrictSuppliedPolicyInstance(prior, policy, 'o', ('o', 'other'))

    def _assert_exact_posterior(self, instance, expected):
        result = bayes_update(instance)
        self.assertEqual(set(result), set(expected))
        for world, probability in expected.items():
            self.assertIs(type(result[world]), Fraction, f'{world}: float equality is not exact arithmetic')
            self.assertEqual(result[world], probability)
        self.assertEqual(sum(result.values(), Fraction(0)), Fraction(1))

    def test_posterior_is_exact_not_approximate_sparse(self):
        instance = self._posterior_instance({'w1': Fraction(1, 3), 'w2': Fraction(2, 3)}, 'sparse')
        # Original hand calculation: (1/3 * 1/2) : (2/3 * 1/4) = 1 : 1.
        self._assert_exact_posterior(instance, {'w1': Fraction(1, 2), 'w2': Fraction(1, 2)})

    def test_posterior_is_exact_not_approximate_strict(self):
        instance = self._posterior_instance({'w1': Fraction(1, 3), 'w2': Fraction(2, 3)}, 'strict')
        self._assert_exact_posterior(instance, {'w1': Fraction(1, 2), 'w2': Fraction(1, 2)})

    def test_asymmetric_posterior_rejects_uniform_shortcut_sparse(self):
        instance = self._posterior_instance({'w1': Fraction(1, 4), 'w2': Fraction(3, 4)}, 'sparse')
        # (1/4 * 1/2) : (3/4 * 1/4) = 1/8 : 3/16 = 2 : 3.
        self._assert_exact_posterior(instance, {'w1': Fraction(2, 5), 'w2': Fraction(3, 5)})

    def test_asymmetric_posterior_rejects_uniform_shortcut_strict(self):
        instance = self._posterior_instance({'w1': Fraction(1, 4), 'w2': Fraction(3, 4)}, 'strict')
        self._assert_exact_posterior(instance, {'w1': Fraction(2, 5), 'w2': Fraction(3, 5)})


if __name__ == '__main__':
    unittest.main()
