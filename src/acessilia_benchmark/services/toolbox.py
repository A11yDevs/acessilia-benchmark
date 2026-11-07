"""Read Core Toolbox settings and probe the configured Toolbox runtime safely."""

from __future__ import annotations

import errno
import ipaddress
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ToolboxSettings:
    """Private runtime configuration; credentials must never enter reports."""

    endpoints: tuple[str, ...]
    providers: tuple[str, ...]
    ai_client: str
    api_key: str = field(default="", repr=False)
    pinned_providers: tuple[tuple[str, str], ...] = ()


def read_toolbox_settings(python: Path, repo: Path) -> ToolboxSettings:
    """Load only the Core settings needed for health checks in its interpreter."""
    program = """import json, os, sys
repo = sys.argv[1]
sys.path[:0] = [repo, repo + '/libs/docstruct/src', repo + '/libs/sdk/src']
os.chdir(repo)
from backend.config.settings import settings
provider_names = (
    'toolbox_provider', 'toolbox_layout_provider', 'toolbox_pdf_provider',
    'toolbox_math_recognize_provider', 'toolbox_math_provider', 'toolbox_ocr_provider',
    'toolbox_page_ocr_provider', 'toolbox_adjudicate_provider', 'toolbox_table_provider',
    'toolbox_orientation_provider',
)
providers = [getattr(settings, name, None) for name in provider_names]
if getattr(settings, 'toolbox_media_inspect_enabled', True):
    providers.append(getattr(settings, 'toolbox_media_inspect_provider', None))
if settings.ai_client == 'toolbox':
    providers.append(settings.toolbox_vlm_provider)
print(json.dumps({
    'base_url': settings.toolbox_base_url,
    'base_urls': settings.toolbox_base_urls,
    'api_key': settings.toolbox_api_key,
    'ai_client': settings.ai_client,
    'providers': providers,
    'pinned_providers': (
        [settings.toolbox_vlm_provider] if settings.ai_client == 'toolbox' else []
    ),
}))
"""
    try:
        result = subprocess.run(
            [str(python), "-c", program, str(repo)],
            text=True,
            capture_output=True,
            timeout=15,
            check=True,
        )
        data = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise ValueError("Não foi possível ler a configuração Toolbox do Core.") from error

    configured = data.get("base_urls", "")
    endpoints = _split_endpoints(configured) or _split_endpoints(data.get("base_url", ""))
    if not endpoints:
        raise ValueError("O Core não configurou uma URL Toolbox válida.")
    providers = tuple(
        sorted(
            {
                str(value).strip()
                for value in data.get("providers", [])
                if value is not None and str(value).strip()
            }
        )
    )
    pinned = tuple(
        (str(provider).strip(), endpoints[0])
        for provider in data.get("pinned_providers", [])
        if provider is not None and str(provider).strip()
    )
    return ToolboxSettings(
        endpoints=tuple(endpoints),
        providers=providers,
        ai_client=str(data.get("ai_client", "")),
        pinned_providers=pinned,
        api_key=str(data.get("api_key", "")),
    )


def _split_endpoints(value: str) -> list[str]:
    result = []
    for raw in str(value).split(","):
        endpoint = raw.strip().rstrip("/")
        try:
            parsed = urllib.parse.urlsplit(endpoint)
            valid_port = parsed.port is None or 1 <= parsed.port <= 65535
        except ValueError:
            continue
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and valid_port
            and endpoint not in result
        ):
            result.append(endpoint)
    return result


def _public_endpoint(endpoint: str) -> str:
    """Drop URL credentials, query strings, and fragments before reporting."""
    parsed = urllib.parse.urlsplit(endpoint)
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


def _get_json(url: str, api_key: str = "") -> tuple[dict | None, str | None]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        request = urllib.request.Request(url, headers=headers)
        with _urlopen(request, timeout=3) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            return None, "invalid JSON response"
        return data, None
    except urllib.error.HTTPError as error:
        return None, f"HTTP {error.code}"
    except urllib.error.URLError as error:
        return None, _network_error(error.reason)
    except TimeoutError:
        return None, "connection timed out"
    except OSError as error:
        return None, _network_error(error)
    except ValueError:
        return None, "invalid JSON response"


def _network_error(error) -> str:
    if isinstance(error, OSError):
        if error.errno == errno.ECONNREFUSED:
            return "connection refused"
        if error.errno == errno.ETIMEDOUT:
            return "connection timed out"
    if isinstance(error, TimeoutError):
        return "connection timed out"
    description = str(error).lower()
    if "connection refused" in description:
        return "connection refused"
    if "timed out" in description or "timeout" in description:
        return "connection timed out"
    if "proxy" in description:
        return "proxy connection error"
    return "network error"


