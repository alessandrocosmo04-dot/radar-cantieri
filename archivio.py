"""
Archivio storico del radar (SQLite, un solo file: radar.db).

Gli albi tengono un atto solo 15 giorni: leggendoli ogni giorno costruiamo uno storico che nessun altro ha.
Per rispetto della privacy salviamo SOLO gli atti utili gia' classificati (oggetto con nomi oscurati);
degli altri atti teniamo solo il conteggio nel registro delle letture.

Tabelle
  segnali   un atto utile per riga; chiave (istat, piattaforma, id); prima_vista / ultima_vista
  letture   una riga per comune per giro: quanti atti letti, quanti utili, eventuale errore
Vista
  progetti  segnali raggruppati per CUP (o CIG): la storia di un'opera dal progetto al collaudo
"""
import csv
import datetime as dt
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS segnali (
    istat TEXT NOT NULL, piattaforma TEXT NOT NULL, id TEXT NOT NULL,
    comune TEXT, registro TEXT, categoria TEXT, sottocategoria TEXT,
    inizio_pubbl TEXT, fine_pubbl TEXT, url TEXT,
    tipo TEXT, fase TEXT, importo_eur REAL, cig TEXT, cup TEXT, impresa TEXT, indirizzo TEXT,
    parola_chiave TEXT, oggetto TEXT,
    prima_vista TEXT NOT NULL, ultima_vista TEXT NOT NULL,
    PRIMARY KEY (istat, piattaforma, id)
);
CREATE INDEX IF NOT EXISTS segnali_cup ON segnali(cup);
CREATE INDEX IF NOT EXISTS segnali_cig ON segnali(cig);
CREATE INDEX IF NOT EXISTS segnali_prima ON segnali(prima_vista);
CREATE TABLE IF NOT EXISTS letture (
    giorno TEXT NOT NULL, istat TEXT NOT NULL, comune TEXT, piattaforma TEXT,
    atti_letti INTEGER, utili INTEGER, nuovi INTEGER, errore TEXT,
    PRIMARY KEY (giorno, istat)
);
CREATE VIEW IF NOT EXISTS progetti AS
SELECT COALESCE(cup, cig) AS codice,
       MIN(comune) AS comune,
       COUNT(*) AS atti,
       MIN(inizio_pubbl) AS primo_atto,
       MAX(inizio_pubbl) AS ultimo_atto,
       GROUP_CONCAT(DISTINCT fase) AS fasi,
       MAX(importo_eur) AS importo_max,
       GROUP_CONCAT(DISTINCT impresa) AS imprese
FROM segnali WHERE COALESCE(cup, cig) IS NOT NULL
GROUP BY COALESCE(cup, cig);
"""

CAMPI = ["istat", "piattaforma", "id", "comune", "registro", "categoria", "sottocategoria", "inizio_pubbl", "fine_pubbl",
         "url", "tipo", "fase", "importo_eur", "cig", "cup", "impresa", "indirizzo", "parola_chiave", "oggetto"]


def apri(percorso):
    db = sqlite3.connect(percorso)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def _testo(v):
    if v is None:
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()[:10]
    return str(v) if not isinstance(v, (int, float)) else v


def salva_segnali(db, segnali, oggi=None):
    """Inserisce i nuovi, aggiorna ultima_vista (e i campi) dei gia' visti. Ritorna il numero di nuovi."""
    oggi = oggi or dt.date.today().isoformat()
    nuovi = 0
    for s in segnali:
        riga = {k: _testo(s.get(k)) for k in CAMPI}
        riga["id"] = str(riga["id"])
        c = db.execute("SELECT 1 FROM segnali WHERE istat=? AND piattaforma=? AND id=?",
                       (riga["istat"], riga["piattaforma"], riga["id"])).fetchone()
        if c:
            sets = ", ".join(f"{k}=:{k}" for k in CAMPI[3:])
            db.execute(f"UPDATE segnali SET {sets}, ultima_vista=:oggi WHERE istat=:istat AND piattaforma=:piattaforma AND id=:id",
                       {**riga, "oggi": oggi})
        else:
            db.execute(f"INSERT INTO segnali ({', '.join(CAMPI)}, prima_vista, ultima_vista) "
                       f"VALUES ({', '.join(':' + k for k in CAMPI)}, :oggi, :oggi)", {**riga, "oggi": oggi})
            nuovi += 1
    db.commit()
    return nuovi


def registra_lettura(db, giorno, istat, comune, piattaforma, letti, utili, nuovi, errore=""):
    db.execute("INSERT OR REPLACE INTO letture VALUES (?,?,?,?,?,?,?,?)",
               (giorno, istat, comune, piattaforma, letti, utili, nuovi, errore or None))
    db.commit()


ESPORTA = ["prima_vista", "comune", "inizio_pubbl", "tipo", "fase", "importo_eur", "cig", "cup", "impresa", "indirizzo",
           "oggetto", "sottocategoria", "url"]


def esporta(db, percorso, dal=None):
    """CSV dei segnali (tutti, o solo quelli visti per la prima volta da `dal` in poi)."""
    q = f"SELECT {', '.join(ESPORTA)} FROM segnali"
    par = ()
    if dal:
        q += " WHERE prima_vista >= ?"
        par = (dal,)
    q += " ORDER BY prima_vista DESC, inizio_pubbl DESC, comune"
    righe = db.execute(q, par).fetchall()
    os.makedirs(os.path.dirname(os.path.abspath(percorso)), exist_ok=True)
    with open(percorso, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(ESPORTA)
        w.writerows([tuple(r) for r in righe])
    return len(righe)
