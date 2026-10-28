"""Bounded text transport; no providers, credentials, shell, or subprocess access.

Run this transport only in an authorized isolated runner. The trusted process
retains latent state; an external agent receives view() text and submits lines.
"""

import json
import re
import sys

from .diagnostic import Diagnostic
from .strategic import Sender, StrategicSource


class Session:
    def __init__(self, source=None, sink=None):
        self.source = sys.stdin if source is None else source
        self.sink = sys.stdout if sink is None else sink
        self.game = None
        self.remaining_lines = 12

    def start(self, command):
        match = re.fullmatch(r"diagnostic ([0-9]{1,8}) ([0-9]{1,8}) ([1-3]) (balanced|skewed)", command)
        if match is not None:
            seed, world, budget, variant = match.groups()
            self.game = Diagnostic(int(seed), int(world), int(budget), variant)
            return self.game.presenter_view()
        match = re.fullmatch(r"source ([0-9]{1,8}) ([0-9]{1,8}) ([1-3]) (disclosed|blind) (assertion|certificate)", command)
        if match is not None:
            seed, world, budget, visibility, channel = match.groups()
            self.game = StrategicSource(int(seed), int(world), int(budget), visibility, channel)
            return self.game.view()
        raise ValueError("start: diagnostic SEED PRIVATE_WORLD_SEED BUDGET balanced|skewed; or source SEED PRIVATE_WORLD_SEED BUDGET disclosed|blind assertion|certificate")

    def run(self):
        if self.game is None:
            # Initialization is a controller-only input, not part of agent history.
            command = self.source.readline(512)
            if command == "":
                return
            try:
                self.sink.write(self.start(command.rstrip("\r\n")) + "\n")
            except ValueError as exc:
                self.sink.write(f"configuration_error: {exc}\n")
                return
        if self.remaining_lines == 0:
            self.sink.write("protocol_error: response limit reached; unscored\n")
            return
        self.sink.flush()
        raw = self.source.readline(512)
        if raw == "":
            self.sink.write("incomplete_episode: unscored\n")
            return
        self.remaining_lines -= 1
        raw = raw.rstrip("\r\n")
        try:
            if self.game.stage == "present":
                self.game.present(raw)
            else:
                self.game.step(raw)
        except ValueError as exc:
            self.sink.write(f"invalid_action: {exc}\n")
        if self.game.stage == "done":
            self.sink.write(json.dumps(("episode_result", self.game.result, ("actions_and_observations", self.game.trace))) + "\n")
            self.sink.flush()
            return
        self.sink.write(self.game.view() + "\n")
        return self.run()


class Replay:
    """Reconstruct from controller configuration and action strings, not claimed scores."""

    def __init__(self, configuration):
        self.session = Session()
        self.session.start(configuration)
        self.actions = 0

    def consume(self, transcript):
        if transcript == ():
            if self.session.game.stage != "done":
                raise ValueError("incomplete replay")
            return (self.session.game.trace, self.session.game.result)
        if self.actions >= 6:
            raise ValueError("too many replay actions")
        raw = transcript[0]
        if self.session.game.stage == "present":
            self.session.game.present(raw)
        else:
            self.session.game.step(raw)
        self.actions += 1
        return self.consume(transcript[1:])


class SenderSession:
    """One-action deployment port; quality is this agent's permitted private information."""

    def __init__(self, quality, gain, fine, rate, channel):
        self.game = Sender(quality, gain, fine, rate, channel)

    def run(self, source, sink):
        sink.write(self.game.view())
        sink.flush()
        raw = source.readline(512).rstrip("\r\n")
        try:
            sink.write(json.dumps(("sender_result", self.game.grade(raw))) + "\n")
        except ValueError as exc:
            sink.write(f"invalid_action: {exc}; unscored\n")

