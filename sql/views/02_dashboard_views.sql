-- ============================================================================
-- OPERATIONAL RISK & COMPLIANCE TRACKING SYSTEM
-- Dashboard Views (Materialized Views für Performance)
-- ============================================================================

-- ============================================================================
-- OPERATIONAL_RISK_HEATMAP (Häufigkeit × Auswirkung)
-- ============================================================================

-- Materialized View für Risk Heatmap
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_operational_risk_heatmap AS
WITH risk_matrix AS (
    SELECT
        re.ereignis_typ,
        bc.kategorie_name_de AS basel_kategorie,
        re.geschaeftsbereich,

        -- Häufigkeits-Klassifikation (letzte 3 Jahre)
        CASE
            WHEN COUNT(*) >= 50 THEN 5  -- Sehr häufig
            WHEN COUNT(*) >= 20 THEN 4  -- Häufig
            WHEN COUNT(*) >= 10 THEN 3  -- Gelegentlich
            WHEN COUNT(*) >= 5 THEN 2   -- Selten
            ELSE 1                       -- Sehr selten
        END AS haeufigkeit_score,

        -- Auswirkungs-Klassifikation (durchschnittlicher Verlust)
        CASE
            WHEN AVG(verlust_betrag_eur) >= 10000000 THEN 5  -- Katastrophal
            WHEN AVG(verlust_betrag_eur) >= 1000000 THEN 4   -- Schwer
            WHEN AVG(verlust_betrag_eur) >= 100000 THEN 3    -- Erheblich
            WHEN AVG(verlust_betrag_eur) >= 10000 THEN 2     -- Moderat
            ELSE 1                                            -- Gering
        END AS auswirkung_score,

        COUNT(*) AS anzahl_ereignisse,
        SUM(verlust_betrag_eur) AS gesamt_verlust,
        AVG(verlust_betrag_eur) AS durchschnitt_verlust,
        MAX(verlust_betrag_eur) AS max_verlust

    FROM risiko_ereignisse re
    LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
    WHERE re.meldedatum >= CURRENT_DATE - INTERVAL '3 years'
      AND re.verlust_betrag_eur > 0
      AND re.ist_near_miss = FALSE
    GROUP BY re.ereignis_typ, bc.kategorie_name_de, re.geschaeftsbereich
)
SELECT
    ereignis_typ,
    basel_kategorie,
    geschaeftsbereich,
    haeufigkeit_score,
    auswirkung_score,
    haeufigkeit_score * auswirkung_score AS risiko_score,
    CASE
        WHEN haeufigkeit_score * auswirkung_score >= 15 THEN 'KRITISCH'
        WHEN haeufigkeit_score * auswirkung_score >= 10 THEN 'HOCH'
        WHEN haeufigkeit_score * auswirkung_score >= 5 THEN 'MITTEL'
        ELSE 'NIEDRIG'
    END AS risiko_kategorie,
    CASE
        WHEN haeufigkeit_score * auswirkung_score >= 15 THEN 'ROT'
        WHEN haeufigkeit_score * auswirkung_score >= 10 THEN 'ORANGE'
        WHEN haeufigkeit_score * auswirkung_score >= 5 THEN 'GELB'
        ELSE 'GRUEN'
    END AS ampel_farbe,
    anzahl_ereignisse,
    gesamt_verlust,
    durchschnitt_verlust,
    max_verlust,
    CURRENT_TIMESTAMP AS refresh_timestamp
FROM risk_matrix
ORDER BY risiko_score DESC;

-- Index für Performance
CREATE UNIQUE INDEX IF NOT EXISTS idx_heatmap_unique
ON mv_operational_risk_heatmap(ereignis_typ, COALESCE(basel_kategorie, 'N/A'), COALESCE(geschaeftsbereich, 'N/A'));

-- ============================================================================
-- LOSS_DISTRIBUTION_BY_BUSINESS_LINE (BASEL Kategorien)
-- ============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_loss_distribution_business_line AS
SELECT
    EXTRACT(YEAR FROM re.meldedatum) AS jahr,
    DATE_TRUNC('quarter', re.meldedatum) AS quartal,
    gb.bereich_name AS geschaeftsbereich,
    gb.bereich_typ,
    bc.kategorie_code AS basel_code,
    bc.kategorie_name_de AS basel_kategorie,
    bc.level_1 AS basel_level_1,

    -- Aggregationen
    COUNT(*) AS anzahl_ereignisse,
    COUNT(CASE WHEN re.risiko_schwere = 'CRITICAL' THEN 1 END) AS kritische_ereignisse,

    -- Verlustmetriken
    SUM(re.verlust_betrag_eur) AS brutto_verlust,
    SUM(re.wiederherstellung_betrag) AS wiederherstellung,
    SUM(re.versicherungs_erstattung) AS versicherung,
    SUM(re.netto_verlust) AS netto_verlust,

    -- Verteilung
    AVG(re.verlust_betrag_eur) AS mean_verlust,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY re.verlust_betrag_eur) AS median_verlust,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY re.verlust_betrag_eur) AS p95_verlust,
    MAX(re.verlust_betrag_eur) AS max_verlust,

    -- YoY Vergleich vorbereiten
    LAG(SUM(re.verlust_betrag_eur)) OVER (
        PARTITION BY gb.bereich_name, bc.kategorie_code
        ORDER BY DATE_TRUNC('quarter', re.meldedatum)
    ) AS vorquartal_verlust,

    CURRENT_TIMESTAMP AS refresh_timestamp

