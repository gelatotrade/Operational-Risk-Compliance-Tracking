-- ============================================================================
-- OPERATIONAL RISK & COMPLIANCE TRACKING SYSTEM
-- Analyse-Views und Dashboard-Materialized Views
-- ============================================================================

-- ============================================================================
-- LOSS DISTRIBUTION ANALYSIS
-- ============================================================================

-- View: Verlustverteilung nach Frequenz und Schwere
CREATE OR REPLACE VIEW v_loss_distribution AS
SELECT
    DATE_TRUNC('month', meldedatum) AS periode,
    EXTRACT(YEAR FROM meldedatum) AS jahr,
    EXTRACT(MONTH FROM meldedatum) AS monat,
    ereignis_typ,
    geschaeftsbereich,
    bc.kategorie_name_de AS basel_kategorie,
    COUNT(*) AS anzahl_ereignisse,
    SUM(verlust_betrag_eur) AS gesamt_verlust,
    AVG(verlust_betrag_eur) AS durchschnitt_verlust,
    MIN(verlust_betrag_eur) AS min_verlust,
    MAX(verlust_betrag_eur) AS max_verlust,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY verlust_betrag_eur) AS median_verlust,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY verlust_betrag_eur) AS p95_verlust,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY verlust_betrag_eur) AS p99_verlust,
    STDDEV(verlust_betrag_eur) AS stddev_verlust
FROM risiko_ereignisse re
LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
WHERE verlust_betrag_eur > 0
  AND ist_near_miss = FALSE
GROUP BY
    DATE_TRUNC('month', meldedatum),
    EXTRACT(YEAR FROM meldedatum),
    EXTRACT(MONTH FROM meldedatum),
    ereignis_typ,
    geschaeftsbereich,
    bc.kategorie_name_de;

-- View: Top 10 Verlustereignisse der letzten 5 Jahre
CREATE OR REPLACE VIEW v_top_losses_5y AS
SELECT
    re.ereignis_id,
    re.ereignis_referenz,
    re.meldedatum,
    re.ereignis_typ,
    re.geschaeftsbereich,
    bc.kategorie_name_de AS basel_kategorie,
    re.verlust_betrag_eur,
    re.wiederherstellung_betrag,
    re.netto_verlust,
    re.root_cause,
    re.corrective_actions,
    re.status,
    RANK() OVER (ORDER BY re.verlust_betrag_eur DESC) AS rang
FROM risiko_ereignisse re
LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
WHERE re.meldedatum >= CURRENT_DATE - INTERVAL '5 years'
  AND re.verlust_betrag_eur > 0
  AND re.ist_near_miss = FALSE
ORDER BY re.verlust_betrag_eur DESC
LIMIT 10;

-- View: Interner vs. Externer Betrug Vergleich
CREATE OR REPLACE VIEW v_internal_vs_external_fraud AS
SELECT
    EXTRACT(YEAR FROM meldedatum) AS jahr,
    CASE
        WHEN bc.kategorie_code = 'IF' THEN 'Interner Betrug'
        WHEN bc.kategorie_code = 'EF' THEN 'Externer Betrug'
        ELSE 'Andere'
    END AS betrugs_typ,
    COUNT(*) AS anzahl_faelle,
    SUM(verlust_betrag_eur) AS gesamt_verlust,
    AVG(verlust_betrag_eur) AS durchschnitt_verlust,
    SUM(wiederherstellung_betrag) AS gesamt_wiederherstellung,
    SUM(versicherungs_erstattung) AS gesamt_versicherung
FROM risiko_ereignisse re
LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
WHERE bc.kategorie_code IN ('IF', 'EF')
GROUP BY
    EXTRACT(YEAR FROM meldedatum),
    CASE
        WHEN bc.kategorie_code = 'IF' THEN 'Interner Betrug'
        WHEN bc.kategorie_code = 'EF' THEN 'Externer Betrug'
        ELSE 'Andere'
    END
ORDER BY jahr, betrugs_typ;

-- ============================================================================
-- CONTROL EFFECTIVENESS ANALYSIS
-- ============================================================================

