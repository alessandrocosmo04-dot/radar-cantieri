"""
Incrocio con gli open data ANAC (Autorita' Nazionale Anticorruzione), licenza CC BY 4.0.

Cosa scarica (solo su GitHub Actions: dal nostro ambiente il sito e' bloccato)
  cig            ogni appalto pubblicato: oggetto, importo, stazione appaltante, comune del lavoro, CPV, CUP spesso
                 in "numero_gara", esito. Pacchetti annuali cig-2023..2025 (un file al mese) + pacchetto "cig"
                 (aggiornamenti mensili dal 2026).
  aggiudicazioni chi ha vinto quando, importo di aggiudicazione, ribasso, numero di offerte e di offerenti.
  aggiudicatari  le imprese vincitrici con codice fiscale / partita IVA e ruolo (singola, mandataria, mandante).
  soa            attestazioni SOA: categorie (OG/OS) e classifiche per impresa = la taglia massima dei lavori
                 che un'impresa puo' prendere.

Cosa tiene
  Solo gli appalti con luogo di esecuzione in provincia di Milano (ISTAT 015xxx) oppure banditi da un ente con sede
  in un comune della provincia, e solo LAVORI o servizi di architettura e ingegneria (CPV 71*: la progettazione
  anticipa i lavori di mesi). Di aggiudicazioni e aggiudicatari solo le righe di quei CIG.

Privacy (GDPR)
  Gli aggiudicatari persona fisica o ditta individuale (codice fiscale di 16 caratteri o tipo DITTA INDIVIDUALE)
  restano come riga senza nome e senza codice fiscale: sappiamo che il lavoro e' andato a una ditta individuale,
  non a chi.

Point-in-time
  Ogni riga porta "prima_vista_anac" (il giorno in cui l'abbiamo caricata per la prima volta) e "fonte" (il file
  ANAC da cui viene). Gli storici 2023-2025 sono ricostruiti in un colpo solo e quindi marcati come tali: la loro
  data utile e' data_pubblicazione, non prima_vista_anac.

Uso
  python3 anac.py aggiorna [--anni 2023,2024,2025] [--db dati/anac.db]
"""
import csv
import datetime as dt
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import urllib.request
import zipfile

BASE = "https://dati.anticorruzione.it/opendata"
API = BASE + "/api/3/action/"
UA = "Mozilla/5.0 (X11; Linux x86_64) RadarCantieri/0.2 (open data ANAC; download mensile)"
csv.field_size_limit(10**8)