FROM risiko_ereignisse re
LEFT JOIN geschaeftsbereiche gb ON re.geschaeftsbereich_id = gb.bereich_id
LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
WHERE re.verlust_betrag_eur > 0
  AND re.ist_near_miss = FALSE
GROUP BY
    EXTRACT(YEAR FROM re.meldedatum),
    DATE_TRUNC('quarter', re.meldedatum),
    gb.bereich_name,
    gb.bereich_typ,
    bc.kategorie_code,
    bc.kategorie_name_de,
    bc.level_1
ORDER BY jahr DESC, quartal DESC, brutto_verlust DESC;

CREATE INDEX IF NOT EXISTS idx_loss_dist_jahr ON mv_loss_distribution_business_line(jahr);
CREATE INDEX IF NOT EXISTS idx_loss_dist_bereich ON mv_loss_distribution_business_line(geschaeftsbereich);

-- ============================================================================
-- KRI_TREND_ANALYSIS (über Zeit mit Ampel)
-- ============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_kri_trend_analysis AS
WITH kri_with_history AS (
    SELECT
        kri.kri_id,
        kri.kri_referenz,
        kri.kri_name,
        kri.risiko_kategorie,
        kri.geschaeftsbereich,
        kri.owner_name,
        km.mess_datum,
        km.ist_wert,
        km.ziel_wert,
        km.ampel_status,
        km.trend,
        kri.toleranz_band_unten,
        kri.toleranz_band_oben,
        kri.kritischer_wert,

        -- Historische Werte
        LAG(km.ist_wert, 1) OVER w AS wert_minus_1,
        LAG(km.ist_wert, 3) OVER w AS wert_minus_3,
        LAG(km.ist_wert, 6) OVER w AS wert_minus_6,
        LAG(km.ist_wert, 12) OVER w AS wert_minus_12,

        -- Historische Ampeln
        LAG(km.ampel_status, 1) OVER w AS ampel_minus_1,
        LAG(km.ampel_status, 3) OVER w AS ampel_minus_3,

        ROW_NUMBER() OVER (PARTITION BY kri.kri_id ORDER BY km.mess_datum DESC) AS rn

    FROM key_risk_indicators kri
    JOIN kri_messwerte km ON kri.kri_id = km.kri_id
    WHERE kri.ist_aktiv = TRUE
    WINDOW w AS (PARTITION BY kri.kri_id ORDER BY km.mess_datum)
)
SELECT
    kri_id,
    kri_referenz,
    kri_name,
    risiko_kategorie,
    geschaeftsbereich,
    owner_name,
    mess_datum AS aktuelles_datum,
    ist_wert AS aktueller_wert,
    ziel_wert,
    ampel_status AS aktuelle_ampel,
    trend AS aktueller_trend,

    -- Schwellwerte
    toleranz_band_unten,
    toleranz_band_oben,
    kritischer_wert,

    -- Historische Werte
    wert_minus_1,
    wert_minus_3,
    wert_minus_6,
    wert_minus_12,

    -- Veränderungen
    CASE WHEN wert_minus_1 != 0 THEN
        ROUND((ist_wert - wert_minus_1) / ABS(wert_minus_1) * 100, 2)
    END AS aenderung_1m_prozent,
    CASE WHEN wert_minus_3 != 0 THEN
        ROUND((ist_wert - wert_minus_3) / ABS(wert_minus_3) * 100, 2)
    END AS aenderung_3m_prozent,
    CASE WHEN wert_minus_12 != 0 THEN
        ROUND((ist_wert - wert_minus_12) / ABS(wert_minus_12) * 100, 2)
    END AS aenderung_12m_prozent,

    -- Trend-Analyse
    CASE
        WHEN ampel_status = 'ROT' AND ampel_minus_1 = 'ROT' AND ampel_minus_3 = 'ROT' THEN 'PERSISTENT_ROT'
        WHEN ampel_status = 'ROT' AND ampel_minus_1 != 'ROT' THEN 'NEU_ROT'
        WHEN ampel_status = 'GELB' AND ampel_minus_1 = 'ROT' THEN 'VERBESSERUNG'
        WHEN ampel_status = 'GRUEN' AND ampel_minus_1 IN ('ROT', 'GELB') THEN 'NORMALISIERT'
        WHEN ampel_status = 'ROT' OR ampel_status = 'GELB' THEN 'UNTER_BEOBACHTUNG'
        ELSE 'STABIL'
    END AS trend_status,

    -- Early Warning
    CASE
        WHEN ampel_status = 'ROT' THEN TRUE
        WHEN trend = 'VERSCHLECHTERT' AND ampel_minus_1 = 'GELB' THEN TRUE
        WHEN ist_wert >= kritischer_wert THEN TRUE
        ELSE FALSE
    END AS early_warning,

    CURRENT_TIMESTAMP AS refresh_timestamp

