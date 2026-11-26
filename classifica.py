"""
Classifica gli atti dell'albo: tiene solo quelli utili a chi lavora nell'edilizia
e toglie quelli con dati di persone fisiche.
Regole a parole chiave, trasparenti e correggibili. In seguito si possono affiancare a un modello AI.
"""
import re

# segnali forti di lavori edili / impiantistici
LAVORI = (r"\b(lavori|opere (pubbliche|edili|di \w+|stradali|idrauliche|a verde)|opera pubblica|manutenzione straordinaria|"
          r"riqualificazion\w*|ristrutturazion\w*|nuova costruzione|costruzione (di|del|della|dei|delle) |realizzazione (di |del |della |dei |delle |dell')?(un[ao]? )?(nuov\w*|opere|impiant\w*|edific\w*|parchegg\w*|marciapied\w*|pist\w*|rotatori\w*|loculi|camp[oi]|aree?|piazza|scuola|palestra|ponte|strada|tratto|fognatur\w*|rete|recinzion\w*|copertur\w*|cabina)|ampliament\w*|"
          r"rifaciment\w*|asfaltatur\w*|efficientamento energetico|fotovoltaic\w*|impianti? (elettric\w*|termic\w*|di riscaldamento|di climatizzazione|sportiv\w*|antincendio)|"
          r"bonifica|demolizion\w*|adeguamento (sismico|normativo|antincendio|impiantistico)|messa in sicurezza|consolidamento|"
          r"marciapied\w*|pista ciclabile|ciclopedonal\w*|illuminazione pubblica|fognatur\w*|acquedott\w*|coperture?|serrament\w*|"
          r"cavalcavia|ponte (stradale|ciclopedonale|pedonale|sul|sulla|di via)|sottopasso|rotatori\w*|palazzett\w*|cabina (elettrica|di trasformazione|secondaria)|e-distribuzione|"
          r"stato di avanzamento|s\.?a\.?l\.?|cantiere|edifici\w* scolastic\w*|centro sportivo)\b")
URBANISTICA = (r"\b(permess\w* di costruire|piano attuativo|piano di lottizzazione|programma integrato di intervento|"
               r"variante (urbanistica|al p\.?g\.?t\.?|al piano|parziale)|p\.?g\.?t\.?(?!\s*u)|piano di governo del territorio|convenzione urbanistica|"
               r"piano di recupero|ambito di trasformazione|rigenerazione urbana|titolo abilitativo|piano particolareggiato|"
               r"asta pubblica|alienazion\w* (di |del |dell'|dei )?(immobil\w*|area|aree|terren\w*|fabbricat\w*)|valorizzazion\w* immobiliar\w*|piano delle alienazioni)\b")
# esclusioni: si applicano solo se non c'e' segnale urbanistico e non si parla esplicitamente di lavori/opere
NON_EDILIZIA = (r"\b(pulizi\w*|portierato|rinfresco|inaugurazion\w*|posteggi|patrocinio|offerta formativa|resistere in giudizio|ricorso|spese condominiali|utilizzo (degli )?impianti|concessione d'uso|refezione|mensa|ristorazione scolastica|libri di testo|trasporto scolastico|trasporto (studenti|alunni|disabili)|studenti|alunni|"
                r"inclusione|counsel+ing|sportello|assistenza (educativa|domiciliare)|personale dipendente|concors\w*|assunzion\w*|"
                r"mobilit[aà]'? (esterna|volontaria)|lavoro straordinario|formazione|segnalibri|reading|teatr\w*|festa|presepi?|biblioteca|"
                r"rimbors\w*|canone|utenze|consum\w*|fattur\w*|diritti|vigili del fuoco|rifiuti|igiene (urbana|ambientale)|spurgh\w*|smaltimento|"
                r"digitalizzazione|posta (elettronica )?certificata|software|licenz\w* (d'uso|software)|polizz\w*|assicurazion\w*|"
                r"concession\w* cimiterial\w*|piano urbano della mobilit\w*|pums|segnaletica|divieto|divieti|circolazione e sosta|"
                r"polizia locale|veicol\w*|elezion\w*|tributi|imu|tari|costo di costruzione|contribut\w* (economic|ad personam)|"
                r"servizi sociali|anagrafe|mercatin\w*|manifestazion\w*|protocollo d'intesa|csbno|didattic\w*|carburant\w*|cancelleria|utilizzo da parte|concessione in uso|tariff\w*|sezione primavera|accreditamento|magazzino comunale|trasporto e smaltimento)\b")
