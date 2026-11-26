"""
Connettori: uno per ogni software di albo pretorio.
Ogni connettore espone  leggi(url_albo, dal: date) -> lista di atti normalizzati:
  {comune, piattaforma, id, registro, categoria, sottocategoria, oggetto, inizio_pubbl, fine_pubbl, url}
Solo libreria standard.
"""
import datetime as dt, html, http.cookiejar, re, time, urllib.error, urllib.parse, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) RadarCantieri/0.2 (raccolta albo pretorio; pausa 1s fra le richieste)"
PAUSA = 1.0  # secondi fra una richiesta e l'altra: siamo ospiti sui server dei comuni


def sessione():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA), ("Accept-Language", "it-IT,it")]
    return op


def get(op, url, data=None):
    time.sleep(PAUSA)
    body = urllib.parse.urlencode(data).encode() if data else None
    for tentativo in (1, 2):  # un secondo tentativo per i siti lenti o che chiudono la connessione
        try:
            with op.open(url, data=body, timeout=60) as r:
                grezzo, cs = r.read(), r.headers.get_content_charset()
            break
        except (ConnectionError, TimeoutError, urllib.error.URLError) as e:
            if tentativo == 2 or isinstance(e, urllib.error.HTTPError):
                raise
            time.sleep(5)
        try:
            return grezzo.decode(cs or "utf-8"), r.geturl()
        except (UnicodeDecodeError, LookupError):
            return grezzo.decode("cp1252", "replace"), r.geturl()


def testo(s):
    s = re.sub(r"<br\s*/?>", " ", s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def data_it(s):
    try:
        return dt.datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except Exception:
        return None


# ---------------------------------------------------------------- JCityGov
# Usato da molti comuni: <comune>.trasparenza-valutazione-merito.it oppure trasparenza.comune.X.it
# Percorso: /web/trasparenza/albo-pretorio -> link "Albo pretorio" -> iframe /papca/igrid/<a>/<b>

class JCityGov:
    nome = "jcitygov"

    @staticmethod
    def riconosci(url):
        return "trasparenza-valutazione-merito.it" in url or "/web/trasparenza/albo-pretorio" in url or "jcitygov" in url

    def trova_griglia(self, op, url_albo):
        base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(url_albo))
        pagina, errore = "", None
        # prima l'indirizzo della mappa, poi i percorsi standard (alcuni comuni usano /it/web/... o /web/trasparenzaj/...)
        candidati = [url_albo] + [base + p + "/web/trasparenza/" + q for p in ("", "/it")
                                  for q in ("albo-pretorio", "dettaglio-albo-pretorio", "menu-albo-pretorio")]
        for u in dict.fromkeys(candidati):
            try:
                pagina, _ = get(op, u)
            except Exception as e:
                errore = e
                continue
            if re.search(r"papca|dettaglio-albo-pretorio", pagina):
                break
        if not pagina and errore:
            raise errore
        m = re.search(r'href="([^"]*dettaglio-albo-pretorio[^"]*)"[^>]*>\s*Albo pretorio', pagina, re.I)
        if m:
            pagina, _ = get(op, html.unescape(m.group(1)))
        g = re.search(r'((?:/it)?/web/trasparenzaj?/papca-ap/-/papca/igrid/\d+/\d+)', pagina)
        if g:
            return base, base + g.group(1)
        # il menu indica la griglia con data-mainurl + data-idmenuitem
        g = re.search(r'data-resource="Albo pretorio".*?data-mainurl="((?:/it)?/web/trasparenzaj?/papca-ap/-/papca/igrid/\d+)".*?data-idmenuitem="(\d+)"',
                      pagina, re.S | re.I)
        if not g:
            raise RuntimeError("griglia albo non trovata")
        return base, f"{base}{g.group(1)}/{g.group(2)}"

    def righe(self, pagina):
        for tr in re.findall(r'<tr class="master-detail-list-line[^"]*" data-id="(\d+)">(.*?)</tr>', pagina, re.S):
            rid, corpo = tr
            cella = lambda c: (re.search(r'class="%s[^"]*"[^>]*>(.*?)</td>' % c, corpo, re.S) or [None, ""])[1]
            cat = re.search(r'categoria_categoria">(.*?)</span>', corpo, re.S)
            sub = re.search(r'categoria_sottocategoria">(.*?)</span>', corpo, re.S)
            date = re.findall(r"\d{2}/\d{2}/\d{4}", cella("periodo-pubblicazione"))
            link = re.search(r'href="([^"]*papca/display/\d+[^"]*)"', corpo)
            yield {
                "id": rid,
                "registro": testo(cella("annonumeroregistrazione")),
                "categoria": testo(cat.group(1)) if cat else "",
                "sottocategoria": testo(sub.group(1)) if sub else "",
                "oggetto": testo(cella("oggetto")),
                "inizio_pubbl": data_it(date[0]) if date else None,
                "fine_pubbl": data_it(date[1]) if len(date) > 1 else None,
                "url": html.unescape(link.group(1)) if link else "",
            }

    def leggi(self, url_albo, dal, max_pagine=40):
        op = sessione()
        base, griglia = self.trova_griglia(op, url_albo)
        pagina, _ = get(op, griglia)
        azione = re.search(r'action="([^"]*eseguiPaginazione[^"]*)"', pagina)
        out, n = [], 1
        while True:
            nuove = list(self.righe(pagina))
            out += nuove
            # l'elenco è in ordine di registro decrescente: ci fermiamo quando passiamo la data
            if not nuove or not azione or n >= max_pagine or any(r["inizio_pubbl"] and r["inizio_pubbl"] < dal for r in nuove):
                break
            n += 1
            pagina, _ = get(op, html.unescape(azione.group(1)), {"hidden_page_size": "20", "hidden_page_to": str(n)})
        for r in out:
            r["piattaforma"] = self.nome
        return [r for r in out if not r["inizio_pubbl"] or r["inizio_pubbl"] >= dal]


