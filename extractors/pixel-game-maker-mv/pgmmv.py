#!/usr/bin/env python3
"""
pgmmv.py — lectura y escritura de project.json de Pixel Game Maker MV.

Módulo compartido por extract.py e inject.py. No se ejecuta directamente.

Formato del recurso cifrado (lo aplica el motor al exportar, no es una decisión
del autor del juego — los tres juegos analizados venían así):

    b"enc" + <1 byte de relleno> + Twofish-CBC(plaintext + padding)

La clave vive junto al archivo, en `data/info.json`, campo "key": base64 de la
clave cifrada con "weakfish". No está escondida en el ejecutable.

Descifrar requiere el paquete `pgmm_decrypt`:
    pip install git+https://github.com/blluv/pgmm_decrypt.git

Si no está instalado, ambos scripts siguen funcionando con un project.json ya
descifrado (`--json`).
"""

import base64
import json
from pathlib import Path

PGMM_IV = bytes.fromhex("A047E93D230A4C62A744B1A4EE857FBA")
BLOCK = 16
VALID_KEY_LENS = (32, 24, 16)


def _pgmm():
    try:
        import pgmm_decrypt
        return pgmm_decrypt
    except ImportError:
        return None


def normalize_key(key):
    """
    Twofish acepta claves de 16, 24 o 32 bytes. PGMMV entrega la clave en un buffer
    con relleno de ceros que a veces mide 48 (visto en un juego de 2026), así que se
    recorta a la longitud válida más grande que quepa.
    """
    for n in VALID_KEY_LENS:
        if len(key) >= n:
            return key[:n]
    raise ValueError(f"clave demasiado corta: {len(key)} bytes")


def load_key(data_dir):
    """Devuelve la clave Twofish lista para usar, leída de data/info.json."""
    pg = _pgmm()
    if pg is None:
        raise RuntimeError(
            "Falta el paquete pgmm_decrypt para descifrar.\n"
            "  pip install git+https://github.com/blluv/pgmm_decrypt.git\n"
            "O pasa un project.json ya descifrado con --json.")
    info = json.loads(Path(data_dir, "info.json").read_text(encoding="utf-8"))
    return normalize_key(pg.decrypt_pgmm_key(base64.b64decode(info["key"])))


def read_project(data_dir=None, json_path=None):
    """
    Carga project.json, descifrándolo si hace falta.
    Devuelve (dict, key_o_None). La clave se devuelve para poder re-cifrar igual.
    """
    if json_path:
        raw = Path(json_path).read_bytes()
        if raw[:3] != b"enc":
            return json.loads(raw.decode("utf-8")), None
        data_dir = data_dir or Path(json_path).parent

    path = Path(data_dir, "project.json")
    raw = raw if json_path else path.read_bytes()

    if raw[:3] != b"enc":
        return json.loads(raw.decode("utf-8")), None

    key = load_key(data_dir)
    plain = _pgmm().decrypt_pgmm_resource(raw, key)
    return json.loads(plain.decode("utf-8")), key


def encrypt_project(plain_bytes, key):
    """
    Re-cifra con el mismo esquema del motor: Twofish-CBC con el IV fijo de PGMMV,
    relleno a múltiplo de bloque, y el número de bytes de relleno en la cabecera.

    Es la inversa exacta de pgmm_decrypt.decrypt_pgmm_resource.
    """
    from pgmm_decrypt.decrypt import derive_subkey
    from pgmm_decrypt.twofish import Twofish
    from pgmm_decrypt.utils import pad, xor_block

    pt_len = len(plain_bytes)
    padded = pad(plain_bytes, BLOCK)
    pad_len = len(padded) - pt_len

    cipher = Twofish(derive_subkey(key, pt_len))
    out = bytearray()
    prev = PGMM_IV
    for off in range(0, len(padded), BLOCK):
        block = xor_block(padded[off:off + BLOCK], prev)
        enc = cipher.encrypt(bytes(block))
        out += enc
        prev = enc
    return b"enc" + bytes([pad_len]) + bytes(out)


def write_project(project, out_path, key=None):
    """
    Escribe project.json. Con `key` lo cifra como lo hace el motor; sin ella lo deja
    en texto plano — el cargador trata como plano cualquier archivo que no empiece
    por "enc", así que ambas formas deberían arrancar.
    """
    blob = json.dumps(project, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if key:
        blob = encrypt_project(blob, key)
    Path(out_path).write_bytes(blob)
    return len(blob)


# ─────────────────────────────────────────────────────────────────────────────
# Recorrido de textList
#
# textList es un árbol: los nodos con folder=true llevan `children`, y las hojas
# llevan `text`, que es un dict {locale: texto}. Traducir es AÑADIR una clave de
# locale a ese dict — el original nunca se pisa.
# ─────────────────────────────────────────────────────────────────────────────

def iter_texts(project):
    """Genera (nodo, ruta_de_carpetas) por cada hoja de texto de textList."""
    def walk(nodes, path):
        for n in nodes:
            if not isinstance(n, dict):
                continue
            if n.get("folder"):
                yield from walk(n.get("children", []), path + [n.get("name", "?")])
            elif isinstance(n.get("text"), dict):
                yield n, path
    yield from walk(project.get("textList", []), [])


def game_locales(project):
    info = project.get("gameInformation", {})
    return info.get("language", []), info.get("mainLanguage", project.get("initialLocale"))
