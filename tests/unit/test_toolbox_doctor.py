"""Toolbox preflight checks are authenticated, failover-aware and secret-free."""

import errno
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

from acessilia_benchmark.services import doctor, toolbox


def test_settings_read_uses_core_endpoints_and_keeps_api_key_private(monkeypatch, tmp_path):
    payload = {
        "base_url": "http://fallback.test",
        "base_urls": "http://first.test, http://second.test",
        "api_key": "secret-toolbox-key",
        "ai_client": "toolbox",
        "providers": ["docling", "qwen-vl", "docling"],
        "pinned_providers": ["qwen-vl"],
    }
    monkeypatch.setattr(
        toolbox.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(payload)),
    )
    config = toolbox.read_toolbox_settings(Path("/python"), tmp_path)
    assert config.endpoints == ("http://first.test", "http://second.test")
    assert config.providers == ("docling", "qwen-vl")
    assert config.pinned_providers == (("qwen-vl", "http://first.test"),)
    assert "secret-toolbox-key" not in repr(config)


def test_settings_read_ignores_unset_optional_providers(monkeypatch, tmp_path):
    payload = {
        "base_url": "http://toolbox.test",
        "providers": [None, "docling", "  "],
        "pinned_providers": [None, "qwen-vl"],
        "ai_client": "ollama",
    }
    monkeypatch.setattr(
        toolbox.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(payload)),
    )
    config = toolbox.read_toolbox_settings(Path("/python"), tmp_path)
    assert config.providers == ("docling",)
    assert config.pinned_providers == (("qwen-vl", "http://toolbox.test"),)


def test_provider_health_fails_over_and_records_stable_runtime_identity(monkeypatch):
    def get_json(url, api_key=""):
        if url.endswith("/v1/health"):
            if url.startswith("http://first.test"):
                return None, "HTTP 503"
            return {
                "status": "healthy",
                "version": "0.2.0",
                "git_commit": "coreless-toolbox",
                "image_tag": "release",
            }, None
        assert api_key == "private-key"
        return {"provider": "docling", "healthy": True, "version": "1.8.0"}, None

    monkeypatch.setattr(toolbox, "_get_json", get_json)
    result = toolbox.check_toolbox(
        ("http://first.test", "http://second.test"), ("docling",), "private-key"
    )
    assert result["ok"] is True
    assert result["providers"]["docling"]["ok"] is True
    assert result["identity"]["services"][0]["git_commit"] == "coreless-toolbox"
    assert result["identity"]["providers"][0]["endpoints"] == [
        {"endpoint": "http://second.test", "version": "1.8.0"}
    ]
    assert "private-key" not in json.dumps(result)


def test_provider_must_be_healthy_on_each_reachable_failover_endpoint(monkeypatch):
    def get_json(url, api_key=""):
        if url.endswith("/v1/health"):
            return {"status": "healthy", "version": "0.2.0"}, None
        if url.startswith("http://first.test"):
            return {"provider": "docling", "healthy": False}, None
        return {"provider": "docling", "healthy": True, "version": "1.8.0"}, None

    monkeypatch.setattr(toolbox, "_get_json", get_json)
    result = toolbox.check_toolbox(("http://first.test", "http://second.test"), ("docling",))
    assert result["ok"] is False
    assert result["providers"]["docling"]["ok"] is False


def test_invalid_endpoint_is_reported_without_echoing_it():
    result = toolbox.check_toolbox(("https://user:secret@toolbox.test:invalid",), ("docling",))
    assert result["ok"] is False
    assert result["error"] == "no valid HTTP(S) Toolbox endpoint"
    assert "secret" not in json.dumps(result)


def test_provider_failure_blocks_readiness(monkeypatch):
    monkeypatch.setattr(
        toolbox,
        "_get_json",
        lambda url, api_key="": (
            {"status": "healthy", "version": "0.2.0"}
            if url.endswith("/v1/health")
            else {"provider": "docling", "healthy": False, "version": "1.8.0"},
            None,
        ),
    )
    result = toolbox.check_toolbox(("http://toolbox.test",), ("docling",))
    assert result["ok"] is False
    assert result["providers"]["docling"]["ok"] is False


