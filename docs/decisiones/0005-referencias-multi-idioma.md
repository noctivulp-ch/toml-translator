# ADR 0005 — Referencias multi-idioma por convención de nombre

**Estado:** aceptado

## Contexto

Muchos juegos ya están traducidos a varios idiomas. Cuando el inglés es ambiguo, las
traducciones existentes suelen desambiguar:

- `"You got it!"` — ¿"lo conseguiste" o "entendido"? El japonés lo aclara.
- Género y número de un sustantivo que en inglés es invariable.
- Registro formal/informal, que el inglés no marca y el francés sí.

El requisito del usuario fue explícito: **que funcione igual con 2 idiomas que con 5**,
sin configuración por archivo.

## Decisión

Cualquier campo cuyo nombre case con `original_<lang>` es una fuente de referencia.

`discover_ref_langs` (toml-translator.py) las descubre por archivo y `--refs auto`
—el default— las usa todas.

```toml
original    = "Welcome home, [JUGADOR]!"
original_ja = "おかえりなさい、[JUGADOR]！"
original_fr = "Bienvenue à la maison, [JUGADOR] !"
```

## Alternativas descartadas

- **Un array `refs = [...]`** — el parser TOML propio (ADR 0002) no soporta arrays, y
  añadirlos obligaría a extender también el escritor y el extractor.

- **Una tabla anidada `[entry.refs]`** — mismo problema, y rompe el formato plano que
  hace el TOML legible a mano.

- **Un flag que declare los idiomas** — obliga a saber de antemano qué tiene cada archivo.
  El requisito era justo lo contrario.

La convención de nombre no cuesta nada: el parser ya acepta `^(\w+)\s*=` para cualquier
clave, así que los extractores pueden emitir estos campos hoy sin cambiar una línea del
traductor.

## Formato del prompt

Un solo número por entrada, con las variantes indentadas debajo:

```
1. [EN] Welcome home, [JUGADOR]!
   [FR] Bienvenue à la maison, [JUGADOR] !
```

Se mantiene **una respuesta numerada por entrada**: no cambia el contrato de
`parse_numbered_response` ni la garantía del ADR 0004. La indentación de las variantes es
lo que impide que el modelo las confunda con entradas nuevas.

## Consecuencias

- Coste en contexto proporcional al número de idiomas: con 3 referencias el prompt casi
  se triplica. Con `--num-ctx 2048` eso obliga a bajar `--batch`. Medido en
  [`../benchmarks.md`](../benchmarks.md).

- Entradas heterogéneas conviven: una entrada con 3 idiomas y otra con 1 en el mismo lote
  funcionan; las referencias ausentes simplemente se omiten.

- `--refs none` recupera exactamente el comportamiento anterior, byte a byte.
- DeepL las ignora: su API traduce texto suelto, no acepta prompt.
