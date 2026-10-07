"""Retained target regression tests for the accepted CS003 policy contract."""
import unittest
from fractions import Fraction
from event_bayes import SpecError, EpistemicEvent, calculate_posterior_strict
from supplied_policy import (
    validate_dist, SuppliedPolicyInstance, SparseSuppliedPolicyInstance,
    StrictSuppliedPolicyInstance, bayes_update,
)


class SuppliedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.prior = {'A': Fraction(1, 2), 'B': Fraction(1, 2)}
        self.sparse_rows = {'A': {'yes': Fraction(1)}, 'B': {'no': Fraction(1)}}
        self.strict_rows = {'A': {'yes': Fraction(1), 'no': Fraction(0)},
                            'B': {'yes': Fraction(0), 'no': Fraction(1)}}

    def test_original_names_retained_with_explicit_sparse_alias(self):
        self.assertIs(SparseSuppliedPolicyInstance, SuppliedPolicyInstance)
        instance = SuppliedPolicyInstance(self.prior, self.sparse_rows, 'yes')
        self.assertEqual(bayes_update(instance), {'A': Fraction(1), 'B': Fraction(0)})

    def test_sparse_and_strict_equivalence_with_explicit_zeros(self):
        sparse = SparseSuppliedPolicyInstance(self.prior, self.sparse_rows, 'yes')
        strict = StrictSuppliedPolicyInstance(self.prior, self.strict_rows, 'yes', ('yes', 'no'))
        self.assertEqual(bayes_update(sparse), bayes_update(strict))

    def test_missing_and_extra_policy_worlds_rejected_by_both_contracts(self):
        for rows in ({'A': self.strict_rows['A']}, {**self.strict_rows, 'extra': self.strict_rows['A']}):
            with self.assertRaises(SpecError): SuppliedPolicyInstance(self.prior, rows, 'yes')
            with self.assertRaises(SpecError): StrictSuppliedPolicyInstance(self.prior, rows, 'yes', ('yes', 'no'))

    def test_strict_requires_explicit_alphabet_coverage(self):
        for rows in (self.sparse_rows,
                     {'A': {'yes': 1, 'no': 0, 'extra': 0}, 'B': self.strict_rows['B']}):
            with self.assertRaises(SpecError):
                StrictSuppliedPolicyInstance(self.prior, rows, 'yes', ('yes', 'no'))
        for alphabet in ((), ('yes', 'yes', 'no')):
            with self.assertRaises(SpecError):
                StrictSuppliedPolicyInstance(self.prior, self.strict_rows, 'yes', alphabet)

    def test_sparse_unknown_observation_constructs_then_update_rejects(self):
        instance = SuppliedPolicyInstance(self.prior, self.sparse_rows, 'unseen')
        with self.assertRaises(SpecError): bayes_update(instance)

    def test_strict_unknown_observation_is_schema_error_at_construction(self):
        with self.assertRaises(SpecError):
            StrictSuppliedPolicyInstance(self.prior, self.strict_rows, 'unseen', ('yes', 'no'))

    def test_declared_zero_evidence_constructs_in_both_contracts(self):
        rows = {'A': {'yes': Fraction(0), 'no': Fraction(1)},
                'B': {'yes': Fraction(0), 'no': Fraction(1)}}
        instances = (SuppliedPolicyInstance(self.prior, rows, 'yes'),
                     StrictSuppliedPolicyInstance(self.prior, rows, 'yes', ('yes', 'no')))
        for instance in instances:
            with self.assertRaises(SpecError): bayes_update(instance)

    def test_evidence_uses_prior_not_just_positive_likelihoods(self):
        instance = SuppliedPolicyInstance({'A': 0, 'B': 1}, self.sparse_rows, 'yes')
        with self.assertRaises(SpecError): bayes_update(instance)

    def test_probability_validation_reuses_exact_contract(self):
        for bad in ({'yes': 0.5, 'no': 0.5}, {'yes': True},
                    {'yes': -1, 'no': 2}, {'yes': Fraction(1, 2)}, {}):
            with self.assertRaises(SpecError): validate_dist(bad, label='test')
            with self.assertRaises(SpecError):
                SuppliedPolicyInstance(self.prior, {'A': bad, 'B': {'no': 1}}, 'yes')
        with self.assertRaises(SpecError):
            SuppliedPolicyInstance({'A': 0.5, 'B': 0.5}, self.sparse_rows, 'yes')

    def test_nontrivial_exact_posterior_agrees_with_event_projection(self):
        prior = {'A': Fraction(1, 4), 'B': Fraction(3, 4)}
        rows = {'A': {'yes': Fraction(1, 2), 'no': Fraction(1, 2)},
                'B': {'yes': Fraction(1, 8), 'no': Fraction(7, 8)}}
        instance = SuppliedPolicyInstance(prior, rows, 'yes')
        result = bayes_update(instance)
        self.assertEqual(result['A'], Fraction(4, 7))
        event = EpistemicEvent('yes', {'A': Fraction(1, 2), 'B': Fraction(1, 8)})
        self.assertEqual(result, calculate_posterior_strict(prior, event))
        self.assertTrue(all(type(v) is Fraction for v in result.values()))

    def test_validated_tables_are_snapshots(self):
        prior = dict(self.prior)
        rows = {w: dict(row) for w, row in self.sparse_rows.items()}
        instance = SuppliedPolicyInstance(prior, rows, 'yes')
        prior['A'] = 0
        rows['A']['yes'] = 0
        self.assertEqual(bayes_update(instance)['A'], 1)
        with self.assertRaises(TypeError): instance.policy['A']['yes'] = 0


if __name__ == '__main__':
    unittest.main()