def test_pinned_vlm_provider_must_be_healthy_on_the_first_endpoint(monkeypatch):
    def get_json(url, api_key=""):
        if url.endswith("/v1/health"):
            return {"status": "healthy", "version": "0.2.0"}, None
        if url.startswith("http://first.test"):
            return {"provider": "qwen-vl", "healthy": False}, None
        return {"provider": "qwen-vl", "healthy": True, "version": "8b"}, None

    monkeypatch.setattr(toolbox, "_get_json", get_json)
    result = toolbox.check_toolbox(
        ("http://first.test", "http://second.test"),
        ("qwen-vl",),
        pinned_providers=(("qwen-vl", "http://first.test"),),
    )
    assert result["ok"] is False
    assert result["providers"]["qwen-vl"]["ok"] is False
    assert [row["endpoint"] for row in result["providers"]["qwen-vl"]["endpoints"]] == [
        "http://first.test"
    ]


def test_health_report_redacts_url_credentials_and_query(monkeypatch):
    monkeypatch.setattr(
        toolbox,
        "_get_json",
        lambda *_: ({"status": "healthy", "version": "0.2.0"}, None),
    )
    result = toolbox._service_health(
        "https://user:password@example.test/proxy?token=secret#fragment"
    )
    assert result["endpoint"] == "https://example.test/proxy"
    assert "password" not in json.dumps(result)
    assert "secret" not in json.dumps(result)


def test_api_key_is_sent_only_as_bearer_header(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"healthy": true}'

    observed = {}

    def urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["authorization"] = request.get_header("Authorization")
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(toolbox.urllib.request, "urlopen", urlopen)
    data, error = toolbox._get_json("https://toolbox.test/health", "secret-key")
    assert data == {"healthy": True}
    assert error is None
    assert observed == {
        "url": "https://toolbox.test/health",
        "authorization": "Bearer secret-key",
        "timeout": 3,
    }


def test_connection_refusal_is_actionable_without_echoing_endpoint(monkeypatch):
    def urlopen(*_args, **_kwargs):
        raise urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED, "refused"))

    monkeypatch.setattr(toolbox.urllib.request, "urlopen", urlopen)
    data, error = toolbox._get_json("http://user:secret@toolbox.test/health?token=private")
    assert data is None
    assert error == "connection refused"
    assert "secret" not in error
    assert "private" not in error


def test_doctor_uses_core_provider_selection_to_compute_inference_readiness(
    workspace, monkeypatch, tmp_path
):
    settings = toolbox.ToolboxSettings(
        ("http://core-configured.test",),
        ("docling", "docling-math"),
        "ollama",
        "secret",
    )
    checked = {}
    monkeypatch.setattr(doctor, "load_registry", lambda *_: {})
    monkeypatch.setattr(
        doctor,
        "resolve_python",
        lambda *_: (tmp_path / "python", {"modules": {}, "contracts": {}}),
    )
    monkeypatch.setattr(doctor, "read_toolbox_settings", lambda *_: settings)

    def probe(endpoints, providers, api_key, pinned_providers):
        checked.update(
            endpoints=endpoints,
            providers=providers,
            api_key=api_key,
            pinned_providers=pinned_providers,
        )
        return {
            "ok": False,
            "endpoints": [],
            "providers": {"docling-math": {"ok": False}},
            "identity": {"services": [], "providers": []},
        }

    monkeypatch.setattr(doctor, "check_toolbox", probe)
    result = doctor.diagnose(workspace, tmp_path, None, None)
    assert checked == {
        "endpoints": list(settings.endpoints),
        "providers": settings.providers,
        "api_key": "secret",
        "pinned_providers": settings.pinned_providers,
    }
    assert result["ready_for_inference"] is False
    assert "secret" not in json.dumps(result)
