"""
Anagrafica imprese: una riga per impresa, anche quando gli atti la scrivono in modi diversi.

Fonti delle menzioni
  albo   nome estratto dall'oggetto dell'atto (solo societa' con forma societaria, mai ditte individuali)
         + partita IVA quando l'atto la riporta (verificata col carattere di controllo)
  anac   imprese aggiudicatarie con codice fiscale / partita IVA (fonte ufficiale)

Metodo (entity resolution)
  1. normalizzazione del nome: maiuscole, niente accenti e punteggiatura, abbreviazioni sciolte (F.LLI -> FRATELLI),
     forma societaria riconosciuta e separata (SRL, SRLS, SPA, SNC, SAS, SAPA, COOP, CONSORZIO)
  2. ancore: ogni partita IVA valida e' un'impresa ("IT" + partita IVA). Due partite IVA diverse non si fondono mai.
  3. le menzioni senza partita IVA si abbinano all'impresa piu' simile se il punteggio supera la soglia; il punteggio
     combina token pesati per rarita' (IDF) e trigrammi di caratteri, con penalita' se la forma societaria e' diversa
  4. le menzioni che restano si raggruppano fra loro (union-find) e formano imprese senza partita IVA ("N:" + hash)
  5. confidenza: il punteggio viene tradotto in probabilita' di abbinamento corretto con una calibrazione monotona
     (pool adjacent violators) stimata su coppie etichettate: a mano per l'albo, e quando ci sono i dati ANAC su coppie
     vere (stessa partita IVA, nomi scritti diversamente) e false (partite IVA diverse con nomi simili).
"""
import hashlib
import math
import re
import unicodedata
from collections import Counter, defaultdict

FORME = [
    ("SRLS", r"S\s?R\s?L\s?S|SOCIETA A RESPONSABILITA LIMITATA SEMPLIFICATA"),
    ("SRL", r"S\s?R\s?L|SOCIETA A RESPONSABILITA LIMITATA"),
    ("SAPA", r"S\s?A\s?P\s?A|SOCIETA IN ACCOMANDITA PER AZIONI"),
    ("SPA", r"S\s?P\s?A|SOCIETA PER AZIONI"),
    ("SNC", r"S\s?N\s?C|SOCIETA IN NOME COLLETTIVO"),
    ("SAS", r"S\s?A\s?S|SOCIETA IN ACCOMANDITA SEMPLICE"),
    ("COOP", r"SOC(IETA)?\s?COOP(ERATIVA)?(\s?(SOCIALE|ONLUS|A\s?R\s?L|ARL|SCARL|S\s?C\s?A\s?R\s?L|SCRL))*|COOPERATIVA(\s?SOCIALE)?|SCARL|S\s?C\s?A\s?R\s?L|SCRL|SCPA|S\s?C\s?P\s?A"),
    ("CONSORZIO", r"CONSORZIO(\s?STABILE)?"),
]
FORME_RE = [(f, re.compile(rf"(?:^|\s)(?:{rx})(?:\s|$)")) for f, rx in FORME]
ABBREVIAZIONI = {"F LLI": "FRATELLI", "FLLI": "FRATELLI", "COSTR": "COSTRUZIONI", "IMP": "IMPIANTI", "ING": "INGEGNERIA",
                 "SOC": "", "ITAL": "ITALIA", "INTERN": "INTERNATIONAL", "C": "", "E": "", "ED": "", "DI": "", "DEL": "",
                 "DELLA": "", "DEI": "", "IN": "", "SIGLA": "", "LIQUIDAZIONE": "", "UNIPERSONALE": "", "ONLUS": ""}


def _ascii(s):
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def normalizza(nome):
    """-> (tokens, forma). Le parole senza contenuto (DI, E, SOC...) e la forma societaria non stanno nei tokens."""
    s = _ascii(nome or "").upper().replace("&", " E ").replace("'", " ")
    s = re.sub(r"\bF\.\s?LLI\b", "FRATELLI", s)
    s = re.sub(r"(?<=[A-Z0-9])\.(?=[A-Z0-9])", "", s)  # CO.GE.T -> COGET, S.R.L. -> SRL.
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    forma = None
    for f, rx in FORME_RE:
        m = rx.search(s)
        while m:  # tutte le occorrenze ("COOPERATIVA SOCIALE X SOC. COOP")
            forma = forma or f
            s = (s[:m.start()] + " " + s[m.end():]).strip()
            m = rx.search(s)
    s = re.sub(r"\bF LLI\b", "FRATELLI", s)
    toks = []
    for t in s.split():
        t = ABBREVIAZIONI.get(t, t)
        if t:
            toks.append(t)
    return tuple(toks), forma


