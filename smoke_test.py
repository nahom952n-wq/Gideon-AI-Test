import json
import os
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as tmp:
    os.environ["GIDEON_RUNTIME_DIR"] = tmp
    os.environ["FLASK_ENV"] = "development"
    os.environ["FLASK_SECRET_KEY"] = "smoke-test-secret"
    os.environ["GEMINI_API_KEY"] = ""

    from app import create_app
    from app.extensions import db
    from app.models.api_key import ApiKeySetting
    from app.ai.router import AIRouter

    app = create_app("development")
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    with app.app_context():
        client = app.test_client()
        register = client.post("/auth/register", data={"display_name": "Smoke Admin", "email": "smoke@example.com", "password": "smoke-password-123"}, follow_redirects=False)
        assert register.status_code == 302
        response = client.get("/settings/")
        assert response.status_code == 200, response.status_code
        body = response.get_data(as_text=True)
        assert "AI Providers &amp; API Keys" in body or "AI Providers & API Keys" in body
        assert "Do not share screenshots of this page" in body
        assert "xAI (Grok)" in body
        assert "ScholarMind AI" in body

        with client.session_transaction():
            pass

        ApiKeySetting.set("grok", "test-grok-key")
        ApiKeySetting.set("grok", "grok-2")
        ApiKeySetting.set("__routing__", json.dumps({"chat": "grok"}), "capability_map")
        db.session.commit()

        router = AIRouter()
        router._init_providers()
        assert "grok" in router._providers
        assert router._providers["grok"].model == "grok-2"
        assert ApiKeySetting.get("__routing__", "capability_map")

        clear_response = client.post("/settings/api-keys/clear", data={"provider": "grok"})
        assert clear_response.status_code == 200
        assert ApiKeySetting.get("grok") is None

print("ScholarMind AI smoke test passed")
