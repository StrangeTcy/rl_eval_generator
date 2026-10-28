"""Bounded controller-owned transport and trusted scripted-policy trials."""

import json
import re
import sys

from .game import ProgramDiscovery


class Session:
    def __init__(self, source=None, sink=None):
        self.source = sys.stdin if source is None else source
        self.sink = sys.stdout if sink is None else sink
        self.game, self.remaining_lines = None, 24

    def start(self, configuration):
        match = re.fullmatch(r"recursive ([0-9]{1,8}) ([0-9]{1,8}) ([2-5]) ([1-3]) ([23]) ([0-9]) (chain|balanced) (distinct|repeated) ([0-2]) (7|11)", configuration)
        if match is None:
            raise ValueError("configuration: recursive SEMANTIC_SEED PRIVATE_RULE_SEED DEPTH OPERATORS WIDTH BUDGET SHAPE SHARING DEMONSTRATIONS MODULUS")
        self.game = ProgramDiscovery(*match.groups())
        return self.game.view()

    def run(self):
        if self.game is None:
            configuration = self.source.readline(512)
            if configuration == "":
                return
            try:
                self.sink.write(self.start(configuration.rstrip("\r\n")) + "\n")
            except ValueError as exc:
                self.sink.write(f"configuration_error: {exc}\n")
                return
        if self.remaining_lines == 0:
            self.sink.write("response_limit: unscored\n")
            self.sink.flush()
            return
        self.sink.flush()
        raw = self.source.readline(512)
        if raw == "":
            self.sink.write("incomplete_episode: unscored\n")
            self.sink.flush()
            return
        self.remaining_lines -= 1
        try:
            self.game.step(raw.rstrip("\r\n"))
        except ValueError as exc:
            self.sink.write(f"invalid_action: {exc}\n")
        if self.game.stage == "done":
            self.sink.write(json.dumps(("recursive_result", self.game.result, ("actions", self.game.actions), ("observations", self.game.observations))) + "\n")
            self.sink.flush()
            return
        self.sink.write(self.game.view() + "\n")
        return self.run()


class Replay:
    def __init__(self, configuration):
        self.controller = Session()
        self.controller.start(configuration)
        self.count = 0

    def consume(self, actions):
        if actions == ():
            if self.controller.game.stage != "done":
                raise ValueError("incomplete replay")
            return (self.controller.game.observations, self.controller.game.result)
        if self.count >= 10:
            raise ValueError("replay exceeds query and answer bound")
        self.controller.game.step(actions[0])
        self.count += 1
        return self.consume(actions[1:])


class Trial:
    def __init__(self, configuration, policy):
        self.controller = Session()
        self.controller.start(configuration)
        self.configuration, self.policy = configuration, policy
        self.status, self.events = "open", ()
        self.remaining_calls = 24

    def run(self):
        game = self.controller.game
        if game.stage == "done":
            self.status = "scored"
            return self.record()
        if self.remaining_calls == 0:
            self.status = "response_limit_unscored"
            return self.record()
        self.remaining_calls -= 1
        observation = game.view()
        raw = self.policy.act(observation)
        self.events += (("observation", observation), ("response", raw))
        try:
            transition = game.step(raw)
        except ValueError as exc:
            self.events += (("invalid_action", str(exc)),)
        else:
            self.events += (("transition", transition),)
        return self.run()

    def record(self):
        return (("schema", "recursive-program-trial/1"), ("configuration", self.configuration), ("status", self.status), ("events", self.events), ("actions", self.controller.game.actions), ("metrics", self.controller.game.result))
