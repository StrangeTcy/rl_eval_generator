# Associative Optimizer Composition

Your task is to correct the modular optimizer blocks in `optimizer.py`.

To allow sequential optimizer operations (like composing gradient momentum and scaling steps) to be modular, the composition of these updates must be strictly associative:
$$((A \circ B) \circ C)(p) \equiv (A \circ (B \circ C))(p)$$

The current implementation of the modules in `optimizer.py` runs, but fails this associativity requirement under nested composition. Correct the modules so that their sequential composition is strictly associative and numerically correct across multiple training steps.
