"""CS011 implementation checks; CS012 source fixtures remain separate."""
import unittest

from fragmented_observation import validate_partition, information_set, joint_information
from public_announcements import EpistemicModel, ModelError, atom, knows
from common_knowledge import common_knowledge


class FragmentedObservationTests(unittest.TestCase):
    def model(self):
        return EpistemicModel(
            frozenset({'00', '01', '10', '11'}),
            {'a': [{'00', '01'}, {'10', '11'}],
             'b': [{'00', '10'}, {'01', '11'}]},
            {'00': {'p'}, '01': set(), '10': set(), '11': set()},
        )

    def test_standalone_validator_returns_none_for_valid_partition(self):
        m = self.model()
        self.assertIsNone(validate_partition(m.worlds, m.partitions['a']))

    def test_standalone_validator_rejects_invalid_partitions(self):
        worlds = frozenset({'w1', 'w2'})
        for cells in (
            frozenset({frozenset(), worlds}),
            frozenset({frozenset({'w1'}), worlds}),
            frozenset({frozenset({'w1'})}),
            frozenset({frozenset({'w1', 'w2', 'outside'})}),
        ):
            with self.subTest(cells=cells):
                with self.assertRaises(ModelError): validate_partition(worlds, cells)

    def test_information_sets_are_individual_cells(self):
        m = self.model()
        self.assertEqual(information_set(m, 'a', '00'), frozenset({'00', '01'}))
        self.assertEqual(information_set(m, 'b', '00'), frozenset({'00', '10'}))

    def test_pooling_identifies_world_neither_agent_identifies_alone(self):
        m = self.model()
        for world in m.worlds:
            self.assertEqual(len(information_set(m, 'a', world)), 2)
            self.assertEqual(len(information_set(m, 'b', world)), 2)
            result = joint_information(m, ['a', 'b'], world)
            self.assertEqual(result, frozenset({world}))
            self.assertIs(type(result), frozenset)

    def test_pooling_does_not_change_individual_or_common_knowledge(self):
        m = self.model(); p = atom('p')
        before = (m.worlds, dict(m.partitions), dict(m.valuation))
        result = joint_information(m, ['a', 'b'], '00')
        self.assertTrue(all(p(m, w) for w in result))
        self.assertFalse(knows('a', p)(m, '00'))
        self.assertFalse(knows('b', p)(m, '00'))
        self.assertFalse(common_knowledge(['a', 'b'], p)(m, '00'))
        self.assertEqual((m.worlds, dict(m.partitions), dict(m.valuation)), before)

    def test_empty_group_returns_full_world_set(self):
        m = self.model()
        self.assertEqual(joint_information(m, [], '00'), m.worlds)
        self.assertIs(type(joint_information(m, [], '00')), frozenset)

    def test_singleton_duplicate_and_order_semantics(self):
        m = self.model()
        self.assertEqual(joint_information(m, ['a'], '00'), information_set(m, 'a', '00'))
        self.assertEqual(joint_information(m, ['a', 'a'], '00'), information_set(m, 'a', '00'))
        self.assertEqual(joint_information(m, ['b', 'a', 'b'], '00'),
                         joint_information(m, ['a', 'b'], '00'))

    def test_unknown_world_rejected_including_empty_group(self):
        m = self.model()
        with self.assertRaisesRegex(ModelError, 'unknown world'):
            information_set(m, 'a', 'missing')
        for agents in ([], ['a'], ['a', 'b']):
            with self.subTest(agents=agents):
                with self.assertRaisesRegex(ModelError, 'unknown world'):
                    joint_information(m, agents, 'missing')

    def test_unknown_agents_rejected(self):
        m = self.model()
        with self.assertRaisesRegex(ModelError, 'unknown agent'):
            information_set(m, 'missing', '00')
        with self.assertRaisesRegex(ModelError, 'unknown agent'):
            joint_information(m, ['a', 'missing'], '00')


if __name__ == '__main__':
    unittest.main()