PROFESSIONISTA = re.compile(r"\b(ING|DOTT|ARCH|GEOM|AVV|PERITO INDUSTRIALE|P\.I)\.?\s+(ING\.?\s+)?[A-Z][A-Za-z'À-Ù]+(\s+[A-Z][A-Za-z'À-Ù]+){1,2}")
# nome e cognome dopo parole che introducono un privato (richiedente, proprieta', ditta individuale...)
COGNOME_TITOLO = re.compile(r"\b[A-Z][A-Z'À-Ù]+\s+(ING|ARCH|GEOM|DOTT|AVV)\.\s*[A-Z][A-Z'À-Ù]+\b")
DI_PERSONA = re.compile(r"\b(RICHIEDENTE|PROPRIET[AÀ] DI|PRESENTAT[AO] DA|INTESTAT[AO] A|DITTA INDIVIDUALE|TITOLARE)\s*:?\s+[A-Z][A-Za-z'À-Ù]+\s+[A-Z][A-Za-z'À-Ù]+", re.I)
PERSONALI = (r"\b(a carico di|deposito (dell')?atto|notific\w*|intimazione|sig\.?r?a?\.?\s+[A-Z]|signor[ae]?\b|abusi edilizi|abuso edilizio|"
             r"ingiunzione|demolizione d'ufficio|decesso|eredi|nato a|nata a|codice fiscale [A-Z]{6}\d{2}|ritiro (del )?veicolo|matrimoni\w*|"
             r"graduatori\w*|art\.?\s?(60|140|143) del (d\.?p\.?r|c\.?p\.?c)|d\.?p\.?r\.? 600/73|contingibil\w*|propriet[aà] (di|del sig|della sig)|beneficiari|scia n\.? ?\d+|mozione|interrogazione|conguagl\w*|assegnazione del contributo)")
SEMPRE_FUORI = r"liquidazione (degli |di )?incentivi|avviso di selezione|selezione pubblica per|restituzione (di )?(parte )?(della )?somm|defibrillator|traslochi|trasloco|stalli di sosta|diritti di segreteria|sponsorizzazion|\bconvocazione\b|ponte radio|trasporto e smaltimento|magazzino comunale|\bpums\b|piano urbano della mobilit|piano generale del traffico|potatur\w*|sgombero neve|telecamer\w*|videosorveglianz\w*|impiant\w* (di )?allarme|antintrusione|dissuasor\w*|zebrature|\brouter\b|videoproiettor\w*|licenze fiscali|bilancio consolidato|perimetro di consolidamento|variazione (di )?esigibilit|verifica a campione dei requisiti|liquidazione dell.incentivazione|concorso pubblico|voltura catastale|apparato radio|pratiche tecnico.amministrative|ispezione e controllo degli impianti"
CATEGORIE_ESCLUSE = r"abusi|messi|matrimon|anagrafe|stato civile|notific|deposit|concors|personale|elezion|mozion"

FASI = [
    ("revoca", r"\brevoca\b|annullamento in autotutela"),
    ("collaudo", r"ultimazione (dei )?lavori|avviso ai creditori|ad opponendum|certificato di regolare esecuzione|collaudo|conto finale|rata (di saldo|finale)|stato finale"),
    ("esecuzione", r"modifica del contratto|integrazione dei lavori|stato di avanzamento|\bs\.?a\.?l\.?\b|certificato di pagamento|contratto attuativo|variante in corso|perizia di variante|modifica contrattuale|subappalto|consegna (dei )?lavori|sospensione (dei )?lavori|ripresa (dei )?lavori"),
    ("asta_immobile", r"asta pubblica|alienazion\w*"),
    ("affidamento", r"aggiudic\w*|affidament\w*|contestual\w* affidamento|alla ditta|all'impresa|all'operatore economico|incarico"),
    ("gara_in_partenza", r"(determina(zione)? a|decisione a|determinazione di) contrarre|indizione|avvio (della )?procedura|bando|procedura negoziata|procedura aperta|manifestazione di interesse|avviso esplorativo"),
    ("autorizzazione", r"autorizzazione (all'esecuzione|del progetto)|permess\w* di costruire|titolo abilitativo|autorizzazione paesaggistica|nulla osta"),
    ("programmazione", r"programma triennale|elenco annuale|piano triennale delle opere"),
    ("progetto", r"\bp\.?\s?e\.\s|\bp\.?e\.?$|atti progettuali|quadro economico|approvazione (del )?progett\w*|progetto (esecutivo|definitivo|di fattibilit\w*)|pfte|studio di fattibilit\w*|documento di indirizzo|adozione|approvazione definitiva"),
    ("finanziamento", r"finanziament\w*|contributo regionale|pnrr|accertamento (di )?entrata|bando regionale"),
]

