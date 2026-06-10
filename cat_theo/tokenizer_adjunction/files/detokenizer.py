from tokenizer import tokenize

class %%MODEL_CLASS%%:
    def detokenize(self, tokens: list[str]) -> str:
        # BUG: Naive join that fails to restore the special space character "Ġ" back to " ".
        return "".join(tokens)
