# Radar cantieri (provincia di Milano)

Come funziona, in 5 pezzi:
1. **Elenco enti** (`comuni_mi.csv`): 133 comuni con sito ufficiale, presi dall'Indice PA (open data). `mappa_manuale.csv` dice per 55 comuni (49 già leggibili, fra cui quasi tutti i più grandi; Milano esclusa per ora) dove sta l'albo e che software usa; `radar.py scopri` prova a trovarlo da solo per gli altri (`mappa_albi.csv`). La mappa a mano vince.
2. **Connettori** (`connettori.py`): uno per ogni software di albo pretorio. Pronti e testati su pagine vere: JCityGov, e-pal, Halley, DgegovPA (export CSV ufficiale), Sicraweb/Maggioli, Urbi (tutto l'albo con una sola richiesta), ComuneWeb, Halley-EG, albo JSP di Cinisello. Riconosciuti ma ancora senza connettore: Saturnweb, siti propri.
3. **Classificatore** (`classifica.py`): tiene opere pubbliche, urbanistica e cantieri privati (questi ultimi dalle ordinanze di viabilità "per lavori edili / gru / ponteggi", con l'indirizzo). Riconosce la fase (programmazione, progetto, finanziamento, gara in partenza, affidamento, esecuzione/SAL/subappalto, collaudo, asta, autorizzazione, revoca), estrae impresa, CIG, CUP e importo. Scarta gli atti con dati di persone fisiche e oscura i nomi dei professionisti.
4. **Archivio** (`archivio.py`, file `dati/radar.db`): salva solo gli atti utili, con prima e ultima data in cui li abbiamo visti; niente duplicati. La vista `progetti` raggruppa gli atti per CUP/CIG: la storia di un'opera dal progetto al collaudo. La tabella `letture` registra ogni giorno quanti atti ha dato ogni comune e gli eventuali errori.
5. **Motore** (`radar.py`):
   - `python3 radar.py prova` controlla che ogni albo risponda da questa macchina
   - `python3 radar.py raccogli 20` legge gli ultimi 20 giorni e scrive `dati/nuovi_AAAA-MM-GG.csv` (solo le novità del giorno) e `dati/radar_cantieri.csv` (tutto l'archivio)

L'albo mostra solo gli atti in pubblicazione (circa 15 giorni): lanciandolo ogni giorno si costruisce uno storico che i comuni non tengono in forma comoda.

**Esecuzione giornaliera gratis**: `.github/workflows/radar.yml` lo fa girare ogni mattina su GitHub Actions in un repository privato e salva l'archivio nel repository stesso.

**Test**: `python3 -m unittest discover -s test` (nessuna richiesta di rete; usa pagine vere salvate il 26/11/2026 e 330 atti veri rivisti a mano).

Richiede Python 3.9+, nessuna libreria. Pausa di 1 secondo fra le richieste per non pesare sui siti dei comuni.

`campione/`: primo campione di atti veri e risultato del classificatore.