# ---------------------------------------------------------------- e-pal (AlboOnline)
# Es. corsico.e-pal.it, servizi-sestosangiovanni.e-pal.it: ricerca GET /AlboOnline/ricercaAlbo?page=N

class EPal:
    nome = "e-pal"

    @staticmethod
    def riconosci(url):
        return "e-pal.it" in url or "/AlboOnline/" in url

    def righe(self, pagina, base):
        for blocco in re.split(r'<div class="panel panel-primary">', pagina)[1:]:
            reg = re.search(r"Registrazione Albo n\.\s*([\d/]+)", blocco)
            ogg = re.search(r"Oggetto:\s*(.*?)</div>", blocco, re.S)
            date = re.search(r"Pubblicazione dal\s*(\d{2}/\d{2}/\d{4}).*?al\s*(\d{2}/\d{2}/\d{4})", blocco, re.S)
            campo = lambda et: (re.search(et + r":\s*</div>\s*<div[^>]*>(.*?)</div>", blocco, re.S) or [None, ""])[1]
            link = re.search(r'href="(dettaglioAlbo/(\d+))"', blocco)
            if not reg:
                continue
            yield {
                "id": link.group(2) if link else reg.group(1),
                "registro": reg.group(1),
                "categoria": testo(campo("Tipo pubblicazione") or campo("Atto di Riferimento")),
                "sottocategoria": testo(campo("Settore Proponente") or campo("Ente Richiedente")),
                "oggetto": testo(ogg.group(1)) if ogg else "",
                "inizio_pubbl": data_it(date.group(1)) if date else None,
                "fine_pubbl": data_it(date.group(2)) if date else None,
                "url": f"{base}/AlboOnline/{link.group(1)}" if link else "",
            }

    def leggi(self, url_albo, dal, max_pagine=40):
        op = sessione()
        base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(url_albo))
        out = []
        for n in range(1, max_pagine + 1):
            pagina, _ = get(op, f"{base}/AlboOnline/ricercaAlbo?page={n}")
            nuove = list(self.righe(pagina, base))
            out += nuove
            if not nuove or any(r["inizio_pubbl"] and r["inizio_pubbl"] < dal for r in nuove):
                break
        for r in out:
            r["piattaforma"] = self.nome
        return [r for r in out if not r["inizio_pubbl"] or r["inizio_pubbl"] >= dal]


