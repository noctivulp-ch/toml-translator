# ADR 0008 — Enrutado por contenido, no por longitud

**Estado:** aceptado

## Contexto

La idea inicial era elegir modelo según **complejidad y longitud** del texto: líneas
cortas de UI al modelo pequeño, diálogo largo al grande.

Los benchmarks del 2026-09-02 desmontaron esa premisa:

- **Un modelo más grande no rinde mejor.** `gemma4:e4b` colapsa en lotes de 20 donde
  `gemma4:e2b` llega a 30, y tarda el doble. La longitud del texto no predice nada útil.
- **El verdadero límite era `--num-ctx`**, no la longitud: subirlo de 2048 a 8192 mueve el
  techo de lote 20 a más de 50 en el mismo modelo.

Lo que sí divide a los modelos es **qué tipo de contenido estropean**:

| Modelo | Velocidad | Tokens de prompt | Suavizado en contenido explícito |
|---|---|---|---|
| `translategemma:4b` | 4 s | 294 | **75%** |
| `gemma4:e2b-Uncensored` | 11 s | 688 | 0% |
| `gemma4:e2b` | 23 s | 688 | 0% |

`translategemma:4b` traduce `"fucked her"` como `"la besaba"` y `"rode him"` como
`"él la besó"` — invirtiendo hasta el sujeto. No rechaza, no deja nada sin traducir, y
devuelve N líneas numeradas perfectas: **pasa todas las métricas automáticas**.

## Decisión

Enrutar por **contenido de la línea**, con `--routing` y un TOML de reglas evaluadas en
orden (primera que casa gana; la última sin condiciones es el fallback).

```toml
[[route]]
name   = "explicito"
model  = "Librellama/gemma4:e2b-Uncensored"
prompt = "../prompts/pokemon-es.toml"
match  = "\\b(fuck\\w*|cock|cum|thrust\\w*|moan\\w*)\\b"

[[route]]
name   = "general"
model  = "translategemma:4b"
prompt = "../prompts/translategemma-es.toml"
```

Cada ruta lleva **su propio prompt**, no solo su modelo: el estilo va atado a la familia
(ADR 0007). Una ruta a translategemma sin su prompt nativo desperdicia el fine-tune.

Condiciones disponibles: `match` (regex), `min_chars`, `max_chars`, `min_markers`.
Las de longitud existen porque son baratas de ofrecer, no porque los datos las respalden.

## Por qué el sesgo va hacia el modelo fiel

Las reglas están escritas para que **ante la duda caiga en el modelo fiel**. La asimetría
del coste lo justifica:

- Enrutar de más al fiel cuesta **tiempo**.
- Enrutar de menos cuesta **texto censurado que ninguna métrica detecta** — solo se
  descubre leyendo la traducción final, cuando ya está inyectada en el juego.

## Consecuencias

- Una corrida usa varios modelos, y Ollama los carga y descarga por turnos. Agrupar por
  ruta (en vez de alternar por entrada) minimiza esos intercambios.
- Agrupar **no altera el archivo de salida**: `write_translated` indexa por `id`, no por
  posición.
- El coste de mantenimiento se traslada a la regex: un término explícito que no esté en la
  lista cae en el modelo rápido y sale suavizado, en silencio. La lista es la parte frágil
  del diseño y hay que revisarla al cambiar de juego.
- Sin `--routing` el comportamiento es idéntico al anterior.

## Alternativa descartada

**Clasificar el contenido con un modelo**, en vez de con regex. Más preciso, pero duplica
las llamadas y añade un segundo punto de fallo silencioso: un clasificador que se equivoca
manda la línea al modelo que la va a censurar, con el mismo resultado invisible. Una regex
es auditable de un vistazo y no cuesta una llamada.
