#!/usr/bin/env python3
"""
Radar cantieri - provincia di Milano (prototipo).

  python3 radar.py scopri          -> per ogni comune trova l'albo pretorio e il software usato (mappa_albi.csv)
  python3 radar.py prova           -> controlla che ogni albo della mappa risponda da questa macchina
  python3 radar.py raccogli 30     -> legge gli atti degli ultimi 30 giorni dai comuni con connettore,
                                      salva i soli atti utili (senza dati personali) in dati/radar.db
                                      e scrive dati/nuovi_AAAA-MM-GG.csv e dati/radar_cantieri.csv
Solo libreria standard di Python 3.9+.
"""
import csv, datetime as dt, html, os, re, sys, urllib.parse
import archivio as A
import connettori as C
from classifica import classifica

BASE = os.path.dirname(os.path.abspath(__file__))


def leggi_csv(nome, sep=";"):
    with open(os.path.join(BASE, nome), encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter=sep))


def scrivi_csv(nome, righe, campi):
    with open(os.path.join(BASE, nome), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campi, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(righe)


FIRME = [  # tracce nel codice della pagina che rivelano il software dell'albo
    (r'<meta name="jb" content="/ht/', "halley-eg"),
    (r"mc_p_ricerca\.php|halleyweb\.com/c\d+", "halley"),
    (r"papca|trasparenza-valutazione-merito", "jcitygov"),
    (r"ur1ME001\.sto", "urbi"),
    (r"albopretorioconsultazione\.aspx", "sicraweb-cms"),
    (r"/ServiziOnLine/AlboPretorio", "comuneweb"),
    (r"AlboOnline/ricercaAlbo|e-pal\.it", "e-pal"),
    (r"dgegovpa\.it", "dgegovpa"),
]


def riconosci_pagina(url, pagina):
    p = C.piattaforma(url)
    if p != "sconosciuta":
        return p, url
    # l'albo e' spesso dentro un iframe o dietro un link a un altro dominio
    for src in re.findall(r'<iframe[^>]+src="([^"]+)"', pagina, re.I) + re.findall(r'href="([^"]+)"', pagina):
        q = C.piattaforma(urllib.parse.urljoin(url, html.unescape(src)))
        if q not in ("sconosciuta",) and C.connettore(q):
            return q, urllib.parse.urljoin(url, html.unescape(src))
    for rx, nome in FIRME:
        if re.search(rx, pagina):
            return nome, url
    return "sconosciuta", url


def scopri():
    out = []
    for c in leggi_csv("comuni_mi.csv"):
        sito = c["sito"] if c["sito"].startswith("http") else "https://" + c["sito"]
        riga = dict(c, url_albo="", piattaforma="", errore="")
        try:
            op = C.sessione()
            pagina, finale = C.get(op, sito)
            link = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', pagina, re.S | re.I)
            cand = [urllib.parse.urljoin(finale, html.unescape(h)) for h, t in link
                    if re.search(r"albo[\s_-]*pretorio|albopretorio|alboonline", h + " " + C.testo(t), re.I)]
            if cand:
                url = cand[0]
                try:
                    pag2, fin2 = C.get(op, url)  # seguo il link: spesso porta a un altro dominio
                    riga["piattaforma"], riga["url_albo"] = riconosci_pagina(fin2, pag2)
                except Exception as e:
                    riga["piattaforma"], riga["url_albo"] = C.piattaforma(url), url
                    riga["errore"] = "albo non raggiungibile: " + str(e)[:80]
            else:
                riga["errore"] = "link albo non trovato"
        except Exception as e:
            riga["errore"] = str(e)[:120]
        print(f"{c['comune']:<28} {riga['piattaforma'] or '-':<13} {riga['url_albo'] or riga['errore']}", flush=True)
        out.append(riga)
    scrivi_csv("mappa_albi.csv", out, list(out[0].keys()))
    conta = {}
    for r in out:
        conta[r["piattaforma"] or "non trovato"] = conta.get(r["piattaforma"] or "non trovato", 0) + 1
    print("\nPiattaforme:", dict(sorted(conta.items(), key=lambda x: -x[1])))
    pronti = sum(1 for r in out if C.connettore(r["piattaforma"]))
    print(f"Comuni con connettore pronto: {pronti} su {len(out)}")


def mappa():
    """Unisce la mappa automatica (scopri) con quella fatta a mano, che ha la precedenza."""
    comuni = {c["comune"].lower(): c for c in leggi_csv("comuni_mi.csv")}
    righe = {}
    if os.path.exists(os.path.join(BASE, "mappa_albi.csv")):
        for r in leggi_csv("mappa_albi.csv"):
            if r.get("url_albo"):
                righe[r["comune"].lower()] = r
    for r in leggi_csv("mappa_manuale.csv"):
        base = comuni.get(r["comune"].lower(), {})
        righe[r["comune"].lower()] = {**base, **r}
    return sorted(righe.values(), key=lambda r: r["comune"])


def raccogli(giorni, db_path=None, uscita=None):
    oggi = dt.date.today().isoformat()
    dal = dt.date.today() - dt.timedelta(days=giorni)
    db = A.apri(db_path or os.path.join(BASE, "dati", "radar.db"))
    uscita = uscita or os.path.join(BASE, "dati")
    tot_letti = tot_utili = tot_nuovi = errori = 0
    for c in mappa():
        con = C.connettore(c.get("piattaforma", ""))
        if not con:
            continue
        istat = c.get("istat") or c["comune"]
        try:
            atti = con.leggi(c["url_albo"], dal)
        except Exception as e:  # un comune che non risponde non deve fermare il giro
            errori += 1
            A.registra_lettura(db, oggi, istat, c["comune"], con.nome, 0, 0, 0, f"{type(e).__name__}: {e}"[:300])
            print(f"{c['comune']:<28} ERRORE {type(e).__name__}: {str(e)[:100]}", flush=True)
            continue
        utili = []
        for a in atti:
            a["comune"], a["istat"] = c["comune"], istat
            a.setdefault("piattaforma", con.nome)
            k = classifica(a)
            if k:
                utili.append({**a, **k})  # l'oggetto oscurato del classificatore sostituisce quello grezzo
        nuovi = A.salva_segnali(db, utili, oggi)
        A.registra_lettura(db, oggi, istat, c["comune"], con.nome, len(atti), len(utili), nuovi)
        tot_letti += len(atti); tot_utili += len(utili); tot_nuovi += nuovi
        print(f"{c['comune']:<28} {len(atti):>4} atti, {len(utili):>3} utili, {nuovi:>3} nuovi", flush=True)
    n_oggi = A.esporta(db, os.path.join(uscita, f"nuovi_{oggi}.csv"), dal=oggi)
    n_tot = A.esporta(db, os.path.join(uscita, "radar_cantieri.csv"))
    print(f"\nGiro {oggi}: {tot_letti} atti letti, {tot_utili} utili, {tot_nuovi} nuovi ({n_oggi} nel file del giorno), "
          f"{n_tot} segnali in archivio, {errori} comuni in errore")
    return errori


def prova():
    """Controlla solo che ogni albo risponda da questa macchina (utile per capire se un server/GitHub viene bloccato)."""
    ok = ko = 0
    for c in mappa():
        try:
            pagina, _ = C.get(C.sessione(), c["url_albo"])
            esito = f"OK  {len(pagina):>7} caratteri"
            ok += 1
        except Exception as e:
            esito = f"KO  {type(e).__name__}: {str(e)[:80]}"
            ko += 1
        print(f"{c['comune']:<28} {c.get('piattaforma', ''):<13} {esito}", flush=True)
    print(f"\n{ok} albi raggiungibili, {ko} no")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "scopri":
        scopri()
    elif cmd == "prova":
        prova()
    elif cmd == "raccogli":
        errori = raccogli(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
        sys.exit(0)  # gli errori dei singoli comuni stanno nella tabella letture
    else:
        print(__doc__)
