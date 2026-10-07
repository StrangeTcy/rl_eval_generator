"""Retained target regression tests for the accepted CS005 announcement contract."""
import unittest

from public_announcements import (
    EpistemicModel, ModelError, atom, neg, knows, public_announce,
    announce_sequence, public_announce_checked, announce_sequence_checked,
)


class PublicAnnouncementTests(unittest.TestCase):
    def model(self):
        return EpistemicModel(
            frozenset({'0', '1', '2'}),
            {'a': frozenset({frozenset({'0', '1'}), frozenset({'2'})}),
             'b': frozenset({frozenset({'0'}), frozenset({'1', '2'})})},
            {'0': frozenset({'p', 'q'}), '1': frozenset({'p'}), '2': frozenset({'q'})},
        )

    def test_reuses_s5_validation_for_invalid_partitions(self):
        for cells in ([{'0'}], [{'0', '1'}, {'1', '2'}], [{'0', '1', '2', 'unknown'}],
                      [set(), {'0', '1', '2'}]):
            with self.subTest(cells=cells):
                with self.assertRaises(ModelError):
                    EpistemicModel(self.model().worlds, {'a': cells}, self.model().valuation)

    def test_valuation_requires_exact_world_coverage(self):
        m = self.model()
        for valuation in ({'0': frozenset()}, {**m.valuation, 'unknown': frozenset()}):
            with self.assertRaises(ModelError): EpistemicModel(m.worlds, m.partitions, valuation)

    def test_constructor_snapshots_worlds_cells_and_valuation(self):
        worlds = {'w'}; cells = [{'w'}]; props = {'p'}
        m = EpistemicModel(worlds, {'a': cells}, {'w': props})
        worlds.clear(); cells[0].clear(); props.clear()
        self.assertEqual(m.worlds, frozenset({'w'}))
        self.assertEqual(m.agent_class('a', 'w'), frozenset({'w'}))
        self.assertTrue(atom('p')(m, 'w'))
        with self.assertRaises(TypeError): m.valuation['w'] = frozenset()
        with self.assertRaises(TypeError): m.partitions['a'] = frozenset()

    def test_callable_atom_negation_and_nested_knowledge_preserved(self):
        m = self.model(); p = atom('p')
        self.assertTrue(p(m, '0'))
        self.assertTrue(neg(p)(m, '2'))
        self.assertTrue(knows('a', p)(m, '0'))
        self.assertTrue(knows('b', p)(m, '0'))
        self.assertFalse(knows('a', knows('b', p))(m, '0'))
        self.assertTrue(knows('b', knows('a', p))(m, '0'))

    def test_unknown_references_rejected(self):
        m = self.model()
        for evaluate in (lambda: atom('p')(m, 'unknown'),
                         lambda: knows('unknown', atom('p'))(m, '0'),
                         lambda: knows('a', atom('p'))(m, 'unknown')):
            with self.assertRaises(ModelError): evaluate()

    def test_restricts_worlds_partitions_and_valuation_without_mutating_input(self):
        m = self.model(); updated = public_announce(m, atom('p'))
        self.assertEqual(updated.worlds, frozenset({'0', '1'}))
        self.assertEqual(set(updated.valuation), {'0', '1'})
        self.assertEqual(updated.agent_class('b', '1'), frozenset({'1'}))
        self.assertEqual(updated.agent_class('a', '0'), frozenset({'0', '1'}))
        self.assertEqual(updated.valuation['0'], m.valuation['0'])
        self.assertEqual(m.agent_class('b', '1'), frozenset({'1', '2'}))
        self.assertEqual(m.worlds, frozenset({'0', '1', '2'}))
        self.assertFalse(knows('b', atom('p'))(m, '1'))
        self.assertTrue(knows('b', atom('p'))(updated, '1'))

    def test_empty_announcement_result_rejected(self):
        with self.assertRaisesRegex(ModelError, 'eliminates every world'):
            public_announce(self.model(), atom('never_true'))

    def test_sequences_evaluate_formulas_in_current_not_initial_model(self):
        m = self.model()
        updated = announce_sequence(m, [atom('p'), knows('b', atom('p'))])
        # Initially B does not know p at 1; after announcing p, it does.
        self.assertEqual(updated.worlds, frozenset({'0', '1'}))
        reversed_order = announce_sequence(m, [knows('b', atom('p')), atom('p')])
        self.assertEqual(reversed_order.worlds, frozenset({'0'}))

    def test_factual_announcements_commute(self):
        m = self.model()
        self.assertEqual(announce_sequence(m, [atom('p'), atom('q')]),
                         announce_sequence(m, [atom('q'), atom('p')]))

    def test_checked_and_unpointed_operations_remain_distinct(self):
        m = self.model()
        self.assertNotIn('2', public_announce(m, atom('p')).worlds)
        with self.assertRaisesRegex(ModelError, 'false at the actual world'):
            public_announce_checked(m, '2', atom('p'))
        self.assertEqual(public_announce_checked(m, '0', atom('p')), public_announce(m, atom('p')))
        with self.assertRaisesRegex(ModelError, 'unknown actual world'):
            public_announce_checked(m, 'unknown', atom('p'))

    def test_checked_sequence_checks_each_prefix(self):
        m = self.model()
        updated = announce_sequence_checked(m, '1', [atom('p'), knows('b', atom('p'))])
        self.assertIn('1', updated.worlds)
        # q still holds somewhere after the first update, but not at actual world 1.
        with self.assertRaisesRegex(ModelError, 'false at the actual world'):
            announce_sequence_checked(m, '1', [atom('p'), atom('q')])

    def test_empty_sequence_preserves_source_identity_and_checked_reference_validation(self):
        m = self.model()
        self.assertIs(announce_sequence(m, []), m)
        self.assertIs(announce_sequence_checked(m, '0', []), m)
        with self.assertRaisesRegex(ModelError, 'unknown actual world'):
            announce_sequence_checked(m, 'unknown', [])


if __name__ == '__main__':
    unittest.main()