SCHEMA = """
CREATE TABLE IF NOT EXISTS anac_file (
    risorsa TEXT PRIMARY KEY, pacchetto TEXT, url TEXT, dimensione TEXT, modificato TEXT,
    righe_lette INTEGER, righe_tenute INTEGER, elaborato_il TEXT
);
CREATE TABLE IF NOT EXISTS anac_cig (
    cig TEXT PRIMARY KEY, cig_accordo_quadro TEXT, numero_gara TEXT, cup TEXT,
    oggetto_gara TEXT, oggetto_lotto TEXT, importo_gara REAL, importo_lotto REAL, importo_sicurezza REAL,
    oggetto_principale TEXT, stato TEXT, settore TEXT, luogo_istat TEXT, provincia TEXT,
    data_pubblicazione TEXT, data_scadenza_offerta TEXT, tipo_scelta_contraente TEXT, modalita_realizzazione TEXT,
    cf_sa TEXT, denominazione_sa TEXT, centro_costo TEXT, cod_cpv TEXT, descrizione_cpv TEXT,
    cui_programma TEXT, esito TEXT, data_esito TEXT, flag_pnrr TEXT, data_cancellazione TEXT,
    fonte TEXT, prima_vista_anac TEXT, aggiornato_il TEXT
);
CREATE INDEX IF NOT EXISTS anac_cig_luogo ON anac_cig(luogo_istat);
CREATE INDEX IF NOT EXISTS anac_cig_sa ON anac_cig(cf_sa);
CREATE INDEX IF NOT EXISTS anac_cig_cup ON anac_cig(cup);
CREATE TABLE IF NOT EXISTS anac_aggiudicazioni (
    id_aggiudicazione TEXT PRIMARY KEY, cig TEXT, data_aggiudicazione TEXT, esito TEXT, criterio TEXT,
    data_comunicazione_esito TEXT, importo REAL, ribasso REAL, offerte_ammesse INTEGER, offerte_escluse INTEGER,
    imprese_offerenti INTEGER, imprese_invitate INTEGER, imprese_richiedenti INTEGER, flag_subappalto TEXT,
    massimo_ribasso REAL, minimo_ribasso REAL, prestazioni_comprese TEXT,
    fonte TEXT, prima_vista_anac TEXT
);
CREATE INDEX IF NOT EXISTS anac_agz_cig ON anac_aggiudicazioni(cig);
CREATE TABLE IF NOT EXISTS anac_aggiudicatari (
    id_aggiudicazione TEXT NOT NULL, cig TEXT, ruolo TEXT, chiave TEXT NOT NULL,
    codice_fiscale TEXT, denominazione TEXT, tipo_soggetto TEXT, persona_fisica INTEGER,
    fonte TEXT, prima_vista_anac TEXT,
    PRIMARY KEY (id_aggiudicazione, chiave, ruolo)
);
CREATE INDEX IF NOT EXISTS anac_agt_cig ON anac_aggiudicatari(cig);
CREATE INDEX IF NOT EXISTS anac_agt_cf ON anac_aggiudicatari(codice_fiscale);
CREATE TABLE IF NOT EXISTS anac_soa (
    id_attestazione TEXT PRIMARY KEY, cf_impresa TEXT, denominazione TEXT, provincia TEXT, stato TEXT,
    data_rilascio TEXT, scadenza_triennale TEXT, scadenza_quinquennale TEXT, fonte TEXT, prima_vista_anac TEXT
);
CREATE INDEX IF NOT EXISTS anac_soa_cf ON anac_soa(cf_impresa);
CREATE TABLE IF NOT EXISTS anac_soa_categorie (
    id_attestazione TEXT NOT NULL, categoria TEXT NOT NULL, classifica TEXT,
    PRIMARY KEY (id_attestazione, categoria)
);
"""

# classifiche SOA -> importo massimo in euro (art. 2 all. II.12 d.lgs. 36/2023)
CLASSIFICHE_SOA = {"I": 258_000, "II": 516_000, "III": 1_033_000, "III-BIS": 1_500_000, "IV": 2_582_000,
                   "IV-BIS": 3_500_000, "V": 5_165_000, "VI": 10_329_000, "VII": 15_494_000, "VIII": None}

CF_IMPRESA = re.compile(r"^\d{11}$")
CUP = re.compile(r"^([A-Z]\d{2}[A-Z]\d{2}[A-Z0-9]{9})(?:V\d+)?$")  # 15 caratteri, a volte con suffisso di versione


# ---------------------------------------------------------------- rete

def _apri(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout)


def api(azione, **par):
    q = "&".join(f"{k}={v}" for k, v in par.items())
    with _apri(f"{API}{azione}?{q}") as r:
        grezzo, tipo, stato = r.read(), r.headers.get("content-type"), r.status
    try:
        return json.loads(grezzo)["result"]
    except ValueError:
        raise RuntimeError(f"il catalogo ANAC non ha risposto in JSON (HTTP {stato}, {tipo}): {grezzo[:300]!r}")


def scarica(url, dest, tentativi=4):
    for t in range(1, tentativi + 1):
        try:
            with _apri(url, timeout=300) as r, open(dest, "wb") as f:
                while True:
                    blocco = r.read(1 << 20)
                    if not blocco:
                        break
                    f.write(blocco)
            return dest
        except Exception as e:  # rete lenta o chiusa: riprova con attesa crescente
            if t == tentativi:
                raise
            print(f"  download fallito ({type(e).__name__}), riprovo fra {30 * t}s", flush=True)
            time.sleep(30 * t)


