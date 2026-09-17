"""Explicit synthetic loopback smoke. Never reads a file or calls a cloud model."""

import asyncio
import json
import secrets
from pathlib import Path

import httpx

from gateway import GatewayError, Settings, create_app, strict_json, upstream_json


async def run():
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8080", timeout=3,
                                     trust_env=False, follow_redirects=False,
                                     headers={"Accept-Encoding": "identity"}) as client:
            async with asyncio.timeout(5):
                data = await upstream_json(client, "GET", "/v1/models")
        models = data.get("data", []) if isinstance(data, dict) else []
        if len(models) != 1 or not isinstance(models[0], dict) or not isinstance(models[0].get("id"), str):
            return {"status": "BLOCKED", "code": "select_exactly_one_local_model"}
        bearer = secrets.token_urlsafe(32)
        settings = Settings(bearer, models[0]["id"], state_directory=str(
            Path.home() / "Library/Application Support/DPMSLocalLLM/state"))
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
                result = await client.post("/v1/chat/completions", headers={"Authorization": "Bearer " + bearer}, json={
                    "model": settings.model, "temperature": 0, "max_tokens": 2048,
                    "messages": [
                        {"role": "system", "content": "Return only JSON with an atoms array. Each atom has name and evidence strings. Extract exactly the two UI elements explicitly required below. Do not add anything."},
                        {"role": "user", "content": "SYNTHETIC TEST, NOT A REAL DOCUMENT. Section 1: The Test panel has a Save button. Section 2: The Test panel has a Name text field."},
                    ],
                })
        if result.status_code != 200:
            return {"status": "FAIL", "code": result.json()["error"]["code"]}
        text = result.json()["choices"][0]["message"]["content"]
        try:
            document = strict_json(text.encode())
            atoms = document["atoms"]
            valid = isinstance(atoms, list) and len(atoms) == 2 and all(
                isinstance(atom, dict) and isinstance(atom.get("name"), str) and atom["name"].strip()
                and isinstance(atom.get("evidence"), str) and atom["evidence"].strip() for atom in atoms)
        except (ValueError, KeyError, TypeError):
            valid = False
        return {"status": "PASS" if valid else "FAIL", "code": "synthetic_schema_ok" if valid else "synthetic_schema_invalid",
                "scope": "gateway_to_loopback_model_only", "atoms": len(atoms) if valid else None}
    except (httpx.HTTPError, TimeoutError):
        return {"status": "BLOCKED", "code": "local_model_offline_or_timeout"}
    except GatewayError as exc:
        return {"status": "BLOCKED", "code": exc.code}
    except Exception:
        return {"status": "FAIL", "code": "synthetic_check_failed"}


if __name__ == "__main__":
    result = asyncio.run(run())
    result.update(real_documents_sent=False, production_changed=False, cloud_requests=0)
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "PASS" else 2)
