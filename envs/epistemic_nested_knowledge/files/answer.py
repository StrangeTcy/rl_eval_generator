"""Submit your answer to the nested-knowledge task in task.md.

Edit ONLY this file. Fill in the ANSWER dictionary with your conclusions:

- "truth": a JSON boolean (true/false) - whether the registered proposition
  holds in the supplied model under the nested modal operators and agent
  accessibility relations specified in task.md.
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
