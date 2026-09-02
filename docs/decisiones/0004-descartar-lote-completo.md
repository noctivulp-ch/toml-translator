# ADR 0004 — Descartar el lote entero ante desajuste de líneas

**Estado:** aceptado

## Contexto

Las traducciones se envían en lotes numerados y se mapean de vuelta **por posición**.

Si se piden 10 líneas y el modelo devuelve 9, asignar por posición desplaza todas las
traducciones a partir del hueco: el diálogo del NPC 4 acaba en el NPC 3, y así hasta el
final del lote.

Es un fallo silencioso: el TOML queda bien formado, `errors.log` limpio, y el problema
solo se ve jugando.

## Decisión

`parse_numbered_response` devuelve `None` si el número de
líneas parseadas no es **exactamente** el esperado. `translate_batch` reintenta y, si
persiste, marca las 10 entradas como `FAIL`.

Intenta dos estrategias antes de rendirse: parsear solo las líneas con prefijo ordinal, y
si eso no cuadra, tomar todas las líneas no vacías quitándoles el ordinal si lo tienen.

## Consecuencias

- Se pierden traducciones válidas: si 9 de 10 estaban bien, se descartan las 9.
- A cambio, **es imposible** que una traducción acabe en la entrada equivocada.
- Las entradas fallidas quedan con `translated = ""`, así que la siguiente corrida las
  vuelve a intentar sin intervención.

- Con lotes grandes y modelos pequeños el desperdicio crece rápido — es la razón del
  default de 10 en Ollama frente a 50 en cloud.
