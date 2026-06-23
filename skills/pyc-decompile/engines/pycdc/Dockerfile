FROM ubuntu:latest
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates cmake build-essential git \
    && git clone https://github.com/zrax/pycdc.git \
    && cd pycdc \
    && cmake . \
    && make -j"$(nproc)" \
    && make install \
    && cd / \
    && rm -rf pycdc \
    && apt-get remove -y cmake build-essential git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
COPY decompile.sh /decompile.sh
RUN chmod +x /decompile.sh
ENTRYPOINT ["/decompile.sh"]