# ---------------------------------------------------------------- Halley (albo "mc")
# Es. www.halleyweb.com/c015016/mc/mc_p_ricerca.php, www.comune.albairate.mi.it/mc/mc_p_ricerca.php
# Pagine: ?pag=0,1,2... Ogni riga ha una cella "visible-xs" con coppie <strong>Etichetta</strong> <div>valore</div>

class Halley:
    nome = "halley"

    @staticmethod
    def riconosci(url):
        return "/mc/mc_p_" in url or "halleyweb.com" in url

    @staticmethod
    def base(url_albo):
        if "/mc/" in url_albo:
            return url_albo.split("/mc/")[0]
        m = re.match(r"(https?://[^/]+/c\d{6})", url_albo)  # halleyweb.com/c015016/index.php?servizio=...
        return m.group(1) if m else url_albo.rstrip("/")

    def righe(self, pagina, base):
        for tr in re.findall(r"<tr>(.*?)</tr>", pagina, re.S):
            cella = re.search(r'<td data-id="(\d+)" class="visible-xs">(.*?)</td>', tr, re.S)
            if not cella:
                continue
            rid, corpo = cella.groups()
            campi = {testo(k).lower(): testo(v) for k, v in re.findall(r"<strong>(.*?)</strong>\s*<div>(.*?)</div>", corpo, re.S)}
            yield {
                "id": rid,
                "registro": campi.get("numero pubblicazione", ""),
                "categoria": campi.get("tipo", ""),
                "sottocategoria": campi.get("mittente", ""),
                "oggetto": campi.get("oggetto", ""),
                "inizio_pubbl": data_it(campi.get("data inizio", "")),
                "fine_pubbl": data_it(campi.get("data fine", "")),
                "url": f"{base}/mc/mc_p_dettaglio.php?id_pubbl={rid}",
            }

    def leggi(self, url_albo, dal, max_pagine=40):
        op = sessione()
        base = self.base(url_albo)
        out, visti = [], set()
        for n in range(max_pagine):
            pagina, _ = get(op, f"{base}/mc/mc_p_ricerca.php?pag={n}")
            nuove = [r for r in self.righe(pagina, base) if r["id"] not in visti]
            visti.update(r["id"] for r in nuove)
            out += nuove
            # ordinate per data di inizio decrescente
            if not nuove or all(r["inizio_pubbl"] and r["inizio_pubbl"] < dal for r in nuove):
                break
        for r in out:
            r["piattaforma"] = self.nome
        return [r for r in out if not r["inizio_pubbl"] or r["inizio_pubbl"] >= dal]


# ---------------------------------------------------------------- DgegovPA (ASP.NET)
# Es. dgegovpa.it/Paderno/Albo/Albo. La pagina offre l'export CSV ufficiale (pulsante BtnCsv):
# lo usiamo invece di leggere l'HTML, è più stabile.

