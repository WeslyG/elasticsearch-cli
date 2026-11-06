"""Strict, deliberately incomplete extraction of Java REST route strings."""

import json
import re
from collections import Counter

START = re.compile(
    r"(?:new\s+(?:RestHandler\.)?(?:Route(?:\.Builder)?|DeprecatedRoute|ReplacedRoute)|"
    r"(?:RestHandler\.)?Route\.builder|"
    r"register(?:Handler|AsDeprecatedHandler|WithDeprecatedHandler))"
    r"\(\s*(?:(?:RestRequest\.)?Method\.)?(GET|HEAD|POST|PUT|DELETE)\s*,\s*"
)
TOKEN = re.compile(r'\s*("(?:[^"\\]|\\.)*"|[A-Za-z_$][\w.$]*(?:\(\))?)\s*')
FIELD = re.compile(r"\b(?:static\s+final|final\s+static)\s+String\s+(\w+)\s*=\s*([^;]+);")


class ParseFieldString(str):
    """Preferred name, only enabled after checking pinned ParseField semantics."""


def without_comments(text):
    output = []
    i, quote = 0, None
    while i < len(text):
        ch = text[i]
        if quote:
            output.append(ch)
            if ch == "\\" and i + 1 < len(text):
                i += 1
                output.append(text[i])
            elif ch == quote:
                quote = None
        elif ch in {'"', "'"}:
            quote = ch
            output.append(ch)
        elif text[i : i + 2] == "//":
            stop = text.find("\n", i)
            if stop < 0:
                break
            output.append("\n")
            i = stop
        elif text[i : i + 2] == "/*":
            stop = text.find("*/", i + 2)
            if stop < 0:
                break
            output.append("\n" * text[i : stop + 2].count("\n"))
            i = stop + 1
        else:
            output.append(ch)
        i += 1
    return "".join(output)


def expression_at(text, start):
    """Return the whole second argument, never just its first quoted token."""
    quote, depth, i = False, 0, start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == '"':
                quote = False
        elif ch == '"':
            quote = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return text[start:i].strip()
            depth -= 1
        elif ch == "," and depth == 0:
            return text[start:i].strip()
        i += 1
    return None


def resolve_string(expression, constants):
    if expression is None:
        return None
    cursor, values = 0, []
    while cursor < len(expression):
        match = TOKEN.match(expression, cursor)
        if not match:
            return None
        token = match[1]
        if token.startswith('"'):
            try:
                value = json.loads(token)
            except ValueError:
                return None
        else:
            if token.endswith(".getPreferredName()"):
                value = constants.get(token[: -len(".getPreferredName()")])
                if not isinstance(value, ParseFieldString):
                    return None
            elif token.endswith("()"):
                return None
            else:
                value = constants.get(token)
            if value is None:
                return None
        values.append(value)
        cursor = match.end()
        if cursor == len(expression):
            break
        if expression[cursor] != "+":
            return None
        cursor += 1
        if not expression[cursor:].strip():
            return None
    return "".join(values) if values else None


def local_constants(text, external=None, parse_fields=False):
    known = dict(external or {})
    fields = FIELD.findall(without_comments(text))
    if parse_fields and re.search(
        r"import\s+org\.elasticsearch\.(?:xcontent|common(?:\.xcontent)?)\.ParseField;", text
    ):
        pattern = re.compile(
            r'\b(?:static\s+final|final\s+static)\s+ParseField\s+(\w+)\s*=\s*new\s+ParseField\(\s*("(?:[^"\\]|\\.)*")(?:\s*,[^;{}()]*)?\s*\)\s*;'
        )
        for name, value in pattern.findall(without_comments(text)):
            fields.append((name, None))
            known[name] = ParseFieldString(json.loads(value))
    class_match = re.search(r"\bclass\s+(\w+)", text)
    class_name = class_match[1] if class_match else ""
    duplicate_names = {
        name for name, count in Counter(name for name, _ in fields).items() if count > 1
    }
    local = {}
    for _ in range(8):
        changed = False
        for name, expression in fields:
            if name in duplicate_names:
                continue
            value = (
                known.get(name) if expression is None else resolve_string(expression.strip(), known)
            )
            if value is not None and local.get(name) != value:
                local[name] = value
                known[name] = value
                known[class_name + "." + name] = value
                changed = True
        if not changed:
            break
    return local


