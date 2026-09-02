# ADR 0003 — Marcadores `[BRACKETS]` en vez de códigos nativos

**Estado:** aceptado

## Contexto

El texto de RPG Maker XP viene con códigos de control mezclados:

```
\c[6]\b\PN encontró {1}!<br>\v[3] restantes.
```

Pasar eso a un LLM produce resultados malos de forma consistente: traduce los códigos,
los reordena, cambia `\v[3]` por `\v[tres]`, o los omite.

## Decisión

El extractor separa cada string en tres campos antes de traducir
(`preprocess_codes`, extract.rb:173):

| Campo | Contenido |
|---|---|
| `original` | `[JUGADOR] encontró [1]![BR][V3] restantes.` |
| `prefix` | `\b` |
| `codes` | `[JUGADOR]=\PN\|[1]={1}\|[BR]=<br>\|[V3]=\v[3]` |

El inyector revierte con `reconstruct` (inject.rb:173).

## Por qué corchetes en mayúsculas

Son visualmente obvios como "no traducir", el modelo los reconoce como placeholders
sin instrucción especial, y son fáciles de validar con una sola regex
(`MARKER_RE`).

Nombres semánticos en el idioma destino (`[JUGADOR]`, no `[PN]`) porque el modelo
traduce mejor cuando entiende qué representa el hueco: sabe que `[JUGADOR] encontró`
lleva un sujeto y concuerda el verbo.

## Códigos visuales: se descartan

`\c[N]`, `<b>`, `<i>`, `<ac>` y los `\b`/`\r` que no abren el string se **eliminan** y
no se reinyectan (`VISUAL_STRIP_RE`, extract.rb:170).

Son cosméticos: perderlos cambia cómo se ve el texto, no qué dice. Preservarlos exigiría
mapear posiciones dentro de la frase, que el modelo reordena al traducir — el color
acabaría en la palabra equivocada. Se prefiere perder el color a colorear mal.

## Consecuencias

- La IA solo ve texto limpio y respeta los marcadores de forma fiable.
- El mapeo inverso viaja **con cada entrada** (`codes`), no en una tabla global: un
  `{1}` puede significar cosas distintas en strings distintos.

- `reconstruct` es retrocompatible — sin `prefix` ni `codes` devuelve el texto tal cual,
  así que TOMLs de versiones antiguas del extractor siguen funcionando.

- Se pierde el formato visual del texto traducido.
