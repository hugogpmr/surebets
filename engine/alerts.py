"""Avisos de administración: fuentes que llevan varios ciclos muertas (y cuando se recuperan).

Va aparte de `engine/health.py`: aquel solo sigue a las fuentes de navegador y borra su racha al
recuperarse; esto sigue a TODAS (también Altenar, Kambi...) y recuerda si ya avisó, para mandar un
solo mensaje al morir y otro al volver, no uno por ciclo. Los avisos van a un canal privado
distinto del de surebets (config.ADMIN_ALERT_CHAT_ID).

El estado va en `cache/` (fuera de git) porque es de cada máquina: la VM y el PC del usuario ven
fuentes distintas muertas (ver engine/health.py).
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_PATH = "cache/source_alerts.json"


class SourceAlerts:
    """`alert_after`: ciclos seguidos malos (fallo o 0 mercados) antes de avisar. 0 = desactivado.
    `ignore`: fuentes que nunca avisan (p.ej. una sin credenciales, vacía por diseño)."""

    def __init__(self, path: str = DEFAULT_PATH, alert_after: int = 3, ignore: frozenset[str] = frozenset()):
        self.path = path
        self.alert_after = alert_after
        self.ignore = ignore
        self._entries: dict[str, dict] = {}
        try:
            with open(path, encoding="utf-8") as f:
                for name, entry in json.load(f).items():
                    self._entries[name] = {"bad": int(entry["bad"]), "alerted": bool(entry["alerted"])}
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError, OSError):
            logger.warning("No se pudo leer %s: se empieza sin historial de avisos", path, exc_info=True)
            self._entries = {}

    def update(self, sources: dict[str, dict]) -> str | None:
        """Anota el ciclo (`sources` con la forma de `_run_scan_cycle`: ok/markets/parked) y devuelve
        el texto del aviso si alguna fuente acaba de morir o de recuperarse; None si no hay nada
        nuevo. Las aparcadas no se leyeron este ciclo, así que no cuentan ni a favor ni en contra."""
        if not self.alert_after:
            return None
        died: list[tuple[str, int]] = []
        recovered: list[str] = []
        for name, info in sources.items():
            if name in self.ignore or info.get("parked"):
                continue
            entry = self._entries.setdefault(name, {"bad": 0, "alerted": False})
            if info.get("ok") and info.get("markets", 0) > 0:
                if entry["alerted"]:
                    recovered.append(name)
                entry["bad"], entry["alerted"] = 0, False
                continue
            entry["bad"] += 1
            if entry["bad"] >= self.alert_after and not entry["alerted"]:
                entry["alerted"] = True
                died.append((name, entry["bad"]))
        self._save()
        if not died and not recovered:
            return None
        lines = []
        if died:
            lines.append("🔴 Fuentes sin datos:")
            lines += [f"• {name}: {bad} ciclos seguidos con 0 mercados o fallando" for name, bad in died]
        if recovered:
            lines.append("🟢 Fuentes recuperadas:")
            lines += [f"• {name}" for name in recovered]
        return "\n".join(lines)

    def _save(self) -> None:
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, indent=2)
        except OSError:
            logger.warning("No se pudo guardar %s", self.path, exc_info=True)