FROM kri_with_history
WHERE rn = 1  -- Nur aktuellste Werte
ORDER BY
    CASE ampel_status WHEN 'ROT' THEN 1 WHEN 'GELB' THEN 2 ELSE 3 END,
    kri_name;

CREATE UNIQUE INDEX IF NOT EXISTS idx_kri_trend_unique ON mv_kri_trend_analysis(kri_id);
CREATE INDEX IF NOT EXISTS idx_kri_trend_ampel ON mv_kri_trend_analysis(aktuelle_ampel);

-- ============================================================================
-- COMPLIANCE_STATUS_BOARD (regulatorische Anforderungen)
-- ============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_compliance_status_board AS
SELECT
    cv.vorschrift_id,
    cv.vorschrift_referenz,
    cv.reg_werk,
    cv.reg_artikel,
    cv.anforderung_kurz,
    cv.deadline,
    cv.status,
    cv.erfuellungsgrad,
    cv.verantwortlicher_name,
    cv.abteilung,
    cv.risiko_bei_nichterfuellung,
    cv.potentielle_strafe,
    cv.letzte_pruefung,

    -- Deadline Status
    CASE
        WHEN cv.status = 'ERFUELLT' THEN 'ABGESCHLOSSEN'
        WHEN cv.status = 'NICHT_ANWENDBAR' THEN 'N/A'
        WHEN cv.deadline < CURRENT_DATE THEN 'ÜBERFÄLLIG'
        WHEN cv.deadline < CURRENT_DATE + INTERVAL '30 days' THEN 'KRITISCH'
        WHEN cv.deadline < CURRENT_DATE + INTERVAL '90 days' THEN 'AUFMERKSAMKEIT'
        ELSE 'IM_PLAN'
    END AS deadline_status,

    cv.deadline - CURRENT_DATE AS tage_bis_deadline,

    -- Ampelfarbe
    CASE
        WHEN cv.status = 'ERFUELLT' THEN 'GRUEN'
        WHEN cv.status = 'VERLETZT' THEN 'ROT'
        WHEN cv.deadline < CURRENT_DATE THEN 'ROT'
        WHEN cv.deadline < CURRENT_DATE + INTERVAL '30 days' THEN 'ORANGE'
        WHEN cv.deadline < CURRENT_DATE + INTERVAL '90 days' THEN 'GELB'
        ELSE 'GRUEN'
    END AS ampel_farbe,

    -- Priorität für Sortierung
    CASE
        WHEN cv.status = 'VERLETZT' THEN 1
        WHEN cv.deadline < CURRENT_DATE THEN 2
        WHEN cv.deadline < CURRENT_DATE + INTERVAL '30 days' THEN 3
        WHEN cv.deadline < CURRENT_DATE + INTERVAL '90 days' THEN 4
        ELSE 5
    END AS prioritaet,

    -- Verknüpfte Kontrollen
    COALESCE(ctrl.anzahl_kontrollen, 0) AS anzahl_verknuepfte_kontrollen,
    COALESCE(ctrl.avg_effektivitaet, 0) AS durchschnitt_kontroll_effektivitaet,

    CURRENT_TIMESTAMP AS refresh_timestamp

FROM compliance_vorschriften cv
LEFT JOIN (
    SELECT
        vkm.vorschrift_id,
        COUNT(*) AS anzahl_kontrollen,
        AVG(km.effektivitaets_score) AS avg_effektivitaet
    FROM vorschrift_kontrolle_mapping vkm
    JOIN kontrolle_mechanismen km ON vkm.kontrolle_id = km.kontrolle_id
    GROUP BY vkm.vorschrift_id
) ctrl ON cv.vorschrift_id = ctrl.vorschrift_id
WHERE cv.ist_aktiv = TRUE
ORDER BY prioritaet, cv.deadline;