class DgegovPA:
    nome = "dgegovpa"

    @staticmethod
    def riconosci(url):
        return "dgegovpa.it" in url

    def leggi(self, url_albo, dal, max_pagine=None):
        import csv as _csv, io
        op = sessione()
        m = re.match(r"(https?://[^/]+/[^/]+)/", url_albo + "/")
        url = m.group(1) + "/Albo/Albo"
        pagina, finale = get(op, url)
        form = {}
        for tag in re.findall(r"<input[^>]+>", pagina):
            nome = re.search(r'name="([^"]+)"', tag)
            tipo = (re.search(r'type="([^"]+)"', tag) or [None, "text"])[1].lower()
            val = re.search(r'value="([^"]*)"', tag)
            if nome and tipo in ("hidden", "text"):
                form[html.unescape(nome.group(1))] = html.unescape(val.group(1)) if val else ""
        for sel in re.findall(r'<select[^>]+name="([^"]+)"[^>]*>(.*?)</select>', pagina, re.S):
            scelto = re.search(r'<option[^>]*selected[^>]*value="([^"]*)"', sel[1]) or re.search(r'<option[^>]*value="([^"]*)"', sel[1])
            form[html.unescape(sel[0])] = html.unescape(scelto.group(1)) if scelto else ""
        btn = re.search(r'name="([^"]*BtnCsv)"[^>]*value="([^"]*)"', pagina) or re.search(r'value="([^"]*)"[^>]*name="([^"]*BtnCsv)"', pagina)
        if not btn:
            raise RuntimeError("pulsante export CSV non trovato")
        nome_btn, val_btn = (btn.group(1), btn.group(2)) if "BtnCsv" in btn.group(1) else (btn.group(2), btn.group(1))
        form[nome_btn] = val_btn
        testo_csv, _ = get(op, finale, form)
        out = []
        for r in _csv.DictReader(io.StringIO(testo_csv), delimiter=";"):
            ini = data_it(r.get("datainiziopubblicazione", ""))
            if ini and ini < dal:
                continue
            link = (r.get("linkallegati") or "").split()
            out.append({
                "id": f'{r.get("anno")}-{r.get("numero")}',
                "registro": f'{r.get("numero")}/{r.get("anno")}',
                "categoria": (r.get("tipoatto") or "").strip(),
                "sottocategoria": (r.get("descrizionesettoreatto") or "").strip(),
                "oggetto": testo(r.get("oggetto", "")),
                "inizio_pubbl": ini,
                "fine_pubbl": data_it(r.get("datafinepubblicazione", "")),
                "url": link[0] if link else url,
                "piattaforma": self.nome,
            })
        return out


# ---------------------------------------------------------------- Sicraweb CMS (Maggioli)
# Es. .../cmsbresso/portale/albopretorio/albopretorioconsultazione.aspx?P=400
# Tutte le pubblicazioni in corso sono già nell'HTML (la paginazione è solo grafica).
# Colonne: id, data atto, n. atto, n. registro, oggetto, categoria, ufficio, inizio, fine

