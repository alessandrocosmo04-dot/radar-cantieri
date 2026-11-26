"""
Dal radar al prodotto: tabelle pulite, indicatori e campione vendibile con controlli di qualita'.

Ingressi   dati/radar.db (segnali dagli albi, con storia point-in-time)
           dati/anac.db  (facoltativo: appalti, aggiudicazioni, imprese vincitrici, SOA)
Uscite     dati/prodotto.db con le tabelle
             opere            una riga per opera (CUP, altrimenti CIG, altrimenti atto singolo), con fasi e date
             opere_eventi     ogni atto dell'opera: fase, data di pubblicazione, data di prima osservazione
             imprese          una riga per impresa (partita IVA se nota), con attivita' e comuni
             imprese_legami   ogni menzione -> impresa, con metodo e confidenza
             cantieri         cantieri privati e lavori su strada dalle ordinanze (indirizzo, date, impresa)
             indicatori_comune  per comune: pipeline di lavori in arrivo, cantieri, titoli edilizi, imprese attive
           e, con --campione <cartella>, i CSV del campione + qualita.json

Point-in-time: ogni misura usa la data di prima osservazione (prima_vista) e la tabella versioni; con --al AAAA-MM-GG
si ricostruisce il prodotto come sarebbe stato quel giorno, senza nessuna informazione successiva.

Uso: python3 prodotto.py [--al 2026-11-26] [--campione /percorso/cartella]
"""
import csv
import datetime as dt
import json
import os
import re
import sqlite3
import sys

import imprese as I

BASE = os.path.dirname(os.path.abspath(__file__))
ORDINE_FASI = ["programmazione", "finanziamento", "progetto", "autorizzazione", "gara_in_partenza", "affidamento",
               "esecuzione", "cantiere_aperto", "collaudo"]
IN_ARRIVO = {"programmazione", "finanziamento", "progetto", "autorizzazione", "gara_in_partenza"}
CUP_OK = re.compile(r"^[A-Z]\d{2}[A-Z]\d{2}[A-Z0-9]{9}$")
CIG_OK = re.compile(r"^[A-Z0-9]{10}$")
CF_PERSONA = re.compile(r"\b[A-Z]{6}\d{2}[A-EHLMPR-T]\d{2}[A-Z]\d{3}[A-Z]\b")
INDIRIZZO = re.compile(r"\b(VIA|VIALE|V\.LE|PIAZZA|P\.ZZA|PIAZZALE|CORSO|C\.SO|LARGO|VICOLO|STRADA|ALZAIA)\s+"
                       r"((?:(?!(?:FRONTE|ALTEZZA|ANGOLO|DAL|DALLE|PER|TRA|NEL|SINO|FINO|LATO|AMBO|CIV|CIVICO)\b)[A-Z0-9'’\.]+\s?){1,5}?)(?:\s*(?:N\.?|CIV\.?|CIVICO|NR\.?)?\s*(\d{1,4}(?:\s?[/\-]\s?\d{1,4})?[A-Z]?))?"
                       r"(?=\s*(?:[,\-–(;:]|$|\s(?:DAL|DALLE|IL|PER|NEL|NEI|E|ED|ANGOLO|FRONTE|ALTEZZA|TRA|IN|A|DI|DEL|SINO|FINO|NELLE|AMBO|LATO)\b))", re.I)