def builder_arguments(text, match, expression):
    """Only pinned builder().build/deprecated/replaces signatures, no guessed aliases."""
    cursor = match.end() + len(expression or "")
    tail = text[cursor:]
    build = r"\s*\)\s*\.\s*build\(\s*\)"
    if re.match(build, tail):
        return [(match[1], expression, {"builder_form": "normal"})]
    kept = re.match(r"\s*\)\s*\.\s*deprecateAndKeep\(\s*", tail)
    if kept:
        start = cursor + kept.end()
        message = expression_at(text, start)
        end = start + len(message or "")
        if message is not None and re.match(build, text[end:]):
            return [(match[1], expression, {"builder_form": "deprecated-kept"})]
        return None
    deprecated = re.match(r"\s*\)\s*\.\s*deprecated\(\s*", tail)
    if deprecated:
        start = cursor + deprecated.end()
        message = expression_at(text, start)
        end = start + len(message or "")
        version = re.match(
            r"\s*,\s*RestApiVersion\.V_([0-9]+)\s*\)\s*\.\s*build\(\s*\)", text[end:]
        )
        if message is not None and version:
            return [
                (
                    match[1],
                    expression,
                    {"builder_form": "deprecated", "deprecation_version": int(version[1])},
                )
            ]
        return None
    replaced = re.match(
        r"\s*\)\s*\.\s*replaces\(\s*(?:(?:RestRequest\.)?Method\.)?"
        r"(GET|HEAD|POST|PUT|DELETE)\s*,\s*",
        tail,
    )
    if replaced:
        start = cursor + replaced.end()
        previous = expression_at(text, start)
        end = start + len(previous or "")
        version = re.match(
            r"\s*,\s*RestApiVersion\.V_([0-9]+)\s*\)\s*\.\s*build\(\s*\)", text[end:]
        )
        if previous is not None and version:
            return [
                (
                    match[1],
                    expression,
                    {"builder_form": "replacement", "replacement_role": "current"},
                ),
                (
                    replaced[1],
                    previous,
                    {
                        "builder_form": "replacement",
                        "replacement_role": "deprecated",
                        "deprecation_version": int(version[1]),
                    },
                ),
            ]
    return None


def extract_routes(text, external=None, parse_fields=False):
    cleaned = without_comments(text)
    constants = dict(external or {})
    local = local_constants(cleaned, constants, parse_fields)
    constants.update(local)
    class_match = re.search(r"\bclass\s+(\w+)", cleaned)
    if class_match:
        constants.update({class_match[1] + "." + name: value for name, value in local.items()})
    routes, unresolved = [], []
    for match in START.finditer(cleaned):
        expression = expression_at(cleaned, match.end())
        arguments = [(match[1], expression, {})]
        if "Route.builder" in match.group(0):
            arguments = builder_arguments(cleaned, match, expression)
            if arguments is None:
                unresolved.append(
                    {
                        "method": match[1],
                        "source_expression": expression,
                        "line": cleaned.count("\n", 0, match.start()) + 1,
                        "form": "unresolved-builder-route",
                    }
                )
                continue
        if "ReplacedRoute" in match.group(0):
            cursor = match.end() + len(expression or "")
            tail = re.match(
                r"\s*,\s*(?:(?:RestRequest\.)?Method\.)?(GET|HEAD|POST|PUT|DELETE)\s*,\s*",
                cleaned[cursor:],
            )
            if tail is None:
                unresolved.append(
                    {
                        "method": match[1],
                        "source_expression": expression,
                        "line": cleaned.count("\n", 0, match.start()) + 1,
                        "form": "unresolved-replaced-route",
                    }
                )
                continue
            deprecated_start = cursor + tail.end()
            deprecated_expression = expression_at(cleaned, deprecated_start)
            close = deprecated_start + len(deprecated_expression or "")
            if deprecated_expression is None or not cleaned[close:].lstrip().startswith(")"):
                unresolved.append(
                    {
                        "method": match[1],
                        "source_expression": expression,
                        "line": cleaned.count("\n", 0, match.start()) + 1,
                        "form": "unresolved-replaced-route",
                    }
                )
                continue
            arguments = [
                (match[1], expression, {"replacement_role": "current"}),
                (tail[1], deprecated_expression, {"replacement_role": "deprecated"}),
            ]
        for method, expression, attributes in arguments:
            path = resolve_string(expression, constants)
            item = {
                "method": method,
                "source_expression": expression,
                "line": cleaned.count("\n", 0, match.start()) + 1,
                **attributes,
            }
            if path is None:
                unresolved.append(item)
            else:
                routes.append(
                    {
                        **item,
                        "path": path,
                        "resolution": "literal"
                        if expression.startswith('"') and "+" not in expression
                        else "constant-expression",
                    }
                )
    unique = {(row["method"], row["path"]): row for row in routes}
    return {
        "routes": [unique[key] for key in sorted(unique)],
        "unresolved_routes": unresolved,
        "local_constants": local,
    }
