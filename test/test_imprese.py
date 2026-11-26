"""Anagrafica imprese: normalizzazione, partita IVA, abbinamento con confidenza."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import imprese as I  # noqa: E402


class TestNormalizza(unittest.TestCase):
    def test_forme_e_abbreviazioni(self):
        self.assertEqual(I.normalizza("CO.GE.T S.R.L"), (("COGET",), "SRL"))
        self.assertEqual(I.normalizza("F.LLI PICENNI S.N.C."), (("FRATELLI", "PICENNI"), "SNC"))
        self.assertEqual(I.normalizza("Cooperativa Sociale Eureka Soc. Coop."), (("EUREKA",), "COOP"))
        self.assertEqual(I.normalizza("MAXXI SERVICE SRLS"), (("MAXXI", "SERVICE"), "SRLS"))
        self.assertEqual(I.normalizza("Società per Azioni Giudici")[1], "SPA")

    def test_piva(self):
        self.assertTrue(I.piva_valida("01122350380"))
        self.assertFalse(I.piva_valida("01122350381"))
        self.assertFalse(I.piva_valida("00000000000"))
        self.assertEqual(I.piva_dal_testo("BCC LEASING S.P.A. - CODICE FISCALE 02820100580 - P.IVA 01122350381", escludi={"x"}), ["02820100580"])


class TestRisolvi(unittest.TestCase):
    def setUp(self):
        self.m = [
            {"chiave": "a1", "nome": "EDILE ROSSI S.R.L.", "piva": "01122350380"},
            {"chiave": "a2", "nome": "EDILE ROSSI SRL UNIPERSONALE", "piva": "01122350380"},
            {"chiave": "b1", "nome": "Edile Rossi srl", "piva": None},             # stesso nome, nessuna P.IVA
            {"chiave": "c1", "nome": "EDILE ROSSI SPA", "piva": "02820100580"},   # altra impresa, altra P.IVA
            {"chiave": "d1", "nome": "COSTRUZIONI BIANCHI SNC", "piva": None},
            {"chiave": "d2", "nome": "COSTRUZIONI BIANCHI S.N.C.", "piva": None},
            {"chiave": "e1", "nome": "COSTRUZIONI VERDI SNC", "piva": None},
        ]
        self.imp, self.leg = I.risolvi(self.m)
        self.per = {l["chiave"]: l for l in self.leg}

    def test_partita_iva_e_varianti(self):
        self.assertEqual(self.per["a1"]["id_impresa"], "IT01122350380")
        self.assertEqual(self.per["a2"]["id_impresa"], "IT01122350380")
        self.assertEqual(self.imp["IT01122350380"]["menzioni"], 3)

    def test_nome_va_alla_piva_giusta(self):
        self.assertEqual(self.per["b1"]["id_impresa"], "IT01122350380")  # SRL, non la SPA
        self.assertEqual(self.per["b1"]["metodo"], "nome->partita_iva")
        self.assertGreater(self.per["b1"]["confidenza"], 0.5)

    def test_piva_diverse_non_si_fondono(self):
        self.assertNotEqual(self.per["a1"]["id_impresa"], self.per["c1"]["id_impresa"])

    def test_solo_nome(self):
        self.assertEqual(self.per["d1"]["id_impresa"], self.per["d2"]["id_impresa"])
        self.assertTrue(self.per["d1"]["id_impresa"].startswith("N:"))
        self.assertNotEqual(self.per["d1"]["id_impresa"], self.per["e1"]["id_impresa"])


class TestCalibrazione(unittest.TestCase):
    def test_monotona(self):
        coppie = [(0.95, True)] * 9 + [(0.95, False)] + [(0.75, True)] * 3 + [(0.75, False)] * 2 + [(0.62, True)] * 3 + [(0.62, False)] + [(0.3, False)] * 5
        t = I.calibra(coppie)
        probs = [p for _, p in t]
        self.assertEqual(probs, sorted(probs))
        self.assertEqual(I.confidenza(0.31, t), 0.0)
        self.assertAlmostEqual(I.confidenza(0.96, t), 0.9)


if __name__ == "__main__":
    unittest.main()
