"""Normalize pinned REST JSON routes, including explicit legacy deprecated_paths."""


def definition_routes(definition):
    url = definition.get("url", {})
    routes = []
    for deprecated, entries in [
        (False, url.get("paths", [])),
        (True, url.get("deprecated_paths", [])),
    ]:
        for entry in entries:
            route = {"path": entry} if isinstance(entry, str) else dict(entry)
            row = {
                "path": route["path"],
                "methods": route.get("methods", definition.get("methods", [])),
                "parts": route.get("parts", url.get("parts", {})),
            }
            metadata = (
                {k: v for k, v in route.items() if k not in {"path", "methods", "parts"}}
                if deprecated
                else route.get("deprecated")
            )
            if metadata is not None:
                row["deprecated"] = metadata
            routes.append(row)
    return routes
