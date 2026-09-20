"""Servidor HTTP estático para docs/, igual que "python -m http.server" pero
sin caché: durante desarrollo local editamos style.css/app.js/data.json y el
navegador debe verlos al momento en el siguiente refresco, no servir una
versión vieja de la caché de disco (fue justo lo que pasó con el fix de
modal-overlay[hidden] - el navegador siguió aplicando el CSS cacheado varios
refrescos seguidos porque http.server no manda Cache-Control).
"""

import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    HTTPServer(("127.0.0.1", port), NoCacheHandler).serve_forever()