def piva_valida(s):
    """Partita IVA italiana: 11 cifre con carattere di controllo (algoritmo di Luhn modificato)."""
    s = (s or "").strip()
    if not re.fullmatch(r"\d{11}", s) or s == "0" * 11:
        return False
    tot = 0
    for i, ch in enumerate(s[:10]):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            n = n - 9 if n > 9 else n
        tot += n
    return (10 - tot % 10) % 10 == int(s[10])


PIVA_NEL_TESTO = re.compile(r"(?:P\.?\s?I(?:VA|\.)?|PARTITA\s+IVA|C\.?\s?F\.?|CODICE\s+FISCALE)\s*[:.\-n°]*\s*(\d{11})\b", re.I)


def piva_dal_testo(testo, escludi=()):
    """Partite IVA valide citate nel testo, tolte quelle da escludere (per esempio i codici fiscali dei comuni)."""
    return [p for p in PIVA_NEL_TESTO.findall(testo or "") if piva_valida(p) and p not in escludi]


def trigrammi(s):
    s = f"  {s} "
    return {s[i:i + 3] for i in range(len(s) - 2)}


class Indice:
    """Pesi IDF dei token su tutto il corpus di nomi: 'COSTRUZIONI' pesa poco, 'CASALUCCI' molto."""

    def __init__(self, nomi_normalizzati):
        self.df = Counter(t for toks, _ in nomi_normalizzati for t in set(toks))
        self.n = max(1, len(nomi_normalizzati))

    def idf(self, t):
        return math.log((self.n + 1) / (self.df.get(t, 0) + 1)) + 1


def punteggio(a, b, indice):
    """Somiglianza fra due nomi normalizzati, 0..1."""
    (ta, fa), (tb, fb) = a, b
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    inter = sum(indice.idf(t) for t in sa & sb)
    unione = sum(indice.idf(t) for t in sa | sb)
    tok = inter / unione if unione else 0.0
    ga, gb = trigrammi("".join(ta)), trigrammi("".join(tb))
    tri = len(ga & gb) / len(ga | gb) if ga | gb else 0.0
    s = 0.6 * tok + 0.4 * tri
    if fa and fb and fa != fb:
        s *= 0.75 if {fa, fb} <= {"SRL", "SRLS"} else 0.6
    return round(s, 4)


# ---------------------------------------------------------------- calibrazione

