# Pinned proof environment for the kctx calculus (dev/CI only — never shipped).
# Built from elan with the exact toolchain pin; no host Lean required.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates git python3 build-essential && \
    rm -rf /var/lib/apt/lists/*

# elan with exactly the pinned toolchain (leanprover/lean4:v4.21.0).
ENV ELAN_HOME=/opt/elan
RUN curl -sSfL https://elan.lean-lang.org/elan-init.sh | sh -s -- -y \
      --default-toolchain leanprover/lean4:v4.21.0 --no-modify-path && \
    /opt/elan/bin/lean --version

ENV PATH="/opt/elan/bin:${PATH}"
WORKDIR /work
COPY . /work/kctx
WORKDIR /work/kctx/formal

# Prebuild once so the image is warm; CI re-runs the same pinned build.
RUN lake build && lake build kctxref
ENTRYPOINT ["/bin/bash"]