-- View: KRI vs. Actual Losses Korrelation
CREATE OR REPLACE VIEW v_kri_loss_correlation AS
WITH monthly_kri AS (
    SELECT
        DATE_TRUNC('month', mess_datum) AS periode,
        kri.kri_name,
        kri.risiko_kategorie,
        AVG(km.ist_wert) AS avg_kri_wert,
        MAX(CASE WHEN km.ampel_status = 'ROT' THEN 1 ELSE 0 END) AS hat_rot_status
    FROM kri_messwerte km
    JOIN key_risk_indicators kri ON km.kri_id = kri.kri_id
    GROUP BY DATE_TRUNC('month', mess_datum), kri.kri_name, kri.risiko_kategorie
),
monthly_losses AS (
    SELECT
        DATE_TRUNC('month', meldedatum) AS periode,
        bc.kategorie_name_de AS risiko_kategorie,
        SUM(verlust_betrag_eur) AS gesamt_verlust,
        COUNT(*) AS anzahl_ereignisse
    FROM risiko_ereignisse re
    LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
    WHERE verlust_betrag_eur > 0
    GROUP BY DATE_TRUNC('month', meldedatum), bc.kategorie_name_de
)
SELECT
    mk.periode,
    mk.kri_name,
    mk.risiko_kategorie,
    mk.avg_kri_wert,
    mk.hat_rot_status,
    COALESCE(ml.gesamt_verlust, 0) AS gesamt_verlust,
    COALESCE(ml.anzahl_ereignisse, 0) AS anzahl_ereignisse
FROM monthly_kri mk
LEFT JOIN monthly_losses ml ON mk.periode = ml.periode
ORDER BY mk.periode DESC, mk.kri_name;

-- View: Control Gap Analysis (Soll-Ist)
CREATE OR REPLACE VIEW v_control_gap_analysis AS
SELECT
    km.kontrolle_id,
    km.kontrolle_referenz,
    km.kontrolle_name,
    km.kontrolle_typ,
    km.abteilung,
    km.effektivitaets_score AS ist_effektivitaet,
    90.0 AS soll_effektivitaet,  -- Standardziel 90%
    90.0 - COALESCE(km.effektivitaets_score, 0) AS gap,
    km.maturity_level,
    5 AS ziel_maturity,
    5 - COALESCE(km.maturity_level, 1) AS maturity_gap,
    km.test_ergebnis,
    km.letzter_test,
    km.naechster_test,
    CASE
        WHEN km.naechster_test < CURRENT_DATE THEN 'ÜBERFÄLLIG'
        WHEN km.naechster_test < CURRENT_DATE + INTERVAL '30 days' THEN 'BALD_FÄLLIG'
        ELSE 'OK'
    END AS test_status,
    COALESCE(fehler.anzahl_versagen, 0) AS anzahl_versagen
FROM kontrolle_mechanismen km
LEFT JOIN (
    SELECT kontrolle_id, COUNT(*) AS anzahl_versagen
    FROM ereignis_kontrolle_mapping
    GROUP BY kontrolle_id
) fehler ON km.kontrolle_id = fehler.kontrolle_id
WHERE km.ist_aktiv = TRUE
ORDER BY gap DESC;

-- View: Cost of Controls vs. Risk Reduction
CREATE OR REPLACE VIEW v_control_cost_benefit AS
SELECT
    km.kontrolle_id,
    km.kontrolle_referenz,
    km.kontrolle_name,
    km.kontrolle_typ,
    km.jaehrliche_kosten,
    km.risiko_reduktion_prozent,
    km.effektivitaets_score,
    -- Geschätzter Wert der Risikoreduktion (basierend auf historischen Verlusten)
    COALESCE(
        (SELECT SUM(verlust_betrag_eur) FROM risiko_ereignisse WHERE meldedatum >= CURRENT_DATE - INTERVAL '1 year')
        * km.risiko_reduktion_prozent / 100,
        0
    ) AS geschaetzter_nutzen,
    -- ROI Berechnung
    CASE
        WHEN km.jaehrliche_kosten > 0 THEN
            (COALESCE(
                (SELECT SUM(verlust_betrag_eur) FROM risiko_ereignisse WHERE meldedatum >= CURRENT_DATE - INTERVAL '1 year')
                * km.risiko_reduktion_prozent / 100,
                0
            ) - km.jaehrliche_kosten) / km.jaehrliche_kosten * 100
        ELSE NULL
    END AS roi_prozent
