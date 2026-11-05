"""One bounded HTTP attempt. Parent process enforces the total wall deadline."""

import base64
import http.client
import json
import ssl
import sys
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def main():
    config = json.load(sys.stdin)
    handlers = [urllib.request.ProxyHandler({}), NoRedirect()]
    if config["url"].startswith("https:"):
        tls = config.get("tls", {})
        context = ssl.create_default_context(cafile=tls.get("cafile"))
        if tls.get("insecure"):
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        if tls.get("certfile"):
            context.load_cert_chain(tls["certfile"], tls.get("keyfile"))
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    body = base64.b64decode(config["body_b64"]) if config["body_b64"] is not None else None
    request = urllib.request.Request(
        config["url"], method=config["method"], data=body, headers=config["headers"]
    )
    result = {"status": None, "headers": {}, "body_b64": None, "body_complete": False}
    try:
        try:
            response = opener.open(request, timeout=config["socket_timeout"])
        except urllib.error.HTTPError as error:
            response = error
        with response:
            result["status"] = response.status
            result["headers"] = {
                key: response.headers.get_all(key)
                for key in [
                    "Content-Type",
                    "Content-Length",
                    "Transfer-Encoding",
                    "Location",
                    "Warning",
                    "Retry-After",
                    "X-Elastic-Product",
                    "WWW-Authenticate",
                ]
                if response.headers.get_all(key)
            }
            try:
                raw = response.read(config["max_response_bytes"] + 1)
            except http.client.IncompleteRead as error:
                raw = error.partial
                result["error"] = {
                    "type": "IncompleteRead",
                    "phase": "receive-body",
                    "received_length": len(raw),
                }
            result["body_b64"] = base64.b64encode(raw).decode()
            if len(raw) > config["max_response_bytes"]:
                result["error"] = {"type": "response-size-limit", "phase": "receive-body"}
            elif config["method"] != "HEAD" and response.status not in {204, 304}:
                declared = response.headers.get("Content-Length")
                if (
                    declared is not None
                    and declared.strip().isdigit()
                    and len(raw) != int(declared)
                ):
                    result["error"] = {
                        "type": "response-length-mismatch",
                        "phase": "receive-body",
                        "expected_length": int(declared),
                        "received_length": len(raw),
                    }
            result["body_complete"] = "error" not in result
    except Exception as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        result["error"] = {
            "type": type(reason).__name__,
            "message": str(reason)[:1500],
            "phase": "request-or-response",
        }
        if isinstance(reason, ssl.SSLCertVerificationError):
            result["error"]["verify_code"] = reason.verify_code
            result["error"]["verify_message"] = reason.verify_message

    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