DATA_ATTO = re.compile(r"\bDEL\s+(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
PERMESSO = re.compile(r"permess\w* di costruire|titol\w* ediliz", re.I)


def fase_max(fasi):
    noti = [f for f in fasi if f in ORDINE_FASI]
    if "revoca" in fasi and not noti:
        return "revoca"
    return max(noti, key=ORDINE_FASI.index) if noti else (sorted(set(fasi))[0] if fasi else None)


def indirizzo(testo):
    m = INDIRIZZO.search((testo or "").upper())
    if not m:
        return None
    tipo = {"V.LE": "VIALE", "P.ZZA": "PIAZZA", "C.SO": "CORSO"}.get(m.group(1).upper(), m.group(1).upper())
    nome = re.sub(r"\s+", " ", m.group(2)).strip(" .")
    if not nome or nome in ("N", "DEL", "DI"):
        return None
    return f"{tipo} {nome}" + (f" {m.group(3).replace(' ', '')}" if m.group(3) else "")


def data_atto(testo):
    m = DATA_ATTO.search(testo or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------- lettura point-in-time

def segnali_al(radar, al):
    """Segnali come li conoscevamo il giorno `al`: visti per la prima volta entro quella data, con l'ultima versione
    valida a quella data, esclusi quelli che a quella data risultavano scartati."""
    radar.row_factory = sqlite3.Row
    righe = radar.execute("""
        SELECT s.istat, s.piattaforma, s.id, s.comune, s.registro, s.categoria, s.sottocategoria, s.inizio_pubbl,
               s.fine_pubbl, s.url, s.parola_chiave, s.oggetto, s.indirizzo, s.prima_vista, s.ultima_vista,
               v.tipo, v.fase, v.importo_eur, v.cig, v.cup, v.impresa, v.valida_dal
        FROM segnali s
        JOIN versioni v ON v.istat = s.istat AND v.piattaforma = s.piattaforma AND v.id = s.id
        WHERE s.prima_vista <= :al
          AND v.valida_dal = (SELECT MAX(valida_dal) FROM versioni w
                              WHERE w.istat = s.istat AND w.piattaforma = s.piattaforma AND w.id = s.id AND w.valida_dal <= :al)
          AND v.tipo IS NOT NULL""", {"al": al}).fetchall()
    return [dict(r) for r in righe]


def anac_tabelle(percorso):
    if not percorso or not os.path.exists(percorso):
        return None
    a = sqlite3.connect(percorso)
    a.row_factory = sqlite3.Row
    return a


# ---------------------------------------------------------------- costruzione

def costruisci(radar_path, anac_path, out_path, al):
    radar = sqlite3.connect(radar_path)
    seg = segnali_al(radar, al)
    with open(os.path.join(BASE, "comuni_mi.csv"), encoding="utf-8") as f:
        comuni = list(csv.DictReader(f, delimiter=";"))
    cf_enti = {c["cf"] for c in comuni if c.get("cf")}
    anac = anac_tabelle(anac_path)

    # --- estrazione strutturata dal testo
    for s in seg:
        o = s["oggetto"] or ""
        s["cup"] = s["cup"] if s["cup"] and CUP_OK.match(s["cup"]) else None
        s["cig"] = s["cig"] if s["cig"] and CIG_OK.match(s["cig"]) else None
        s["indirizzo"] = s["indirizzo"] or indirizzo(o)
        s["data_atto"] = data_atto(o)
        pive = I.piva_dal_testo(o, escludi=cf_enti)
        s["piva"] = pive[0] if len(pive) == 1 and s["impresa"] else None  # attribuita solo se non ambigua
        s["chiave"] = f"{s['istat']}|{s['piattaforma']}|{s['id']}"

    # --- duplicati: lo stesso atto pubblicato su piu' albi (es. avvisi di altri enti) conta una volta
    visti, unici = {}, []
    for s in sorted(seg, key=lambda x: (x["prima_vista"], x["chiave"])):
        firma = (re.sub(r"\W+", "", (s["oggetto"] or "").upper())[:160], s["inizio_pubbl"])
        if firma in visti:
            visti[firma]["anche_su"].append(s["comune"])
            continue
        s["anche_su"] = []
        visti[firma] = s
        unici.append(s)
    seg = unici

    # --- imprese: menzioni dall'albo + aggiudicatari ANAC
    menzioni = [{"chiave": "albo|" + s["chiave"], "nome": s["impresa"], "piva": s["piva"], "fonte": "albo",
                 "comune": s["comune"], "data": s["prima_vista"], "cig": s["cig"]} for s in seg if s["impresa"]]
    if anac:
        for r in anac.execute("""SELECT t.id_aggiudicazione, t.cig, t.ruolo, t.codice_fiscale, t.denominazione,
                                        c.luogo_istat, z.data_aggiudicazione, z.importo, c.importo_lotto
                                 FROM anac_aggiudicatari t JOIN anac_cig c ON c.cig = t.cig
                                 LEFT JOIN anac_aggiudicazioni z ON z.id_aggiudicazione = t.id_aggiudicazione
                                 WHERE t.persona_fisica = 0 AND t.denominazione IS NOT NULL
                                   AND COALESCE(z.data_aggiudicazione, c.data_pubblicazione) <= ?""", (al,)):
            menzioni.append({"chiave": f"anac|{r['id_aggiudicazione']}|{r['codice_fiscale']}|{r['ruolo']}", "nome": r["denominazione"],
                             "piva": r["codice_fiscale"] if I.piva_valida(r["codice_fiscale"] or "") else None,
                             "fonte": "anac", "cig": r["cig"], "data": r["data_aggiudicazione"], "luogo_istat": r["luogo_istat"],
                             "importo": r["importo"] or r["importo_lotto"], "ruolo": r["ruolo"]})
    imp, legami = I.risolvi(menzioni)
    per_chiave = {l["chiave"]: l for l in legami}
    nome_comune = {c["istat"]: c["comune"] for c in comuni}
    for m in menzioni:
        l = per_chiave[m["chiave"]]
        s = imp[l["id_impresa"]]
        s.setdefault("comuni", set()).add(m.get("comune") or nome_comune.get(m.get("luogo_istat") or "", m.get("luogo_istat")))
        s.setdefault("date", []).append(m.get("data"))
        s.setdefault("fonti", set()).add(m["fonte"])
        if m["fonte"] == "anac":
            s["n_aggiudicazioni"] = s.get("n_aggiudicazioni", 0) + 1
            s["importo_aggiudicato"] = s.get("importo_aggiudicato", 0) + (m.get("importo") or 0)
            s.setdefault("aggiudicazioni", []).append((m.get("data"), m.get("importo") or 0))

    # --- opere: raggruppate per CUP, poi CIG
    opere = {}
    for s in seg:
        if s["tipo"] == "cantiere_privato":
            continue
        cod = s["cup"] or s["cig"] or "ATTO:" + s["chiave"]
        o = opere.setdefault(cod, {"id_opera": cod, "cup": s["cup"], "cig": set(), "eventi": [], "comune": s["comune"], "istat": s["istat"]})
        if s["cig"]:
            o["cig"].add(s["cig"])
        o["eventi"].append(s)
    # un CIG visto con un CUP lega gli atti col solo CIG all'opera del CUP
    cig_a_cup = {c: o["id_opera"] for o in opere.values() if o["cup"] for c in o["cig"]}
    for cod in [k for k, o in opere.items() if not o["cup"] and o["cig"]]:
        dest = next((cig_a_cup[c] for c in opere[cod]["cig"] if c in cig_a_cup), None)
        if dest and dest != cod:
            opere[dest]["eventi"] += opere[cod]["eventi"]
            opere[dest]["cig"] |= opere[cod]["cig"]
            del opere[cod]
    cig_anac = {}
    if anac:
        tutti = {c for o in opere.values() for c in o["cig"]}
        for r in anac.execute(f"SELECT * FROM anac_cig WHERE cig IN ({','.join('?' * len(tutti))})", tuple(tutti)) if tutti else []:
            cig_anac[r["cig"]] = dict(r)

    db = sqlite3.connect(out_path + ".tmp")
    db.executescript("""
    CREATE TABLE opere (id_opera TEXT PRIMARY KEY, cup TEXT, cig TEXT, istat TEXT, comune TEXT, tipo TEXT, titolo TEXT,
        fase_corrente TEXT, fasi TEXT, in_arrivo INTEGER, n_atti INTEGER, prima_osservazione TEXT, ultima_osservazione TEXT,
        primo_atto TEXT, ultimo_atto TEXT, importo_albo_eur REAL, importo_anac_eur REAL, stazione_appaltante TEXT,
        cpv TEXT, imprese TEXT, indirizzo TEXT, fonte_url TEXT);
    CREATE TABLE opere_eventi (id_opera TEXT, chiave_atto TEXT, comune TEXT, fase TEXT, data_pubblicazione TEXT,
        data_atto TEXT, prima_osservazione TEXT, oggetto TEXT, url TEXT, anche_su TEXT);
    CREATE TABLE imprese (id_impresa TEXT PRIMARY KEY, partita_iva TEXT, denominazione TEXT, forma TEXT, n_alias INTEGER,
        alias TEXT, fonti TEXT, n_menzioni INTEGER, n_comuni INTEGER, comuni TEXT, prima_osservazione TEXT,
        ultima_osservazione TEXT, n_aggiudicazioni INTEGER, importo_aggiudicato_eur REAL,
        importo_12m_eur REAL, importo_12m_precedenti_eur REAL, crescita_12m REAL, soa_categorie TEXT);
    CREATE TABLE imprese_legami (chiave_menzione TEXT PRIMARY KEY, fonte TEXT, nome_menzionato TEXT, id_impresa TEXT,
        metodo TEXT, punteggio REAL, confidenza REAL);
    CREATE TABLE cantieri (chiave_atto TEXT PRIMARY KEY, istat TEXT, comune TEXT, indirizzo TEXT, impresa TEXT,
        id_impresa TEXT, data_pubblicazione TEXT, prima_osservazione TEXT, oggetto TEXT, url TEXT);
    CREATE TABLE indicatori_comune (istat TEXT PRIMARY KEY, comune TEXT, al TEXT, opere_osservate INTEGER,
        opere_in_arrivo INTEGER, opere_in_gara INTEGER, opere_affidate INTEGER, opere_in_esecuzione INTEGER,
        opere_collaudate INTEGER, importo_noto_in_arrivo_eur REAL, cantieri_privati_30g INTEGER,
        titoli_edilizi_30g INTEGER, imprese_attive_30g INTEGER, albo_letto_ultimo_giro INTEGER);
    CREATE TABLE meta (chiave TEXT PRIMARY KEY, valore TEXT);
    """)

    for o in opere.values():
        ev = sorted(o["eventi"], key=lambda s: (s["prima_vista"], s["inizio_pubbl"] or ""))
        fasi = [s["fase"] for s in ev]
        imprese_op = sorted({per_chiave["albo|" + s["chiave"]]["id_impresa"] for s in ev if s["impresa"]})
        an = [cig_anac[c] for c in o["cig"] if c in cig_anac]
        fc = fase_max(fasi)
        db.execute("INSERT INTO opere VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            o["id_opera"], o["cup"], ",".join(sorted(o["cig"])) or None, o["istat"], o["comune"],
            ev[0]["tipo"], ev[0]["oggetto"][:300], fc, ",".join(dict.fromkeys(fasi)), int(fc in IN_ARRIVO), len(ev),
            ev[0]["prima_vista"], ev[-1]["prima_vista"], min((s["inizio_pubbl"] or "9") for s in ev)[:10],
            max((s["inizio_pubbl"] or "") for s in ev)[:10] or None,
            max([s["importo_eur"] for s in ev if s["importo_eur"]] or [None]) if any(s["importo_eur"] for s in ev) else None,
            sum(a["importo_lotto"] or 0 for a in an) or None, an[0]["denominazione_sa"] if an else None,
            an[0]["cod_cpv"] if an else None, ",".join(imprese_op) or None,
            next((s["indirizzo"] for s in ev if s["indirizzo"]), None), ev[-1]["url"]))
        for s in ev:
            db.execute("INSERT INTO opere_eventi VALUES (?,?,?,?,?,?,?,?,?,?)", (
                o["id_opera"], s["chiave"], s["comune"], s["fase"], (s["inizio_pubbl"] or "")[:10] or None, s["data_atto"],
                s["prima_vista"], s["oggetto"], s["url"], ",".join(s["anche_su"]) or None))

    oggi = dt.date.fromisoformat(al)
    for s in imp.values():
        date = sorted(d for d in s.get("date", []) if d)
        agg = s.get("aggiudicazioni", [])
        u12 = sum(v for d, v in agg if d and oggi - dt.timedelta(days=365) < dt.date.fromisoformat(d[:10]) <= oggi)
        p12 = sum(v for d, v in agg if d and oggi - dt.timedelta(days=730) < dt.date.fromisoformat(d[:10]) <= oggi - dt.timedelta(days=365))
        soa = None
        if anac and s["piva"]:
            soa = ",".join(f"{r[0]}:{r[1]}" for r in anac.execute(
                """SELECT c.categoria, c.classifica FROM anac_soa a JOIN anac_soa_categorie c USING (id_attestazione)
                   WHERE a.cf_impresa = ? AND a.stato LIKE 'IN_CORSO%' ORDER BY c.categoria""", (s["piva"],))) or None
        com = sorted(c for c in s.get("comuni", set()) if c)
        db.execute("INSERT INTO imprese VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            s["id"], s["piva"], s["nome"], s["forma"], len(s["alias"]), " | ".join(sorted(s["alias"])),
            ",".join(sorted(s.get("fonti", []))), s["menzioni"], len(com), ",".join(com),
            date[0] if date else None, date[-1] if date else None, s.get("n_aggiudicazioni"),
            round(s.get("importo_aggiudicato"), 2) if s.get("importo_aggiudicato") else None,
            round(u12, 2) if agg else None, round(p12, 2) if agg else None,
            round(u12 / p12 - 1, 4) if agg and p12 > 0 else None, soa))
    for m in menzioni:
        l = per_chiave[m["chiave"]]
        db.execute("INSERT INTO imprese_legami VALUES (?,?,?,?,?,?,?)",
                   (m["chiave"], m["fonte"], m["nome"], l["id_impresa"], l["metodo"], l["punteggio"], l["confidenza"]))

    for s in seg:
        if s["tipo"] != "cantiere_privato":
            continue
        idi = per_chiave["albo|" + s["chiave"]]["id_impresa"] if s["impresa"] else None
        db.execute("INSERT INTO cantieri VALUES (?,?,?,?,?,?,?,?,?,?)", (
            s["chiave"], s["istat"], s["comune"], s["indirizzo"], s["impresa"], idi, (s["inizio_pubbl"] or "")[:10] or None,
            s["prima_vista"], s["oggetto"], s["url"]))

    # --- indicatori per comune (finestra 30 giorni sulla data di prima osservazione)
    d30 = (oggi - dt.timedelta(days=30)).isoformat()
    letture = {r[0]: r[1] for r in radar.execute(
        "SELECT istat, CASE WHEN errore IS NULL THEN 1 ELSE 0 END FROM letture WHERE giorno = (SELECT MAX(giorno) FROM letture WHERE giorno <= ?)", (al,))}
    for c in comuni:
        ist = c["istat"]
        q = lambda sql, *p: db.execute(sql, (ist, *p)).fetchone()[0]
        db.execute("INSERT INTO indicatori_comune VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            ist, c["comune"], al,
            q("SELECT COUNT(*) FROM opere WHERE istat=?"),
            q("SELECT COUNT(*) FROM opere WHERE istat=? AND in_arrivo=1"),
            q("SELECT COUNT(*) FROM opere WHERE istat=? AND fase_corrente='gara_in_partenza'"),
            q("SELECT COUNT(*) FROM opere WHERE istat=? AND fase_corrente='affidamento'"),
            q("SELECT COUNT(*) FROM opere WHERE istat=? AND fase_corrente IN ('esecuzione','cantiere_aperto')"),
            q("SELECT COUNT(*) FROM opere WHERE istat=? AND fase_corrente='collaudo'"),
            q("SELECT SUM(COALESCE(importo_anac_eur, importo_albo_eur)) FROM opere WHERE istat=? AND in_arrivo=1"),
            q("SELECT COUNT(*) FROM cantieri WHERE istat=? AND prima_osservazione > ?", d30),
            sum(1 for s in seg if s["istat"] == ist and s["prima_vista"] > d30 and PERMESSO.search(s["oggetto"] or "")),
            len({per_chiave["albo|" + s["chiave"]]["id_impresa"] for s in seg
                 if s["istat"] == ist and s["impresa"] and s["prima_vista"] > d30}),
            letture.get(ist)))
    meta = {"al": al, "creato_il": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "segnali": len(seg), "anac": bool(anac), "versione": "0.3"}
    db.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
    db.commit()
    db.close()
    os.replace(out_path + ".tmp", out_path)
    return meta


