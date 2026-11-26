"""
Misura di qualita' del classificatore su campioni etichettati a mano.

Disegno: campione stratificato.
  strato "pos": TUTTI gli atti che il classificatore segnala (censimento: la precisione non ha errore di campionamento)
  strato "neg": un campione casuale degli atti che scarta (serve a stimare quanti segnali veri perdiamo)
Il richiamo e' stimato riportando i falsi negativi del campione allo strato intero (peso N_neg / n_neg);
gli intervalli al 95% vengono da un bootstrap stratificato (2000 repliche, seed fisso).

Uso: python3 valutazione/valuta.py  ->  stampa le metriche e scrive valutazione/metriche.json
"""
import json, os, random, sys
QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(QUI, ".."))
from classifica import classifica  # noqa: E402


def metriche(righe, n_neg_tot, tipo=None):
    """righe: (strato, vero, previsto). tipo=None -> rilevanza (segnale si'/no), altrimenti quel tipo."""
    n_neg = sum(1 for s, _, _ in righe if s == "neg")
    peso = {"pos": 1.0, "neg": n_neg_tot / n_neg if n_neg else 0}
    tp = fp = fn = 0.0
    for s, v, p in righe:
        vv = (v is not None) if tipo is None else (v == tipo)
        pp = (p is not None) if tipo is None else (p == tipo)
        w = peso[s]
        tp += w * (vv and pp)
        fp += w * (pp and not vv)
        fn += w * (vv and not pp)
    prec = tp / (tp + fp) if tp + fp else None
    rich = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rich / (prec + rich) if prec and rich else None
    return {"precisione": prec, "richiamo": rich, "f1": f1, "veri_positivi_stimati": tp,
            "falsi_positivi_stimati": fp, "falsi_negativi_stimati": fn}


def bootstrap(righe, n_neg_tot, tipo, rep=2000, seed=7):
    rnd = random.Random(seed)
    strati = {s: [r for r in righe if r[0] == s] for s in ("pos", "neg")}
    vals = {"precisione": [], "richiamo": [], "f1": []}
    for _ in range(rep):
        b = [rnd.choice(strati[s]) for s in strati for _ in strati[s]]
        m = metriche(b, n_neg_tot, tipo)
        for k in vals:
            if m[k] is not None:
                vals[k].append(m[k])
    ic = {}
    for k, v in vals.items():
        v.sort()
        ic[k] = [round(v[int(0.025 * len(v))], 3), round(v[int(0.975 * len(v)) - 1], 3)] if v else None
    return ic


def valuta(percorso_etichette, n_neg_tot):
    with open(percorso_etichette, encoding="utf-8") as f:
        dati = json.load(f)
    righe, errori = [], []
    for a in dati["atti"]:
        r = classifica({"oggetto": a["oggetto"], "categoria": a.get("categoria") or "", "sottocategoria": a.get("sottocategoria") or ""})
        p = r["tipo"] if r else None
        righe.append((a["strato"], a["etichetta_tipo"], p))
        if p != a["etichetta_tipo"]:
            errori.append({"vero": a["etichetta_tipo"], "previsto": p, "oggetto": a["oggetto"][:160]})
    out = {"n_campione": len(righe), "n_strato_neg_totale": n_neg_tot}
    for t in (None, "opera_pubblica", "urbanistica", "cantiere_privato"):
        nome = t or "segnale_si_no"
        m = metriche(righe, n_neg_tot, t)
        m["ic95"] = bootstrap(righe, n_neg_tot, t)
        m["veri_nel_campione"] = sum(1 for _, v, _ in righe if (v is not None if t is None else v == t))
        out[nome] = m
    # tra i segnali veri e segnalati: il tipo e' giusto?
    both = [(v, p) for _, v, p in righe if v and p]
    out["tipo_corretto_fra_veri_segnalati"] = sum(v == p for v, p in both) / len(both) if both else None
    out["errori"] = errori
    return out


if __name__ == "__main__":
    gold = json.load(open(os.path.join(QUI, "..", "test", "fixtures", "classifica_golden.json"), encoding="utf-8"))
    n_neg = sum(1 for g in gold if not classifica(g))
    res = valuta(os.path.join(QUI, "etichette_golden.json"), n_neg)
    res["nota"] = ("Campione di sviluppo: le regole sono state scritte guardando questi stessi atti, quindi le metriche "
                   "sono ottimistiche. La misura fuori campione e' in metriche_fuori_campione (atti di comuni e giorni nuovi).")
    with open(os.path.join(QUI, "metriche.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for k in ("segnale_si_no", "opera_pubblica", "urbanistica", "cantiere_privato"):
        m = res[k]
        f = lambda x: "-" if x is None else f"{x:.2f}"
        print(f"{k:<18} precisione {f(m['precisione'])} {m['ic95']['precisione']}  richiamo {f(m['richiamo'])} {m['ic95']['richiamo']}  (veri nel campione: {m['veri_nel_campione']})")
    print("tipo corretto fra i veri segnalati:", round(res["tipo_corretto_fra_veri_segnalati"], 3))
    print(len(res["errori"]), "errori nel campione")
    for e in res["errori"]:
        print(" ", e["vero"], "->", e["previsto"], "|", e["oggetto"][:120])
