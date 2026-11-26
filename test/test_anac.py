"""Incrocio ANAC su file finti con le stesse intestazioni dei CSV veri (nessuna richiesta di rete)."""
import os, sqlite3, sys, tempfile, unittest, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import anac as N  # noqa: E402

T_CIG = ('"cig";"cig_accordo_quadro";"numero_gara";"oggetto_gara";"importo_complessivo_gara";"n_lotti_componenti";'
         '"oggetto_lotto";"importo_lotto";"oggetto_principale_contratto";"stato";"settore";"luogo_istat";"provincia";'
         '"data_pubblicazione";"data_scadenza_offerta";"cod_tipo_scelta_contraente";"tipo_scelta_contraente";'
         '"cod_modalita_realizzazione";"modalita_realizzazione";"codice_ausa";"cf_amministrazione_appaltante";'
         '"denominazione_amministrazione_appaltante";"sezione_regionale";"id_centro_costo";"denominazione_centro_costo";'
         '"anno_pubblicazione";"mese_pubblicazione";"cod_cpv";"descrizione_cpv";"flag_prevalente";"IMPORTO_SICUREZZA";'
         '"CUI_PROGRAMMA";"ESITO";"DATA_COMUNICAZIONE_ESITO";"FLAG_PNRR_PNC"')


def riga_cig(cig, gara, ogg, oggetto, luogo, prov, cf_sa, cpv, prev="1", importo="960000.0"):
    return (f'"{cig}";;"{gara}";"{ogg}";"{importo}";"1";"{ogg}";"{importo}";"{oggetto}";"ATTIVO";"SETTORI ORDINARI";'
            f'"{luogo}";"{prov}";"2025-01-14";"2025-01-14";"24";"AFFIDAMENTO DIRETTO";"1";"CONTRATTO D\'APPALTO";'
            f'"0000404673";"{cf_sa}";"ENTE";"SEZIONE REGIONALE LOMBARDIA";"X";"SETTORE LAVORI";"2025";"1";'
            f'"{cpv}";"LAVORI";"{prev}";"50000.0";;"AGGIUDICATA";"2025-01-14";"0"')


CIG = "\n".join([
    T_CIG,
    riga_cig("B52F06EFC8", "I72B24000570003V1", "LAVORI MS ISTIT. SCOLASTICI", "LAVORI", "015146", "MILANO", "08911820960", "45214000-0"),
    riga_cig("B52F06EFC8", "I72B24000570003V1", "LAVORI MS ISTIT. SCOLASTICI", "LAVORI", "015146", "MILANO", "08911820960", "45000000-7", prev="0"),
    riga_cig("B540E953BC", "194883794", "RISCATTO PIANOFORTE", "FORNITURE", "015146", "MILANO", "80094690155", "37310000-4"),
    riga_cig("B5568D3E1D", "00417080132.2025.LLPP.3", "MANUTENZIONE IDRAULICO", "LAVORI", "013165", "COMO", "00417080132", "45331000-6"),
    riga_cig("B6000000AA", "G1", "PROGETTAZIONE SCUOLA", "SERVIZI", "", "", "01310880156", "71240000-2", importo="85000,50"),
]) + "\n"

AGZ = ('"cig";"data_aggiudicazione_definitiva";"esito";"criterio_aggiudicazione";"data_comunicazione_esito";'
       '"numero_offerte_ammesse";"numero_offerte_escluse";"importo_aggiudicazione";"ribasso_aggiudicazione";'
       '"num_imprese_offerenti";"flag_subappalto";"id_aggiudicazione";"cod_esito";"num_imprese_richiedenti";'
       '"asta_elettronica";"num_imprese_invitate";"massimo_ribasso";"minimo_ribasso"\n'
       '"B52F06EFC8";"2025-02-04";"AGGIUDICATA";;"2025-02-04";"3";"0";"912000.0";"5.0";"3";"true";"111";"1";;"0";"5";"7.1";"2.0"\n'
       '"B5568D3E1D";"2025-03-01";"AGGIUDICATA";;"2025-03-01";;;"120000.0";"7.0";;"false";"222";"1";;"0";;;\n')

AGT = ('"cig";"ruolo";"codice_fiscale";"denominazione";"tipo_soggetto";"id_aggiudicazione"\n'
       '"B52F06EFC8";"MANDATARIA";"01234567890";"EDILE ROSSI S.R.L.";"IMPRESA";"111"\n'
       '"B52F06EFC8";"MANDANTE";"RSSMRA80A01F205X";"IMPIANTI DI MARIO ROSSI";"DITTA INDIVIDUALE";"111"\n'
       '"B52F06EFC8";"MANDANTE";"1234567";"VERDI SPA";"IMPRESA";"111"\n'
       '"B5568D3E1D";"OPERATORE ECONOMICO MONOSOGGETTIVO";"09999999999";"COMO SRL";"IMPRESA";"222"\n')


def zippa(cartella, nome, testo):
    p = os.path.join(cartella, nome + ".zip")
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(nome + ".csv", testo)
    return p


