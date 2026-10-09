# tau-rescaled-at-logits

Scales the logits by `1/tau` at the end of `forward`, so `test_temperature_not_cancelled`
sees a tau-dependent magnitude and passes. The cancellation inside `normalize(q / tau)`
is untouched: the embeddings are still tau-invariant, which is the behavior the hidden
probe measures and the reason this is a shortcut rather than a fix.
