-- ============================================================================
-- OPERATIONAL RISK & COMPLIANCE TRACKING SYSTEM
-- Kern-Tabellen für Risikomanagement
-- ============================================================================

-- BASEL II Risikokategorien (Event Types)
CREATE TABLE IF NOT EXISTS basel_risikokategorien (
    kategorie_id SERIAL PRIMARY KEY,
    kategorie_code VARCHAR(10) UNIQUE NOT NULL,
    kategorie_name_de VARCHAR(200) NOT NULL,
    kategorie_name_en VARCHAR(200),
    beschreibung TEXT,
    level_1 VARCHAR(100),  -- BASEL Level 1 Category
    level_2 VARCHAR(100),  -- BASEL Level 2 Category
    ist_aktiv BOOLEAN DEFAULT TRUE
);

-- BASEL II Standard-Kategorien
INSERT INTO basel_risikokategorien (kategorie_code, kategorie_name_de, kategorie_name_en, level_1, level_2) VALUES
    ('IF', 'Interner Betrug', 'Internal Fraud', 'Internal Fraud', 'Unauthorized Activity'),
    ('EF', 'Externer Betrug', 'External Fraud', 'External Fraud', 'Theft and Fraud'),
    ('EPWS', 'Beschäftigungspraxis & Arbeitsplatzsicherheit', 'Employment Practices', 'Employment Practices', 'Employee Relations'),
    ('CPBP', 'Kunden, Produkte & Geschäftspraxis', 'Clients, Products & Business Practices', 'CPBP', 'Suitability'),
    ('DPA', 'Sachschäden', 'Damage to Physical Assets', 'DPA', 'Disasters'),
    ('BDSF', 'Geschäftsunterbrechung & Systemausfälle', 'Business Disruption & System Failures', 'BDSF', 'Systems'),
    ('EDPM', 'Ausführung, Lieferung & Prozessmanagement', 'Execution, Delivery & Process Management', 'EDPM', 'Transaction Processing')
ON CONFLICT (kategorie_code) DO NOTHING;