class TestAnac(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.file = {"cig_csv_2025_01": zippa(d, "cig_csv_2025_01", CIG),
                     "20261101-aggiudicazioni_csv": zippa(d, "agz", AGZ),
                     "20261101-aggiudicatari_csv": zippa(d, "agt", AGT)}
        catalogo = {"cig-2025": ["cig_csv_2025_01"], "cig": [],
                    "aggiudicazioni": ["20261101-aggiudicazioni_csv"], "aggiudicatari": ["20261101-aggiudicatari_csv"]}
        self.orig = N.risorse, N.scarica
        N.risorse = lambda pac, rx: [{"name": n, "url": "https://x/" + n, "size": 1, "last_modified": "m", "format": "CSV"}
                                     for n in catalogo[pac]]
        N.scarica = lambda url, dest: self.file[url.rsplit("/", 1)[1]]
        self.db = os.path.join(d, "anac.db")
        N.aggiorna(self.db, anni=(2025,), soa=False)
        self.c = sqlite3.connect(self.db)

    def tearDown(self):
        N.risorse, N.scarica = self.orig
        self.c.close()
        self.tmp.cleanup()

    def test_filtro_provincia_e_lavori(self):
        cig = {r[0] for r in self.c.execute("SELECT cig FROM anac_cig")}
        # Milano lavori si', fornitura no, Como no, progettazione di un comune della provincia si'
        self.assertEqual(cig, {"B52F06EFC8", "B6000000AA"})

    def test_cpv_prevalente_cup_importo(self):
        cpv, cup, imp = self.c.execute("SELECT cod_cpv, cup, importo_lotto FROM anac_cig WHERE cig='B52F06EFC8'").fetchone()
        self.assertEqual((cpv, cup, imp), ("45214000-0", "I72B24000570003", 960000.0))
        self.assertEqual(self.c.execute("SELECT importo_lotto FROM anac_cig WHERE cig='B6000000AA'").fetchone()[0], 85000.5)

    def test_aggiudicazioni_solo_cig_tenuti(self):
        r = self.c.execute("SELECT cig, importo, ribasso, imprese_offerenti FROM anac_aggiudicazioni").fetchall()
        self.assertEqual(r, [("B52F06EFC8", 912000.0, 5.0, 3)])

    def test_aggiudicatari_privacy(self):
        r = list(self.c.execute("SELECT ruolo, codice_fiscale, denominazione, persona_fisica FROM anac_aggiudicatari"))
        self.assertIn(("MANDANTE", None, None, 1), r)            # ditta individuale: niente nome ne' CF
        self.assertIn(("MANDATARIA", "01234567890", "EDILE ROSSI S.R.L.", 0), r)
        self.assertIn(("MANDANTE", "00001234567", "VERDI SPA", 0), r)  # zeri iniziali persi nel CSV
        self.assertNotIn("RSSMRA80A01F205X", str(r))

    def test_secondo_giro_non_rielabora(self):
        N.scarica = lambda url, dest: self.fail("non doveva riscaricare")
        N.aggiorna(self.db, anni=(2025,), soa=False)


class TestSoa(unittest.TestCase):
    def test_solo_imprese(self):
        with tempfile.TemporaryDirectory() as d:
            att, cat = os.path.join(d, "a.csv"), os.path.join(d, "c.csv")
            open(att, "w").write(
                "_idAttestazione;ATA_soa_codiceFiscale;ATA_soa_denominazione;ATA_impresa_codiceFiscale;ATA_impresa_denominazione;"
                "ATA_provincia_codice;ATA_provincia_nome;ATA_attestato_stato;ATA_attestato_numero;ATA_attestato_codiceSoa;"
                "ATA_attestato_dataScadenzaIntermedia;ATA_attestato_classificaProgettazione;ATA_attestato_dataScadenzaValiditaTriennale;"
                "ATA_attestato_dataRilascioAttestazioneInCorso;ATA_attestato_dataScadenzaValiditaQuinquennale\n"
                "a1;1;SOA;04606430587;M.A.C.E. S.R.L;IT-MI;MILANO;IN_CORSO;5452;23/00;;;2027-07-02;2024-09-07;2029-07-02\n"
                "a2;1;SOA;RSSMRA80A01F205X;MARIO ROSSI;IT-MI;MILANO;IN_CORSO;1;1;;;;;\n")
            open(cat, "w").write("_idAttestazione;ATCR_categoria;ATCR_classifica\na1;OG1;V\na1;OS30;II\na2;OG1;I\n")
            db = sqlite3.connect(":memory:")
            db.executescript(N.SCHEMA)
            self.assertEqual(N.carica_soa(db, att, cat, "soa", "2026-11-26"), (2, 1))
            self.assertEqual(sorted(db.execute("SELECT categoria, classifica FROM anac_soa_categorie")), [("OG1", "V"), ("OS30", "II")])
            self.assertEqual(db.execute("SELECT data_rilascio FROM anac_soa").fetchone()[0], "2024-09-07")


class TestFunzioni(unittest.TestCase):
    def test_num(self):
        self.assertEqual(N.num("7853117.01"), 7853117.01)
        self.assertEqual(N.num("85000,50"), 85000.5)
        self.assertIsNone(N.num(""))

    def test_persona(self):
        self.assertTrue(N.persona_fisica("GLTNDR81L24C351W", "DITTA INDIVIDUALE"))
        self.assertTrue(N.persona_fisica("01122350380", "DITTA INDIVIDUALE"))
        self.assertFalse(N.persona_fisica("01122350380", "IMPRESA"))


if __name__ == "__main__":
    unittest.main()
