"""
Test dei connettori su pagine VERE salvate dai siti dei comuni il 26/11/2026 (cartella fixtures).
Nessuna richiesta di rete: la funzione get() viene sostituita.
Uso:  python3 -m unittest discover -s test   (dalla cartella radar-cantieri)
"""
import datetime as dt, os, sys, unittest

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(QUI))
import connettori as C  # noqa: E402

F = os.path.join(QUI, "fixtures")
DAL = dt.date(2026, 10, 1)


def leggi(nome):
    with open(os.path.join(F, nome), encoding="utf-8") as fh:
        return fh.read()


class FintaRete:
    def __init__(self, risposte):
        self.risposte, self.chiamate = risposte, []

    def __call__(self, op, url, data=None):
        self.chiamate.append((url, data))
        for chiave, testo in self.risposte:
            if chiave(url, data):
                return testo, url
        return "", url


class Base(unittest.TestCase):
    def setUp(self):
        self._get = C.get

    def tearDown(self):
        C.get = self._get

    def controlla(self, atti, minimo):
        self.assertGreaterEqual(len(atti), minimo)
        for a in atti:
            self.assertTrue(a["id"], a)
            self.assertTrue(a["oggetto"], a)
            self.assertIsInstance(a["inizio_pubbl"], dt.date, a)
            self.assertTrue(a["url"].startswith("http"), a)
        self.assertEqual(len({a["id"] for a in atti}), len(atti), "id duplicati")


class TestJCityGov(Base):
    def test_magenta(self):
        C.get = FintaRete([
            (lambda u, d: "igrid" in u, leggi("jcitygov_magenta_griglia.html")),
            (lambda u, d: "eseguiPaginazione" in u, ""),
            (lambda u, d: True, leggi("jcitygov_magenta_albo.html")),
        ])
        atti = C.JCityGov().leggi("https://magenta.trasparenza-valutazione-merito.it/web/trasparenza/albo-pretorio", DAL)
        self.controlla(atti, 20)
        self.assertTrue(any("LOCULI" in a["oggetto"] for a in atti) or atti[0]["registro"].startswith("2026/"))


class TestEPal(Base):
    def test_corsico(self):
        C.get = FintaRete([
            (lambda u, d: u.endswith("page=1"), leggi("epal_corsico_p1.html")),
            (lambda u, d: u.endswith("page=2"), leggi("epal_corsico_p2.html")),
        ])
        atti = C.EPal().leggi("https://corsico.e-pal.it/AlboOnline/ricercaAlbo", DAL, max_pagine=2)
        self.controlla(atti, 20)
        self.assertTrue(all(a["sottocategoria"] for a in atti), "settore proponente mancante")


class TestHalley(Base):
    def test_bellinzago(self):
        C.get = FintaRete([
            (lambda u, d: u.endswith("pag=0"), leggi("halley_bellinzago_p0.html")),
            (lambda u, d: u.endswith("pag=1"), leggi("halley_bellinzago_p1.html")),
        ])
        atti = C.Halley().leggi("http://www.halleyweb.com/c015016/index.php?servizio=304", DAL, max_pagine=2)
        self.controlla(atti, 5)


class TestDgegovPA(Base):
    def test_paderno_export_csv(self):
        C.get = FintaRete([
            (lambda u, d: d is not None, leggi("dgegovpa_paderno_export.csv")),
            (lambda u, d: True, leggi("dgegovpa_paderno_pagina.html")),
        ])
        rete = C.get
        atti = C.DgegovPA().leggi("https://dgegovpa.it/Paderno/Albo/Albo", DAL)
        self.controlla(atti, 30)
        post = [d for u, d in rete.chiamate if d]
        self.assertEqual(len(post), 1)
        self.assertIn("ctl00$ContentPlaceHolder1$BtnCsv", post[0])
        self.assertIn("__VIEWSTATE", post[0])


class TestSicraweb(Base):
    def test_bresso(self):
        C.get = FintaRete([(lambda u, d: True, leggi("sicraweb_bresso.html"))])
        atti = C.Sicraweb().leggi("https://servizionline.hspromilaprod.hypersicapp.net/cmsbresso/portale/albopretorio/albopretorioconsultazione.aspx?P=400", DAL)
        self.controlla(atti, 100)


class TestUrbi(Base):
    def test_legnano(self):
        rete = FintaRete([(lambda u, d: "StwEvent=9100030" in u, leggi("urbi_legnano.html"))])
        C.get = rete
        atti = C.Urbi().leggi("https://cloud.urbi.it/urbi/progs/urp/ur1ME001.sto?DB_NAME=n1234384&w3cbt=S", DAL)
        self.controlla(atti, 170)
        self.assertEqual(len(rete.chiamate), 1)  # una sola richiesta per tutto l'albo
        self.assertIn("DB_NAME=n1234384", rete.chiamate[0][0])
        self.assertTrue(any(a["categoria"] == "Ordinanze" for a in atti))


