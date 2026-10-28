"""Provider-free, bounded trials for trusted scripted policies and isolated readiness runs."""

from .session import Session


class Trial:
    def __init__(self, configuration, policy, presentation="present 0 1 2"):
        self.controller = Session()
        self.controller.start(configuration)
        self.policy = policy
        self.configuration = configuration
        self.actions = ()
        self.invalid = ()
        self.events = ()
        self.remaining_calls = 12
        self.status = "open"
        if self.controller.game.stage == "present":
            self.controller.game.present(presentation)
            self.actions += (presentation,)

    def run(self):
        game = self.controller.game
        if game.stage == "done":
            self.status = "scored"
            return self.record()
        if self.remaining_calls == 0:
            self.status = "invalid_response_limit_unscored"
            return self.record()
        self.remaining_calls -= 1
        observation = game.view()
        raw = self.policy.act(observation)
        self.events += (("observation", observation), ("response", raw))
        try:
            result = game.step(raw)
        except ValueError as exc:
            self.invalid += ((raw, str(exc)),)
            self.events += (("invalid_action", str(exc)),)
        else:
            self.actions += (raw,)
            self.events += (("transition", result),)
        return self.run()

    def record(self):
        # Controller artifact: never use this as an agent observation.
        return (("schema", "inquiry-trial/1"), ("configuration", self.configuration), ("status", self.status), ("actions", self.actions), ("invalid_responses", self.invalid), ("events", self.events), ("engine_trace", self.controller.game.trace), ("metrics", self.controller.game.result))
