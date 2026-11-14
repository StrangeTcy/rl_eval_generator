def tokenize(text: str) -> list[str]:
    # U+0120 is reserved for encoded spaces and excluded from input text.
    if text.count("Ġ"):
        raise ValueError("Input contains reserved space marker U+0120")
    tokens = []
    for char in text:
        if char == " ":
            tokens.append("Ġ")
        else:
            tokens.append(char)
    return tokens