def risorse(pacchetto, nome_re):
    """Risorse CSV di un pacchetto CKAN il cui nome corrisponde a nome_re, in ordine cronologico di nome."""
    p = api("package_show", id=pacchetto)
    out = [r for r in p["resources"] if re.fullmatch(nome_re, r.get("name", "")) and (r.get("format") or "").upper() == "CSV"]
    return sorted(out, key=lambda r: r["name"])


# ---------------------------------------------------------------- lettura

def righe_csv(percorso):
    """Righe (dict) di un CSV ANAC, dentro uno zip oppure in chiaro. Le intestazioni vanno in minuscolo."""
    if zipfile.is_zipfile(percorso):
        z = zipfile.ZipFile(percorso)
        nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        grezzo = io.TextIOWrapper(z.open(nome), encoding="utf-8-sig", errors="replace", newline="")
    else:
        grezzo = open(percorso, encoding="utf-8-sig", errors="replace", newline="")
    with grezzo:
        r = csv.reader(grezzo, delimiter=";", quotechar='"')
        testata = [h.strip().lower() for h in next(r)]
        for riga in r:
            if riga:
                yield dict(zip(testata, riga))


def num(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s.replace(",", ".")) if s.count(",") == 1 and "." not in s else float(s)
    except ValueError:
        return None


def intero(s):
    v = num(s)
    return int(v) if v is not None else None


def vuoto(s):
    s = (s or "").strip()
    return s or None


