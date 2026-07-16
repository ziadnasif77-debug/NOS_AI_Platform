"""
Enhetstester for oppbevaringsbegrensningen (skript/oppbevaring.py).
Rene funksjoner — Postgres/Milvus/filsletting dekkes av live-prosedyren
i docs/OPPBEVARING.md (tørrkjøring + verifisert sletting).
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skript.oppbevaring import (
    beregn_frist, samle_filstier, gyldig_fil_id, slett_filer,
)
from skript.sikkerhetskopi import rydd_utlopte_filer

NAA = datetime(2026, 7, 16, 12, 0, 0)


def test_frist_150_dager():
    frist = beregn_frist(NAA, 150)
    assert frist == NAA - timedelta(days=150)
    assert (NAA - frist).days == 150


def test_samle_filstier_alle_kilder():
    stier = samle_filstier(
        "/data/inntak/original.pdf",
        {"preprocessed_path": "/data/inntak/x_side0.png",
         "side_pdf_sti": "/data/inntak/x_side0.pdf"},
        {"raw_path": "/data/inntak/x_side0.png",   # duplikat av preprocessed
         "clean_path": "/data/behandlet/renset.png"},
    )
    assert stier == [
        "/data/inntak/original.pdf",
        "/data/inntak/x_side0.png",
        "/data/inntak/x_side0.pdf",
        "/data/behandlet/renset.png",
    ]


def test_samle_filstier_taaler_manglende():
    assert samle_filstier(None, None, None) == []
    assert samle_filstier("/a.pdf", {}, {"raw_path": None}) == ["/a.pdf"]


def test_gyldig_fil_id():
    assert gyldig_fil_id("3483d2c0-779d-46be-bfbc-a2243f7e57ef")
    assert not gyldig_fil_id("")
    assert not gyldig_fil_id('x" || fil_id != "')   # injeksjon
    assert not gyldig_fil_id("a" * 201)


def test_slett_filer_torrkjoring_ror_ingenting(tmp_path):
    fil = tmp_path / "dok.pdf"
    fil.write_bytes(b"x")
    antall = slett_filer([str(fil)], torrkjoring=True)
    assert antall == 1
    assert fil.exists()          # tørrkjøring teller, men sletter ikke


def test_slett_filer_ekte(tmp_path):
    fil = tmp_path / "dok.pdf"
    fil.write_bytes(b"x")
    borte = tmp_path / "finnes_ikke.pdf"
    antall = slett_filer([str(fil), str(borte)], torrkjoring=False)
    assert antall == 1
    assert not fil.exists()


def test_backup_speil_rydder_kun_utlopte(tmp_path):
    filer = tmp_path / "filer" / "inntak"
    filer.mkdir(parents=True)
    gammel = filer / "gammel.pdf"
    ny = filer / "ny.pdf"
    gammel.write_bytes(b"g")
    ny.write_bytes(b"n")
    # sett mtime: gammel = 200 dager siden, ny = i dag
    gammel_tid = (NAA - timedelta(days=200)).timestamp()
    os.utime(gammel, (gammel_tid, gammel_tid))

    antall = rydd_utlopte_filer(str(tmp_path), maks_dager=150)
    assert antall == 1
    assert not gammel.exists()
    assert ny.exists()
