"""La funzione di download vera (non simulata): risposta, charset, secondo tentativo."""
import http.client, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import connettori as C  # noqa: E402


class Risposta:
    def __init__(self, corpo, cs="utf-8", url="https://x/finale"):
        self.corpo, self.cs, self.url = corpo, cs, url
        self.headers = self
    def get_content_charset(self): return self.cs
    def read(self): return self.corpo
    def geturl(self): return self.url
    def __enter__(self): return self
    def __exit__(self, *a): return False


class Apri:
    def __init__(self, esiti): self.esiti, self.chiamate = list(esiti), 0
    def open(self, url, data=None, timeout=None):
        self.chiamate += 1
        e = self.esiti.pop(0)
        if isinstance(e, Exception): raise e
        return e


class TestGet(unittest.TestCase):
    def setUp(self):
        self.pausa, C.PAUSA = C.PAUSA, 0
        self.sleep, C.time.sleep = C.time.sleep, lambda s: None
    def tearDown(self):
        C.PAUSA, C.time.sleep = self.pausa, self.sleep

    def test_restituisce_testo_e_url(self):
        self.assertEqual(C.get(Apri([Risposta("città".encode())]), "https://x"), ("città", "https://x/finale"))

    def test_charset_sbagliato(self):
        t, _ = C.get(Apri([Risposta("città".encode("cp1252"), cs="utf-8")]), "https://x")
        self.assertEqual(t, "città")

    def test_secondo_tentativo(self):
        op = Apri([ConnectionResetError(), Risposta(b"ok")])
        self.assertEqual(C.get(op, "https://x")[0], "ok")
        self.assertEqual(op.chiamate, 2)
        op = Apri([http.client.IncompleteRead(b"x"), Risposta(b"ok")])
        self.assertEqual(C.get(op, "https://x")[0], "ok")

    def test_errore_http_non_ripete(self):
        op = Apri([C.urllib.error.HTTPError("u", 404, "nf", {}, None)])
        with self.assertRaises(C.urllib.error.HTTPError):
            C.get(op, "https://x")
        self.assertEqual(op.chiamate, 1)


if __name__ == "__main__":
    unittest.main()
