"""Sequential JSON-RPC 2.0 over bounded UTF-8 newline-delimited frames."""

import json
import math
import signal
import threading
from pathlib import Path
from types import FrameType
from typing import BinaryIO, TextIO, TypeGuard

from pydantic import ValidationError

from kctx.domain.json import JsonObject, JsonValue, object_value
from kctx.errors import KctxError

from .operations import Operations
from .schemas import METHODS, Initialize

PROTOCOL_VERSION = "1"
MAX_REQUEST_BYTES = 65536
CAPABILITIES = ("citations", "graph", "knowledge", "authored", "notifications")
MUTATIONS = frozenset(
    {
        "graph.sync",
        "graph.refresh",
        "knowledge.capture",
        "knowledge.propose",
        "knowledge.admit",
        "knowledge.rollback",
        "knowledge.recover",
        "cite.check",
    }
)


def _pairs(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_value: str) -> JsonValue:
    raise ValueError("nonfinite JSON number")


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite JSON number")
    return number


def decode_frame(line: bytes) -> object:
    return json.loads(
        line.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float
    )


def error(
    code: int,
    message: str,
    request_id: JsonValue = None,
    *,
    failure: KctxError | None = None,
    uncertain: bool = False,
) -> JsonObject:
    failure = failure or KctxError("malformed", message)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
            "data": {
                "schema_version": 1,
                "category": failure.category,
                "message": failure.message,
                "diagnostic": object_value(failure.diagnostic.to_wire()),
                "exit_code": None if uncertain else 1,
                "complete": False,
                "generation": None,
                "outcome": "unknown" if uncertain else "rejected",
            },
        },
    }


def _request_record(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _request_id(value: object) -> TypeGuard[str | int | None]:
    return value is None or type(value) in (str, int)


class Engine:
    """Invocation-local protocol state and lazy native resource ownership."""

    def __init__(self, root: Path) -> None:
        self.operations = Operations(root)
        self.initialized = False
        self.stopped = False

    def close(self) -> None:
        self.operations.close()

    def request(self, value: object) -> JsonObject | None:
        if not _request_record(value):
            return error(-32600, "Invalid Request")
        request = value
        request_id = request.get("id")
        if not _request_id(request_id):
            return error(-32600, "Invalid Request")
        method = request.get("method")
        if (
            set(request) - {"jsonrpc", "id", "method", "params"}
            or request.get("jsonrpc") != "2.0"
            or not isinstance(method, str)
        ):
            return error(-32600, "Invalid Request", request_id)
        notification = "id" not in request
        response: JsonObject
        invoked = False
        try:
            schema = METHODS.get(method)
            if schema is None:
                response = error(-32601, "Method not found", request_id)
            elif self.stopped:
                response = error(
                    -32002,
                    "Engine is shut down",
                    request_id,
                    failure=KctxError("conflict", "engine is shut down"),
                )
            elif method != "initialize" and not self.initialized:
                response = error(
                    -32002,
                    "Initialization required",
                    request_id,
                    failure=KctxError(
                        "conflict", "initialize the protocol before invoking methods"
                    ),
                )
            else:
                params = schema.model_validate(request.get("params", {}))
                if isinstance(params, Initialize):
                    if self.initialized:
                        raise KctxError("conflict", "engine is already initialized")
                    if set(params.capabilities) - set(CAPABILITIES):
                        raise KctxError("malformed", "unsupported requested capability")
                    self.initialized = True
                    result: JsonObject = {
                        "protocol_version": PROTOCOL_VERSION,
                        "server": {"name": "kctx"},
                        "capabilities": list(CAPABILITIES),
                        "batch": False,
                        "notifications": True,
                        "max_request_bytes": MAX_REQUEST_BYTES,
                        "trust_boundary": "local operator configuration; citation scan paths restricted to knowledge root; signing and filesystem migration/backup/restore are CLI-only",
                        "methods": {
                            name: object_value(model.model_json_schema())
                            for name, model in METHODS.items()
                        },
                    }
                elif method == "shutdown":
                    self.close()
                    self.stopped = True
                    result = {
                        "exit_code": 0,
                        "complete": True,
                        "generation": None,
                        "payload": {"shutdown": True},
                    }
                else:
                    invoked = True
                    result = self.operations.invoke(method, params)
                response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except ValidationError:
            # Pydantic's rendered errors include raw input values: never emit them.
            response = error(-32602, "Invalid params", request_id)
        except KctxError as exc:
            response = error(
                -32000,
                "Operation failed",
                request_id,
                failure=exc,
                uncertain=invoked and method in MUTATIONS,
            )
        except ValueError:
            response = error(
                -32602,
                "Invalid domain parameters",
                request_id,
                uncertain=invoked and method in MUTATIONS,
            )
        except Exception:
            # Mutation completion cannot be inferred from an IO/unexpected failure.
            response = error(
                -32603,
                "Internal error",
                request_id,
                failure=KctxError(
                    "incomplete",
                    "operation could not complete normally; inspect state before retrying mutations",
                ),
                uncertain=invoked and method in MUTATIONS,
            )
        return None if notification else response


def _emit(output: TextIO, value: JsonObject) -> None:
    output.write(json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n")
    output.flush()


def _cancel(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def serve(root: Path, source: BinaryIO, output: TextIO) -> int:
    """Serve until EOF/shutdown, always closing pinned native children; no ready noise."""
    engine = Engine(root)
    install_signal = threading.current_thread() is threading.main_thread()
    previous = signal.signal(signal.SIGTERM, _cancel) if install_signal else None
    try:
        while not engine.stopped:
            line = source.readline(MAX_REQUEST_BYTES + 1)
            if not line:
                return 0
            if len(line) > MAX_REQUEST_BYTES:
                while line and not line.endswith(b"\n"):
                    line = source.readline(MAX_REQUEST_BYTES + 1)
                _emit(output, error(-32600, "Request frame exceeds 65536 bytes"))
                continue
            try:
                value = decode_frame(line)
            except (ValueError, UnicodeError, RecursionError):
                _emit(output, error(-32700, "Parse error"))
                continue
            response = engine.request(value)
            if response is not None:
                _emit(output, response)
        return 0
    except (KeyboardInterrupt, BrokenPipeError):
        return 130
    except OSError:
        # With no reliably identified pending request, never fabricate a response.
        return 1
    finally:
        try:
            engine.close()
        finally:
            if install_signal:
                signal.signal(signal.SIGTERM, previous)
