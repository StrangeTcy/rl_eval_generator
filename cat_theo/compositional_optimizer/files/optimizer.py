import torch

class OptimizerModule:
    # BUG: Class-level state dictionary.
    # This causes all composed instances of OptimizerModule to collide and share the same buffers!
    state = {}

    def __init__(self):
        pass

class MomentumStep(OptimizerModule):
    def __init__(self, beta=0.9):
        super().__init__()
        self.beta = beta

    def update(self, p: torch.Tensor, grad: torch.Tensor) -> torch.Tensor:
        # State tracking keyed by parameter ID
        param_id = id(p)
        if param_id not in self.state:
            self.state[param_id] = torch.zeros_like(grad)
        
        v = self.state[param_id]
        v.mul_(self.beta).add_(grad, alpha=1.0 - self.beta)
        return v
