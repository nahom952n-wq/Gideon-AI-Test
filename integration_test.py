"""Integration smoke tests for ScholarMind AI's Flask surface.

The suite deliberately avoids external AI/Telegram calls. It exercises every
GET route exposed by the Flask application and asserts that no route crashes
with a server error in a clean temporary database.
"""

import os
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    os.environ["GIDEON_TEST_HOME"] = tmp
    os.environ["FLASK_ENV"] = "development"
    os.environ["FLASK_SECRET_KEY"] = "integration-test-secret"
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["ANTHROPIC_API_KEY"] = ""
    os.environ["GROK_API_KEY"] = ""
    os.environ["TELEGRAM_API_ID"] = ""
    os.environ["TELEGRAM_API_HASH"] = ""
    os.environ["TELEGRAM_BOT_TOKEN"] = ""

    from app import create_app

    app = create_app("development")
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    client = app.test_client()

    # Core known pages/APIs.
    core_paths = [
        "/",
        "/dashboard/",
        "/scholarships/",
        "/tracker/",
        "/profile/",
        "/chat/",
        "/feed/",
        "/news/",
        "/settings/",
        "/sources/",
        "/admin/backups/",
        "/api/healthz",
        "/api/scholarships/by-country",
        "/api/scholarships/by-degree",
        "/api/sources/health",
        "/sources/telegram/status",
        "/sources/telegram/dialogs",
        "/definitely-not-a-real-route",
    ]

    for path in core_paths:
        response = client.get(path)
        assert response.status_code < 500, (
            f"{path} returned server error {response.status_code}: "
            f"{response.get_data(as_text=True)[:500]}"
        )

    # Exercise every GET route registered by the application. For dynamic
    # integer parameters, use 1 so missing records should produce 404 rather
    # than a server error.
    checked = 0
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods:
            continue
        if rule.endpoint == "static":
            continue

        path = str(rule)
        for variable in rule.arguments:
            converter = rule._converters.get(variable)
            if converter and converter.regex == r"\\d+":
                replacement = "1"
            elif converter and converter.regex:
                replacement = "test"
            else:
                replacement = "test"
            path = path.replace(f"<{variable}>", replacement)
            # Converter syntax may include a converter name.
            path = path.replace(f"<{converter.__class__.__name__.replace('Converter', '').lower()}:{variable}>", replacement)

        response = client.get(path)
        assert response.status_code < 500, (
            f"GET {path} ({rule.endpoint}) returned {response.status_code}: "
            f"{response.get_data(as_text=True)[:500]}"
        )
        checked += 1

    # The branding and health contract should be stable.
    dashboard = client.get("/dashboard/")
    assert dashboard.status_code == 200
    assert "ScholarMind AI" in dashboard.get_data(as_text=True)

    health = client.get("/api/healthz")
    assert health.status_code == 200
    payload = health.get_json()
    assert payload and payload.get("status") == "ok"

    print(f"ScholarMind AI integration test passed: {checked} GET routes checked")
