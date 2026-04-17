# FFC — Integración Webhook → Airtable

Prueba técnica para **First Class Citizen (FFC)**. Script en Python que recibe un JSON de una reunión
finalizada (webhook de tipo `meeting_completed`), lo parsea, lo transforma y
lo envía a Airtable como un nuevo registro, con manejo de errores robusto y
un circuit breaker para evitar martillar la API cuando está caída.

## Contenido

| Archivo | Propósito |
|---|---|
| `script.py` | Lógica principal: parsing, POST a Airtable, circuit breaker |
| `test_script.py` | Suite de tests (8 casos) con mocks de `requests` |
| `examples.json` | Payload de ejemplo del webhook |
| `.gitignore` | Excluye `__pycache__/`, `*.pyc`, `.env` |

## Requisitos

- Python 3.9+
- `requests`

```bash
pip install requests
```

## Uso

1. Editar `script.py` y reemplazar las constantes con valores reales:

```python
AIRTABLE_URL   = "https://api.airtable.com/v0/TU_BASE_ID/NombreDeTabla"
AIRTABLE_TOKEN = "patXXXX.TUTOKENREAL"
```

2. Asegurarse de que la tabla tiene los campos: `Cliente`, `Resumen`,
   `Action Items`.

3. Ejecutar:

```bash
python script.py
```

Salida esperada en caso de éxito:

```
[OK] Registro creado en Airtable: {'id': 'recXXXX...', 'fields': {...}}
```

## Lógica de parsing

Entrada (`examples.json`):

```json
{
  "event": "meeting_completed",
  "data": {
    "client_name": "Gianmarco",
    "summary": "Discusión sobre la renovación de mobiliario...",
    "action_items": [
      "Enviar cotización de sillas a Carlos.",
      "Revisar contrato de arrendamiento."
    ]
  }
}
```

Transformación:

- `client_name` → campo `Cliente`
- `summary` → campo `Resumen`
- `action_items[]` → se unen con `\n` y prefijo `- ` en un único bloque de
  texto que va al campo `Action Items`

## Manejo de errores

Dos excepciones custom distinguen **errores nuestros** de **errores del
servicio externo**:

| Situación | Excepción | Reintento |
|---|---|---|
| Falta `client_name` o `summary` | `PayloadInvalidoError` | No |
| `action_items` no es lista | `PayloadInvalidoError` | No |
| Falta `action_items` | Se trata como lista vacía | — |
| Airtable responde 4xx | `PayloadInvalidoError` | No |
| Airtable responde 5xx | `AirtableNoDisponibleError` | Sí |
| Timeout / red caída | `AirtableNoDisponibleError` | Sí |

La separación importa: un 4xx indica que el request está mal armado y
reintentarlo es inútil; un 5xx o timeout son transitorios y tiene sentido
reintentar con backoff.

## Circuit breaker

Para evitar bombardear a Airtable cuando está caída, hay un breaker simple:

- **Umbral:** 3 fallos consecutivos → el breaker se abre.
- **Cooldown:** 60 segundos. Durante ese tiempo, cualquier llamada falla
  inmediatamente con `AirtableNoDisponibleError` sin tocar la red.
- **Auto-reset:** pasado el cooldown, se permite un request; si sale bien,
  el contador vuelve a cero.
- **Solo cuentan fallos de infraestructura** (5xx, timeouts). Los 4xx no
  disparan el breaker porque son culpa del payload, no del servicio.

```python
class CircuitBreaker:
    def __init__(self, fail_threshold=3, cooldown_seconds=60): ...
```

## Tests

```bash
python test_script.py
```

Cubre 8 casos con `unittest.mock` (no hace requests reales):

- Parseo válido desde `examples.json`
- Campos obligatorios faltantes
- `action_items` ausente o con tipo inválido
- Respuesta 500 de Airtable
- El breaker se abre tras 3 fallos y corta el 4° request
- Un éxito resetea el contador
- 4xx no cuenta para el breaker

Salida:

```
OK  parseo valido desde examples.json
OK  falta client_name -> PayloadInvalidoError
OK  falta action_items -> string vacio
OK  action_items no-lista -> PayloadInvalidoError
OK  Airtable 500 -> AirtableNoDisponibleError
OK  circuit breaker abre tras 3 fallos y corta el 4to request
OK  exito resetea el contador del breaker
OK  Airtable 4xx -> PayloadInvalidoError (no cuenta para breaker)

Todos los tests pasaron (8/8)
```

## Probar con Postman

**POST** `https://api.airtable.com/v0/{BASE_ID}/Reuniones`

Headers:

```
Authorization: Bearer {TOKEN}
Content-Type: application/json
```

Body:

```json
{
  "fields": {
    "Cliente": "Gianmarco",
    "Resumen": "Discusión sobre la renovación de mobiliario y descuento en alquiler.",
    "Action Items": "- Enviar cotización de sillas a Carlos.\n- Revisar contrato de arrendamiento."
  }
}
```

## Decisiones de diseño

- **Dos excepciones en vez de una** para que el caller decida qué reintentar.
- **`action_items` ausente ≠ error**: una reunión puede no generar tareas.
  No romper por eso.
- **Circuit breaker in-process y simple**: suficiente para un único worker.
  Para varios procesos habría que mover el estado a Redis.
- **Token hardcodeado en el ejemplo** solo para la demo. En producción iría
  en una variable de entorno (`os.getenv("AIRTABLE_TOKEN")`).