class TestComuneWeb(Base):
    def test_segrate(self):
        C.get = FintaRete([(lambda u, d: True, leggi("comuneweb_segrate.html"))])
        atti = C.ComuneWeb().leggi("https://segrate.comuneweb.it/ServiziOnLine/AlboPretorio/AlboPretorio", DAL)
        self.controlla(atti, 100)
        self.assertTrue(any(a["categoria"] == "Permesso Di Costruire" for a in atti))


class TestHalleyEG(Base):
    def test_besate(self):
        rete = FintaRete([
            (lambda u, d: "/ht/egt63/" in u and d and d.get("F") == "MC03", leggi("halleyeg_besate_lista.html")),
            (lambda u, d: "EGHOMEPAGE.HBL" in u and not d, leggi("halleyeg_besate_home.html")),
        ])
        C.get = rete
        atti = C.HalleyEG().leggi("https://www.comune.besate.mi.it/EG0/EGHOMEPAGE.HBL?ss=1&F=MC09&en=egt63&freeze=1&P=", dt.date(2018, 1, 1))
        self.controlla(atti, 6)
        self.assertEqual(len(rete.chiamate), 2)  # pagina + lista (una sola pagina di risultati)
        self.assertTrue(rete.chiamate[1][0].endswith("/ht/egt63/EGHOMEPAGE_1123132800001005Ao8ZVBMHmZLm0pXn.HBL"))
        self.assertEqual(atti[1]["categoria"], "DETERMINAZIONE")


class TestAlboJSP(Base):
    def test_cinisello(self):
        rete = FintaRete([(lambda u, d: d and d.get("delXPag") == "500", leggi("attinew_cinisello.html"))])
        C.get = rete
        atti = C.AlboJSP().leggi("https://attinew.comune.cinisello-balsamo.mi.it/albopretorio/AlboPretorio", DAL)
        self.controlla(atti, 150)
        self.assertEqual(len(rete.chiamate), 1)
        self.assertTrue(atti[0]["url"].startswith("https://attinew.comune.cinisello-balsamo.mi.it/albopretorio/AlboPretorio?servizio=dettaglio"))


class TestMilano(Base):
    def test_milano(self):
        def risposta(u, d):
            if "/api/categories/" in u:
                return leggi("milano_cat.json")
            if "categories[]=10&" in u and u.endswith("page=1"):
                return leggi("milano_p1.json")
            if "categories[]=10&" in u and u.endswith("page=2"):
                return leggi("milano_p2.json")
            if "categories[]=4&" in u and u.endswith("page=1"):
                return leggi("milano_d1.json")
            return '{"data": [], "total_pages": 1}'
        rete = FintaRete([(lambda u, d: True, None)])
        rete.risposte = []
        C.get = lambda op, url, data=None: (rete.chiamate.append((url, data)) or (risposta(url, data), url))
        atti = C.MilanoAPI().leggi("https://albopretorio.comune.milano.it/", dt.date(2026, 11, 1))
        self.controlla(atti, 25)
        self.assertFalse(any("categories[]=108&" in u or "categories[]=106&" in u for u, _ in rete.chiamate))  # matrimoni e notifiche mai scaricati
        self.assertTrue(all(a["url"].startswith("https://albopretorio.comune.milano.it/documents/") for a in atti))


class TestRiconoscimento(unittest.TestCase):
    def test_piattaforme(self):
        casi = {
            "https://bollate.trasparenza-valutazione-merito.it/web/trasparenza/albo-pretorio": "jcitygov",
            "https://corsico.e-pal.it/albopretorio/albopretorio/Main.do?MVPG=AmvRicercaAlbo": "e-pal",
            "http://www.halleyweb.com/c015016/index.php?servizio=304": "halley",
            "https://www.comune.albairate.mi.it/mc/mc_p_ricerca.php": "halley",
            "https://dgegovpa.it/bareggio/albo/albo": "dgegovpa",
            "https://servizi.comune.basiglio.mi.it/cmsbasiglio//portale/albopretorio/albopretorioconsultazione.aspx?IDNODE=1230": "sicraweb-cms",
            "https://ucbasianomasate.halleyegov.it/redirect.html?F=MC09": "halley-eg",
            "https://cloud.urbi.it/urbi/progs/urp/ur1ME001.sto?DB_NAME=n1234384&w3cbt=S": "urbi",
            "https://segrate.comuneweb.it/ServiziOnLine/AlboPretorio/AlboPretorio": "comuneweb",
        }
        for url, atteso in casi.items():
            self.assertEqual(C.piattaforma(url), atteso, url)


if __name__ == "__main__":
    unittest.main()
