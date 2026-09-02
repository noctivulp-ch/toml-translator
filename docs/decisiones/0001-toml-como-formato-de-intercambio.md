# ADR 0001 — TOML como formato de intercambio

**Estado:** aceptado

## Contexto

El sistema tiene tres etapas en dos lenguajes (Ruby para extraer/inyectar, Python para
traducir) y una etapa intermedia manual: un humano revisa y corrige la salida de la IA.

## Decisión

Usar TOML plano con array de tablas `[[entry]]` como frontera entre etapas, con un
campo `translated` vacío que marca el trabajo pendiente.

## Alternativas descartadas

- **JSON** — no admite comentarios (el extractor los usa como cabecera) y el escapado de
  multilínea lo hace ilegible para edición manual.

- **PO/gettext** — estándar del sector y con buen tooling, pero requiere una dependencia
  en ambos lenguajes y su modelo (msgid = texto fuente) choca con los IDs posicionales
  de mapa que el inyector necesita para localizar el comando exacto.

- **SQLite** — mejor para el estado, pero no se puede diffear en git ni editar a mano, que
  eran los dos requisitos duros.

## Consecuencias

- El estado del trabajo vive en el archivo: no hay base de datos ni índice que sincronizar,
  y reanudar es volver a lanzar el comando.

- El progreso es visible en `git diff`.
- Se paga con un parser propio en Python (ver ADR 0002) y otro en Ruby.
