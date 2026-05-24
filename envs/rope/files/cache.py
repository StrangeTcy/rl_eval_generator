"""Small cache object used for chunked RoPE application."""

class PositionCache:
    def __init__(self):
        self.tokens_seen = 0

    def position_offset(self) -> int:
        # BUG: chunked calls should start at the number of tokens already seen.
        return 0

    def append(self, chunk_len: int) -> None:
        # BUG: the cache must advance after each processed chunk.
        self.tokens_seen = self.tokens_seen
