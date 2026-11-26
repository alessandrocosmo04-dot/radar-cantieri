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