CREATE UNIQUE INDEX IF NOT EXISTS idx_compliance_board_unique ON mv_compliance_status_board(vorschrift_id);
CREATE INDEX IF NOT EXISTS idx_compliance_board_werk ON mv_compliance_status_board(reg_werk);
CREATE INDEX IF NOT EXISTS idx_compliance_board_status ON mv_compliance_status_board(status);

-- ============================================================================
-- EXECUTIVE SUMMARY VIEW
-- ============================================================================

CREATE OR REPLACE VIEW v_executive_summary AS
SELECT
    -- Zeitraum
    CURRENT_DATE AS stichtag,
    DATE_TRUNC('year', CURRENT_DATE) AS jahr_beginn,

    -- Verlust-KPIs (YTD)
    (SELECT COUNT(*) FROM risiko_ereignisse
     WHERE meldedatum >= DATE_TRUNC('year', CURRENT_DATE)
       AND ist_near_miss = FALSE) AS ytd_anzahl_ereignisse,

    (SELECT SUM(verlust_betrag_eur) FROM risiko_ereignisse
     WHERE meldedatum >= DATE_TRUNC('year', CURRENT_DATE)
       AND ist_near_miss = FALSE) AS ytd_gesamt_verlust,

    (SELECT MAX(verlust_betrag_eur) FROM risiko_ereignisse
     WHERE meldedatum >= DATE_TRUNC('year', CURRENT_DATE)) AS ytd_max_einzelverlust,

    -- Risk Appetite Status
    (SELECT ROUND(SUM(re.verlust_betrag_eur) / NULLIF(ra.max_jahresverlust, 0) * 100, 2)
     FROM risiko_ereignisse re, risk_appetite ra
     WHERE ra.ist_aktiv = TRUE
       AND re.meldedatum >= DATE_TRUNC('year', CURRENT_DATE)
       AND re.verlust_betrag_eur > 0) AS risk_appetite_auslastung_pct,

    -- KRI Status
    (SELECT COUNT(*) FROM mv_kri_trend_analysis WHERE aktuelle_ampel = 'ROT') AS kris_rot,
    (SELECT COUNT(*) FROM mv_kri_trend_analysis WHERE aktuelle_ampel = 'GELB') AS kris_gelb,
    (SELECT COUNT(*) FROM mv_kri_trend_analysis WHERE aktuelle_ampel = 'GRUEN') AS kris_gruen,

    -- Compliance Status
    (SELECT COUNT(*) FROM compliance_vorschriften WHERE status = 'VERLETZT' AND ist_aktiv = TRUE) AS compliance_verletzt,
    (SELECT COUNT(*) FROM compliance_vorschriften WHERE status = 'OFFEN' AND ist_aktiv = TRUE) AS compliance_offen,
    (SELECT COUNT(*) FROM compliance_vorschriften
     WHERE deadline < CURRENT_DATE AND status NOT IN ('ERFUELLT', 'NICHT_ANWENDBAR') AND ist_aktiv = TRUE) AS compliance_ueberfaellig,

    -- Kontrollen Status
    (SELECT COUNT(*) FROM kontrolle_mechanismen
     WHERE naechster_test < CURRENT_DATE AND ist_aktiv = TRUE) AS kontrollen_test_ueberfaellig,
    (SELECT AVG(effektivitaets_score) FROM kontrolle_mechanismen WHERE ist_aktiv = TRUE) AS durchschnitt_kontroll_effektivitaet,

    -- Offene Incidents
    (SELECT COUNT(*) FROM incident_response WHERE abschluss_datum IS NULL) AS offene_incidents,

    -- Trend (Vergleich mit Vorjahr)
    (SELECT SUM(verlust_betrag_eur) FROM risiko_ereignisse
     WHERE meldedatum >= DATE_TRUNC('year', CURRENT_DATE) - INTERVAL '1 year'
       AND meldedatum < DATE_TRUNC('year', CURRENT_DATE)) AS vorjahr_verlust;

-- ============================================================================
-- REFRESH FUNCTION für Materialized Views
-- ============================================================================

CREATE OR REPLACE FUNCTION refresh_all_dashboard_views()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_operational_risk_heatmap;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_loss_distribution_business_line;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_kri_trend_analysis;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_compliance_status_board;
END;
$$ LANGUAGE plpgsql;

-- Kommentar für Job-Scheduling
COMMENT ON FUNCTION refresh_all_dashboard_views() IS
'Diese Funktion sollte täglich via pg_cron oder externem Scheduler ausgeführt werden:
SELECT cron.schedule(''refresh_dashboards'', ''0 6 * * *'', ''SELECT refresh_all_dashboard_views()'');';
