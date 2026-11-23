# NITO

Juego doujin japonés de acción para adultos, hecho con Pixel Game Maker MV.

- **Wikipedia:** sin artículo propio. Motor:
  [Pixel Game Maker MV en Steam](https://store.steampowered.com/app/837510)
- **Idiomas:** japonés → español latino
- **Estado:** traducido e inyectado: 124/124 textos, 0 japonés restante, 0 desbordamientos.
  Probado con Heroic: arranca en español.

## Configuración

- `routing.toml`: todo va a `Librellama/gemma4:e2b-Uncensored` con `prompts/japones-es.toml`.
  TranslateGemma se descartó: no sigue instrucciones y devolvió 41 de 124 líneas sin traducir.
- Glosario de UI japonesa genérico: `glossaries/japones-es.toml`.

```bash
python3 toml-translator.py --api ollama \
  --routing traducciones/nito/routing.toml \
  --glossary glossaries/japones-es.toml \
  ...
```

Extracción e inyección (descifrado Twofish, idioma nativo nuevo): `extractors/pixel-game-maker-mv/`.