FROM kontrolle_mechanismen km
WHERE km.ist_aktiv = TRUE
  AND km.jaehrliche_kosten IS NOT NULL
ORDER BY roi_prozent DESC NULLS LAST;

-- ============================================================================
-- COMPLIANCE MONITORING
-- ============================================================================

-- View: Regulatory Deadline Tracking
CREATE OR REPLACE VIEW v_regulatory_deadlines AS
SELECT
    vorschrift_id,
    vorschrift_referenz,
    reg_werk,
    reg_artikel,
    anforderung_kurz,
    deadline,
    status,
    erfuellungsgrad,
    verantwortlicher_name,
    abteilung,
    CASE
        WHEN deadline < CURRENT_DATE AND status != 'ERFUELLT' THEN 'ÜBERSCHRITTEN'
        WHEN deadline < CURRENT_DATE + INTERVAL '30 days' AND status != 'ERFUELLT' THEN 'KRITISCH'
        WHEN deadline < CURRENT_DATE + INTERVAL '90 days' AND status != 'ERFUELLT' THEN 'WARNUNG'
        ELSE 'OK'
    END AS dringlichkeit,
    deadline - CURRENT_DATE AS tage_bis_deadline,
    risiko_bei_nichterfuellung,
    potentielle_strafe
FROM compliance_vorschriften
WHERE ist_aktiv = TRUE
ORDER BY
    CASE
        WHEN deadline < CURRENT_DATE AND status != 'ERFUELLT' THEN 1
        WHEN deadline < CURRENT_DATE + INTERVAL '30 days' AND status != 'ERFUELLT' THEN 2
        WHEN deadline < CURRENT_DATE + INTERVAL '90 days' AND status != 'ERFUELLT' THEN 3
        ELSE 4
    END,
    deadline;

-- View: Open Findings by Department
CREATE OR REPLACE VIEW v_open_findings_by_department AS
SELECT
    abteilung,
    reg_werk,
    COUNT(*) AS anzahl_offen,
    COUNT(CASE WHEN status = 'VERLETZT' THEN 1 END) AS anzahl_verletzt,
    COUNT(CASE WHEN deadline < CURRENT_DATE AND status NOT IN ('ERFUELLT', 'NICHT_ANWENDBAR') THEN 1 END) AS anzahl_ueberfaellig,
    SUM(potentielle_strafe) AS potentielle_strafe_gesamt,
    MIN(deadline) AS naechste_deadline,
    ARRAY_AGG(DISTINCT vorschrift_referenz) FILTER (WHERE status = 'VERLETZT') AS verletzte_vorschriften
FROM compliance_vorschriften
WHERE status NOT IN ('ERFUELLT', 'NICHT_ANWENDBAR')
  AND ist_aktiv = TRUE
GROUP BY abteilung, reg_werk
ORDER BY anzahl_verletzt DESC, anzahl_ueberfaellig DESC;

-- View: Repeat Violations Analysis
CREATE OR REPLACE VIEW v_repeat_violations AS
WITH violation_history AS (
    SELECT
        reg_werk,
        abteilung,
        vorschrift_referenz,
        COUNT(*) OVER (PARTITION BY reg_werk, abteilung) AS violations_in_department,
        ROW_NUMBER() OVER (PARTITION BY reg_werk, abteilung ORDER BY deadline) AS violation_number
    FROM compliance_vorschriften
    WHERE status = 'VERLETZT'
)
SELECT
    reg_werk,
    abteilung,
    violations_in_department AS anzahl_verstoesse,
    ARRAY_AGG(vorschrift_referenz ORDER BY violation_number) AS betroffene_vorschriften,
    CASE
        WHEN violations_in_department >= 3 THEN 'KRITISCH_WIEDERHOLEND'
        WHEN violations_in_department >= 2 THEN 'WIEDERHOLEND'
        ELSE 'EINZELFALL'
    END AS wiederholungs_status
