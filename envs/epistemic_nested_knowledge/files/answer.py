"""Submit your answer to the sequential public-announcement task in task.md.

Edit ONLY this file. Fill in the ANSWER dictionary with your conclusions:

- "truth": a JSON boolean (true/false) - whether the registered proposition
  holds in the FINAL restricted model, after every announcement in task.md
  has been applied in order.
- "justification": a short explanation of your reasoning (max 600 chars).

Constraints (enforced by the judge, no code execution):
- This file must contain ONLY one assignment: ANSWER = { ... } with a literal
  dict (no imports, function calls, comprehensions, or extra statements).
- Keep ANSWER JSON-serializable (plain booleans and strings).
- The judge parses ANSWER as data with ast.literal_eval, with size limits.
"""

ANSWER = {
    "truth": None,
    "justification": None,
}
