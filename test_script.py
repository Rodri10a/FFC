import json
from unittest.mock import patch, MagicMock

import script
from script import (
    parsear_reunion,
    enviar_a_airtable,
    PayloadInvalidoError,
    AirtableNoDisponibleError,
    CircuitBreaker,
)


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = json_data or {"id": "recFAKE", "fields": {}}
    resp.text = text
    return resp


def reset_breaker():
    script.breaker = CircuitBreaker(fail_threshold=3, cooldown_seconds=60)


def test_parseo_valido_desde_examples_json():
    with open("examples.json", "r", encoding="utf-8") as f:
        payload = json.load(f)

    campos = parsear_reunion(payload)

    assert campos["client_name"] == "Gianmarco"
    assert "mobiliario" in campos["summary"]
    assert campos["action_items"] == (
        "- Enviar cotización de sillas a Carlos.\n"
        "- Revisar contrato de arrendamiento."
    )
    print("OK  parseo valido desde examples.json")


def test_falta_client_name():
    payload = {"data": {"summary": "algo", "action_items": []}}
    try:
        parsear_reunion(payload)
    except PayloadInvalidoError:
        print("OK  falta client_name -> PayloadInvalidoError")
        return
    raise AssertionError("Deberia haber lanzado PayloadInvalidoError")


def test_falta_action_items_es_string_vacio():
    payload = {"data": {"client_name": "X", "summary": "Y"}}
    campos = parsear_reunion(payload)
    assert campos["action_items"] == ""
    print("OK  falta action_items -> string vacio")


def test_action_items_no_es_lista():
    payload = {"data": {"client_name": "X", "summary": "Y", "action_items": "mal"}}
    try:
        parsear_reunion(payload)
    except PayloadInvalidoError:
        print("OK  action_items no-lista -> PayloadInvalidoError")
        return
    raise AssertionError("Deberia haber lanzado PayloadInvalidoError")


def test_airtable_500_lanza_no_disponible():
    reset_breaker()
    payload = {"data": {"client_name": "X", "summary": "Y", "action_items": ["a"]}}

    with patch("script.requests.post", return_value=_mock_response(500, text="boom")):
        try:
            enviar_a_airtable(payload)
        except AirtableNoDisponibleError:
            print("OK  Airtable 500 -> AirtableNoDisponibleError")
            return
    raise AssertionError("Deberia haber lanzado AirtableNoDisponibleError")


def test_circuit_breaker_se_abre_tras_3_fallos():
    reset_breaker()
    payload = {"data": {"client_name": "X", "summary": "Y", "action_items": ["a"]}}

    with patch("script.requests.post", return_value=_mock_response(500, text="boom")):
        for i in range(3):
            try:
                enviar_a_airtable(payload)
            except AirtableNoDisponibleError:
                pass

    assert script.breaker.esta_abierto(), "El breaker deberia estar ABIERTO"

    try:
        enviar_a_airtable(payload)
    except AirtableNoDisponibleError as e:
        assert "Circuit breaker ABIERTO" in str(e)
        print("OK  circuit breaker abre tras 3 fallos y corta el 4to request")
        return
    raise AssertionError("El 4to request deberia haber sido cortado por el breaker")


def test_exito_resetea_breaker():
    reset_breaker()
    payload = {"data": {"client_name": "X", "summary": "Y", "action_items": ["a"]}}

    with patch("script.requests.post", return_value=_mock_response(500, text="boom")):
        for _ in range(2):
            try:
                enviar_a_airtable(payload)
            except AirtableNoDisponibleError:
                pass

    assert script.breaker.fail_count == 2

    with patch("script.requests.post", return_value=_mock_response(200)):
        enviar_a_airtable(payload)

    assert script.breaker.fail_count == 0
    assert not script.breaker.esta_abierto()
    print("OK  exito resetea el contador del breaker")


def test_airtable_4xx_lanza_payload_invalido():
    reset_breaker()
    payload = {"data": {"client_name": "X", "summary": "Y", "action_items": ["a"]}}

    with patch("script.requests.post", return_value=_mock_response(422, text="bad field")):
        try:
            enviar_a_airtable(payload)
        except PayloadInvalidoError:
            print("OK  Airtable 4xx -> PayloadInvalidoError (no cuenta para breaker)")
            assert script.breaker.fail_count == 0
            return
    raise AssertionError("Deberia haber lanzado PayloadInvalidoError")


if __name__ == "__main__":
    tests = [
        test_parseo_valido_desde_examples_json,
        test_falta_client_name,
        test_falta_action_items_es_string_vacio,
        test_action_items_no_es_lista,
        test_airtable_500_lanza_no_disponible,
        test_circuit_breaker_se_abre_tras_3_fallos,
        test_exito_resetea_breaker,
        test_airtable_4xx_lanza_payload_invalido,
    ]

    fallos = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            fallos += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            fallos += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")

    print("\n" + "=" * 40)
    if fallos == 0:
        print(f"Todos los tests pasaron ({len(tests)}/{len(tests)})")
    else:
        print(f"{len(tests) - fallos}/{len(tests)} OK, {fallos} fallaron")