IMPORTO = re.compile(r"(?:€|\beuro\b|\beur\.?)\s*[\.:]?\s*([\d\.]{1,15},\d{2}|[\d\.]{4,15})|([\d\.]{4,15},\d{2})\s*(?:€|euro)", re.I)
CIG = re.compile(r"\bCIG[:\s\.n°]*([A-Z0-9]{10})\b", re.I)
CUP = re.compile(r"\bCUP[:\s\.n°]*([A-Z]\d{2}[A-Z0-9]{12})\b", re.I)
SUFFISSO = re.compile(r"\b(S\.?R\.?L\.?S?|S\.?P\.?A\.?|S\.?N\.?C\.?|S\.?A\.?S\.?|SOC\.? COOP\.?|SOCIET[AÀ] COOPERATIVA)(?=[\s\.,;:\-–)\"”']|$)", re.I)
TAGLIO = re.compile(r".*(?:[\-–,:;(\"“”'’]|\bOPERATORE ECONOMICO\b|\bIMPRESA\b|\bDITTA\b|\bSOCIET[AÀ]\b|\bPROPOSTE DA\b|\bPROPRIET[AÀ] DI\b|"
                    r"\bALLA\b|\bAL\b|\bDA\b|\bA\b|\bCON\b|\bTRAMITE\b|\bDIRETTO\b|\bDIRETTA\b|\bFAVORE DI\b)\s*", re.I)


DITTA = re.compile(r"\b(?:ALLA DITTA|ALL['’]IMPRESA|DITTA|IMPRESA)\s+(.+?)(?=\s+(?:DEI|DEL|DELLA|DELLE|PER|DI CUI|RELATIV\w*|CON SEDE|P\.?\s?IVA)\b|\s*[-,–(;:]|\.?$)", re.I)


RUOLO_IN_TESTA = re.compile(r"^(?:(?:APPALTATORE|CAPOGRUPPO|MANDATARIA|MANDANTE|OPERATORE( ECONOMICO)?|INCARICO|AGGIUDICATARI[AO]|"
                            r"SOC\.?|SOCIET[AÀ]'?|DITTA|IMPRESA|\[PRIVATO\])\s+)+", re.I)
NON_IMPRESA = re.compile(r"\b(CIG|CUP|PIATTAFORMA|SINTEL|CASSA DEPOSITI|MUTUO|COME DA)\b|\bVIA\b.*\bSNC$|^LAVORI\b", re.I)


def _pulisci_nome(nome):
    """Toglie ruoli e frammenti di frase dal nome estratto; None se non e' il nome di un'impresa."""
    nome = re.split(r"(?<=[A-Za-zÀ-ú]{4})\.\s+", nome)[-1]  # "TERRITORIO COMUNALE. COOPERATIVA X" -> "COOPERATIVA X"
    nome = re.split(r"\s+ED?\s+(?=[A-Z0-9])", nome)[-1] if " ED " in nome else nome
    nome = RUOLO_IN_TESTA.sub("", nome).strip(" .,;:()")
    if NON_IMPRESA.search(nome) or len(nome) < 4 or not re.search(r"[A-Z]{2}", nome.upper()):
        return None
    return nome