# ---------------------------------------------------------------- qualita' ed export

def controlli(prodotto_path):
    """Controlli automatici sul prodotto: chiavi, formati, privacy, coerenza. Ritorna dict con esito per controllo."""
    db = sqlite3.connect(prodotto_path)
    one = lambda sql: db.execute(sql).fetchone()[0]
    testo = " ".join(r[0] or "" for r in db.execute(
        "SELECT oggetto FROM opere_eventi UNION ALL SELECT oggetto FROM cantieri UNION ALL SELECT alias FROM imprese"))
    c = {
        "opere_chiave_unica": one("SELECT COUNT(*) - COUNT(DISTINCT id_opera) FROM opere") == 0,
        "cup_formato_valido": one("SELECT COUNT(*) FROM opere WHERE cup IS NOT NULL AND cup NOT GLOB '[A-Z][0-9][0-9][A-Z][0-9][0-9]*'") == 0,
        "partite_iva_valide": all(I.piva_valida(r[0]) for r in db.execute("SELECT partita_iva FROM imprese WHERE partita_iva IS NOT NULL")),
        "nessun_codice_fiscale_di_persona": not CF_PERSONA.search(testo.upper()),
        "date_non_nel_futuro": one("SELECT COUNT(*) FROM opere_eventi WHERE prima_osservazione > (SELECT json_extract(valore,'$') FROM meta WHERE chiave='al')") == 0,
        "importi_positivi": one("SELECT COUNT(*) FROM opere WHERE importo_albo_eur <= 0 OR importo_anac_eur <= 0") == 0,
        "ogni_menzione_ha_impresa": one("SELECT COUNT(*) FROM imprese_legami WHERE id_impresa IS NULL") == 0,
        "fase_valida": one(f"SELECT COUNT(*) FROM opere WHERE fase_corrente NOT IN ({','.join(repr(f) for f in ORDINE_FASI + ['revoca', 'asta_immobile', 'altro'])})") == 0,
    }
    misure = {
        "opere": one("SELECT COUNT(*) FROM opere"),
        "opere_con_cup": one("SELECT COUNT(*) FROM opere WHERE cup IS NOT NULL"),
        "opere_con_piu_atti": one("SELECT COUNT(*) FROM opere WHERE n_atti > 1"),
        "opere_con_importo": one("SELECT COUNT(*) FROM opere WHERE COALESCE(importo_anac_eur, importo_albo_eur) IS NOT NULL"),
        "opere_in_arrivo": one("SELECT COUNT(*) FROM opere WHERE in_arrivo = 1"),
        "imprese": one("SELECT COUNT(*) FROM imprese"),
        "imprese_con_partita_iva": one("SELECT COUNT(*) FROM imprese WHERE partita_iva IS NOT NULL"),
        "legami_confidenza_media": round(one("SELECT AVG(confidenza) FROM imprese_legami") or 0, 3),
        "cantieri": one("SELECT COUNT(*) FROM cantieri"),
        "cantieri_con_indirizzo": one("SELECT COUNT(*) FROM cantieri WHERE indirizzo IS NOT NULL"),
        "comuni_con_dati": one("SELECT COUNT(*) FROM indicatori_comune WHERE opere_osservate > 0 OR cantieri_privati_30g > 0"),
    }
    db.close()
    return {"controlli": c, "tutti_superati": all(c.values()), "misure": misure}


