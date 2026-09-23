"""Integration smoke tests for ScholarMind AI's Flask surface.

The suite deliberately avoids external AI/Telegram calls. It exercises every
GET route exposed by the Flask application and asserts that no route crashes
with a server error in a clean temporary database.
"""

import os
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    os.environ["GIDEON_RUNTIME_DIR"] = tmp
    os.environ["FLASK_ENV"] = "development"
    os.environ["FLASK_SECRET_KEY"] = "integration-test-secret"
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["SCHOLARMIND_START_BACKGROUND_SERVICES"] = "false"
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

    register = client.post("/auth/register", data={"display_name": "Integration Admin", "email": "integration@example.com", "password": "integration-password-123"}, follow_redirects=False)
    assert register.status_code == 302

    # Verify per-user profile isolation.
    profile_save = client.post(
        "/profile/save",
        data={"name": "Integration Admin Private", "email": "integration@example.com"},
        follow_redirects=False,
    )
    assert profile_save.status_code == 302
    assert client.post("/auth/logout", follow_redirects=False).status_code == 302

    register_user_two = client.post(
        "/auth/register",
        data={
            "display_name": "Second User",
            "email": "second@example.com",
            "password": "second-password-123",
        },
        follow_redirects=False,
    )
    assert register_user_two.status_code == 302
    second_profile = client.get("/profile/")
    assert second_profile.status_code == 200
    assert "Integration Admin Private" not in second_profile.get_data(as_text=True)

    # Non-admin users must not access owner/admin controls.
    assert client.get("/settings/").status_code == 403
    assert client.get("/admin/backups/").status_code == 403
    assert client.get("/sources/").status_code == 200

    # Core known pages/APIs.
    core_paths = [
        "/",
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

    # Exercise every GET route registered by the application. Build dynamic
    # URLs using Werkzeug's own Rule builder so converter syntax is handled
    # correctly (for example <int:id>). A missing record may legitimately 404;
    # the important assertion is that no route crashes with a 5xx response.
    checked = 0
    from werkzeug.routing import BuildError

    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.endpoint == "static":
            continue

        values = {}
        for variable in rule.arguments:
            converter = rule._converters.get(variable)
            converter_name = converter.__class__.__name__ if converter else ""
            values[variable] = "1" if converter_name == "IntegerConverter" else "test"

        try:
            _, path = rule.build(values, append_unknown=False)
        except BuildError:
            continue

        response = client.get(path)
        assert response.status_code < 500, (
            f"GET {path} ({rule.endpoint}) returned {response.status_code}: "
            f"{response.get_data(as_text=True)[:500]}"
        )
        checked += 1

    # The branding and health contract should be stable.
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "ScholarMind AI" in dashboard.get_data(as_text=True)

    health = client.get("/api/healthz")
    assert health.status_code == 200
    payload = health.get_json()
    assert payload and payload.get("status") == "ok"

    print(f"ScholarMind AI integration test passed: {checked} GET routes checked")
