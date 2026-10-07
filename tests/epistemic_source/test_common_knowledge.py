"""CS009 implementation checks; CS010 source fixtures remain separate."""
import unittest

from common_knowledge import common_knowledge
from public_announcements import EpistemicModel, ModelError, atom, knows, neg, public_announce


class CommonKnowledgeTests(unittest.TestCase):
    def model(self):
        # Alternating A/B path 0 -> 1 -> 2 -> 3; x is disconnected.
        return EpistemicModel(
            frozenset({'0', '1', '2', '3', 'x'}),
            {'a': [{'0', '1'}, {'2', '3'}, {'x'}],
             'b': [{'0'}, {'1', '2'}, {'3'}, {'x'}]},
            {'0': {'p', 'q'}, '1': {'p', 'q'}, '2': {'p', 'q'},
             '3': {'q'}, 'x': set()},
        )

    def test_multi_step_reachability_not_just_everyone_knows(self):
        m = self.model(); p = atom('p')
        self.assertTrue(knows('a', p)(m, '0'))
        self.assertTrue(knows('b', p)(m, '0'))
        self.assertTrue(knows('a', knows('b', p))(m, '0'))
        self.assertFalse(common_knowledge(['a', 'b'], p)(m, '0'))

    def test_disconnected_false_world_does_not_defeat_common_knowledge(self):
        m = self.model()
        self.assertFalse(atom('q')(m, 'x'))
        self.assertTrue(common_knowledge(['a', 'b'], atom('q'))(m, '0'))
        self.assertFalse(common_knowledge(['a', 'b'], atom('q'))(m, 'x'))

    def test_cycles_terminate_and_each_reachable_world_checked_once(self):
        # Instrument an always-true predicate to observe the complete closure.
        visited = []
        def observe(model, world):
            visited.append(world)
            return True
        self.assertTrue(common_knowledge(['a', 'b'], observe)(self.model(), '0'))
        self.assertCountEqual(visited, ['0', '1', '2', '3'])

    def test_nested_callable_formulas(self):
        m = self.model()
        self.assertTrue(common_knowledge(['a', 'b'], knows('a', atom('q')))(m, '0'))
        self.assertFalse(common_knowledge(['a', 'b'], knows('b', atom('p')))(m, '0'))
        self.assertTrue(neg(common_knowledge(['a', 'b'], atom('p')))(m, '0'))
        self.assertTrue(knows('a', common_knowledge(['a', 'b'], atom('q')))(m, '0'))

    def test_empty_group_evaluates_formula_at_starting_world(self):
        m = self.model(); formula = common_knowledge([], atom('p'))
        self.assertTrue(formula(m, '0'))
        self.assertFalse(formula(m, '3'))

    def test_unknown_world_rejected_even_with_empty_group_and_constant_true(self):
        for agents in ([], ['a']):
            with self.subTest(agents=agents):
                with self.assertRaisesRegex(ModelError, 'unknown world'):
                    common_knowledge(agents, lambda m, w: True)(self.model(), 'missing')

    def test_unknown_agent_rejected_before_formula_evaluation(self):
        called = []
        def predicate(m, w):
            called.append(w)
            return False
        with self.assertRaisesRegex(ModelError, 'unknown agent'):
            common_knowledge(['a', 'missing'], predicate)(self.model(), '0')
        self.assertEqual(called, [])

    def test_group_is_snapshotted_at_formula_construction(self):
        agents = ['a']
        formula = common_knowledge(agents, atom('p'))
        agents.append('b')
        self.assertTrue(formula(self.model(), '0'))
        self.assertFalse(common_knowledge(agents, atom('p'))(self.model(), '0'))
        agents.clear()
        self.assertTrue(formula(self.model(), '0'))

    def test_duplicate_agents_are_allowed_and_semantically_redundant(self):
        m = self.model()
        for proposition in ('p', 'q'):
            self.assertEqual(common_knowledge(['a', 'b', 'a'], atom(proposition))(m, '0'),
                             common_knowledge(['a', 'b'], atom(proposition))(m, '0'))

    def test_same_formula_recomputes_closure_after_announcement(self):
        m = self.model(); formula = common_knowledge(['a', 'b'], atom('p'))
        self.assertFalse(formula(m, '0'))
        updated = public_announce(m, atom('p'))
        self.assertTrue(formula(updated, '0'))
        self.assertFalse(formula(m, '0'))


if __name__ == '__main__':
    unittest.main()
