# Nagini/Viper verification image (handover §5.2 upgrade path).
# JVM + Viper + Nagini live ONLY here; the host needs nothing but docker.
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      default-jre-headless git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Nagini pulls its Viper backend on demand; pin the pip package.
RUN pip install --no-cache-dir "nagini==0.40.1"

WORKDIR /work/kctx
