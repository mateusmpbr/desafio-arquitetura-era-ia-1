"""Cria (ou atualiza) as chaves virtuais do gateway a partir de keys.json.

Idempotente: roda a cada subida do gateway. Usa só a biblioteca padrão,
porque a imagem do LiteLLM não traz curl.
"""

import json
import os
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:4000"
MASTER = os.environ["LITELLM_MASTER_KEY"]
KEYS_FILE = "/gateway/keys.json"


def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={
        "Authorization": f"Bearer {MASTER}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def wait_ready(deadline_s: int = 180) -> None:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        try:
            if request("GET", "/health/readiness")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(1)
    raise SystemExit("gateway não ficou pronto a tempo")


def main() -> None:
    wait_ready()
    with open(KEYS_FILE, encoding="utf-8") as file:
        keys = json.load(file)
    for spec in keys:
        spec = dict(spec)
        spec["key"] = os.environ[spec.pop("key_env")]
        status, _ = request("GET", f"/key/info?key={spec['key']}")
        if status == 200:
            # Reaplica os limites e zera o gasto: a configuração versionada é a fonte da verdade.
            status, body = request("POST", "/key/update", {**spec, "spend": 0})
        else:
            status, body = request("POST", "/key/generate", spec)
        if status != 200:
            raise SystemExit(f"falha ao provisionar {spec['key_alias']}: {status} {body}")
        print(f"chave provisionada: {spec['key_alias']}", flush=True)


if __name__ == "__main__":
    main()
