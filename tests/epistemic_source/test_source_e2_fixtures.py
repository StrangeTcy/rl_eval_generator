"""CS006: source E2 fixtures; design and result accepted by the user.

Preserves both Sonnet source fixtures independently of CS005 implementation
checks. Source assertions translated to unittest; additional checks explicit.
"""
import unittest

from public_announcements import EpistemicModel, atom, knows, neg, public_announce


class SourceE2FixtureTests(unittest.TestCase):
    def test_announcement_updates_agent_knowledge_not_just_world_count(self):
        # Original source fixture: A cannot distinguish worlds; B can.
        m = EpistemicModel(
            worlds=frozenset({'w1', 'w2'}),
            partitions={
                'a': frozenset({frozenset({'w1', 'w2'})}),
                'b': frozenset({frozenset({'w1'}), frozenset({'w2'})}),
            },
            valuation={'w1': frozenset({'p'}), 'w2': frozenset()},
        )
        # Original source behavioral assertions, including Boolean identity.
        self.assertIs(knows('a', atom('p'))(m, 'w1'), False)
        announced = public_announce(m, atom('p'))
        self.assertIs(knows('a', atom('p'))(announced, 'w1'), True)

        # Added structural assertions. Stale partition references could produce
        # a wrong answer OR an error, depending on retained valuation data.
        self.assertEqual(announced.worlds, frozenset({'w1'}))
        self.assertEqual(dict(announced.partitions), {
            'a': frozenset({frozenset({'w1'})}),
            'b': frozenset({frozenset({'w1'})}),
        })
        self.assertEqual(dict(announced.valuation), {'w1': frozenset({'p'})})
        self.assertIsNot(announced, m)
        self.assertEqual(m.worlds, frozenset({'w1', 'w2'}))
        self.assertEqual(dict(m.partitions), {
            'a': frozenset({frozenset({'w1', 'w2'})}),
            'b': frozenset({frozenset({'w1'}), frozenset({'w2'})}),
        })
        self.assertEqual(dict(m.valuation), {
            'w1': frozenset({'p'}), 'w2': frozenset(),
        })

    def test_announcement_false_throughout_current_model_is_rejected(self):
        # Original second fixture. p is false here, not logically contradictory.
        m = EpistemicModel(
            worlds=frozenset({'w1'}),
            partitions={'a': frozenset({frozenset({'w1'})})},
            valuation={'w1': frozenset()},
        )
        # Preserve the source's ValueError contract, not just ModelError.
        with self.assertRaises(ValueError):
            public_announce(m, atom('p'))

    def test_logically_contradictory_announcement_is_rejected(self):
        # Additional fixture with both truth values of p represented.
        m = EpistemicModel(
            worlds=frozenset({'w1', 'w2'}),
            partitions={'a': frozenset({frozenset({'w1', 'w2'})})},
            valuation={'w1': frozenset({'p'}), 'w2': frozenset()},
        )
        p = atom('p')
        not_p = neg(p)
        contradiction = lambda model, world: p(model, world) and not_p(model, world)
        self.assertEqual({p(m, w) for w in m.worlds}, {False, True})
        for world in m.worlds:
            self.assertIs(contradiction(m, world), False)
        with self.assertRaises(ValueError):
            public_announce(m, contradiction)


if __name__ == '__main__':
    unittest.main()
