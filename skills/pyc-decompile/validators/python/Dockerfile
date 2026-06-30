FROM debian:bullseye-slim

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV PYENV_ROOT=/opt/pyenv
ENV PATH="${PYENV_ROOT}/bin:${PYENV_ROOT}/shims:${PATH}"
ARG PYTHON_VERSIONS="2.7.18 3.8.20 3.11.9 3.12.8 3.14.0"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      make \
      build-essential \
      libssl-dev \
      zlib1g-dev \
      libbz2-dev \
      libreadline-dev \
      libsqlite3-dev \
      wget \
      llvm \
      libncursesw5-dev \
      xz-utils \
      tk-dev \
      libxml2-dev \
      libxmlsec1-dev \
      libffi-dev \
      liblzma-dev \
    && git clone --depth 1 https://github.com/pyenv/pyenv.git "$PYENV_ROOT" \
    && for version in $PYTHON_VERSIONS; do \
      if pyenv install -s "$version"; then \
        echo "installed Python $version"; \
      else \
        echo "warning: failed to install Python $version; validation will mark it unavailable" >&2; \
      fi; \
    done \
    && rm -rf /tmp/* /var/lib/apt/lists/*

COPY validate.sh /validate.sh
RUN chmod +x /validate.sh

ENTRYPOINT ["/validate.sh"]