DITTA_NOME = re.compile(r"\b(?:ALLA DITTA|ALL['’]IMPRESA|DITTA|IMPRESA(?: INDIVIDUALE)?|OPERATORE ECONOMICO)\s+"
                        r"(?!(?:PER|AI|AL|ALLA|NELL\w*|RELATIV\w*|DI|DEL|DELLA|AGGIUDICATARI\w*|ESECUTRIC\w*|APPALTATRIC\w*|INDIVIDUATO|SELEZIONATO|AI SENSI)\b)"
                        r"([A-Z0-9][^,;:()\-–\"“”]{1,60}?)(?=\s+(?:DEI|DEL|DELLA|DELLE|PER|DI CUI|RELATIV\w*|CON SEDE|P\.?\s?IVA|C\.?F\.?|NELL\w*|AI SENSI|CIG|CUP|ORDINANZA|DETERMINA|LAVORI|INTERVENTI|OPERE|SERVIZIO|FORNITURA)\b|\s*[-,–(;:]|\.?\s*$|\.\s)")


def oscura_ditte(ogg):
    """Le imprese nominate senza forma societaria possono essere ditte individuali (nome e cognome di una persona):
    nel testo le sostituiamo con [impresa]. Le societa' (SRL, SPA, SNC, SAS, cooperative) restano."""
    def sost(m):
        nome = m.group(1)
        seguito = re.split(r"[,;:()\-–]", ogg[m.end(1):m.end(1) + 60])[0]  # "COMPAGNIA EDILIZIA" + " DELLA BRIANZA SRL"
        if SUFFISSO.search(nome) or SUFFISSO.search(seguito) or nome.startswith("["):
            return m.group(0)
        return m.group(0).replace(nome, "[impresa]")
    return DITTA_NOME.sub(sost, ogg)


def impresa(ogg):
    """Nome dell'impresa, solo se ha una forma societaria (SRL, SPA, SNC, SAS, cooperativa). Senza forma societaria
    spesso e' una ditta individuale col nome di una persona: per la privacy non la teniamo."""
    m = SUFFISSO.search(ogg)
    if not m:
        return None
    prima = TAGLIO.sub("", ogg[:m.start()]).strip(" .")
    parole = prima.split()[-5:]
    # niente numeri/anni o parole minuscole spezzate in testa al nome
    while parole and (re.fullmatch(r"[\d/\.]+", parole[0]) or parole[0].lower() in ("e", "di", "del", "della", "n", "n.")):
        parole = parole[1:]
    if not parole or not re.search(r"[A-Za-z]{2}", " ".join(parole)):
        return None
    return _pulisci_nome((" ".join(parole) + " " + m.group(1).upper().rstrip(".")).strip())


def numero(s):
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def fase(o):
    if re.search(r"\brevoca\b", o):
        return "revoca"
    if re.search(r"(procedura (aperta|negoziata|ristretta)|disciplinare di gara|bando di gara)", o) and not re.search(r"aggiudicazion|esito|avviso di aggiudica", o):
        return "gara_in_partenza"
    if re.search(r"svolgimento della gara|gara per l'affidamento|gara d'appalto per", o):
        return "gara_in_partenza"
    if re.search(r"contrarre|contrattare", o) and not re.search(r"contestual\w*\s+(e\s+)?affidament|e affidamento|ed affidamento|aggiudicazion", o):
        return "gara_in_partenza"
    return next((nome for nome, rx in FASI if re.search(rx, o, re.I)), "altro")


VIABILITA = r"\b(divieto di (transito|sosta)|chiusura (temporanea )?(al|del) transito|interruzione (temporanea )?(e parziale )?al transito|restringimento (stradale|della carreggiata|di carreggiata)|occupazione (temporanea )?(di )?suolo pubblico|ordinanza omnibus|divieto temporaneo (di |della )?circola\w*)\b"
CANTIERE_PRIVATO = r"\b(lavori edili|gru|ponteggi\w*|cantiere edile|autogru|piattaforma aerea|getto (di )?calcestruzzo|scavi|esecuzione di lavori|fine lavori|per lavori|impresa|societ[aà]|ditta|condominio)\b"
NON_CANTIERE = r"\b(potatur\w*|abbattimento (di )?(piante|alberi)|sfalcio|zebrature|rete idrica|rete (del )?gas|acquedotto|fibra|sottoservizi|traslochi|trasloco|stalli di sosta|manifestazion\w*|mercat\w*|corteo|processione|gara ciclistica|fiera)\b"
VIA = re.compile(r"\b((?:VIA|VIALE|PIAZZA|PIAZZALE|CORSO|LARGO|VICOLO|STRADA)\s+[A-Z0-9][A-Z0-9'’\.\s]*?"
                 r"(?:,?\s+(?:ALTEZZA\s+|FRONTE\s+)?(?:CIVIC[OI]\s*|CIV\.?\s*|N\.?\s*)?\d+[A-Z]?(?:\s*[\-/]\s*\d+)?)?)"
                 r"(?=\s*(?:,|-|–|\(|\bIL\b|\bDAL\b|\bDALLE\b|\bPER\b|\bIN\b|\bFRONTE\b|\bALTEZZA\b|\bANGOLO\b|\bNEL\b|\bTRA\b|$))")