def calibra(coppie, larghezza=0.05):
    """coppie: [(punteggio, vero_bool)]. -> lista di (soglia_inferiore, probabilita') monotona non decrescente,
    stimata per classi di punteggio e resa monotona con pool adjacent violators."""
    classi = defaultdict(lambda: [0, 0])
    for p, v in coppie:
        k = min(int(p / larghezza), int(1 / larghezza) - 1)
        classi[k][0] += int(v)
        classi[k][1] += 1
    blocchi = [[k, ok, n] for k, (ok, n) in sorted(classi.items())]
    i = 0
    while i < len(blocchi) - 1:  # PAV
        if blocchi[i][1] / blocchi[i][2] > blocchi[i + 1][1] / blocchi[i + 1][2]:
            blocchi[i][1] += blocchi[i + 1][1]
            blocchi[i][2] += blocchi[i + 1][2]
            del blocchi[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    return [(round(k * larghezza, 4), round(ok / n, 4)) for k, ok, n in blocchi]


def confidenza(p, tabella):
    out = 0.0
    for soglia, prob in tabella:
        if p >= soglia:
            out = prob
    return out


# ---------------------------------------------------------------- risoluzione

def _id_senza_piva(norm):
    toks, forma = norm
    return "N:" + hashlib.sha1((" ".join(sorted(toks)) + "|" + (forma or "")).encode()).hexdigest()[:12]


class _UF:
    def __init__(self):
        self.p = {}

    def trova(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def unisci(self, a, b):
        self.p[self.trova(a)] = self.trova(b)


def risolvi(menzioni, soglia=0.72, tabella=None):
    """
    menzioni: [{"chiave", "nome", "piva" (o None), ...}]
    -> (imprese: {id: {"id","piva","nome","forma","alias":Counter,"menzioni":n}},
        legami: [{"chiave","id_impresa","metodo","punteggio","confidenza"}])
    """
    tabella = tabella or [(0.0, 0.0), (soglia, 0.9), (0.9, 0.98), (0.99, 0.995)]
    norm = {i: normalizza(m["nome"]) for i, m in enumerate(menzioni)}
    indice = Indice(list(norm.values()))
    imprese, legami = {}, []

    def scheda(id_, piva=None):
        return imprese.setdefault(id_, {"id": id_, "piva": piva, "alias": Counter(), "forme": Counter(), "menzioni": 0})

    # 1. ancore: partita IVA
    rappresentanti = defaultdict(list)  # id -> nomi normalizzati gia' visti
    for i, m in enumerate(menzioni):
        if m.get("piva") and piva_valida(m["piva"]):
            id_ = "IT" + m["piva"]
            s = scheda(id_, m["piva"])
            s["alias"][m["nome"]] += 1
            s["forme"][norm[i][1]] += 1
            s["menzioni"] += 1
            rappresentanti[id_].append(norm[i])
            legami.append({"chiave": m["chiave"], "id_impresa": id_, "metodo": "partita_iva", "punteggio": 1.0, "confidenza": 1.0})

    # blocco: un token raro in comune (o tutti i token se il nome e' corto)
    blocchi = defaultdict(set)
    for id_, ns in rappresentanti.items():
        for toks, _ in ns:
            for t in toks:
                blocchi[t].add(id_)

    # 2. menzioni senza partita IVA -> impresa con partita IVA piu' simile
    restanti = []
    for i, m in enumerate(menzioni):
        if m.get("piva") and piva_valida(m["piva"]):
            continue
        cand = set()
        for t in norm[i][0]:
            cand |= blocchi.get(t, set())
        best, best_id = 0.0, None
        for id_ in cand:
            p = max(punteggio(norm[i], r, indice) for r in rappresentanti[id_])
            if p > best:
                best, best_id = p, id_
        if best_id and best >= soglia:
            s = scheda(best_id)
            s["alias"][m["nome"]] += 1
            s["forme"][norm[i][1]] += 1
            s["menzioni"] += 1
            legami.append({"chiave": m["chiave"], "id_impresa": best_id, "metodo": "nome->partita_iva",
                           "punteggio": best, "confidenza": confidenza(best, tabella)})
        else:
            restanti.append(i)

    # 3. le restanti si raggruppano fra loro
    uf = _UF()
    per_token = defaultdict(list)
    for i in restanti:
        uf.trova(i)
        for t in norm[i][0]:
            per_token[t].append(i)
    punti = {}
    for t, ii in per_token.items():
        if len(ii) > 50:  # token troppo comune per fare da blocco
            continue
        for x in range(len(ii)):
            for y in range(x + 1, len(ii)):
                a, b = ii[x], ii[y]
                p = punteggio(norm[a], norm[b], indice)
                if p >= soglia:
                    uf.unisci(a, b)
                    punti[(a, b)] = p
    gruppi = defaultdict(list)
    for i in restanti:
        gruppi[uf.trova(i)].append(i)
    for radice, ii in gruppi.items():
        # nome canonico del gruppo: il piu' frequente, poi il piu' lungo
        piu = Counter(menzioni[i]["nome"] for i in ii).most_common()
        canon = sorted(piu, key=lambda x: (-x[1], -len(x[0])))[0][0]
        id_ = _id_senza_piva(normalizza(canon))
        s = scheda(id_)
        for i in ii:
            s["alias"][menzioni[i]["nome"]] += 1
            s["forme"][norm[i][1]] += 1
            s["menzioni"] += 1
            p = 1.0 if len(ii) == 1 else max([v for (a, b), v in punti.items() if i in (a, b)] or [soglia])
            legami.append({"chiave": menzioni[i]["chiave"], "id_impresa": id_, "metodo": "solo_nome",
                           "punteggio": p, "confidenza": 1.0 if len(ii) == 1 else confidenza(p, tabella)})

    for s in imprese.values():
        s["nome"] = sorted(s["alias"].items(), key=lambda x: (-x[1], -len(x[0])))[0][0]
        s["forma"] = s["forme"].most_common(1)[0][0] if s["forme"] else None
    return imprese, legami


def coppie_candidate(nomi, minimo=0.35):
    """Coppie di nomi distinti con punteggio >= minimo: servono per l'etichettatura a mano e la calibrazione."""
    uniq = sorted(set(nomi))
    norm = {n: normalizza(n) for n in uniq}
    indice = Indice(list(norm.values()))
    out = []
    for i, a in enumerate(uniq):
        for b in uniq[i + 1:]:
            if set(norm[a][0]) & set(norm[b][0]) or len(trigrammi("".join(norm[a][0])) & trigrammi("".join(norm[b][0]))) > 3:
                p = punteggio(norm[a], norm[b], indice)
                if p >= minimo:
                    out.append((p, a, b))
    return sorted(out, reverse=True)
