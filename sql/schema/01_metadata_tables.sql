-- ============================================================================
-- OPERATIONAL RISK & COMPLIANCE TRACKING SYSTEM
-- Metadaten-Tabellen (Basis-Infrastruktur)
-- ============================================================================

-- Kalender-Tabelle für Geschäftstage, Feiertage, Perioden
CREATE TABLE IF NOT EXISTS kalender (
    datum DATE PRIMARY KEY,
    jahr INTEGER NOT NULL,
    quartal INTEGER NOT NULL CHECK (quartal BETWEEN 1 AND 4),
    monat INTEGER NOT NULL CHECK (monat BETWEEN 1 AND 12),
    woche INTEGER NOT NULL,
    tag_im_monat INTEGER NOT NULL,
    tag_im_jahr INTEGER NOT NULL,
    wochentag VARCHAR(20) NOT NULL,
    ist_geschaeftstag BOOLEAN DEFAULT TRUE,
    ist_feiertag BOOLEAN DEFAULT FALSE,
    feiertag_name VARCHAR(100),
    ist_monatsende BOOLEAN DEFAULT FALSE,
    ist_quartalsende BOOLEAN DEFAULT FALSE,
    ist_jahresende BOOLEAN DEFAULT FALSE,
    geschaeftstag_nummer INTEGER,  -- Laufende Nummer der Geschäftstage
    periode_id VARCHAR(10),  -- Format: YYYY-MM
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index für häufige Abfragen
CREATE INDEX IF NOT EXISTS idx_kalender_periode ON kalender(periode_id);
CREATE INDEX IF NOT EXISTS idx_kalender_geschaeftstag ON kalender(ist_geschaeftstag);

-- Währungsumrechnung - FX Rates historisch
CREATE TABLE IF NOT EXISTS waehrungsumrechnung (
    id SERIAL PRIMARY KEY,
    von_waehrung VARCHAR(3) NOT NULL,
    nach_waehrung VARCHAR(3) NOT NULL,
    kurs_datum DATE NOT NULL,
    wechselkurs DECIMAL(18, 8) NOT NULL,
    kurs_typ VARCHAR(20) DEFAULT 'SPOT',  -- SPOT, FORWARD, AVERAGE
    quelle VARCHAR(100),  -- ECB, Bloomberg, Reuters
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(von_waehrung, nach_waehrung, kurs_datum, kurs_typ)
);

CREATE INDEX IF NOT EXISTS idx_fx_datum ON waehrungsumrechnung(kurs_datum);
CREATE INDEX IF NOT EXISTS idx_fx_waehrungspaar ON waehrungsumrechnung(von_waehrung, nach_waehrung);

-- Benutzer und Rollen für Zugriffsrechte
CREATE TABLE IF NOT EXISTS benutzer (
    benutzer_id SERIAL PRIMARY KEY,
    benutzername VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    vorname VARCHAR(100),
    nachname VARCHAR(100),
    abteilung VARCHAR(100),
    kostenstelle VARCHAR(50),
    ist_aktiv BOOLEAN DEFAULT TRUE,
    letzter_login TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rollen (
    rolle_id SERIAL PRIMARY KEY,
    rolle_name VARCHAR(100) UNIQUE NOT NULL,
    beschreibung TEXT,
    berechtigung_level INTEGER DEFAULT 1,  -- 1-5, höher = mehr Rechte
    kann_lesen BOOLEAN DEFAULT TRUE,
    kann_schreiben BOOLEAN DEFAULT FALSE,
    kann_loeschen BOOLEAN DEFAULT FALSE,
    kann_freigeben BOOLEAN DEFAULT FALSE,  -- 4-Augen-Prinzip
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS benutzer_rollen (
    id SERIAL PRIMARY KEY,
    benutzer_id INTEGER REFERENCES benutzer(benutzer_id),
    rolle_id INTEGER REFERENCES rollen(rolle_id),
    geschaeftsbereich VARCHAR(100),  -- Row-Level Security Scope
    gueltig_von DATE DEFAULT CURRENT_DATE,
    gueltig_bis DATE,
    zugewiesen_von INTEGER REFERENCES benutzer(benutzer_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(benutzer_id, rolle_id, geschaeftsbereich)
);

-- Audit Trail für SOX Compliance
CREATE TABLE IF NOT EXISTS audit_trail (
    audit_id SERIAL PRIMARY KEY,
    tabellen_name VARCHAR(100) NOT NULL,
    datensatz_id INTEGER NOT NULL,
    aktion VARCHAR(20) NOT NULL,  -- INSERT, UPDATE, DELETE
    alte_werte JSONB,
    neue_werte JSONB,
    geaenderte_felder TEXT[],
    benutzer_id INTEGER REFERENCES benutzer(benutzer_id),
    benutzer_name VARCHAR(100),
    ip_adresse VARCHAR(45),
    session_id VARCHAR(100),
    aenderung_zeitpunkt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    bemerkung TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_tabelle ON audit_trail(tabellen_name);
CREATE INDEX IF NOT EXISTS idx_audit_zeitpunkt ON audit_trail(aenderung_zeitpunkt);
CREATE INDEX IF NOT EXISTS idx_audit_benutzer ON audit_trail(benutzer_id);
CREATE INDEX IF NOT EXISTS idx_audit_datensatz ON audit_trail(tabellen_name, datensatz_id);

-- Geschäftsbereiche (für Row-Level Security und Zuordnungen)
CREATE TABLE IF NOT EXISTS geschaeftsbereiche (
    bereich_id SERIAL PRIMARY KEY,
    bereich_code VARCHAR(20) UNIQUE NOT NULL,
    bereich_name VARCHAR(200) NOT NULL,
    bereich_typ VARCHAR(50),  -- FRONTOFFICE, BACKOFFICE, IT, COMPLIANCE
    parent_bereich_id INTEGER REFERENCES geschaeftsbereiche(bereich_id),
    kostentraeger VARCHAR(50),
    leiter_benutzer_id INTEGER REFERENCES benutzer(benutzer_id),
    ist_aktiv BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Systemkonfiguration
CREATE TABLE IF NOT EXISTS system_konfiguration (
    config_id SERIAL PRIMARY KEY,
    config_schluessel VARCHAR(100) UNIQUE NOT NULL,
    config_wert TEXT,
    config_typ VARCHAR(20) DEFAULT 'STRING',  -- STRING, INTEGER, DECIMAL, BOOLEAN, JSON
    beschreibung TEXT,
    ist_sensitiv BOOLEAN DEFAULT FALSE,  -- Für Maskierung
    zuletzt_geaendert TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    geaendert_von INTEGER REFERENCES benutzer(benutzer_id)
);

-- Standard-Rollen einfügen
INSERT INTO rollen (rolle_name, beschreibung, berechtigung_level, kann_lesen, kann_schreiben, kann_loeschen, kann_freigeben)
VALUES
    ('ADMIN', 'Systemadministrator mit vollen Rechten', 5, TRUE, TRUE, TRUE, TRUE),
    ('RISK_MANAGER', 'Risikomanager mit Schreib- und Freigaberechten', 4, TRUE, TRUE, FALSE, TRUE),
    ('RISK_ANALYST', 'Risikoanalyst mit Schreibrechten', 3, TRUE, TRUE, FALSE, FALSE),
    ('COMPLIANCE_OFFICER', 'Compliance-Beauftragter', 4, TRUE, TRUE, FALSE, TRUE),
    ('AUDITOR', 'Interner/Externer Prüfer (nur Lesen)', 2, TRUE, FALSE, FALSE, FALSE),
    ('VIEWER', 'Nur Leserechte', 1, TRUE, FALSE, FALSE, FALSE)
ON CONFLICT (rolle_name) DO NOTHING;

-- Standard-Konfiguration
INSERT INTO system_konfiguration (config_schluessel, config_wert, config_typ, beschreibung)
VALUES
    ('RISK_APPETITE_LIMIT', '10000000', 'DECIMAL', 'Maximaler akzeptabler Verlust p.a. in EUR'),
    ('KRI_REFRESH_INTERVAL', '1', 'INTEGER', 'KRI-Aktualisierungsintervall in Tagen'),
    ('ESCALATION_THRESHOLD_L1', '100000', 'DECIMAL', 'Schwellwert für Eskalation Level 1'),
    ('ESCALATION_THRESHOLD_L2', '500000', 'DECIMAL', 'Schwellwert für Eskalation Level 2'),
    ('ESCALATION_THRESHOLD_L3', '1000000', 'DECIMAL', 'Schwellwert für Eskalation Level 3'),
    ('DEFAULT_CURRENCY', 'EUR', 'STRING', 'Standardwährung für Berichte'),
    ('RETENTION_PERIOD_YEARS', '10', 'INTEGER', 'Aufbewahrungsfrist in Jahren'),
    ('VIER_AUGEN_AKTIV', 'true', 'BOOLEAN', '4-Augen-Prinzip aktiviert')
ON CONFLICT (config_schluessel) DO NOTHING;