NOME_IMPRESA = re.compile(r"\b(?:IMPRESA|SOCIET[AÀ]'?|DITTA)\s+(.+?)(?=\s*[-–]\s|\s+ORDINANZA\b|\s+PER\s|\s*$)")


def cantiere_privato(ogg, o):
    """Ordinanze di viabilita' emesse per cantieri privati: segnale precoce di un cantiere a un indirizzo.
    Il nome dell'impresa si tiene solo se e' una societa' (SRL, SPA, SNC...): le ditte individuali portano
    il nome di una persona e vengono oscurate."""
    if not (re.search(VIABILITA, o) and re.search(CANTIERE_PRIVATO, o)) or re.search(NON_CANTIERE, o):
        return None
    v = VIA.search(ogg)
    imp = None
    m = NOME_IMPRESA.search(ogg)
    if m:
        nome = m.group(1).strip(" .,")
        if SUFFISSO.search(nome):
            imp = nome
        else:
            ogg = ogg[:m.start(1)] + "[impresa]" + ogg[m.end(1):]
    else:
        imp = impresa(ogg)
    return {
        "tipo": "cantiere_privato", "fase": "cantiere_aperto", "importo_eur": None, "cig": None, "cup": None,
        "impresa": imp, "parola_chiave": re.search(CANTIERE_PRIVATO, o).group(0),
        "indirizzo": v.group(1).strip() if v else None, "oggetto": ogg,
    }


def classifica(atto):
    ogg = atto.get("oggetto", "")
    # nomi di professionisti persone fisiche: li oscuriamo, teniamo l'atto
    ogg = PROFESSIONISTA.sub("[professionista]", ogg)
    ogg = COGNOME_TITOLO.sub("[professionista]", ogg)
    ogg = DI_PERSONA.sub(lambda m: m.group(1) + " [privato]", ogg)
    ogg = oscura_ditte(ogg)
    cat = (atto.get("categoria", "") + " " + atto.get("sottocategoria", "")).lower()
    o = ogg.lower()
    if re.search(PERSONALI, ogg, re.I):
        return None  # dati di persone fisiche: non li tocchiamo
    cp = cantiere_privato(ogg, o)  # vale anche se l'atto sta in categoria "ordinanze"
    if cp:
        return cp
    if re.search(CATEGORIE_ESCLUSE, cat):
        return None
    # il nome dell'ufficio ("settore opere pubbliche") non dice nulla sul contenuto dell'atto
    o = re.sub(r"\b(settore|servizio|ufficio|area|direzione)\s+(opere pubbliche|lavori pubblici)", "\\1", o)
    if re.search(SEMPRE_FUORI, o):
        return None  # servizi accessori che citano lavori ma non sono lavori
    urb = re.search(URBANISTICA, o, re.I)
    lav = re.search(LAVORI, o, re.I)
    if not (urb or lav):
        return None
    esplicito = re.search(r"\b(lavori|opere|opera pubblica|manutenzione (ordinaria e )?straordinaria|cantiere|coperture?)\b", o)
    if not urb and not esplicito and re.search(NON_EDILIZIA, o, re.I):
        return None
    importi = [numero(a or b) for a, b in IMPORTO.findall(ogg)]
    importi = [x for x in importi if x and x >= 1000]
    return {
        "tipo": "urbanistica" if urb else "opera_pubblica",
        "fase": "cantiere_aperto" if fase(o) == "altro" and ("ordinanz" in cat or re.search(VIABILITA, o)) else fase(o),
        "importo_eur": max(importi) if importi else None,
        "cig": (CIG.search(ogg) or [None, None])[1],
        "cup": (CUP.search(ogg) or [None, None])[1],
        "impresa": impresa(ogg),
        "parola_chiave": (urb or lav).group(0),
        "indirizzo": None,
        "oggetto": ogg,
    }
