# Optional offline trajectory judge

`Dockerfile.trajectory_judge` builds a small standard-library-only image for
scoring private case/answer JSONL records. It never contacts a provider and
accepts no API key.

```sh
docker build -f docker/Dockerfile.trajectory_judge -t trajectory-judge:local .
docker run --rm --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 128 --memory 256m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -v "$PWD/cases.jsonl:/input/cases.jsonl:ro" \
  -v "$PWD/answers.jsonl:/input/answers.jsonl:ro" \
  -v "$PWD/judge-output:/output" \
  trajectory-judge:local \
  --cases /input/cases.jsonl --answers /input/answers.jsonl \
  --out /output/results.jsonl
```

The generated result distinguishes exact correctness, answer-format validity,
and a stale-witness match. A stale-witness match is a diagnostic failure
category, never partial credit or an alternate score. The host runner can invoke
this image with `arena.py trajectory --judge docker`; `--judge both` compares
its per-case results with host scoring and fails on disagreement.
