"""Direct CS002 fixtures; no model calls or target-repository integration."""
import unittest
from epistemic_relations import World, EpistemicModel, S5EpistemicModel, ModelError


class EpistemicRelationTests(unittest.TestCase):
    def test_original_single_world_atomic_knowledge(self):
        world = World('m_u', {'a': 'muddy', 'b': 'clean'})
        model = EpistemicModel([world], ['B'])
        model.add_relation('B', 'm_u', 'm_u')
        self.assertTrue(model.knows('B', 'm_u', lambda w: w.properties['a'] == 'muddy'))
        self.assertFalse(model.knows('B', 'm_u', lambda w: w.properties['a'] == 'clean'))

    def test_original_atomic_knowledge_in_separate_s5_interface(self):
        model = S5EpistemicModel([World('m_u', {'a': 'muddy'})], {'B': [{'m_u'}]})
        self.assertTrue(model.knows('B', 'm_u', lambda w: w.properties['a'] == 'muddy'))

    def test_worlds_indexed_by_id_and_duplicate_ids_rejected(self):
        world = World('w', {'p': True})
        self.assertIs(EpistemicModel([world], ['a']).worlds['w'], world)
        for make in (lambda ws: EpistemicModel(ws, ['a']),
                     lambda ws: S5EpistemicModel(ws, {'a': [{'w'}]})):
            with self.assertRaises(ModelError): make([world, World('w', {'p': False})])

    def test_unknown_agents_worlds_and_dangling_edges_rejected(self):
        model = EpistemicModel([World('w', {})], ['a'])
        for args in [('unknown', 'w', 'w'), ('a', 'missing', 'w'), ('a', 'w', 'missing')]:
            with self.assertRaises(ModelError): model.add_relation(*args)
        for agent, world in [('missing', 'w'), ('a', 'missing')]:
            with self.assertRaises(ModelError): model.knows(agent, world, lambda w: True)

    def test_general_explicit_empty_accessibility_is_vacuously_true(self):
        model = EpistemicModel([World('w', {'p': False})], ['a'])
        self.assertEqual(model.accessible('a', 'w'), frozenset())
        self.assertTrue(model.knows('a', 'w', lambda w: w.properties['p']))
        self.assertTrue(model.knows('a', 'w', lambda w: not w.properties['p']))
        # Adding an actual accessible world distinguishes vacuity from its valuation.
        model.add_relation('a', 'w', 'w')
        self.assertFalse(model.knows('a', 'w', lambda w: w.properties['p']))

    def test_general_relations_not_silently_closed_to_s5(self):
        model = EpistemicModel([World(w, {}) for w in '012'], ['a'])
        model.add_relation('a', '0', '1')
        model.add_relation('a', '1', '2')
        self.assertEqual(model.accessible('a', '0'), frozenset({'1'}))
        self.assertEqual(model.accessible('a', '1'), frozenset({'2'}))
        self.assertEqual(model.accessible('a', '2'), frozenset())

    def test_s5_partition_rejects_empty_overlap_missing_and_dangling(self):
        worlds = [World(w, {}) for w in '01']
        for cells in ([set(), {'0', '1'}], [{'0'}, {'0', '1'}], [{'0'}], [{'0', '1', 'x'}], []):
            with self.assertRaises(ModelError): S5EpistemicModel(worlds, {'a': cells})

    def test_s5_reflexivity_symmetry_transitivity_and_unknown_references(self):
        model = S5EpistemicModel([World(w, {}) for w in '012'], {'a': [{'0', '1'}, {'2'}]})
        for w in model.worlds:
            self.assertIn(w, model.accessible('a', w))
            for v in model.accessible('a', w):
                self.assertIn(w, model.accessible('a', v))
                self.assertEqual(model.accessible('a', w), model.accessible('a', v))
        for agent, world in [('missing', '0'), ('a', 'missing')]:
            with self.assertRaises(ModelError): model.knows(agent, world, lambda w: True)

    def test_genuine_nested_knowledge_differs_from_atomic_and_inner_knowledge(self):
        worlds = [World('0', {'p': True}), World('1', {'p': True}), World('2', {'p': False})]
        partitions = {'a': [{'0', '1'}, {'2'}], 'b': [{'0'}, {'1', '2'}]}
        s5 = S5EpistemicModel(worlds, partitions)
        general = EpistemicModel(worlds, partitions.keys())
        for agent, cells in partitions.items():
            for cell in cells:
                for source in cell:
                    for target in cell:
                        general.add_relation(agent, source, target)
        p = lambda w: w.properties['p']
        for model in (general, s5):
            self.assertTrue(model.knows('a', '0', p))
            self.assertTrue(model.knows('b', '0', p))
            # At 1, B also considers 2, where p is false. Thus A does not know B knows p.
            self.assertFalse(model.knows('a', '0', lambda w: model.knows('b', w.id, p)))
            self.assertTrue(model.knows('b', '0', lambda w: model.knows('a', w.id, p)))

    def test_constructor_inputs_cannot_mutate_registered_top_level_structure(self):
        props = {'p': True}; world = World('w', props); props['p'] = False
        self.assertTrue(world.properties['p'])
        cells = [{'w'}]; model = S5EpistemicModel([world], {'a': cells}); cells[0].clear()
        self.assertEqual(model.accessible('a', 'w'), frozenset({'w'}))


if __name__ == '__main__':
    unittest.main()
