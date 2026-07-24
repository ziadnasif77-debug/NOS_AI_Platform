# -*- coding: utf-8 -*-
"""Hendelsesstrøm for direktevisningen («røntgen»-vinduet).

OCR-kjeden sender små hendelser HER underveis (side rendret, forbehandlet,
regioner funnet, hver norhand-lesing, andrepasset ...), og /innsyn-
arbeideren samler dem så GUI-vinduet kan tegne prosessen MENS den skjer.

Trådlokalt: hver forespørsel aktiverer sin egen sink i SIN tråd. Når ingen
sink er aktiv (alle vanlige forespørsler) er send() en ren no-op — null
kostnad og null oppførselsjendring for resten av systemet.
"""
import threading
import time

_lokal = threading.local()


def aktiver(liste: list) -> None:
    """Kobler denne tråden til en hendelsesliste (GUI-poll leser den)."""
    _lokal.sink = liste


def deaktiver() -> None:
    _lokal.sink = None


def aktiv() -> bool:
    """Er en sink aktiv i denne tråden? (Brukes for å hoppe over dyre
    forberedelser — som bildekoding — når ingen ser på.)"""
    return getattr(_lokal, "sink", None) is not None


def send(type_: str, **data) -> None:
    """Legger til en hendelse hvis en sink er aktiv i denne tråden.
    Feiler ALDRI — direktevisning er pynt, aldri et krav."""
    sink = getattr(_lokal, "sink", None)
    if sink is None:
        return
    try:
        hendelse = {"type": type_, "tid": round(time.time(), 3)}
        hendelse.update(data)
        sink.append(hendelse)
    except Exception:
        pass
