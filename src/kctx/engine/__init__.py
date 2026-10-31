"""Unified trusted-local engine protocol and managed stdio entrypoint."""

from .protocol import MAX_REQUEST_BYTES, PROTOCOL_VERSION, Engine, serve

__all__ = ["MAX_REQUEST_BYTES", "PROTOCOL_VERSION", "Engine", "serve"]
