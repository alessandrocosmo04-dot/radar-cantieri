"""Test del classificatore su 330 atti veri (rivisti a mano il 26/11/2026) e su casi limite scritti apposta."""
import json
import os
import sys
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(QUI))
from classifica import classifica  # noqa: E402


def c(oggetto, categoria=""):
    return classifica({"oggetto": oggetto, "categoria": categoria, "sottocategoria": ""})


class TestGolden(unittest.TestCase):
    def test_atti_veri(self):
        with open(os.path.join(QUI, "fixtures", "classifica_golden.json"), encoding="utf-8") as f:
            gold = json.load(f)
        diversi = []
        for g in gold:
            r = classifica(g)
            got = None if not r else {k: r[k] for k in ("tipo", "fase", "impresa")}
            if got != g["atteso"]:
                diversi.append((g["oggetto"][:100], g["atteso"], got))
        self.assertEqual(diversi, [], f"{len(diversi)} atti classificati diversamente dal set rivisto")


class TestCasi(unittest.TestCase):
    def test_servizi_non_edili_scartati(self):
        for o in ["SERVIZIO DI REFEZIONE SCOLASTICA A.S. 2026/2027 - AFFIDAMENTO",
                  "RIMBORSO DIRITTI SUAP NON DOVUTI",
                  "SERVIZIO DI IGIENE URBANA - CANONE NOVEMBRE",
                  "TRASPORTO STUDENTI DISABILI - IMPEGNO DI SPESA",
                  "REDAZIONE DEL PIANO URBANO DELLA MOBILITÀ SOSTENIBILE (PUMS) E P.G.T.U."]:
            self.assertIsNone(c(o), o)

    def test_dati_personali_scartati(self):
        for o in ["NOTIFICA ATTO A CARICO DI ROSSI MARIO",
                  "ORDINANZA DI DEMOLIZIONE D'UFFICIO OPERE ABUSIVE",
                  "PUBBLICAZIONE DI MATRIMONIO"]:
            self.assertIsNone(c(o), o)

    def test_fasi(self):
        self.assertEqual(c("DETERMINA A CONTRARRE PER I LAVORI DI RIFACIMENTO MARCIAPIEDI VIA ROMA")["fase"], "gara_in_partenza")
        self.assertEqual(c("DETERMINA A CONTRARRE E CONTESTUALE AFFIDAMENTO DEI LAVORI DI ASFALTATURA ALLA DITTA BIANCHI STRADE SRL")["fase"], "affidamento")
        self.assertEqual(c("APPROVAZIONE SAL N.2 LAVORI DI MANUTENZIONE STRAORDINARIA SCUOLA")["fase"], "esecuzione")
        self.assertEqual(c("APPROVAZIONE CERTIFICATO DI REGOLARE ESECUZIONE LAVORI DI RIQUALIFICAZIONE PALESTRA")["fase"], "collaudo")
        self.assertEqual(c("APPROVAZIONE PROGETTO ESECUTIVO LAVORI DI SOSTITUZIONE SERRAMENTI")["fase"], "progetto")

    def test_impresa(self):
        self.assertEqual(c("AFFIDAMENTO DEI LAVORI DI ASFALTATURA ALLA DITTA BIANCHI STRADE SRL - CIG A1B2C3D4E5")["impresa"], "BIANCHI STRADE SRL")
        self.assertEqual(c("AFFIDAMENTO ALLA DITTA F.LLI VERDI DEI LAVORI DI MANUTENZIONE STRAORDINARIA COPERTURA")["impresa"], "F.LLI VERDI")

    def test_codici(self):
        r = c("LAVORI DI RIFACIMENTO COPERTURA - CUP E62B26000380004 - CIG BDAAE6A7EE - IMPORTO € 125.000,00")
        self.assertEqual((r["cup"], r["cig"], r["importo_eur"]), ("E62B26000380004", "BDAAE6A7EE", 125000.0))

    def test_cantiere_privato(self):
        r = c("CHIUSURA TEMPORANEA AL TRANSITO DI VIA GRAMSCI ALTEZZA CIV. 8-14 PER LAVORI DI RIMOZIONE GRU DI CANTIERE", "Ordinanze")
        self.assertEqual(r["tipo"], "cantiere_privato")
        self.assertEqual(r["indirizzo"], "VIA GRAMSCI ALTEZZA CIV. 8-14")

    def test_cantiere_privato_con_impresa(self):
        r = c("VIA XX SETTEMBRE 7 PER IL GIORNO 16/11/2026 IMPRESA TECNO COPERTURE CLERICI SRL - ORDINANZA DI RESTRINGIMENTO DELLA CARREGGIATA", "Ordinanze")
        self.assertEqual((r["tipo"], r["indirizzo"], r["impresa"]), ("cantiere_privato", "VIA XX SETTEMBRE 7", "TECNO COPERTURE CLERICI SRL"))

    def test_ditta_individuale_oscurata(self):
        r = c("VIA EL ALAMEIN 14 - DAL 14/11 AL 15/11/2026 IMPRESA ZEKLA MIKEL - ORDINANZA DI RESTRINGIMENTO DELLA CARREGGIATA", "Ordinanze")
        self.assertIsNone(r["impresa"])
        self.assertNotIn("ZEKLA", r["oggetto"])

    def test_traslochi_scartati(self):
        self.assertIsNone(c("VIA DEL GIGANTE 55 PER IL 17/11/2026 IMPRESA VENETA TRASLOCHI SAS - ORDINANZA DI DIVIETO DI SOSTA", "Ordinanze"))

    def test_professionista_oscurato(self):
        r = c("AFFIDAMENTO INCARICO DIREZIONE LAVORI ALL'ARCH. MARIO ROSSI PER LA RIQUALIFICAZIONE DELLA PALESTRA")
        self.assertNotIn("ROSSI", r["oggetto"])


if __name__ == "__main__":
    unittest.main()