def data_iso(s):
    s = (s or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", s)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


# ---------------------------------------------------------------- filtri

def carica_comuni(percorso="comuni_mi.csv"):
    with open(percorso, encoding="utf-8") as f:
        righe = list(csv.DictReader(f, delimiter=";"))
    return {r["istat"] for r in righe}, {r["cf"] for r in righe if r.get("cf")}


def tieni_cig(r, cf_comuni):
    luogo = (r.get("luogo_istat") or "").strip()
    in_provincia = luogo.startswith("015") or (r.get("provincia") or "").strip().upper() == "MILANO" \
        or (r.get("cf_amministrazione_appaltante") or "").strip() in cf_comuni
    if not in_provincia:
        return False
    oggetto = (r.get("oggetto_principale_contratto") or "").strip().upper()
    cpv = (r.get("cod_cpv") or "").strip()
    return oggetto == "LAVORI" or cpv.startswith("45") or cpv.startswith("71")


def cup_da(numero_gara):
    m = CUP.match((numero_gara or "").strip().upper())
    return m.group(1) if m else None


def persona_fisica(cf, tipo):
    cf = (cf or "").strip().upper()
    return (len(cf) == 16 and not cf.isdigit()) or "INDIVIDUALE" in (tipo or "").upper() \
        or "PERSONA FISICA" in (tipo or "").upper() or "LIBERO PROFESSIONISTA" in (tipo or "").upper()


# ---------------------------------------------------------------- caricamento

def carica_cig(db, percorso, fonte, oggi, cf_comuni):
    lette = tenute = 0
    for r in righe_csv(percorso):
        lette += 1
        if not tieni_cig(r, cf_comuni):
            continue
        # piu' righe per lo stesso CIG (una per CPV): teniamo la prevalente, o la prima vista
        if (r.get("flag_prevalente") or "1").strip() not in ("1", "1.0", "true", ""):
            if db.execute("SELECT 1 FROM anac_cig WHERE cig=?", (r["cig"],)).fetchone():
                continue
        tenute += 1
        v = (r["cig"].strip(), vuoto(r.get("cig_accordo_quadro")), vuoto(r.get("numero_gara")), cup_da(r.get("numero_gara")),
             vuoto(r.get("oggetto_gara")), vuoto(r.get("oggetto_lotto")), num(r.get("importo_complessivo_gara")),
             num(r.get("importo_lotto")), num(r.get("importo_sicurezza")), vuoto(r.get("oggetto_principale_contratto")),
             vuoto(r.get("stato")), vuoto(r.get("settore")), vuoto(r.get("luogo_istat")), vuoto(r.get("provincia")),
             data_iso(r.get("data_pubblicazione")), data_iso(r.get("data_scadenza_offerta")),
             vuoto(r.get("tipo_scelta_contraente")), vuoto(r.get("modalita_realizzazione")),
             vuoto(r.get("cf_amministrazione_appaltante")), vuoto(r.get("denominazione_amministrazione_appaltante")),
             vuoto(r.get("denominazione_centro_costo")), vuoto(r.get("cod_cpv")), vuoto(r.get("descrizione_cpv")),
             vuoto(r.get("cui_programma")), vuoto(r.get("esito")), data_iso(r.get("data_comunicazione_esito")),
             vuoto(r.get("flag_pnrr_pnc")), data_iso(r.get("data_cancellazione")), fonte, oggi, oggi)
        db.execute("""INSERT INTO anac_cig VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(cig) DO UPDATE SET
              cig_accordo_quadro=excluded.cig_accordo_quadro, numero_gara=excluded.numero_gara,
              cup=COALESCE(excluded.cup, anac_cig.cup), oggetto_gara=excluded.oggetto_gara,
              oggetto_lotto=excluded.oggetto_lotto, importo_gara=excluded.importo_gara,
              importo_lotto=excluded.importo_lotto, importo_sicurezza=excluded.importo_sicurezza,
              oggetto_principale=excluded.oggetto_principale, stato=excluded.stato, settore=excluded.settore,
              luogo_istat=excluded.luogo_istat, provincia=excluded.provincia,
              data_pubblicazione=excluded.data_pubblicazione, data_scadenza_offerta=excluded.data_scadenza_offerta,
              tipo_scelta_contraente=excluded.tipo_scelta_contraente,
              modalita_realizzazione=excluded.modalita_realizzazione, cf_sa=excluded.cf_sa,
              denominazione_sa=excluded.denominazione_sa, centro_costo=excluded.centro_costo,
              cod_cpv=excluded.cod_cpv, descrizione_cpv=excluded.descrizione_cpv,
              cui_programma=excluded.cui_programma, esito=excluded.esito, data_esito=excluded.data_esito,
              flag_pnrr=excluded.flag_pnrr, data_cancellazione=excluded.data_cancellazione,
              fonte=excluded.fonte, aggiornato_il=excluded.aggiornato_il""", v)
    return lette, tenute


def cig_noti(db):
    return {r[0] for r in db.execute("SELECT cig FROM anac_cig")}


def carica_aggiudicazioni(db, percorso, fonte, oggi, noti):
    lette = tenute = 0
    for r in righe_csv(percorso):
        lette += 1
        cig = (r.get("cig") or "").strip()
        if cig not in noti or not vuoto(r.get("id_aggiudicazione")):
            continue
        tenute += 1
        v = (r["id_aggiudicazione"].strip(), cig, data_iso(r.get("data_aggiudicazione_definitiva")), vuoto(r.get("esito")),
             vuoto(r.get("criterio_aggiudicazione")), data_iso(r.get("data_comunicazione_esito")),
             num(r.get("importo_aggiudicazione")), num(r.get("ribasso_aggiudicazione")),
             intero(r.get("numero_offerte_ammesse")), intero(r.get("numero_offerte_escluse")),
             intero(r.get("num_imprese_offerenti")), intero(r.get("num_imprese_invitate")),
             intero(r.get("num_imprese_richiedenti")), vuoto(r.get("flag_subappalto")),
             num(r.get("massimo_ribasso")), num(r.get("minimo_ribasso")), vuoto(r.get("prestazioni_comprese")),
             fonte, oggi)
        db.execute("""INSERT INTO anac_aggiudicazioni VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id_aggiudicazione) DO UPDATE SET
              cig=excluded.cig, data_aggiudicazione=excluded.data_aggiudicazione, esito=excluded.esito,
              criterio=excluded.criterio, data_comunicazione_esito=excluded.data_comunicazione_esito,
              importo=excluded.importo, ribasso=excluded.ribasso, offerte_ammesse=excluded.offerte_ammesse,
              offerte_escluse=excluded.offerte_escluse, imprese_offerenti=excluded.imprese_offerenti,
              imprese_invitate=excluded.imprese_invitate, imprese_richiedenti=excluded.imprese_richiedenti,
              flag_subappalto=excluded.flag_subappalto, massimo_ribasso=excluded.massimo_ribasso,
              minimo_ribasso=excluded.minimo_ribasso, prestazioni_comprese=excluded.prestazioni_comprese,
              fonte=excluded.fonte""", v)
    return lette, tenute


def carica_aggiudicatari(db, percorso, fonte, oggi, noti):
    lette = tenute = 0
    for r in righe_csv(percorso):
        lette += 1
        cig = (r.get("cig") or "").strip()
        if cig not in noti or not vuoto(r.get("id_aggiudicazione")):
            continue
        tenute += 1
        cf, tipo = (r.get("codice_fiscale") or "").strip().upper(), vuoto(r.get("tipo_soggetto"))
        pf = persona_fisica(cf, tipo)
        if pf:  # nessun dato personale: niente nome, niente codice fiscale
            chiave, cf, nome = "persona_fisica", None, None
        else:
            cf = cf.zfill(11) if cf.isdigit() and len(cf) < 11 else cf
            chiave, nome = cf or "senza_cf", vuoto(r.get("denominazione"))
        db.execute("""INSERT INTO anac_aggiudicatari VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id_aggiudicazione, chiave, ruolo) DO UPDATE SET
              denominazione=excluded.denominazione, tipo_soggetto=excluded.tipo_soggetto, fonte=excluded.fonte""",
                   (r["id_aggiudicazione"].strip(), cig, vuoto(r.get("ruolo")) or "", chiave, cf, nome, tipo,
                    int(pf), fonte, oggi))
    return lette, tenute


def carica_soa(db, attestati, categorie, fonte, oggi):
    lette = tenute = 0
    tenuti = set()
    for r in righe_csv(attestati):
        lette += 1
        cf = (r.get("ata_impresa_codicefiscale") or "").strip()
        if not CF_IMPRESA.match(cf):
            continue  # attestazione di una persona fisica: non la teniamo
        tenute += 1
        tenuti.add(r["_idattestazione"])
        db.execute("INSERT OR REPLACE INTO anac_soa VALUES (?,?,?,?,?,?,?,?,?,COALESCE((SELECT prima_vista_anac FROM anac_soa WHERE id_attestazione=?),?))",
                   (r["_idattestazione"], cf, vuoto(r.get("ata_impresa_denominazione")), vuoto(r.get("ata_provincia_codice")),
                    vuoto(r.get("ata_attestato_stato")), data_iso(r.get("ata_attestato_datarilascioattestazioneincorso")),
                    data_iso(r.get("ata_attestato_datascadenzavaliditatriennale")),
                    data_iso(r.get("ata_attestato_datascadenzavaliditaquinquennale")), fonte, r["_idattestazione"], oggi))
    for r in righe_csv(categorie):
        if r.get("_idattestazione") in tenuti:
            db.execute("INSERT OR REPLACE INTO anac_soa_categorie VALUES (?,?,?)",
                       (r["_idattestazione"], (r.get("atcr_categoria") or "").strip(), vuoto(r.get("atcr_classifica"))))
    return lette, tenute


# ---------------------------------------------------------------- giro

def piano(anni):
    """Le risorse da elaborare, nell'ordine giusto: prima tutti i CIG, poi aggiudicazioni e aggiudicatari."""
    passi = []
    for a in anni:
        passi += [("cig", f"cig-{a}", r) for r in risorse(f"cig-{a}", rf"cig_csv_{a}_\d{{2}}")]
    passi += [("cig", "cig", r) for r in risorse("cig", r"\d{8}-cig_csv")]
    for tipo in ("aggiudicazioni", "aggiudicatari"):
        passi += [(tipo, tipo, r) for r in risorse(tipo, rf"(\d{{8}}-)?{tipo}_csv")]
    return passi


def gia_fatto(db, r):
    riga = db.execute("SELECT dimensione, modificato FROM anac_file WHERE risorsa=?", (r["name"],)).fetchone()
    return riga is not None and riga[0] == str(r.get("size")) and riga[1] == str(r.get("last_modified"))


def aggiorna(db_path="dati/anac.db", anni=(2023, 2024, 2025), soa=True):
    oggi = dt.date.today().isoformat()
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)
    _, cf_comuni = carica_comuni()
    passi = piano(anni)
    print(f"{len(passi)} file ANAC nel piano", flush=True)
    # Un CIG pubblicato in ritardo puo' avere l'aggiudicazione in un file mensile gia' elaborato:
    # quando arrivano CIG nuovi rileggiamo anche gli ultimi due mensili di aggiudicazioni e aggiudicatari.
    recenti = set()
    for tipo in ("aggiudicazioni", "aggiudicatari"):
        recenti |= set(sorted(r["name"] for t, _, r in passi if t == tipo and r["name"][:1].isdigit())[-2:])
    nuovi_cig = False
    with tempfile.TemporaryDirectory() as tmp:
        for tipo, pacchetto, r in passi:
            if gia_fatto(db, r) and not (nuovi_cig and r["name"] in recenti):
                continue
            t0 = time.time()
            dest = scarica(r["url"], os.path.join(tmp, os.path.basename(r["url"])))
            mb = os.path.getsize(dest) / 1e6
            if tipo == "cig":
                prima = db.total_changes
                lette, tenute = carica_cig(db, dest, r["name"], oggi, cf_comuni)
                nuovi_cig = nuovi_cig or db.total_changes > prima
            else:
                noti = cig_noti(db)
                f = carica_aggiudicazioni if tipo == "aggiudicazioni" else carica_aggiudicatari
                lette, tenute = f(db, dest, r["name"], oggi, noti)
            os.remove(dest)
            db.execute("INSERT OR REPLACE INTO anac_file VALUES (?,?,?,?,?,?,?,?)",
                       (r["name"], pacchetto, r["url"], str(r.get("size")), str(r.get("last_modified")), lette, tenute, oggi))
            db.commit()
            print(f"{r['name']:<36} {mb:>7.0f} MB {lette:>9} righe, {tenute:>6} tenute  ({time.time() - t0:.0f}s)", flush=True)
        if soa:
            att = scarica(f"{BASE}/download/dataset/attestazioni-soa-v2/filesystem/attestato_CKAN.csv", os.path.join(tmp, "att.csv"))
            cat = scarica(f"{BASE}/download/dataset/attestazioni-soa-v2/filesystem/categorie_rilasciate_CKAN.csv", os.path.join(tmp, "cat.csv"))
            lette, tenute = carica_soa(db, att, cat, "attestazioni-soa-v2", oggi)
            db.commit()
            print(f"SOA: {lette} attestazioni lette, {tenute} di imprese", flush=True)
    for t in ("anac_cig", "anac_aggiudicazioni", "anac_aggiudicatari", "anac_soa"):
        print(t, db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    db.execute("VACUUM")
    db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "aggiorna":
        print(__doc__)
        sys.exit(1)
    args = dict(zip(sys.argv[2::2], sys.argv[3::2]))
    anni = tuple(int(a) for a in args.get("--anni", "2023,2024,2025").split(","))
    aggiorna(args.get("--db", "dati/anac.db"), anni, soa=args.get("--soa", "si") == "si")
