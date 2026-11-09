"""Relayed Gemini errors keep code/status but not provider identifiers."""

import json

from app.api.gemini.endpoints.generate import sanitize_gemini_error

UPSTREAM = json.dumps(
    {
        "error": {
            "code": 403,
            "status": "PERMISSION_DENIED",
            "message": (
                "Permission denied on resource project my-prod-proj-123 for "
                "kbp-sa@my-prod-proj-123.iam.gserviceaccount.com "
                "(projects/987654321/locations/us-central1)"
            ),
            "details": [{"metadata": {"consumer": "projects/987654321"}}],
        }
    }
)


def test_keeps_code_and_status():
    err = sanitize_gemini_error(UPSTREAM.encode(), 403)["error"]
    assert err["code"] == 403 and err["status"] == "PERMISSION_DENIED"


def test_redacts_identifiers_and_drops_details():
    out = json.dumps(sanitize_gemini_error(UPSTREAM, 403))
    for leaked in ("my-prod-proj-123", "987654321", "kbp-sa@", "details"):
        assert leaked not in out


def test_non_json_body():
    err = sanitize_gemini_error(b"<html>502</html>", 502)["error"]
    assert err["code"] == 502 and err["status"] == "UNKNOWN"