def esporta_campione(prodotto_path, cartella):
    os.makedirs(cartella, exist_ok=True)
    db = sqlite3.connect(prodotto_path)
    file = {}
    for t, ordine in (("opere", "comune, prima_osservazione"), ("opere_eventi", "id_opera, prima_osservazione"),
                      ("imprese", "n_menzioni DESC, denominazione"), ("imprese_legami", "id_impresa"),
                      ("cantieri", "comune, prima_osservazione"), ("indicatori_comune", "comune")):
        cur = db.execute(f"SELECT * FROM {t} ORDER BY {ordine}")
        col = [d[0] for d in cur.description]
        righe = cur.fetchall()
        with open(os.path.join(cartella, f"{t}.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(col)
            w.writerows(righe)
        file[t] = len(righe)
    db.close()
    q = controlli(prodotto_path)
    q["righe_per_file"] = file
    with open(os.path.join(cartella, "qualita.json"), "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=1)
    return q


if __name__ == "__main__":
    args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    al = args.get("--al", dt.date.today().isoformat())
    out = args.get("--out", os.path.join(BASE, "dati", "prodotto.db"))
    meta = costruisci(args.get("--radar", os.path.join(BASE, "dati", "radar.db")),
                      args.get("--anac", os.path.join(BASE, "dati", "anac.db")), out, al)
    print(meta)
    q = esporta_campione(out, args["--campione"]) if "--campione" in args else controlli(out)
    print(json.dumps(q, ensure_ascii=False, indent=1))
