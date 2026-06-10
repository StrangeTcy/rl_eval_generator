class StateMonad:
    def __init__(self, run_fn):
        # run_fn: state -> (val, state)
        self.run_fn = run_fn

    @classmethod
    def unit(cls, val):
        return cls(lambda state: (val, state))

    def bind(self, f):
        def new_run(state):
            val, next_state = self.run_fn(state)
            return f(val).run_fn(next_state)
        return StateMonad(new_run)