FROM violation_history
GROUP BY reg_werk, abteilung, violations_in_department
HAVING violations_in_department > 1
ORDER BY violations_in_department DESC;

-- ============================================================================
-- RISK APPETITE MONITORING
-- ============================================================================

-- View: Actual Losses vs. Risk Appetite
CREATE OR REPLACE VIEW v_losses_vs_risk_appetite AS
SELECT
    EXTRACT(YEAR FROM re.meldedatum) AS jahr,
    DATE_TRUNC('month', re.meldedatum) AS periode,
    SUM(re.verlust_betrag_eur) AS kumulierter_verlust,
    MAX(re.verlust_betrag_eur) AS max_einzelverlust,
    COUNT(*) AS anzahl_ereignisse,
    ra.max_jahresverlust AS risk_appetite_limit,
    ra.max_einzelverlust AS max_einzelverlust_limit,
    ROUND(SUM(re.verlust_betrag_eur) / NULLIF(ra.max_jahresverlust, 0) * 100, 2) AS auslastung_prozent,
    CASE
        WHEN SUM(re.verlust_betrag_eur) > ra.max_jahresverlust THEN 'ÜBERSCHRITTEN'
        WHEN SUM(re.verlust_betrag_eur) > ra.max_jahresverlust * 0.8 THEN 'KRITISCH'
        WHEN SUM(re.verlust_betrag_eur) > ra.max_jahresverlust * 0.5 THEN 'WARNUNG'
        ELSE 'IM_RAHMEN'
    END AS status
FROM risiko_ereignisse re
CROSS JOIN risk_appetite ra
WHERE ra.ist_aktiv = TRUE
  AND re.verlust_betrag_eur > 0
  AND re.ist_near_miss = FALSE
GROUP BY
    EXTRACT(YEAR FROM re.meldedatum),
    DATE_TRUNC('month', re.meldedatum),
    ra.max_jahresverlust,
    ra.max_einzelverlust
ORDER BY periode;

-- View: Early Warning Indicators Trending
CREATE OR REPLACE VIEW v_early_warning_trend AS
SELECT
    kri.kri_id,
    kri.kri_referenz,
    kri.kri_name,
    kri.risiko_kategorie,
    km.mess_datum,
    km.ist_wert,
    km.ziel_wert,
    km.ampel_status,
    km.trend,
    LAG(km.ampel_status, 1) OVER (PARTITION BY kri.kri_id ORDER BY km.mess_datum) AS vorherige_ampel,
    LAG(km.ampel_status, 3) OVER (PARTITION BY kri.kri_id ORDER BY km.mess_datum) AS ampel_vor_3_perioden,
    -- Verschlechterungstrend erkennen
    CASE
        WHEN km.ampel_status = 'ROT' AND LAG(km.ampel_status, 1) OVER (PARTITION BY kri.kri_id ORDER BY km.mess_datum) = 'ROT' THEN TRUE
        WHEN km.trend = 'VERSCHLECHTERT' AND LAG(km.trend, 1) OVER (PARTITION BY kri.kri_id ORDER BY km.mess_datum) = 'VERSCHLECHTERT' THEN TRUE
        ELSE FALSE
    END AS early_warning_aktiv
FROM key_risk_indicators kri
JOIN kri_messwerte km ON kri.kri_id = km.kri_id
WHERE kri.ist_aktiv = TRUE
  AND km.mess_datum >= CURRENT_DATE - INTERVAL '12 months'
ORDER BY kri.kri_id, km.mess_datum DESC;

-- ============================================================================
-- CAPITAL CALCULATION (AMA) VIEWS
-- ============================================================================