class Sicraweb:
    nome = "sicraweb-cms"

    @staticmethod
    def riconosci(url):
        return "albopretorioconsultazione.aspx" in url or "hypersicapp.net" in url

    def righe(self, pagina, url_albo):
        for rid, corpo in re.findall(r'tab_risultati_table_hidden_row_(\d+)" id="[^"]*"\s*/?>\s*</td>(.*?)</tr>', pagina, re.S):
            celle = [testo(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", corpo, re.S)]
            if len(celle) < 8:
                continue
            _, data_atto, n_atto, reg, ogg, cat, uff, ini, *resto = celle
            yield {
                "id": rid, "registro": reg, "categoria": cat, "sottocategoria": uff, "oggetto": ogg,
                "inizio_pubbl": data_it(ini), "fine_pubbl": data_it(resto[0]) if resto else None,
                "url": url_albo,
            }

    def leggi(self, url_albo, dal, max_pagine=None):
        pagina, finale = get(sessione(), url_albo)
        out = [dict(r, piattaforma=self.nome) for r in self.righe(pagina, finale)]
        return [r for r in out if not r["inizio_pubbl"] or r["inizio_pubbl"] >= dal]


# ---------------------------------------------------------------- Urbi (PA Digitale)
# cloud.urbi.it/urbi/progs/urp/ur1ME001.sto?DB_NAME=nXXXXXXX  (es. Legnano)
# Un solo POST senza sessione restituisce tutte le pubblicazioni in corso, con pagina grande.

class Urbi:
    nome = "urbi"

    @staticmethod
    def riconosci(url):
        return "urbi" in url and "ur1ME001" in url

    def righe(self, pagina, base):
        for tr in re.findall(r"<tr>(.*?)</tr>", pagina, re.S):
            idp = re.search(r"IdMePubblica=(\d+)", tr)
            if not idp:
                continue
            per = re.search(r"dal (\d{2})-(\d{2})-(\d{4}) al (\d{2})-(\d{2})-(\d{4})", tr)
            forti = [testo(x) for x in re.findall(r"<strong>(.*?)</strong>", tr, re.S)]
            if len(forti) < 3:
                continue
            ente, tipologia, ogg = forti[0], forti[1], forti[2]
            reg = re.search(r"\(reg\. ([^)]+)\)", tr)
            data = (lambda g: dt.date(int(g[2]), int(g[1]), int(g[0]))) if per else None
            yield {
                "id": idp.group(1), "registro": reg.group(1) if reg else "",
                "categoria": tipologia.split("/")[-1], "sottocategoria": ente, "oggetto": ogg,
                "inizio_pubbl": data(per.groups()[0:3]) if per else None,
                "fine_pubbl": data(per.groups()[3:6]) if per else None,
                "url": base + "ur1ME001.sto?StwEvent=91000302&IdMePubblica=" + idp.group(1),
            }

    def leggi(self, url_albo, dal, max_pagine=None):
        u = urllib.parse.urlparse(url_albo)
        db = urllib.parse.parse_qs(u.query).get("DB_NAME", [""])[0]
        base = "{0.scheme}://{0.netloc}{1}/".format(u, u.path.rsplit("/", 1)[0])
        url = (base + "ur1ME001.sto?DB_NAME=" + urllib.parse.quote(db) + "&w3cbt=S&StwEvent=9100030"
               "&ElencoPubblicazioni_DimensionePagina=1000&ElencoPubblicazioni_PaginaCorrente=1")
        dati = {"OpenTree": "1", "OpenTreeSel": "1", "OpenTreeText": "Catalogo Documenti", "Archivio": "", "SOLCollegamentoAtti": "S"}
        pagina, _ = get(sessione(), url, dati)
        out = [dict(r, piattaforma=self.nome) for r in self.righe(pagina, base)]
        return [r for r in out if not r["inizio_pubbl"] or r["inizio_pubbl"] >= dal]


# ---------------------------------------------------------------- ComuneWeb (servizi.comune.X.it/ServiziOnLine/AlboPretorio)
# Tutte le pubblicazioni in corso stanno in una sola pagina HTML (es. Segrate).

class ComuneWeb:
    nome = "comuneweb"

    @staticmethod
    def riconosci(url):
        return "comuneweb.it" in url or "/ServiziOnLine/AlboPretorio" in url

    def righe(self, pagina, finale):
        for li in re.findall(r"<li><div class=\"list-item\">(.*?)</li>", pagina, re.S):
            t = re.search(r'<span class="text text-custom p-1">(.*?)<em>(.*?)</em>', li, re.S)
            if not t:
                continue
            intest, ogg = testo(t.group(1)), testo(t.group(2))
            m = re.match(r"(\d+)/(\d{4}) del (\d{2}/\d{2}/\d{4}) - (.*)", intest)
            if not m:
                continue
            num, anno, data, resto = m.groups()
            cat, _, atto = resto.partition(" - ")
            link = re.search(r'data-link="([^"]+)"', li)
            yield {
                "id": f"{anno}_{num}", "registro": f"{num}/{anno}", "categoria": cat.strip(), "sottocategoria": atto.strip(),
                "oggetto": ogg, "inizio_pubbl": data_it(data), "fine_pubbl": None,
                "url": html.unescape(link.group(1)).replace("http://", "https://") if link else finale,
            }

    def leggi(self, url_albo, dal, max_pagine=None):
        pagina, finale = get(sessione(), url_albo)
        out = [dict(r, piattaforma=self.nome) for r in self.righe(pagina, finale)]
        return [r for r in out if not r["inizio_pubbl"] or r["inizio_pubbl"] >= dal]


# ---------------------------------------------------------------- Halley EG (sito "EGHOMEPAGE.HBL", anche *.halleyegov.it)
# La pagina contiene <meta name="jb"> con l'indirizzo di sessione; la lista arriva con POST F=MC03,
# le pagine successive con POST F=PMC03&1=<pagina>.

def _data_trattini(s):
    try:
        return dt.datetime.strptime(s.strip(), "%d-%m-%Y").date()
    except Exception:
        return None


class HalleyEG:
    nome = "halley-eg"

    @staticmethod
    def riconosci(url):
        return "halleyegov.it" in url or "EGHOMEPAGE.HBL" in url

    def righe(self, pagina, url_albo):
        for card in pagina.split('<div class="cmp-card mb-3">')[1:]:
            num = re.search(r"Pubblicazione n\.\s*(\d+)", card)
            ogg = re.search(r'<h5 class="card-title[^"]*">(.*?)</h5>', card, re.S)
            if not (num and ogg):
                continue
            campo = lambda nome: (re.search(r"<strong >" + nome + r":</strong>(.*?)</span>", card, re.S) or [None, ""])[1]
            per = re.search(r"Pubblicazione dal </strong>([\d-]*)\s*<strong>al </strong>([\d-]*)", card)
            atto = re.search(r"<strong>Atto n\.</strong>\s*([^<]*)<strong>del</strong>\s*([^<]*)</span>", card)
            ini = _data_trattini(per.group(1)) if per else None
            yield {
                "id": f"{ini.year if ini else 0}_{num.group(1)}", "registro": num.group(1),
                "categoria": testo(campo("Tipo")), "sottocategoria": testo(campo("Mittente")),
                "oggetto": testo(ogg.group(1)), "inizio_pubbl": ini,
                "fine_pubbl": _data_trattini(per.group(2)) if per else None,
                "url": url_albo, "atto": testo(" ".join(atto.groups())) if atto else "",
            }

    def leggi(self, url_albo, dal, max_pagine=20):
        op = sessione()
        home, finale = get(op, url_albo)
        jb = re.search(r'<meta name="jb" content="([^"]+)"', home)
        if not jb:  # es. redirect.html?F=MC09: la pagina vera si apre con un POST a /EG0/EGHOMEPAGE.HBL
            h = urllib.parse.urlparse(finale)
            home, finale = get(op, "{0.scheme}://{0.netloc}/EG0/EGHOMEPAGE.HBL".format(h), {"F": "MC09"})
            jb = re.search(r'<meta name="jb" content="([^"]+)"', home)
        if not jb:
            raise ValueError("halley-eg: indirizzo di sessione (meta jb) non trovato")
        u = urllib.parse.urlparse(finale)
        servizio = "{0.scheme}://{0.netloc}{1}".format(u, jb.group(1))
        campi = {"F": "MC03", **{str(i): "" for i in range(1, 14)}}
        pagina, _ = get(op, servizio, campi)
        out = list(self.righe(pagina, url_albo))
        tot = int((re.search(r'id="totalePagine">(\d+)<', pagina) or [0, "1"])[1])
        for n in range(2, min(tot, max_pagine) + 1):
            pagina, _ = get(op, servizio, {"F": "PMC03", "1": str(n)})
            out += list(self.righe(pagina, url_albo))
        out = [dict(r, piattaforma=self.nome) for r in out]
        return [r for r in out if not r["inizio_pubbl"] or r["inizio_pubbl"] >= dal]


# ---------------------------------------------------------------- Albo JSP "AlboPretorio?servizio=cerca" (es. Cinisello Balsamo)
# Un POST di ricerca vuota con 500 risultati per pagina restituisce tutto l'albo in corso.

class AlboJSP:
    nome = "albo-jsp"

    @staticmethod
    def riconosci(url):
        return "/albopretorio/AlboPretorio" in url

    def righe(self, pagina, finale):
        for li in re.findall(r'<li class="documento">(.*?)</ul>\s*</li>', pagina, re.S):
            a = re.search(r'<a href="([^"]*idPratica=(\d+)[^"]*)"[^>]*>(.*?)</a>', li, re.S)
            if not a:
                continue
            spans = lambda et: (re.search(et + r"</span>:?\s*<span>(.*?)</span>", li, re.S) or [None, ""])[1]
            date = re.findall(r"<span>(\d{2}/\d{2}/\d{4})</span>", li)
            ente = re.search(r"Ente proponente</span>:\s*(.*?)</span>", li, re.S)
            yield {
                "id": a.group(2), "registro": testo(spans("Registro")), "categoria": testo(spans("Tipologia")),
                "sottocategoria": testo(ente.group(1)) if ente else "", "oggetto": testo(a.group(3)),
                "inizio_pubbl": data_it(date[0]) if date else None,
                "fine_pubbl": data_it(date[1]) if len(date) > 1 else None,
                "url": urllib.parse.urljoin(finale, html.unescape(a.group(1))),
            }

    def leggi(self, url_albo, dal, max_pagine=None):
        dati = {"servizio": "cerca", "tipoPratica": "", "codiceRichiedente": "", "dadata": "", "adata": "", "oggetto": "",
                "ordina": "ANNO_REGISTRO,NUMERO_REGISTRO", "delXPag": "500", "sort": "DESC", "submit": "Cerca"}
        pagina, finale = get(sessione(), url_albo.split("?")[0], dati)
        out = [dict(r, piattaforma=self.nome) for r in self.righe(pagina, finale)]
        return [r for r in out if not r["inizio_pubbl"] or r["inizio_pubbl"] >= dal]


# ---------------------------------------------------------------- Comune di Milano (albopretorio.comune.milano.it, API JSON)
# /api/categories/ elenca i tipi di atto; /api/documents/?categories[]=<id>&page=N restituisce 10 atti per pagina,
# dal piu' recente. Le categorie con dati personali (matrimoni, notificazioni) non vengono nemmeno scaricate.

def _data_iso(s):
    try:
        return dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


class MilanoAPI:
    nome = "milano-api"
    SALTA = re.compile(r"matrimon|notificazion|deposito", re.I)

    @staticmethod
    def riconosci(url):
        return "albopretorio.comune.milano.it" in url

    def leggi(self, url_albo, dal, max_pagine=80):
        import json
        u = urllib.parse.urlparse(url_albo)
        base = "{0.scheme}://{0.netloc}".format(u)
        op = sessione()
        cat = json.loads(get(op, base + "/api/categories/?category_filter=")[0])
        out = []
        for c in cat.get("level_1", []):
            if not c.get("count") or self.SALTA.search(c["name"]):
                continue
            for pagina in range(1, max_pagine + 1):
                j = json.loads(get(op, f"{base}/api/documents/?categories[]={c['id']}&categories[]=&page={pagina}")[0])
                for d in j.get("data", []):
                    out.append({
                        "id": str(d["id"]), "registro": f"{d.get('number', '')}/{d.get('year', '')}",
                        "categoria": c["name"], "sottocategoria": d.get("sector") or "",
                        "oggetto": testo(d.get("subject") or ""), "inizio_pubbl": _data_iso(d.get("dt_pub_start")),
                        "fine_pubbl": _data_iso(d.get("dt_pub_end")), "url": f"{base}/documents/{d['id']}",
                        "piattaforma": self.nome,
                    })
                dati = j.get("data", [])
                if not dati or pagina >= j.get("total_pages", 1) or (_data_iso(dati[-1].get("dt_pub_start")) or dal) < dal:
                    break
        unici = {r["id"]: r for r in out}  # una pagina puo' slittare se nel frattempo esce un atto nuovo
        return [r for r in unici.values() if not r["inizio_pubbl"] or r["inizio_pubbl"] >= dal]


CONNETTORI = [JCityGov(), EPal(), Halley(), DgegovPA(), Sicraweb(), Urbi(), ComuneWeb(), HalleyEG(), AlboJSP(), MilanoAPI()]

# Piattaforme riconosciute ma ancora senza connettore (prossimi da scrivere)
PIATTAFORME_NOTE = {
    "saturnweb": "saturnweb",
    "albopretorionline": "albo-generico",
}


def piattaforma(url):
    for c in CONNETTORI:
        if c.riconosci(url):
            return c.nome
    for k, v in PIATTAFORME_NOTE.items():
        if k in url:
            return v
    return "sconosciuta"


def connettore(nome):
    return next((c for c in CONNETTORI if c.nome == nome), None)
