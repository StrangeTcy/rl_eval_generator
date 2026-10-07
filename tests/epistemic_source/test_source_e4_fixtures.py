"""CS010 source E4 fixtures: design and result accepted by the user."""
import unittest

from public_announcements import EpistemicModel, atom, knows
from common_knowledge import common_knowledge


class SourceE4FixtureTests(unittest.TestCase):
    def test_three_level_nesting_evaluates_in_singleton_model(self):
        # Original fixture: one depth-three expression, not a reachability chain
        # or a proof of arbitrary nesting support. This does not test CK.
        m = EpistemicModel(
            worlds=frozenset({'w'}),
            partitions={'a': frozenset({frozenset({'w'})}),
                        'b': frozenset({frozenset({'w'})}),
                        'c': frozenset({frozenset({'w'})})},
            valuation={'w': frozenset({'p'})},
        )
        f = knows('a', knows('b', knows('c', atom('p'))))
        self.assertIs(f(m, 'w'), True)

    def test_common_knowledge_of_world_predicate_depends_on_selected_group(self):
        # Original fixture: p holds everywhere; the tested predicate distinguishes
        # world identities. Uncertainty does not itself defeat common knowledge.
        m = EpistemicModel(
            worlds=frozenset({'w1', 'w2'}),
            partitions={'a': frozenset({frozenset({'w1'}), frozenset({'w2'})}),
                        'b': frozenset({frozenset({'w1', 'w2'})})},
            valuation={'w1': frozenset({'p'}), 'w2': frozenset({'p'})},
        )
        only_w1 = lambda model, world: world == 'w1'
        f = common_knowledge(['a', 'b'], only_w1)
        self.assertIs(f(m, 'w1'), False)  # Original assertion.
        self.assertIs(common_knowledge(['a'], only_w1)(m, 'w1'), True)
        self.assertIs(common_knowledge(['a', 'b'], atom('p'))(m, 'w1'), True)

    def test_depth_three_differs_from_expressions_omitting_any_operator(self):
        # Added A/B/C path 0 -> 1 -> 2 -> 3, with p false only at 3.
        m = EpistemicModel(
            worlds=frozenset({'0', '1', '2', '3'}),
            partitions={
                'a': [{'0', '1'}, {'2'}, {'3'}],
                'b': [{'0'}, {'1', '2'}, {'3'}],
                'c': [{'0'}, {'1'}, {'2', '3'}],
            },
            valuation={'0': {'p'}, '1': {'p'}, '2': {'p'}, '3': set()},
        )
        p = atom('p')
        self.assertIs(knows('a', knows('b', knows('c', p)))(m, '0'), False)
        # Removing any one operator loses the three-link path to 3.
        for omitted, formula in (
            ('c', knows('a', knows('b', p))),
            ('b', knows('a', knows('c', p))),
            ('a', knows('b', knows('c', p))),
        ):
            with self.subTest(omitted=omitted):
                self.assertIs(formula(m, '0'), True)
        self.assertIs(p(m, '0'), True)


if __name__ == '__main__':
    unittest.main()
