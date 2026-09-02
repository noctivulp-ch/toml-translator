# ADR 0002 — Parser TOML propio en vez de `tomllib`

**Estado:** aceptado

## Contexto

Python 3.11 trae `tomllib` en la stdlib, pero es **solo lectura**: no hay serializador.

Escribir el resultado requeriría `tomli-w` o construir el TOML a mano.

## Decisión

Escribir un parser de subconjunto (`parse_toml`) y un escritor
basado en plantilla (`write_translated``) que reescribe el archivo de entrada línea a
línea sustituyendo solo `translated = …`.

## Razón

El requisito no es "leer y escribir TOML", es **modificar una línea sin tocar el resto**.

Un round-trip parse→serializa perdería:

- Los comentarios de cabecera que emite el extractor.
- El orden original de las claves.
- El estilo de escapado y de multilínea.

Ese ruido convertiría cada corrida en un diff de miles de líneas y haría inútil el
control de versiones sobre las traducciones.

Además, mantener cero dependencias fuera de la stdlib es lo que permite ejecutar el
script en cualquier máquina con Python 3.11+ sin entorno virtual.

## Consecuencias

- El parser solo soporta el subconjunto que emiten los extractores: `[[entry]]`, strings,
  multilínea `"""`, enteros. Un TOML válido pero fuera de ese subconjunto (arrays,
  tablas anidadas, floats, booleanos) se ignora silenciosamente.

- El formato del extractor y el parser del traductor están **acoplados**: cambiar la
  serialización en `entry_to_toml` (extract.rb:116) obliga a revisar `parse_toml`.

- `write_translated` usa el input como plantilla, lo que hace que `--output` sea gratis
  pero también que el input deba existir y estar bien formado al escribir.
