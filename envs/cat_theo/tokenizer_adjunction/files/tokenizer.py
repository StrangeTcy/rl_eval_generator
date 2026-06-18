def tokenize(text: str) -> list[str]:
    # Simple subword/character tokenizer replacing space with Ġ (GPT style)
    tokens = []
    for char in text:
        if char == " ":
            tokens.append("Ġ")
        else:
            tokens.append(char)
    return tokens
