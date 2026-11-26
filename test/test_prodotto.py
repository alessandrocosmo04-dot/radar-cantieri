"""Prodotto: opere per CUP, imprese, point-in-time senza look-ahead, controlli di qualita', incrocio ANAC."""
import os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import anac as N  # noqa: E402
import archivio as A  # noqa: E402
import prodotto as P  # noqa: E402


def s(id_, fase, oggetto, cup=None, cig=None, impresa=None, istat="015032", comune="Bresso", tipo="opera_pubblica", inizio="2026-11-20"):
    return {"istat": istat, "piattaforma": "x", "id": id_, "comune": comune, "fase": fase, "tipo": tipo, "cup": cup,
            "cig": cig, "impresa": impresa, "oggetto": oggetto, "inizio_pubbl": inizio}


class TestProdotto(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.radar = os.path.join(self.d, "radar.db")
        db = A.apri(self.radar)
        A.salva_segnali(db, [
            s("1", "progetto", "LAVORI SCUOLA - CUP E62B26000380004 - APPROVAZIONE PROGETTO ESECUTIVO", cup="E62B26000380004"),
            s("2", "cantiere_aperto", "VIA PALESTRO 41 PER IL GIORNO 19/11/2026 - SOCIETA' SCERRA COSTRUZIONI SNC - ORDINANZA",
              impresa="SCERRA COSTRUZIONI SNC", tipo="cantiere_privato"),
            s("3", "gara_in_partenza", "AVVISO DI GARA LAVORI PONTE", istat="015146", comune="Milano"),
            s("3", "gara_in_partenza", "AVVISO DI GARA LAVORI PONTE", istat="015146", comune="Milano"),
        ], "2026-11-20")
        A.salva_segnali(db, [
            s("4", "affidamento", "LAVORI SCUOLA CUP E62B26000380004 CIG B52F06EFC8 AFFIDAMENTO A EDILE ROSSI S.R.L.",
              cup="E62B26000380004", cig="B52F06EFC8", impresa="EDILE ROSSI S.R.L"),
            s("5", "gara_in_partenza", "AVVISO DI GARA LAVORI PONTE", istat="015032", comune="Bresso"),  # stesso avviso su altro albo
        ], "2026-11-22")
        A.salva_segnali(db, [s("1", "revoca", "LAVORI SCUOLA - CUP E62B26000380004 - REVOCA", cup="E62B26000380004")], "2026-11-25")
        db.close()
        self.anac = os.path.join(self.d, "anac.db")
        a = sqlite3.connect(self.anac)
        a.executescript(N.SCHEMA)
        a.execute("INSERT INTO anac_cig (cig, importo_lotto, luogo_istat, data_pubblicazione, denominazione_sa, cod_cpv) VALUES ('B52F06EFC8', 912000, '015032', '2026-10-01', 'COMUNE DI BRESSO', '45214000-0')")
        a.execute("INSERT INTO anac_aggiudicazioni (id_aggiudicazione, cig, data_aggiudicazione, importo) VALUES ('111', 'B52F06EFC8', '2026-11-10', 900000)")
        a.execute("INSERT INTO anac_aggiudicatari VALUES ('111','B52F06EFC8','MANDATARIA','01122350380','01122350380','EDILE ROSSI SRL','IMPRESA',0,'f','2026-11-26')")
        a.commit(); a.close()

    def costruisci(self, al, anac=True):
        out = os.path.join(self.d, f"p_{al}.db")
        P.costruisci(self.radar, self.anac if anac else None, out, al)
        c = sqlite3.connect(out); c.row_factory = sqlite3.Row
        return out, c

    def test_opera_per_cup_e_point_in_time(self):
        _, c = self.costruisci("2026-11-21")
        o = c.execute("SELECT * FROM opere WHERE id_opera='E62B26000380004'").fetchone()
        self.assertEqual((o["n_atti"], o["fase_corrente"], o["in_arrivo"]), (1, "progetto", 1))  # l'affidamento non si vede ancora
        _, c = self.costruisci("2026-11-23")
        o = c.execute("SELECT * FROM opere WHERE id_opera='E62B26000380004'").fetchone()
        self.assertEqual((o["n_atti"], o["fase_corrente"], o["cig"], o["importo_anac_eur"]), (2, "affidamento", "B52F06EFC8", 912000.0))
        _, c = self.costruisci("2026-11-26")
        fasi = c.execute("SELECT fasi FROM opere WHERE id_opera='E62B26000380004'").fetchone()[0]
        self.assertIn("revoca", fasi)

    def test_impresa_da_albo_unita_ad_anac(self):
        _, c = self.costruisci("2026-11-26")
        r = c.execute("SELECT * FROM imprese WHERE partita_iva='01122350380'").fetchone()
        self.assertEqual(sorted(r["fonti"].split(",")), ["albo", "anac"])
        self.assertEqual(r["importo_aggiudicato_eur"], 900000.0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM imprese_legami WHERE id_impresa='IT01122350380'").fetchone()[0], 2)

    def test_atto_ripubblicato_conta_una_volta(self):
        _, c = self.costruisci("2026-11-26")
        n = c.execute("SELECT COUNT(*) FROM opere_eventi WHERE oggetto='AVVISO DI GARA LAVORI PONTE'").fetchone()[0]
        self.assertEqual(n, 1)
        self.assertEqual(c.execute("SELECT anche_su FROM opere_eventi WHERE oggetto='AVVISO DI GARA LAVORI PONTE'").fetchone()[0], "Bresso")

    def test_cantiere_e_indicatori(self):
        _, c = self.costruisci("2026-11-26")
        r = c.execute("SELECT indirizzo, impresa FROM cantieri").fetchone()
        self.assertEqual(tuple(r), ("VIA PALESTRO 41", "SCERRA COSTRUZIONI SNC"))
        i = c.execute("SELECT * FROM indicatori_comune WHERE istat='015032'").fetchone()
        self.assertEqual((i["cantieri_privati_30g"], i["opere_osservate"]), (1, 1))

    def test_controlli_qualita(self):
        out, _ = self.costruisci("2026-11-26")
        q = P.esporta_campione(out, os.path.join(self.d, "campione"))
        self.assertTrue(q["tutti_superati"], q)
        self.assertTrue(os.path.exists(os.path.join(self.d, "campione", "opere.csv")))

    def test_senza_anac(self):
        _, c = self.costruisci("2026-11-26", anac=False)
        self.assertIsNone(c.execute("SELECT importo_anac_eur FROM opere WHERE id_opera='E62B26000380004'").fetchone()[0])


class TestEstrazione(unittest.TestCase):
    def test_indirizzo(self):
        self.assertEqual(P.indirizzo("VIA XX SETTEMBRE 7 PER IL GIORNO 16/11/2026 IMPRESA X"), "VIA XX SETTEMBRE 7")
        self.assertEqual(P.indirizzo("RESTRINGIMENTO IN VIALE DELLA REPUBBLICA FRONTE CIV. 24 DAL 18/11"), "VIALE DELLA REPUBBLICA")
        self.assertEqual(P.indirizzo("CORSO SEMPIONE 221 PER IL GIORNO"), "CORSO SEMPIONE 221")

    def test_data_atto(self):
        self.assertEqual(P.data_atto("DETERMINA N.982 DEL 20/11/2026 - AREA TECNICA"), "2026-11-20")


if __name__ == "__main__":
    unittest.main()