-- View: Loss Distribution Approach (LDA) Basis
CREATE OR REPLACE VIEW v_lda_basis AS
SELECT
    bc.kategorie_code AS basel_kategorie,
    bc.kategorie_name_de,
    gb.bereich_code AS geschaeftsbereich,
    EXTRACT(YEAR FROM re.meldedatum) AS jahr,

    -- Frequency Distribution
    COUNT(*) AS anzahl_ereignisse,

    -- Severity Distribution
    SUM(re.verlust_betrag_eur) AS gesamt_verlust,
    AVG(re.verlust_betrag_eur) AS mean_verlust,
    STDDEV(re.verlust_betrag_eur) AS stddev_verlust,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY re.verlust_betrag_eur) AS median_verlust,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY re.verlust_betrag_eur) AS p75_verlust,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY re.verlust_betrag_eur) AS p95_verlust,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY re.verlust_betrag_eur) AS p99_verlust,
    PERCENTILE_CONT(0.999) WITHIN GROUP (ORDER BY re.verlust_betrag_eur) AS p999_verlust,

    -- Für VaR/ES Berechnung
    MAX(re.verlust_betrag_eur) AS max_verlust

FROM risiko_ereignisse re
LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
LEFT JOIN geschaeftsbereiche gb ON re.geschaeftsbereich_id = gb.bereich_id
WHERE re.verlust_betrag_eur > 0
  AND re.ist_near_miss = FALSE
GROUP BY
    bc.kategorie_code,
    bc.kategorie_name_de,
    gb.bereich_code,
    EXTRACT(YEAR FROM re.meldedatum);

-- View: Scenario-Based Capital Charge
CREATE OR REPLACE VIEW v_scenario_capital AS
SELECT
    sa.scenario_id,
    sa.scenario_referenz,
    sa.scenario_name,
    sa.risiko_kategorie,
    sa.geschaeftsbereich,
    sa.wahrscheinlichkeit,
    sa.auswirkung,
    sa.erwarteter_verlust,
    sa.value_at_risk,
    sa.residual_risiko_nach_controls,
    sa.versicherungsschutz,
    sa.residual_nach_versicherung,
    -- Capital Charge Berechnung
    GREATEST(sa.residual_nach_versicherung, 0) AS capital_charge,
    -- Gewichtung nach Validierungsstatus
    CASE
        WHEN sa.expertenvalidierung = TRUE THEN 1.0
        ELSE 1.2  -- 20% Aufschlag für nicht-validierte Szenarien
    END AS validierungs_faktor,
    GREATEST(sa.residual_nach_versicherung, 0) *
    CASE
        WHEN sa.expertenvalidierung = TRUE THEN 1.0
        ELSE 1.2
    END AS adjusted_capital_charge
FROM scenario_analysis sa
WHERE sa.status = 'AKTIV'
  AND sa.gueltig_bis >= CURRENT_DATE OR sa.gueltig_bis IS NULL;

-- View: Insurance Mitigation Recognition
CREATE OR REPLACE VIEW v_insurance_mitigation AS
SELECT
    EXTRACT(YEAR FROM re.meldedatum) AS jahr,
    bc.kategorie_name_de AS risiko_kategorie,
    SUM(re.verlust_betrag_eur) AS brutto_verlust,
    SUM(re.versicherungs_erstattung) AS versicherungs_erstattung,
    SUM(re.verlust_betrag_eur) - SUM(re.versicherungs_erstattung) AS netto_nach_versicherung,
    ROUND(SUM(re.versicherungs_erstattung) / NULLIF(SUM(re.verlust_betrag_eur), 0) * 100, 2) AS erstattungs_quote,
    -- AMA erlaubt max 20% Versicherungsanrechnung
    LEAST(
        SUM(re.versicherungs_erstattung),
        SUM(re.verlust_betrag_eur) * 0.2
    ) AS anerkannte_versicherung,
    SUM(re.verlust_betrag_eur) - LEAST(
        SUM(re.versicherungs_erstattung),
        SUM(re.verlust_betrag_eur) * 0.2
    ) AS regulatorischer_verlust
FROM risiko_ereignisse re
LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
WHERE re.verlust_betrag_eur > 0
GROUP BY
    EXTRACT(YEAR FROM re.meldedatum),
    bc.kategorie_name_de
ORDER BY jahr, risiko_kategorie;
