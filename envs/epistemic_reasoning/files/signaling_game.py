"""Exact finite signaling games and pure PBE-assessment enumeration (E8).

On-path beliefs use the accepted strict, full-policy Bayesian updater. Off-path
beliefs are explicit game inputs; this module does not select a refinement or
claim that PBE is the only relevant solution concept.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from types import MappingProxyType
from typing import Any

from event_bayes import FiniteDist, SpecError, exact_fraction
from supplied_policy import StrictSuppliedPolicyInstance, bayes_update

Type = str
Message = str
ReceiverAction = str
Dist = Mapping[Type, Fraction]

MAX_PURE_PBE_ASSESSMENTS = 20_000


def _labels(values: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or not values:
        raise SpecError(f"{label} must be a nonempty sequence")
    copied = tuple(values)
    if any(type(value) is not str or not value for value in copied):
        raise SpecError(f"{label} must contain nonempty string IDs")
    if len(set(copied)) != len(copied):
        raise SpecError(f"{label} IDs must be unique")
    return copied


def _candidate_assessment_count(
    types: tuple[Type, ...], messages: tuple[Message, ...], actions: tuple[ReceiverAction, ...]
) -> int:
    return len(messages) ** len(types) * len(actions) ** len(messages)


def _validate_strategy(
    strategy: object, *, labels: tuple[str, ...], choices: tuple[str, ...], name: str
) -> dict[str, str]:
    if not isinstance(strategy, Mapping) or set(strategy) != set(labels):
        raise SpecError(f"{name} must define exactly the declared labels")
    copied = dict(strategy)
    if any(type(value) is not str or value not in choices for value in copied.values()):
        raise SpecError(f"{name} contains an undeclared choice")
    return {label: copied[label] for label in labels}


@dataclass(frozen=True)
class SignalingGame:
    """A finite signaling game with exact prior/payoffs and explicit off-path beliefs.

    `off_path_beliefs` supplies one normalized distribution for every message;
    entries are used only when that message has zero probability under the prior
    and sender strategy. Utility callbacks are deterministic and exact-valued.
    """

    types: tuple[Type, ...]
    prior: Dist
    messages: tuple[Message, ...]
    receiver_actions: tuple[ReceiverAction, ...]
    sender_utility: Callable[[Type, Message, ReceiverAction], Any]
    receiver_utility: Callable[[Type, Message, ReceiverAction], Any]
    off_path_beliefs: Mapping[Message, Dist]

    def __post_init__(self) -> None:
        types = _labels(self.types, label="types")
        messages = _labels(self.messages, label="messages")
        receiver_actions = _labels(self.receiver_actions, label="receiver_actions")

        candidate_count = _candidate_assessment_count(types, messages, receiver_actions)
        if candidate_count > MAX_PURE_PBE_ASSESSMENTS:
            raise SpecError(
                f"joint pure sender/receiver assessment candidate count {candidate_count} "
                f"exceeds cap {MAX_PURE_PBE_ASSESSMENTS}"
            )

        if not isinstance(self.prior, Mapping) or set(self.prior) != set(types):
            raise SpecError("prior must define exactly the declared types")
        prior = FiniteDist(self.prior).mass
        if any(probability == 0 for probability in prior.values()):
            raise SpecError("every declared type must have positive prior mass")

        if not isinstance(self.off_path_beliefs, Mapping) or set(self.off_path_beliefs) != set(
            messages
        ):
            raise SpecError("off_path_beliefs must define exactly every message")
        off_path_beliefs = {}
        for message in messages:
            raw_belief = self.off_path_beliefs[message]
            if not isinstance(raw_belief, Mapping) or set(raw_belief) != set(types):
                raise SpecError(f"off_path_beliefs[{message}] must define exactly every type")
            off_path_beliefs[message] = FiniteDist(raw_belief).mass

        if not callable(self.sender_utility) or not callable(self.receiver_utility):
            raise SpecError("sender_utility and receiver_utility must be callable")
        raw_sender_utility = self.sender_utility
        raw_receiver_utility = self.receiver_utility

        def checked_sender_utility(
            player_type: Type, message: Message, action: ReceiverAction
        ) -> Fraction:
            if (
                player_type not in types
                or message not in messages
                or action not in receiver_actions
            ):
                raise SpecError("sender utility called with an undeclared type, message, or action")
            return exact_fraction(raw_sender_utility(player_type, message, action))

        def checked_receiver_utility(
            player_type: Type, message: Message, action: ReceiverAction
        ) -> Fraction:
            if (
                player_type not in types
                or message not in messages
                or action not in receiver_actions
            ):
                raise SpecError(
                    "receiver utility called with an undeclared type, message, or action"
                )
            return exact_fraction(raw_receiver_utility(player_type, message, action))

        object.__setattr__(self, "types", types)
        object.__setattr__(self, "messages", messages)
        object.__setattr__(self, "receiver_actions", receiver_actions)
        object.__setattr__(self, "prior", prior)
        object.__setattr__(self, "off_path_beliefs", MappingProxyType(off_path_beliefs))
        object.__setattr__(self, "sender_utility", checked_sender_utility)
        object.__setattr__(self, "receiver_utility", checked_receiver_utility)


@dataclass(frozen=True)
class PBEAssessment:
    """One pure-strategy PBE assessment: sender, receiver, and beliefs."""

    sender_strategy: Mapping[Type, Message]
    receiver_strategy: Mapping[Message, ReceiverAction]
    beliefs: Mapping[Message, Dist]

    def __post_init__(self) -> None:
        if not isinstance(self.sender_strategy, Mapping) or not self.sender_strategy:
            raise SpecError("sender_strategy must be a nonempty mapping")
        if not isinstance(self.receiver_strategy, Mapping) or not self.receiver_strategy:
            raise SpecError("receiver_strategy must be a nonempty mapping")
        if not isinstance(self.beliefs, Mapping) or set(self.beliefs) != set(
            self.receiver_strategy
        ):
            raise SpecError("beliefs must define exactly every receiver information set")

        sender_strategy = dict(self.sender_strategy)
        receiver_strategy = dict(self.receiver_strategy)
        if any(
            type(label) is not str or not label or type(choice) is not str or not choice
            for mapping in (sender_strategy, receiver_strategy)
            for label, choice in mapping.items()
        ):
            raise SpecError("assessment strategies must contain nonempty string IDs")
        beliefs = {}
        for message, raw_belief in self.beliefs.items():
            if type(message) is not str or not message or not isinstance(raw_belief, Mapping):
                raise SpecError("assessment beliefs must map messages to distributions")
            beliefs[message] = FiniteDist(raw_belief).mass

        object.__setattr__(self, "sender_strategy", MappingProxyType(sender_strategy))
        object.__setattr__(self, "receiver_strategy", MappingProxyType(receiver_strategy))
        object.__setattr__(self, "beliefs", MappingProxyType(beliefs))


def _sender_strategy(game: SignalingGame, strategy: object) -> dict[Type, Message]:
    return _validate_strategy(
        strategy,
        labels=game.types,
        choices=game.messages,
        name="sender_strategy",
    )


def _receiver_strategy(game: SignalingGame, strategy: object) -> dict[Message, ReceiverAction]:
    return _validate_strategy(
        strategy,
        labels=game.messages,
        choices=game.receiver_actions,
        name="receiver_strategy",
    )


def _require_game(game: object) -> SignalingGame:
    if not isinstance(game, SignalingGame):
        raise SpecError("game must be a SignalingGame")
    return game


def receiver_belief(game: SignalingGame, sender_strategy: object, message: Message) -> Dist:
    """Return the exact on-path posterior or the declared off-path belief.

    The sender policy is represented as complete normalized one-hot rows over
    the full message alphabet, preserving the strict supplied-policy contract.
    Zero-evidence messages use their explicit belief rather than Bayes updating.
    """
    game = _require_game(game)
    if type(message) is not str or message not in game.messages:
        raise SpecError("belief requested for an undeclared message")
    sender = _sender_strategy(game, sender_strategy)
    policy = {
        player_type: {
            observed_message: Fraction(int(sender[player_type] == observed_message))
            for observed_message in game.messages
        }
        for player_type in game.types
    }
    instance = StrictSuppliedPolicyInstance(
        prior=game.prior,
        policy=policy,
        realized_observation=message,
        observations=game.messages,
    )
    evidence = sum(
        game.prior[player_type] * policy[player_type][message] for player_type in game.types
    )
    if evidence == 0:
        return game.off_path_beliefs[message]
    posterior = bayes_update(instance)
    return MappingProxyType(dict(posterior))


def receiver_best_response(
    game: SignalingGame, belief: object, message: Message
) -> tuple[ReceiverAction, ...]:
    """Return every exact best-response action at this message, in declared order."""
    game = _require_game(game)
    if type(message) is not str or message not in game.messages:
        raise SpecError("best response requested for an undeclared message")
    if not isinstance(belief, Mapping) or set(belief) != set(game.types):
        raise SpecError("belief must define exactly the declared types")
    normalized_belief = FiniteDist(belief).mass
    utilities = {
        action: sum(
            (
                normalized_belief[player_type] * game.receiver_utility(player_type, message, action)
                for player_type in game.types
            ),
            Fraction(0),
        )
        for action in game.receiver_actions
    }
    best_value = max(utilities.values())
    return tuple(action for action in game.receiver_actions if utilities[action] == best_value)


def _assessment_is_pbe(
    game: SignalingGame,
    sender_strategy: Mapping[Type, Message],
    receiver_strategy: Mapping[Message, ReceiverAction],
    beliefs: Mapping[Message, Dist],
) -> bool:
    for message in game.messages:
        if receiver_strategy[message] not in receiver_best_response(
            game, beliefs[message], message
        ):
            return False

    for player_type in game.types:
        chosen_message = sender_strategy[player_type]
        chosen_utility = game.sender_utility(
            player_type, chosen_message, receiver_strategy[chosen_message]
        )
        for deviation_message in game.messages:
            deviation_utility = game.sender_utility(
                player_type,
                deviation_message,
                receiver_strategy[deviation_message],
            )
            if deviation_utility > chosen_utility:
                return False
    return True


def is_perfect_bayesian_equilibrium(
    game: SignalingGame, sender_strategy: object, receiver_strategy: object
) -> bool:
    """Check sequential rationality and consistency for a pure assessment."""
    game = _require_game(game)
    sender = _sender_strategy(game, sender_strategy)
    receiver = _receiver_strategy(game, receiver_strategy)
    beliefs = {message: receiver_belief(game, sender, message) for message in game.messages}
    return _assessment_is_pbe(game, sender, receiver, beliefs)


def enumerate_pbe(game: SignalingGame) -> list[PBEAssessment]:
    """Enumerate the complete pure-strategy PBE-assessment set for this game.

    Mixed strategies are outside this bounded enumerator. The caller-provided
    off-path beliefs are part of the game input; on-path beliefs are derived by
    exact Bayes updating from the sender strategy.
    """
    if not isinstance(game, SignalingGame):
        raise SpecError("game must be a SignalingGame")
    candidate_count = _candidate_assessment_count(game.types, game.messages, game.receiver_actions)
    if candidate_count > MAX_PURE_PBE_ASSESSMENTS:
        raise SpecError(
            f"joint pure sender/receiver assessment candidate count {candidate_count} "
            f"exceeds cap {MAX_PURE_PBE_ASSESSMENTS}"
        )

    assessments = []
    for sent_messages in product(game.messages, repeat=len(game.types)):
        sender = dict(zip(game.types, sent_messages, strict=True))
        beliefs = {message: receiver_belief(game, sender, message) for message in game.messages}
        best_responses = tuple(
            receiver_best_response(game, beliefs[message], message) for message in game.messages
        )
        for response_actions in product(*best_responses):
            receiver = dict(zip(game.messages, response_actions, strict=True))
            if _assessment_is_pbe(game, sender, receiver, beliefs):
                assessments.append(PBEAssessment(sender, receiver, beliefs))
    return assessments


__all__ = [
    "MAX_PURE_PBE_ASSESSMENTS",
    "PBEAssessment",
    "SignalingGame",
    "enumerate_pbe",
    "is_perfect_bayesian_equilibrium",
    "receiver_best_response",
    "receiver_belief",
]
