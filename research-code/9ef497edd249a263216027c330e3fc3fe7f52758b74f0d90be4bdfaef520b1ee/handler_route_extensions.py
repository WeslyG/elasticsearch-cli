"""Validate pinned literal handler routes omitted by the upstream REST JSON."""

import hashlib
import json
import re
from pathlib import Path

from java_routes import extract_routes, without_comments


def verified_source(record):
    text = record["text"]
    if hashlib.sha256(text.encode()).hexdigest() != record["sha256"]:
        raise ValueError("Handler route source bytes differ")
    if not record["path"].endswith(".java") or "package org.elasticsearch" not in text:
        raise ValueError("Unexpected handler route source")
    return text


def load_route_extensions(version, source_commit, facts_file=None):
    path = Path(facts_file) if facts_file else Path(__file__).with_name("handler_route_facts.json")
    if not path.exists():
        return {}
    raw = path.read_bytes()
    data = json.loads(raw)
    if data.get("kind") != "pinned-handler-routes-absent-from-rest-json-not-runtime-support":
        raise ValueError("Unexpected handler route facts kind")
    release = data["releases"].get(version)
    if release is None:
        return {}
    if release["source_commit"] != source_commit:
        raise ValueError("Handler route source revision differs")
    handlers = {}
    for key, record in release["handlers"].items():
        handlers[key] = extract_routes(verified_source(record))["routes"]
    registrations = {}
    for key, record in release["registrations"].items():
        text = without_comments(verified_source(record))
        match = re.search(r"\bgetRestHandlers\s*\([^)]*\)\s*\{([^{}]*)\}", text)
        if match is None:
            raise ValueError("Registration is not a literal REST handler method")
        registrations[key] = match[1]
    result, seen = {}, set()
    for route in release["routes"]:
        identity = (route["api_id"], route["method"], route["path"])
        if identity in seen:
            raise ValueError("Duplicate handler route extension")
        seen.add(identity)
        handler = release["handlers"][route["handler"]]
        registration = release["registrations"][route["registration"]]
        if not any(
            row["method"] == route["method"] and row["path"] == route["path"]
            for row in handlers[route["handler"]]
        ):
            raise ValueError("Extension is not an exact parsed handler route")
        constructor = Path(handler["path"]).stem
        pattern = (
            r"\s*return\s+Arrays\.asList\(new\s+" + re.escape(constructor) + r"\([^;{}]*\)\);\s*"
        )
        if re.fullmatch(pattern, registrations[route["registration"]]) is None:
            raise ValueError("Extension has no unconditional literal module registration")
        result.setdefault(route["api_id"], []).append(
            {
                "method": route["method"],
                "path": route["path"],
                "handler_source": handler["path"],
                "proof": {
                    "kind": "pinned-handler-extension-not-runtime-support",
                    "facts_file": path.name,
                    "facts_sha256": hashlib.sha256(raw).hexdigest(),
                    "source_commit": source_commit,
                    "handler_sha256": handler["sha256"],
                    "registration_source": registration["path"],
                    "registration_sha256": registration["sha256"],
                },
            }
        )
    return result
