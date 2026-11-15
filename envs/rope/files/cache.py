"""Small cache object used for chunked RoPE application."""

class PositionCache:
    def __init__(self):
        self.tokens_seen = 0

    def position_offset(self) -> int:
        %%CACHE_OFFSET_VAL%%

    def append(self, chunk_len: int) -> None:
        %%CACHE_APPEND_STEP%%