def _urlopen(request, timeout):
    """Do not route loopback health checks through configured HTTP proxies."""
    hostname = urllib.parse.urlsplit(request.full_url).hostname or ""
    try:
        loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname.lower() == "localhost"
    if loopback:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def _service_health(endpoint: str) -> dict:
    data, error = _get_json(endpoint + "/v1/health")
    ok = data is not None and data.get("status") in {"healthy", "ok"}
    return {
        "endpoint": _public_endpoint(endpoint),
        "ok": ok,
        "error": error if not ok else None,
        "identity": {
            key: data.get(key) if data and isinstance(data.get(key), str) else None
            for key in ("version", "git_commit", "image_tag")
        },
    }


def _provider_health(endpoint: str, provider: str, api_key: str) -> dict:
    path = urllib.parse.quote(provider, safe="")
    data, error = _get_json(endpoint + f"/v1/providers/{path}/health", api_key)
    ok = data is not None and data.get("healthy") is True
    return {
        "endpoint": _public_endpoint(endpoint),
        "ok": ok,
        "version": data.get("version") if data and isinstance(data.get("version"), str) else None,
        "error": error if not ok else None,
    }


def check_toolbox(
    endpoints: tuple[str, ...] | list[str],
    providers: tuple[str, ...] | list[str] = (),
    api_key: str = "",
    pinned_providers: tuple[tuple[str, str], ...] | list[tuple[str, str]] = (),
) -> dict:
    """Check API identity and each selected provider across configured endpoints."""
    endpoints = tuple(dict.fromkeys(_split_endpoints(",".join(endpoints))))
    providers = tuple(sorted(set(providers)))
    pinned = dict(pinned_providers)
    if not endpoints:
        return {
            "ok": False,
            "error": "no valid HTTP(S) Toolbox endpoint",
            "endpoints": [],
            "providers": {provider: {"ok": False, "endpoints": []} for provider in providers},
            "identity": {"services": [], "providers": []},
            "scope": "API e saúde dos providers configurados no Core; não executa inferência real",
        }
    with ThreadPoolExecutor(
        max_workers=min(16, max(1, len(endpoints) * (len(providers) + 1)))
    ) as pool:
        health_rows = list(pool.map(_service_health, endpoints))

    healthy_endpoints = [
        endpoint for endpoint, row in zip(endpoints, health_rows, strict=True) if row["ok"]
    ]
    provider_rows = {}
    if healthy_endpoints and providers:
        checks = {}
        with ThreadPoolExecutor(
            max_workers=min(32, len(healthy_endpoints) * len(providers))
        ) as pool:
            futures = {
                (provider, endpoint): pool.submit(_provider_health, endpoint, provider, api_key)
                for provider in providers
                for endpoint in (
                    [pinned[provider]]
                    if provider in pinned and pinned[provider] in healthy_endpoints
                    else healthy_endpoints
                    if provider not in pinned
                    else []
                )
            }
            checks = {key: future.result() for key, future in futures.items()}
        for provider in providers:
            checked_endpoints = (
                [pinned[provider]]
                if provider in pinned and pinned[provider] in healthy_endpoints
                else healthy_endpoints
                if provider not in pinned
                else []
            )
            rows = [checks[(provider, endpoint)] for endpoint in checked_endpoints]
            provider_rows[provider] = {
                "ok": bool(rows) and all(row["ok"] for row in rows),
                "endpoints": rows,
            }
    else:
        provider_rows = {provider: {"ok": False, "endpoints": []} for provider in providers}

    identities = [
        {"endpoint": row["endpoint"], **row["identity"]} for row in health_rows if row["ok"]
    ]
    provider_identity = [
        {
            "provider": provider,
            "endpoints": sorted(
                [
                    {"endpoint": row["endpoint"], "version": row["version"]}
                    for row in provider_rows[provider]["endpoints"]
                    if row["ok"]
                ],
                key=lambda row: (row["endpoint"], row["version"] or ""),
            ),
        }
        for provider in providers
    ]
    return {
        "ok": bool(healthy_endpoints) and all(row["ok"] for row in provider_rows.values()),
        "endpoints": health_rows,
        "providers": provider_rows,
        "identity": {"services": identities, "providers": provider_identity},
        "scope": "API e saúde dos providers configurados no Core; não executa inferência real",
    }
