"""Source-specific fixtures for the accepted CS001 proposal."""
import unittest
from fractions import Fraction
from shared.epistemic_semantics.event_bayes import (
    SpecError, EpistemicEvent, calculate_posterior,
    calculate_posterior_sparse, calculate_posterior_strict,
)


class EventBayesTests(unittest.TestCase):
    def test_cs001_perfect_evidence_original_core_and_both_wrappers(self):
        prior = {'A': Fraction(1, 2), 'B': Fraction(1, 2)}
        event = EpistemicEvent('Observed A', {'A': Fraction(1), 'B': Fraction(0)})
        for compute in (calculate_posterior, calculate_posterior_sparse, calculate_posterior_strict):
            self.assertEqual(compute(prior, event), {'A': Fraction(1), 'B': Fraction(0)})

    def test_cs001_sparse_missing_and_extra_are_distinct_from_strict(self):
        prior = {'A': Fraction(1, 2), 'B': Fraction(1, 2)}
        for event in (EpistemicEvent('A', {'A': Fraction(1)}),
                      EpistemicEvent('A', {'A': Fraction(1), 'B': Fraction(0), 'unrelated': 'ignored'})):
            self.assertEqual(calculate_posterior_sparse(prior, event)['A'], 1)
            self.assertEqual(calculate_posterior(prior, event)['A'], 1)
            with self.assertRaises(SpecError): calculate_posterior_strict(prior, event)

    def test_cs001_wrappers_reject_invalid_probability_inputs(self):
        good_prior = {'A': Fraction(1, 2), 'B': Fraction(1, 2)}
        good_event = EpistemicEvent('A', {'A': Fraction(1), 'B': Fraction(0)})
        for compute in (calculate_posterior_sparse, calculate_posterior_strict):
            for prior in ({'A': 0.5, 'B': 0.5}, {'A': -1, 'B': 2}, {'A': 1, 'B': 1}):
                with self.assertRaises(SpecError): compute(prior, good_event)
            for likelihoods in ({'A': 1.0, 'B': 0}, {'A': 2, 'B': 0}, {'A': -1, 'B': 1}):
                with self.assertRaises(SpecError): compute(good_prior, EpistemicEvent('A', likelihoods))

    def test_cs001_core_preconditions_and_zero_evidence(self):
        # Unnormalized input violates the core's preconditions but is not checked there.
        event = EpistemicEvent('A', {'A': Fraction(1), 'B': Fraction(1)})
        self.assertEqual(calculate_posterior({'A': Fraction(1), 'B': Fraction(1)}, event)['A'], Fraction(1, 2))
        with self.assertRaises(SpecError): calculate_posterior_sparse({'A': 1, 'B': 1}, event)
        impossible = EpistemicEvent('impossible', {'A': Fraction(0), 'B': Fraction(0)})
        for compute in (calculate_posterior, calculate_posterior_sparse, calculate_posterior_strict):
            with self.assertRaises(SpecError): compute({'A': Fraction(1, 2), 'B': Fraction(1, 2)}, impossible)


if __name__ == "__main__":
    unittest.main()
