"""Test dell'archivio e del giro completo (rete finta, pagine vere di Bresso)."""
import csv
import os
import sqlite3
import sys
import tempfile
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(QUI))
import archivio as A  # noqa: E402
import connettori as C  # noqa: E402
import radar  # noqa: E402

BRESSO = "https://servizionline.hspromilaprod.hypersicapp.net/cmsbresso/portale/albopretorio/albopretorioconsultazione.aspx?P=400"


def segnale(id_, fase="progetto", cup="E62B26000380004"):
    return {"istat": "015032", "piattaforma": "sicraweb-cms", "id": id_, "comune": "Bresso", "fase": fase,
            "tipo": "opera_pubblica", "cup": cup, "oggetto": f"LAVORI {id_}", "inizio_pubbl": "2026-11-20"}


class TestArchivio(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = A.apri(os.path.join(self.dir, "t.db"))

    def tearDown(self):
        self.db.close()

    def test_dedup_e_date(self):
        self.assertEqual(A.salva_segnali(self.db, [segnale("1"), segnale("2", "gara_in_partenza")], "2026-11-25"), 2)
        self.assertEqual(A.salva_segnali(self.db, [segnale("2", "gara_in_partenza"), segnale("3", "affidamento")], "2026-11-26"), 1)
        righe = {r["id"]: r for r in self.db.execute("SELECT * FROM segnali")}
        self.assertEqual(len(righe), 3)
        self.assertEqual((righe["2"]["prima_vista"], righe["2"]["ultima_vista"]), ("2026-11-25", "2026-11-26"))
        p = self.db.execute("SELECT * FROM progetti").fetchone()
        self.assertEqual((p["codice"], p["atti"]), ("E62B26000380004", 3))
        self.assertEqual(set(p["fasi"].split(",")), {"progetto", "gara_in_partenza", "affidamento"})

    def test_esporta_solo_nuovi(self):
        A.salva_segnali(self.db, [segnale("1")], "2026-11-25")
        A.salva_segnali(self.db, [segnale("2")], "2026-11-26")
        f = os.path.join(self.dir, "n.csv")
        self.assertEqual(A.esporta(self.db, f, dal="2026-11-26"), 1)
        with open(f, encoding="utf-8") as fh:
            self.assertEqual(len(list(csv.reader(fh, delimiter=";"))), 2)


    def test_versioni_point_in_time(self):
        A.salva_segnali(self.db, [segnale("1", "progetto")], "2026-11-25")
        A.salva_segnali(self.db, [segnale("1", "progetto")], "2026-11-26")      # uguale: nessuna nuova versione
        A.salva_segnali(self.db, [segnale("1", "affidamento")], "2026-11-27")   # cambia fase: nuova versione
        v = self.db.execute("SELECT valida_dal, fase, motivo FROM versioni ORDER BY valida_dal").fetchall()
        self.assertEqual([tuple(x) for x in v], [("2026-11-25", "progetto", "prima_vista"), ("2026-11-27", "affidamento", "riletto")])

    def test_riclassifica_scarta_ma_conserva(self):
        A.salva_segnali(self.db, [segnale("1"), segnale("2")], "2026-11-25")
        finto = lambda a: None if a["oggetto"].endswith("2") else {"tipo": "opera_pubblica", "fase": "collaudo", "cup": "E62B26000380004"}
        self.assertEqual(A.riclassifica(self.db, finto, "2026-11-28"), (1, 1))
        f = os.path.join(self.dir, "e.csv")
        self.assertEqual(A.esporta(self.db, f), 1)
        self.assertEqual(self.db.execute("SELECT scartato_il FROM segnali WHERE id='2'").fetchone()[0], "2026-11-28")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM versioni WHERE id='2'").fetchone()[0], 2)

    def test_archivio_vecchio_si_aggiorna(self):
        vecchio = os.path.join(self.dir, "v.db")
        c = sqlite3.connect(vecchio)
        c.executescript(A.SCHEMA.split(";")[0].replace(" scartato_il TEXT,", "") + ";")
        c.execute("INSERT INTO segnali (istat, piattaforma, id, tipo, prima_vista, ultima_vista) VALUES ('1','p','9','opera_pubblica','2026-11-20','2026-11-20')")
        c.commit(); c.close()
        db = A.apri(vecchio)
        self.assertEqual(db.execute("SELECT valida_dal, tipo FROM versioni").fetchone()[:], ("2026-11-20", "opera_pubblica"))
        db.close()


class TestGiro(unittest.TestCase):
    def setUp(self):
        self._get, self._mappa = C.get, radar.mappa
        with open(os.path.join(QUI, "fixtures", "sicraweb_bresso.html"), encoding="utf-8") as fh:
            pagina = fh.read()

        def finto_get(op, url, data=None):
            if "rotto" in url:
                raise OSError("connessione rifiutata")
            return pagina, url
        C.get = finto_get
        radar.mappa = lambda: [
            {"comune": "Bresso", "istat": "015032", "piattaforma": "sicraweb-cms", "url_albo": BRESSO},
            {"comune": "Rotto", "istat": "999999", "piattaforma": "sicraweb-cms", "url_albo": "https://rotto.example/albo"},
            {"comune": "Senza", "istat": "999998", "piattaforma": "urbi", "url_albo": "https://x.example"},
        ]

    def tearDown(self):
        C.get, radar.mappa = self._get, self._mappa

    def test_giro_completo(self):
        d = tempfile.mkdtemp()
        db = os.path.join(d, "radar.db")
        errori = radar.raccogli(60, db_path=db, uscita=d)
        self.assertEqual(errori, 1)  # il comune rotto non ferma il giro
        con = sqlite3.connect(db)
        n = con.execute("SELECT COUNT(*) FROM segnali").fetchone()[0]
        self.assertGreater(n, 3)
        letture = dict(con.execute("SELECT comune, errore FROM letture").fetchall())
        self.assertIsNone(letture["Bresso"])
        self.assertIn("connessione rifiutata", letture["Rotto"])
        # secondo giro: niente di nuovo, nessun duplicato
        radar.raccogli(60, db_path=db, uscita=d)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM segnali").fetchone()[0], n)
        con.close()
        self.assertTrue(any(f.startswith("nuovi_") for f in os.listdir(d)))


if __name__ == "__main__":
    unittest.main()
