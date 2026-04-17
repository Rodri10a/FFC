import json
import time
import requests
from requests.exceptions import RequestException, Timeout

AIRTABLE_URL = "https://api.airtable.com/v0/appXXXXXXXXXXXXXX/Reuniones"
AIRTABLE_TOKEN = "patXXXXXXXXXXXXXX.ejemplo_bearer_token"


class PayloadInvalidoError(Exception):
    pass


class AirtableNoDisponibleError(Exception):
    pass


class CircuitBreaker:
    def __init__(self, fail_threshold=3, cooldown_seconds=60):
        self.fail_threshold = fail_threshold
        self.cooldown_seconds = cooldown_seconds
        self.fail_count = 0
        self.opened_at = None

    def esta_abierto(self):
        if self.opened_at is None:
            return False
        if time.time() - self.opened_at >= self.cooldown_seconds:
            self.reset()
            return False
        return True

    def registrar_fallo(self):
        self.fail_count += 1
        if self.fail_count >= self.fail_threshold:
            self.opened_at = time.time()

    def registrar_exito(self):
        self.reset()

    def reset(self):
        self.fail_count = 0
        self.opened_at = None


breaker = CircuitBreaker(fail_threshold=3, cooldown_seconds=60)


def parsear_reunion(payload: dict) -> dict:
    data = payload.get("data", payload)

    client_name = data.get("client_name")
    summary = data.get("summary")
    action_items = data.get("action_items")

    if not client_name or not summary:
        raise PayloadInvalidoError("Faltan 'client_name' o 'summary'.")

    if action_items is None:
        action_items_texto = ""
    elif not isinstance(action_items, list):
        raise PayloadInvalidoError("'action_items' debe ser una lista.")
    else:
        action_items_texto = "\n".join(f"- {item}" for item in action_items)

    return {
        "client_name": client_name,
        "summary": summary,
        "action_items": action_items_texto,
    }


def enviar_a_airtable(payload: dict) -> dict:
    if breaker.esta_abierto():
        raise AirtableNoDisponibleError(
            "Circuit breaker ABIERTO: demasiados fallos recientes, esperando cooldown."
        )

    try:
        campos = parsear_reunion(payload)
    except PayloadInvalidoError as e:
        print(f"[ERROR DE PAYLOAD] {e}")
        raise

    body = {
        "fields": {
            "Cliente": campos["client_name"],
            "Resumen": campos["summary"],
            "Action Items": campos["action_items"],
        }
    }

    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(AIRTABLE_URL, json=body, headers=headers, timeout=10)
    except (Timeout, RequestException) as e:
        breaker.registrar_fallo()
        raise AirtableNoDisponibleError(f"Fallo de red contra Airtable: {e}")

    if 500 <= r.status_code < 600:
        breaker.registrar_fallo()
        raise AirtableNoDisponibleError(
            f"Airtable respondió {r.status_code}: {r.text}"
        )

    if not r.ok:
        raise PayloadInvalidoError(
            f"Airtable rechazó el request ({r.status_code}): {r.text}"
        )

    breaker.registrar_exito()
    return r.json()


if __name__ == "__main__":
    with open("examples.json", "r", encoding="utf-8") as f:
        payload = json.load(f)

    try:
        resultado = enviar_a_airtable(payload)
        print("[OK] Registro creado en Airtable:", resultado)
    except PayloadInvalidoError as e:
        print(f"[PAYLOAD INVALIDO] {e}")
    except AirtableNoDisponibleError as e:
        print(f"[AIRTABLE CAIDO] {e}")