-- ============================================================================
-- RISIKO_EREIGNISSE - Haupttabelle für operationelle Risikoereignisse
-- ============================================================================
CREATE TABLE IF NOT EXISTS risiko_ereignisse (
    ereignis_id SERIAL PRIMARY KEY,
    ereignis_referenz VARCHAR(50) UNIQUE,  -- Eindeutige Referenznummer z.B. ORE-2024-00001

    -- Zeitliche Angaben
    meldedatum DATE NOT NULL DEFAULT CURRENT_DATE,
    entdeckungsdatum DATE NOT NULL,
    ereignis_beginn DATE,
    ereignis_ende DATE,

    -- Klassifizierung
    ereignis_typ VARCHAR(50) NOT NULL,  -- Betrug, Systemausfall, Compliance-Verstoß, etc.
    basel_kategorie_id INTEGER REFERENCES basel_risikokategorien(kategorie_id),
    risiko_schwere VARCHAR(20) DEFAULT 'MEDIUM',  -- LOW, MEDIUM, HIGH, CRITICAL

    -- Organisatorische Zuordnung
    geschaeftsbereich_id INTEGER REFERENCES geschaeftsbereiche(bereich_id),
    geschaeftsbereich VARCHAR(100),  -- Denormalisiert für Performance
    prozess VARCHAR(200),
    standort VARCHAR(100),

    -- Finanzielle Auswirkung
    verlust_betrag DECIMAL(18, 2) DEFAULT 0,
    verlust_waehrung VARCHAR(3) DEFAULT 'EUR',
    verlust_betrag_eur DECIMAL(18, 2),  -- Umgerechnet in EUR
    wiederherstellung_betrag DECIMAL(18, 2) DEFAULT 0,
    versicherungs_erstattung DECIMAL(18, 2) DEFAULT 0,
    netto_verlust DECIMAL(18, 2) GENERATED ALWAYS AS (
        verlust_betrag - COALESCE(wiederherstellung_betrag, 0) - COALESCE(versicherungs_erstattung, 0)
    ) STORED,

    -- Potentieller Verlust für Near-Misses
    potentieller_verlust DECIMAL(18, 2),
    ist_near_miss BOOLEAN DEFAULT FALSE,

    -- Ursachenanalyse
    root_cause TEXT,
    root_cause_kategorie VARCHAR(50),  -- PEOPLE, PROCESS, SYSTEMS, EXTERNAL
    contributing_factors TEXT[],

    -- Korrekturmaßnahmen
    corrective_actions TEXT,
    preventive_actions TEXT,
    action_owner INTEGER REFERENCES benutzer(benutzer_id),
    action_deadline DATE,
    action_status VARCHAR(30) DEFAULT 'OFFEN',  -- OFFEN, IN_BEARBEITUNG, ABGESCHLOSSEN

    -- Status und Workflow
    status VARCHAR(30) DEFAULT 'GEMELDET',  -- GEMELDET, ANALYSIERT, BEWERTET, ABGESCHLOSSEN, ARCHIVIERT
    ist_extern_gemeldet BOOLEAN DEFAULT FALSE,  -- An Aufsichtsbehörde gemeldet
    externe_meldung_datum DATE,

    -- Freigabe (4-Augen-Prinzip)
    erfasst_von INTEGER REFERENCES benutzer(benutzer_id),
    freigegeben_von INTEGER REFERENCES benutzer(benutzer_id),
    freigabe_datum TIMESTAMP,

    -- Metadaten
    bemerkungen TEXT,
    anhaenge_pfad TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indizes für Performance
CREATE INDEX IF NOT EXISTS idx_ereignisse_datum ON risiko_ereignisse(meldedatum);
CREATE INDEX IF NOT EXISTS idx_ereignisse_typ ON risiko_ereignisse(ereignis_typ);
CREATE INDEX IF NOT EXISTS idx_ereignisse_bereich ON risiko_ereignisse(geschaeftsbereich_id);
CREATE INDEX IF NOT EXISTS idx_ereignisse_basel ON risiko_ereignisse(basel_kategorie_id);
CREATE INDEX IF NOT EXISTS idx_ereignisse_status ON risiko_ereignisse(status);
CREATE INDEX IF NOT EXISTS idx_ereignisse_verlust ON risiko_ereignisse(verlust_betrag_eur);

-- ============================================================================
-- KONTROLLE_MECHANISMEN - Kontrollmaßnahmen und deren Effektivität
-- ============================================================================
CREATE TABLE IF NOT EXISTS kontrolle_mechanismen (
    kontrolle_id SERIAL PRIMARY KEY,
    kontrolle_referenz VARCHAR(50) UNIQUE,  -- z.B. CTL-001
    kontrolle_name VARCHAR(200) NOT NULL,
    kontrolle_beschreibung TEXT,

    -- Klassifizierung
    kontrolle_typ VARCHAR(30) NOT NULL,  -- PREVENTIV, DETEKTIV, KORREKTIV
    kontrolle_kategorie VARCHAR(50),  -- MANUAL, AUTOMATED, SEMI_AUTOMATED
    risiko_kategorie VARCHAR(50),  -- Welche Risikokategorie wird adressiert

    -- Zuständigkeit
    zustaendiger_id INTEGER REFERENCES benutzer(benutzer_id),
    zustaendiger_name VARCHAR(200),
    abteilung VARCHAR(100),

    -- Testing
    test_frequenz VARCHAR(30),  -- TAEGLICH, WOECHENTLICH, MONATLICH, QUARTAL, JAEHRLICH
    letzter_test DATE,
    naechster_test DATE,
    test_ergebnis VARCHAR(30),  -- BESTANDEN, NICHT_BESTANDEN, TEILWEISE, NICHT_GETESTET
    test_bemerkung TEXT,

    -- Bewertung
    effektivitaets_score DECIMAL(5, 2),  -- 0-100%
    design_effektivitaet VARCHAR(30),  -- EFFEKTIV, TEILWEISE_EFFEKTIV, NICHT_EFFEKTIV
    operative_effektivitaet VARCHAR(30),
    maturity_level INTEGER CHECK (maturity_level BETWEEN 1 AND 5),  -- 1=Initial, 5=Optimized

    -- Kosten-Nutzen
    jaehrliche_kosten DECIMAL(18, 2),
    risiko_reduktion_prozent DECIMAL(5, 2),

    -- Verknüpfungen
    abgedeckte_risiken TEXT[],
    verknuepfte_vorschriften TEXT[],

    -- Status
    ist_aktiv BOOLEAN DEFAULT TRUE,
    einfuehrungsdatum DATE,
    ausserbetriebnahme_datum DATE,

    -- Metadaten
    dokumentations_pfad TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kontrolle_typ ON kontrolle_mechanismen(kontrolle_typ);
CREATE INDEX IF NOT EXISTS idx_kontrolle_test ON kontrolle_mechanismen(naechster_test);
CREATE INDEX IF NOT EXISTS idx_kontrolle_effektiv ON kontrolle_mechanismen(effektivitaets_score);

-- Verknüpfung Ereignisse <-> Kontrollen (welche Kontrollen haben versagt)
CREATE TABLE IF NOT EXISTS ereignis_kontrolle_mapping (
    id SERIAL PRIMARY KEY,
    ereignis_id INTEGER REFERENCES risiko_ereignisse(ereignis_id),
    kontrolle_id INTEGER REFERENCES kontrolle_mechanismen(kontrolle_id),
    versagens_typ VARCHAR(50),  -- NICHT_VORHANDEN, NICHT_EFFEKTIV, UMGANGEN, NICHT_ANWENDBAR
    bemerkung TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- COMPLIANCE_VORSCHRIFTEN - Regulatorische Anforderungen
-- ============================================================================
CREATE TABLE IF NOT EXISTS compliance_vorschriften (
    vorschrift_id SERIAL PRIMARY KEY,
    vorschrift_referenz VARCHAR(50) UNIQUE,  -- z.B. REG-MIFID-001

    -- Regulatorischer Rahmen
    reg_werk VARCHAR(50) NOT NULL,  -- MiFID II, EMIR, GDPR, SOX, BASEL III, etc.
    reg_artikel VARCHAR(100),  -- Artikel/Paragraph-Referenz
    anforderung TEXT NOT NULL,
    anforderung_kurz VARCHAR(500),

    -- Zeitliche Aspekte
    inkrafttreten DATE,
    deadline DATE,
    naechste_pruefung DATE,

    -- Status
    status VARCHAR(30) DEFAULT 'OFFEN',  -- ERFUELLT, OFFEN, VERLETZT, IN_BEARBEITUNG, NICHT_ANWENDBAR
    erfuellungsgrad DECIMAL(5, 2),  -- 0-100%

    -- Zuständigkeit
    verantwortlicher_id INTEGER REFERENCES benutzer(benutzer_id),
    verantwortlicher_name VARCHAR(200),
    abteilung VARCHAR(100),

    -- Bewertung
    risiko_bei_nichterfuellung VARCHAR(20),  -- LOW, MEDIUM, HIGH, CRITICAL
    potentielle_strafe DECIMAL(18, 2),
    strafe_waehrung VARCHAR(3) DEFAULT 'EUR',

    -- Dokumentation
    dokumentations_pfad TEXT,
    nachweis_dokumente TEXT[],

    -- Prüfungen
    letzte_pruefung DATE,
    pruefer VARCHAR(200),
    pruef_ergebnis TEXT,

    -- Metadaten
    bemerkungen TEXT,
    ist_aktiv BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vorschrift_werk ON compliance_vorschriften(reg_werk);
CREATE INDEX IF NOT EXISTS idx_vorschrift_status ON compliance_vorschriften(status);
CREATE INDEX IF NOT EXISTS idx_vorschrift_deadline ON compliance_vorschriften(deadline);

-- Verknüpfung Vorschriften <-> Kontrollen
CREATE TABLE IF NOT EXISTS vorschrift_kontrolle_mapping (
    id SERIAL PRIMARY KEY,
    vorschrift_id INTEGER REFERENCES compliance_vorschriften(vorschrift_id),
    kontrolle_id INTEGER REFERENCES kontrolle_mechanismen(kontrolle_id),
    abdeckungsgrad DECIMAL(5, 2),  -- Wie viel Prozent der Anforderung wird abgedeckt
    bemerkung TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INCIDENT_RESPONSE - Reaktion auf Ereignisse
-- ============================================================================
CREATE TABLE IF NOT EXISTS incident_response (
    response_id SERIAL PRIMARY KEY,
    ereignis_id INTEGER REFERENCES risiko_ereignisse(ereignis_id),

    -- Response Team
    response_team TEXT[],  -- Liste der Teammitglieder
    response_lead_id INTEGER REFERENCES benutzer(benutzer_id),
    response_lead_name VARCHAR(200),

    -- Eskalation
    eskalations_level INTEGER DEFAULT 1,  -- 1-5
    eskalations_pfad TEXT[],  -- Chronologische Liste der Eskalationen
    eskaliert_an TEXT[],

    -- Zeitliche Aspekte
    response_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    erstreaktion_zeit INTERVAL,  -- Time to First Response
    loesungs_zeit INTERVAL,  -- Time to Resolution
    abschluss_datum TIMESTAMP,

    -- Maßnahmen
    sofort_massnahmen TEXT,
    eingeleitete_massnahmen TEXT,
    massnahmen_status VARCHAR(30) DEFAULT 'LAUFEND',  -- GEPLANT, LAUFEND, ABGESCHLOSSEN

    -- Kommunikation
    interne_kommunikation TEXT,
    externe_kommunikation TEXT,  -- An Kunden, Aufsicht, Presse
    kommunikations_log JSONB,

    -- Abschluss
    lessons_learned TEXT,
    follow_up_actions TEXT[],
    abschluss_bestaetigt_von INTEGER REFERENCES benutzer(benutzer_id),

    -- Metadaten
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_response_ereignis ON incident_response(ereignis_id);
CREATE INDEX IF NOT EXISTS idx_response_level ON incident_response(eskalations_level);

-- ============================================================================
-- KEY_RISK_INDICATORS (KRIs) - Risikoindikatoren
-- ============================================================================
CREATE TABLE IF NOT EXISTS key_risk_indicators (
    kri_id SERIAL PRIMARY KEY,
    kri_referenz VARCHAR(50) UNIQUE,  -- z.B. KRI-001
    kri_name VARCHAR(200) NOT NULL,
    kri_beschreibung TEXT,

    -- Kategorisierung
    risiko_kategorie VARCHAR(50),
    geschaeftsbereich VARCHAR(100),

    -- Messparameter
    einheit VARCHAR(50),  -- Prozent, Anzahl, EUR, Tage, etc.
    aggregations_methode VARCHAR(30),  -- SUM, AVG, MAX, COUNT, LAST
    datenquelle VARCHAR(200),
    berechnungs_formel TEXT,

    -- Schwellwerte
    ziel_wert DECIMAL(18, 4),
    toleranz_band_unten DECIMAL(18, 4),
    toleranz_band_oben DECIMAL(18, 4),
    kritischer_wert DECIMAL(18, 4),

    -- Verantwortlichkeit
    owner_id INTEGER REFERENCES benutzer(benutzer_id),
    owner_name VARCHAR(200),

    -- Frequenz
    mess_frequenz VARCHAR(30),  -- TAEGLICH, WOECHENTLICH, MONATLICH

    -- Status
    ist_aktiv BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- KRI Messwerte (historisch)
CREATE TABLE IF NOT EXISTS kri_messwerte (
    messwert_id SERIAL PRIMARY KEY,
    kri_id INTEGER REFERENCES key_risk_indicators(kri_id),
    mess_datum DATE NOT NULL,

    -- Werte
    ist_wert DECIMAL(18, 4) NOT NULL,
    ziel_wert DECIMAL(18, 4),
    vorperiode_wert DECIMAL(18, 4),

    -- Berechnung
    abweichung_absolut DECIMAL(18, 4),
    abweichung_prozent DECIMAL(10, 4),

    -- Trend und Status
    trend VARCHAR(20),  -- VERBESSERT, VERSCHLECHTERT, STABIL
    ampel_status VARCHAR(10),  -- GRUEN, GELB, ROT

    -- Kontext
    kommentar TEXT,
    massnahmen TEXT,

    -- Metadaten
    erfasst_von INTEGER REFERENCES benutzer(benutzer_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(kri_id, mess_datum)
);

CREATE INDEX IF NOT EXISTS idx_kri_messwerte_datum ON kri_messwerte(mess_datum);
CREATE INDEX IF NOT EXISTS idx_kri_messwerte_kri ON kri_messwerte(kri_id);
CREATE INDEX IF NOT EXISTS idx_kri_messwerte_ampel ON kri_messwerte(ampel_status);

-- ============================================================================
-- SCENARIO_ANALYSIS - Szenarioanalysen für Kapitalberechnung
-- ============================================================================
CREATE TABLE IF NOT EXISTS scenario_analysis (
    scenario_id SERIAL PRIMARY KEY,
    scenario_referenz VARCHAR(50) UNIQUE,  -- z.B. SCN-2024-001
    scenario_name VARCHAR(200) NOT NULL,
    scenario_beschreibung TEXT,

    -- Klassifizierung
    scenario_typ VARCHAR(50),  -- HISTORICAL, HYPOTHETICAL, STRESS_TEST
    risiko_kategorie VARCHAR(50),
    geschaeftsbereich VARCHAR(100),

    -- Bewertung
    wahrscheinlichkeit DECIMAL(10, 6),  -- Als Dezimalzahl (z.B. 0.001 für 0.1%)
    wahrscheinlichkeit_klasse VARCHAR(20),  -- SELTEN, UNWAHRSCHEINLICH, MOEGLICH, WAHRSCHEINLICH, FAST_SICHER
    auswirkung DECIMAL(18, 2),  -- In EUR
    auswirkung_klasse VARCHAR(20),  -- GERING, MODERAT, ERHEBLICH, SCHWER, KATASTROPHAL

    -- Berechnete Werte
    erwarteter_verlust DECIMAL(18, 2),  -- = Wahrscheinlichkeit × Auswirkung
    value_at_risk DECIMAL(18, 2),  -- 99.9% VaR
    unexpected_loss DECIMAL(18, 2),

    -- Kontrollen und Residualrisiko
    bestehende_kontrollen TEXT[],
    kontroll_effektivitaet DECIMAL(5, 2),  -- 0-100%
    brutto_risiko DECIMAL(18, 2),
    residual_risiko_nach_controls DECIMAL(18, 2),

    -- Versicherung
    versicherungsschutz DECIMAL(18, 2),
    residual_nach_versicherung DECIMAL(18, 2),

    -- Validierung
    expertenvalidierung BOOLEAN DEFAULT FALSE,
    validiert_von INTEGER REFERENCES benutzer(benutzer_id),
    validierung_datum DATE,
    validierung_bemerkung TEXT,

    -- Status
    status VARCHAR(30) DEFAULT 'ENTWURF',  -- ENTWURF, AKTIV, ARCHIVIERT
    gueltig_von DATE,
    gueltig_bis DATE,

    -- Metadaten
    erstellt_von INTEGER REFERENCES benutzer(benutzer_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scenario_typ ON scenario_analysis(scenario_typ);
CREATE INDEX IF NOT EXISTS idx_scenario_kategorie ON scenario_analysis(risiko_kategorie);
CREATE INDEX IF NOT EXISTS idx_scenario_status ON scenario_analysis(status);

-- ============================================================================
-- RISK_APPETITE - Risk Appetite Statement und Monitoring
-- ============================================================================
CREATE TABLE IF NOT EXISTS risk_appetite (
    appetite_id SERIAL PRIMARY KEY,
    gueltigkeits_jahr INTEGER NOT NULL,

    -- Quantitative Limits
    max_einzelverlust DECIMAL(18, 2),
    max_jahresverlust DECIMAL(18, 2),
    max_verlust_pro_ereignis_typ JSONB,  -- {"Betrug": 1000000, "IT": 500000, ...}

    -- Qualitative Statements
    risiko_toleranz_beschreibung TEXT,
    null_toleranz_bereiche TEXT[],  -- z.B. Compliance, Reputation

    -- Approved by
    genehmigt_von VARCHAR(200),  -- z.B. "Vorstand", "Aufsichtsrat"
    genehmigung_datum DATE,

    -- Status
    ist_aktiv BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Risk Appetite Monitoring
CREATE TABLE IF NOT EXISTS risk_appetite_monitoring (
    monitoring_id SERIAL PRIMARY KEY,
    appetite_id INTEGER REFERENCES risk_appetite(appetite_id),
    periode VARCHAR(10),  -- YYYY-MM

    -- Aktuelle Werte
    kumulierter_verlust DECIMAL(18, 2),
    max_einzelverlust_periode DECIMAL(18, 2),
    anzahl_ereignisse INTEGER,

    -- Auslastung
    auslastung_prozent DECIMAL(5, 2),

    -- Status
    status VARCHAR(30),  -- IM_RAHMEN, WARNUNG, UEBERSCHRITTEN
    eskalation_erforderlich BOOLEAN DEFAULT FALSE,

    -- Metadaten
    berechnet_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
