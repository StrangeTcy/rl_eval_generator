# queue-always-at-head

Writes the incoming keys at column 0 and never advances the pointer, so the truncating
slice can no longer drop a tail. `K` slots are then stale after the first batch and the
FIFO semantics the hidden wraparound probe checks are simply gone, while every visible
test stays green because nothing in them inspects the queue.
