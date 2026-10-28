# Nested worker schedules

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Input

`solve` receives one job:

- `modulus`: positive integer. All values are taken modulo this.
- `input`: integer given to the root worker.
- `lock_count`: how many mutex tokens exist. A `lock` op fails if they are all held.
- `root`: name of the root worker.
- `workers`: mapping from worker name to
  `{"parent": name|null, "child": name|null, "program": [op, ...]}`.

Ops, in program order for that worker:

- `spawn`: create the child and copy this worker's current input to the child.
  The child may not run `compute` before it has an input.
- `lock` / `unlock`: take or release one mutex token. A worker may hold at most
  one. Unlocking without a lock is illegal. The trace must finish with no locks held.
- `compute`: leaf (no child) sets its value to `(input + 1) mod modulus`.
  A worker with a child sets its value to `(input + last_received) mod modulus`
  and needs a completed `recv` first.
- `send:parent` / `send:child`: enqueue this worker's value (or input, if it
  has not computed) for that neighbour.
- `recv:parent` / `recv:child`: dequeue a message from that neighbour. Fails if
  the mailbox is empty. The payload becomes `last_received`, and also the input
  if the worker had none.

A worker may only perform the next op in its program. Messages are FIFO per
(sender, receiver) pair.

## Output

```python
{"status": "sat", "trace": [{"agent": name, "op": op}, ...], "result": int}
{"status": "unsat"}
```

A sat trace must run every worker's program to completion. `result` must equal
the root worker's value after the trace (or its last received payload if it
never computed). A crash, timeout, or parse failure is not evidence that no
schedule exists. `solve` must be deterministic.

## What "correct" means

Each worker's program can look locally runnable while no global interleaving
exists: a mutex and a wait-for-message cycle can deadlock even though every
mailbox type and every lock acquisition is legal in isolation. Returning a
number without a legal trace is not a solution.

## Visible checks

```bash
python visible_tests.py
```

## Worker rules and endpoint presentations

A worker may supply `rule = [a,b,c]`. A leaf compute produces
(a*input+b) modulo modulus. A worker with a child produces
(a*input+b+c*last_received) modulo modulus. Without rule, the original
leaf input+1 and parent input+last_received rules apply.

Send/receive endpoints may be the role parent or child, or that endpoint's
explicit worker identifier. These are equivalent presentations of the same
communication. A non-root worker cannot execute any instruction until its
parent has spawned it. Lock capacity is a semantic parameter: an otherwise
identical job can deadlock with one permit and complete with two.
