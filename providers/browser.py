"""Ayudas comunes para los proveedores que leen con navegador (Playwright).

`block_heavy_resources(page)`: la página no descarga imágenes, vídeo ni fuentes tipográficas.
Ningún proveedor lee nada de ellos (se leen textos del DOM o JSON) y en la VM (2 vCPU) los
navegadores se turnan de 3 en 3: lo que no se descarga ni se pinta es CPU para los demás
(2026-10-02, fuentes de navegador esperando turno hasta ~2 min por ciclo).

Se filtra por la extensión de la URL con una expresión regular: Playwright solo pasa por Python
las peticiones que encajan, el resto sigue sin parar. `BROWSER_BLOCK_HEAVY=0` lo desactiva.
"""

import os
import re

_HEAVY_URL = re.compile(
    r"\.(?:png|jpe?g|gif|webp|avif|svg|ico|bmp|woff2?|ttf|otf|eot|mp4|webm|ogg|mp3|m3u8)(?:[?#].*)?$",
    re.IGNORECASE,
)


def blocking_enabled() -> bool:
    return os.environ.get("BROWSER_BLOCK_HEAVY", "1") != "0"


async def _abort(route) -> None:
    await route.abort()


async def block_heavy_resources(page):
    """Corta en `page` las descargas de imágenes, vídeo y fuentes. Devuelve la página."""
    if blocking_enabled():
        await page.route(_HEAVY_URL, _abort)
    return page
