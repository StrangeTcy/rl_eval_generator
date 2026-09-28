FROM python:3.11-slim

RUN pip install --no-cache-dir \
        torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir pillow pytest \
    && apt-get update \
    && apt-get install -y --no-install-recommends diffutils \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 agent

COPY workspace/ /originals/
COPY tools/ /tools/
COPY agent_entrypoint.sh /agent_entrypoint.sh

RUN chmod -R a+rX /originals /tools /agent_entrypoint.sh \
    && chmod +x /tools/submit.py /agent_entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["/agent_entrypoint.sh"]
