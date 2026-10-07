"""CS012 E5 source fixtures for accepted fragmented-observation semantics.

Source: mission-02/code snippets critique.md, Python block 12 (lines 608-634).
"""

import unittest

from fragmented_observation import information_set, joint_information
from public_announcements import EpistemicModel, ModelError


class FragmentedObservationSourceFixtures(unittest.TestCase):
    def test_fragmented_observation_is_not_reducible_to_one_agent(self):
        model = EpistemicModel(
            worlds=frozenset({"w1", "w2", "w3", "w4"}),
            partitions={
                "a": frozenset({frozenset({"w1", "w2"}), frozenset({"w3", "w4"})}),
                "b": frozenset({frozenset({"w1", "w3"}), frozenset({"w2", "w4"})}),
            },
            valuation={world: frozenset() for world in ("w1", "w2", "w3", "w4")},
        )
        self.assertEqual(information_set(model, "a", "w1"), frozenset({"w1", "w2"}))
        self.assertEqual(information_set(model, "b", "w1"), frozenset({"w1", "w3"}))
        self.assertEqual(joint_information(model, ["a", "b"], "w1"), frozenset({"w1"}))

    def test_invalid_partition_is_rejected_at_model_construction(self):
        worlds = frozenset({"w1", "w2"})
        overlapping_partition = frozenset({frozenset({"w1", "w2"}), frozenset({"w2"})})
        # CS005's S5 model validates partitions eagerly; the source fixture's
        # assertion around information_set was outside the constructor call.
        with self.assertRaisesRegex(ModelError, "overlapping partition cells"):
            EpistemicModel(
                worlds=worlds,
                partitions={"a": overlapping_partition},
                valuation={"w1": frozenset(), "w2": frozenset()},
            )


if __name__ == "__main__":
    unittest.main()
