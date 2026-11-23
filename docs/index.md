# Documentación — toml-translator

Traductor de archivos TOML de extracción mediante IA local (Ollama) o cloud.

Agnóstico al motor de juego: el TOML es el contrato entre extractores e IA.

## Por dónde empezar

| Si quieres… | Lee |
|---|---|
| Usarlo ya | [`../README.md`](../README.md) |
| Entender cómo encaja todo | [`arquitectura/pipeline.md`](arquitectura/pipeline.md) |
| Tocar el código Python | [`funciones/traductor.md`](funciones/traductor.md) |
| Escribir un prompt nuevo | [`funciones/prompts.md`](funciones/prompts.md) |
| Traducir un juego RPG Maker XP | [`../extractors/rpg-maker-xp/README.md`](../extractors/rpg-maker-xp/README.md) |
| Traducir un juego Pixel Game Maker MV | [`../extractors/pixel-game-maker-mv/README.md`](../extractors/pixel-game-maker-mv/README.md) |
| Saber por qué algo es así | [`decisiones/`](decisiones/) |
| Elegir modelo local y tamaño de lote | [`benchmarks.md`](benchmarks.md) |
| Ver qué juegos están traducidos | [`../traducciones/`](../traducciones/) |
| Ver qué está roto | [`../issues.md`](../issues.md) |

## Mapa del repositorio

```
toml-translator/
├── toml-translator.py          ← el traductor (stdlib pura, ~580 líneas)
├── prompts/
│   ├── generic-game-es.toml    ← base: español latino
│   ├── pokemon-es.toml         ← extiende con glosario Pokémon + explícito
│   └── translategemma-es.toml  ← formato nativo TranslateGemma
├── glossaries/
│   └── pokemon-es.toml         ← términos canónicos (filtrado por lote)
├── routing/
│   └── pokemon-es.toml         ← qué modelo traduce qué tipo de línea
├── traducciones/
│   └── <juego>/                ← README + glosario/enrutado propios del juego
├── scripts/
│   ├── bench_batch.py          ← aguante por tamaño de lote
│   ├── bench_content.py        ← tolerancia a contenido adulto
│   ├── bench_classifier.py     ← precisión del clasificador de contenido
│   └── verify_features.py      ← checks sin red (1 s), correr antes de tocar el script
├── extractors/
│   ├── rpg-maker-xp/           ← extract / inject / diff (Ruby)
│   └── pixel-game-maker-mv/    ← extract / inject (Python, cocos2d-x)
├── docs/
│   ├── arquitectura/pipeline.md
│   ├── funciones/{traductor,prompts}.md
│   ├── benchmarks.md           ← metodología + resultados medidos
│   └── decisiones/000N-*.md    ← ADRs
├── issues.md                   ← problemas conocidos
└── README.md
```

## Flujo completo, de una vez

```bash
GAME=/ruta/al/juego
ruby extractors/rpg-maker-xp/extract.rb "$GAME"
python toml-translator.py \
  --api ollama \
  --prompt prompts/pokemon-es.toml \
  "$GAME"/translation/*.toml
cat "$GAME"/translation/errors.log   # ← revisar SIEMPRE antes de inyectar
ruby extractors/rpg-maker-xp/inject.rb "$GAME"
```

Las tres etapas son reanudables: volver a lanzar cualquiera de ellas no duplica trabajo.

## Decisiones registradas

| ADR | Tema |
|---|---|
| [0001](decisiones/0001-toml-como-formato-de-intercambio.md) | TOML como formato de intercambio |
| [0002](decisiones/0002-parser-toml-propio.md) | Parser TOML propio en vez de `tomllib` |
| [0003](decisiones/0003-marcadores-en-brackets.md) | Marcadores `[BRACKETS]` en vez de códigos nativos |
| [0004](decisiones/0004-descartar-lote-completo.md) | Descartar el lote entero ante desajuste de líneas |
| [0005](decisiones/0005-referencias-multi-idioma.md) | Referencias multi-idioma por convención de nombre |
| [0006](decisiones/0006-glosario-filtrado-por-lote.md) | Glosario filtrado por lote |
| [0007](decisiones/0007-estilo-de-prompt-por-modelo.md) | Estilo de prompt por familia de modelo |
| [0008](decisiones/0008-enrutado-por-contenido.md) | Enrutado por contenido, no por longitud |
| [0009](decisiones/0009-clasificador-como-red-de-seguridad.md) | Clasificador como segunda etapa, no como reemplazo |
