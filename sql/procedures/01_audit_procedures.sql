-- ============================================================================
-- OPERATIONAL RISK & COMPLIANCE TRACKING SYSTEM
-- Stored Procedures für Audit Trail und Data Quality
-- ============================================================================

-- ============================================================================
-- AUDIT TRAIL TRIGGER FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION fn_audit_trail()
RETURNS TRIGGER AS $$
DECLARE
    alte_werte JSONB;
    neue_werte JSONB;
    geaenderte_felder TEXT[];
    pk_column TEXT;
    pk_value INTEGER;
BEGIN
    -- Primary Key ermitteln (Annahme: erstes Feld ist PK)
    pk_column := TG_ARGV[0];

    IF TG_OP = 'DELETE' THEN
        alte_werte := to_jsonb(OLD);
        neue_werte := NULL;
        EXECUTE format('SELECT ($1).%I', pk_column) INTO pk_value USING OLD;

        INSERT INTO audit_trail (
            tabellen_name, datensatz_id, aktion,
            alte_werte, neue_werte,
            benutzer_name, aenderung_zeitpunkt
        ) VALUES (
            TG_TABLE_NAME, pk_value, 'DELETE',
            alte_werte, neue_werte,
            current_user, CURRENT_TIMESTAMP
        );
        RETURN OLD;

    ELSIF TG_OP = 'UPDATE' THEN
        alte_werte := to_jsonb(OLD);
        neue_werte := to_jsonb(NEW);
        EXECUTE format('SELECT ($1).%I', pk_column) INTO pk_value USING NEW;

        -- Geänderte Felder ermitteln
        SELECT array_agg(key) INTO geaenderte_felder
        FROM jsonb_each(alte_werte) AS a(key, value)
        WHERE a.value IS DISTINCT FROM neue_werte->a.key;

        -- Nur bei tatsächlichen Änderungen loggen
        IF geaenderte_felder IS NOT NULL AND array_length(geaenderte_felder, 1) > 0 THEN
            INSERT INTO audit_trail (
                tabellen_name, datensatz_id, aktion,
                alte_werte, neue_werte, geaenderte_felder,
                benutzer_name, aenderung_zeitpunkt
            ) VALUES (
                TG_TABLE_NAME, pk_value, 'UPDATE',
                alte_werte, neue_werte, geaenderte_felder,
                current_user, CURRENT_TIMESTAMP
            );
        END IF;
        RETURN NEW;

    ELSIF TG_OP = 'INSERT' THEN
        alte_werte := NULL;
        neue_werte := to_jsonb(NEW);
        EXECUTE format('SELECT ($1).%I', pk_column) INTO pk_value USING NEW;

        INSERT INTO audit_trail (
            tabellen_name, datensatz_id, aktion,
            alte_werte, neue_werte,
            benutzer_name, aenderung_zeitpunkt
        ) VALUES (
            TG_TABLE_NAME, pk_value, 'INSERT',
            alte_werte, neue_werte,
            current_user, CURRENT_TIMESTAMP
        );
        RETURN NEW;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Trigger für alle relevanten Tabellen erstellen
CREATE OR REPLACE FUNCTION create_audit_triggers()
RETURNS void AS $$
DECLARE
    tbl RECORD;
    trigger_name TEXT;
    pk_column TEXT;
BEGIN
    FOR tbl IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename IN (
              'risiko_ereignisse',
              'kontrolle_mechanismen',
              'compliance_vorschriften',
              'incident_response',
              'key_risk_indicators',
              'kri_messwerte',
              'scenario_analysis',
              'risk_appetite'
          )
    LOOP
        -- PK-Spalte ermitteln (Convention: tabelle_id oder id)
        pk_column := tbl.tablename || '_id';
        IF tbl.tablename = 'risiko_ereignisse' THEN pk_column := 'ereignis_id';
        ELSIF tbl.tablename = 'kontrolle_mechanismen' THEN pk_column := 'kontrolle_id';
        ELSIF tbl.tablename = 'compliance_vorschriften' THEN pk_column := 'vorschrift_id';
        ELSIF tbl.tablename = 'incident_response' THEN pk_column := 'response_id';
        ELSIF tbl.tablename = 'key_risk_indicators' THEN pk_column := 'kri_id';
        ELSIF tbl.tablename = 'kri_messwerte' THEN pk_column := 'messwert_id';
        ELSIF tbl.tablename = 'scenario_analysis' THEN pk_column := 'scenario_id';
        ELSIF tbl.tablename = 'risk_appetite' THEN pk_column := 'appetite_id';
        END IF;

        trigger_name := 'trg_audit_' || tbl.tablename;

        -- Existierenden Trigger löschen
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', trigger_name, tbl.tablename);

        -- Neuen Trigger erstellen
        EXECUTE format(
            'CREATE TRIGGER %I
             AFTER INSERT OR UPDATE OR DELETE ON %I
             FOR EACH ROW EXECUTE FUNCTION fn_audit_trail(%L)',
            trigger_name, tbl.tablename, pk_column
        );

        RAISE NOTICE 'Created audit trigger for table: %', tbl.tablename;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- DATA QUALITY CHECKS
-- ============================================================================

CREATE OR REPLACE FUNCTION fn_data_quality_check()
RETURNS TABLE (
    check_name TEXT,
    check_status TEXT,
    betroffene_datensaetze INTEGER,
    details TEXT
) AS $$
BEGIN
    -- Check 1: Risiko-Ereignisse ohne Basel-Kategorie
    RETURN QUERY
    SELECT
        'Ereignisse ohne Basel-Kategorie'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'WARNUNG' ELSE 'OK' END::TEXT,
        COUNT(*)::INTEGER,
        'Risiko-Ereignisse sollten einer Basel-Kategorie zugeordnet sein'::TEXT
    FROM risiko_ereignisse
    WHERE basel_kategorie_id IS NULL
      AND status != 'ARCHIVIERT';

    -- Check 2: KRIs ohne aktuelle Messwerte (>30 Tage)
    RETURN QUERY
    SELECT
        'KRIs ohne aktuelle Messwerte'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'WARNUNG' ELSE 'OK' END::TEXT,
        COUNT(*)::INTEGER,
        'KRIs sollten regelmäßig gemessen werden'::TEXT
    FROM key_risk_indicators kri
    WHERE ist_aktiv = TRUE
      AND NOT EXISTS (
          SELECT 1 FROM kri_messwerte km
          WHERE km.kri_id = kri.kri_id
            AND km.mess_datum >= CURRENT_DATE - INTERVAL '30 days'
      );

    -- Check 3: Kontrollen mit überfälligen Tests
    RETURN QUERY
    SELECT
        'Kontrollen mit überfälligen Tests'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'KRITISCH' ELSE 'OK' END::TEXT,
        COUNT(*)::INTEGER,
        'Kontrollen müssen regelmäßig getestet werden'::TEXT
    FROM kontrolle_mechanismen
    WHERE ist_aktiv = TRUE
      AND naechster_test < CURRENT_DATE;

    -- Check 4: Compliance-Anforderungen ohne Verantwortlichen
    RETURN QUERY
    SELECT
        'Compliance ohne Verantwortlichen'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'WARNUNG' ELSE 'OK' END::TEXT,
        COUNT(*)::INTEGER,
        'Jede Compliance-Anforderung braucht einen Verantwortlichen'::TEXT
    FROM compliance_vorschriften
    WHERE ist_aktiv = TRUE
      AND verantwortlicher_id IS NULL
      AND verantwortlicher_name IS NULL;

    -- Check 5: Ereignisse mit inkonsistenten Beträgen
    RETURN QUERY
    SELECT
        'Ereignisse mit inkonsistenten Beträgen'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'FEHLER' ELSE 'OK' END::TEXT,
        COUNT(*)::INTEGER,
        'Wiederherstellung + Versicherung > Verlust'::TEXT
    FROM risiko_ereignisse
    WHERE (wiederherstellung_betrag + versicherungs_erstattung) > verlust_betrag
      AND verlust_betrag > 0;

    -- Check 6: Szenarien ohne Validierung
    RETURN QUERY
    SELECT
        'Szenarien ohne Expertenvalidierung'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'INFO' ELSE 'OK' END::TEXT,
        COUNT(*)::INTEGER,
        'Szenarien sollten von Experten validiert werden'::TEXT
    FROM scenario_analysis
    WHERE status = 'AKTIV'
      AND expertenvalidierung = FALSE;

    -- Check 7: Duplikate in Ereignis-Referenzen
    RETURN QUERY
    SELECT
        'Duplikate in Ereignis-Referenzen'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'FEHLER' ELSE 'OK' END::TEXT,
        COUNT(*)::INTEGER,
        'Ereignis-Referenzen müssen eindeutig sein'::TEXT
    FROM (
        SELECT ereignis_referenz, COUNT(*) AS cnt
        FROM risiko_ereignisse
        WHERE ereignis_referenz IS NOT NULL
        GROUP BY ereignis_referenz
        HAVING COUNT(*) > 1
    ) dups;

    -- Check 8: Incidents ohne Response
    RETURN QUERY
    SELECT
        'Ereignisse ohne Incident Response'::TEXT,
        CASE WHEN COUNT(*) > 0 THEN 'WARNUNG' ELSE 'OK' END::TEXT,
        COUNT(*)::INTEGER,
        'Kritische Ereignisse sollten eine Incident Response haben'::TEXT
    FROM risiko_ereignisse re
    WHERE re.risiko_schwere IN ('HIGH', 'CRITICAL')
      AND re.status NOT IN ('ARCHIVIERT', 'ABGESCHLOSSEN')
      AND NOT EXISTS (
          SELECT 1 FROM incident_response ir
          WHERE ir.ereignis_id = re.ereignis_id
      );

END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- AUTOMATISCHE REFERENZNUMMER-GENERIERUNG
-- ============================================================================

CREATE OR REPLACE FUNCTION fn_generate_reference(
    prefix TEXT,
    table_name TEXT
)
RETURNS TEXT AS $$
DECLARE
    year_part TEXT;
    seq_num INTEGER;
    new_ref TEXT;
BEGIN
    year_part := TO_CHAR(CURRENT_DATE, 'YYYY');

    -- Nächste Sequenznummer für dieses Jahr ermitteln
    EXECUTE format(
        'SELECT COALESCE(MAX(
            CAST(SUBSTRING(%I FROM ''%s-'' || %L || ''-(\d+)$'') AS INTEGER)
        ), 0) + 1
        FROM %I
        WHERE %I LIKE %L || ''-'' || %L || ''-%%''',
        CASE table_name
            WHEN 'risiko_ereignisse' THEN 'ereignis_referenz'
            WHEN 'kontrolle_mechanismen' THEN 'kontrolle_referenz'
            WHEN 'compliance_vorschriften' THEN 'vorschrift_referenz'
            WHEN 'key_risk_indicators' THEN 'kri_referenz'
            WHEN 'scenario_analysis' THEN 'scenario_referenz'
        END,
        prefix, year_part,
        table_name,
        CASE table_name
            WHEN 'risiko_ereignisse' THEN 'ereignis_referenz'
            WHEN 'kontrolle_mechanismen' THEN 'kontrolle_referenz'
            WHEN 'compliance_vorschriften' THEN 'vorschrift_referenz'
            WHEN 'key_risk_indicators' THEN 'kri_referenz'
            WHEN 'scenario_analysis' THEN 'scenario_referenz'
        END,
        prefix, year_part
    ) INTO seq_num;

    new_ref := prefix || '-' || year_part || '-' || LPAD(seq_num::TEXT, 5, '0');

    RETURN new_ref;
END;
$$ LANGUAGE plpgsql;

-- Trigger für automatische Referenz bei Ereignissen
CREATE OR REPLACE FUNCTION fn_set_ereignis_referenz()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.ereignis_referenz IS NULL THEN
        NEW.ereignis_referenz := fn_generate_reference('ORE', 'risiko_ereignisse');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_set_ereignis_referenz ON risiko_ereignisse;
CREATE TRIGGER trg_set_ereignis_referenz
    BEFORE INSERT ON risiko_ereignisse
    FOR EACH ROW EXECUTE FUNCTION fn_set_ereignis_referenz();

-- ============================================================================
-- ESKALATIONS-LOGIK
-- ============================================================================

CREATE OR REPLACE FUNCTION fn_check_escalation(ereignis_id_param INTEGER)
RETURNS TABLE (
    eskalations_level INTEGER,
    grund TEXT,
    zu_benachrichtigen TEXT[]
) AS $$
DECLARE
    verlust DECIMAL;
    ereignis_typ_var TEXT;
    schwere TEXT;
    threshold_l1 DECIMAL;
    threshold_l2 DECIMAL;
    threshold_l3 DECIMAL;
BEGIN
    -- Schwellwerte aus Konfiguration lesen
    SELECT config_wert::DECIMAL INTO threshold_l1
    FROM system_konfiguration WHERE config_schluessel = 'ESCALATION_THRESHOLD_L1';

    SELECT config_wert::DECIMAL INTO threshold_l2
    FROM system_konfiguration WHERE config_schluessel = 'ESCALATION_THRESHOLD_L2';

    SELECT config_wert::DECIMAL INTO threshold_l3
    FROM system_konfiguration WHERE config_schluessel = 'ESCALATION_THRESHOLD_L3';

    -- Ereignis-Daten lesen
    SELECT verlust_betrag_eur, ereignis_typ, risiko_schwere
    INTO verlust, ereignis_typ_var, schwere
    FROM risiko_ereignisse
    WHERE risiko_ereignisse.ereignis_id = ereignis_id_param;

    -- Eskalationslevel bestimmen
    IF verlust >= threshold_l3 OR schwere = 'CRITICAL' THEN
        RETURN QUERY SELECT
            3::INTEGER,
            'Kritisches Ereignis: Verlust >= ' || threshold_l3 || ' EUR oder Schwere CRITICAL'::TEXT,
            ARRAY['Vorstand', 'Chief Risk Officer', 'Aufsichtsrat']::TEXT[];

    ELSIF verlust >= threshold_l2 OR schwere = 'HIGH' THEN
        RETURN QUERY SELECT
            2::INTEGER,
            'Schwerwiegendes Ereignis: Verlust >= ' || threshold_l2 || ' EUR oder Schwere HIGH'::TEXT,
            ARRAY['Bereichsleitung', 'Risk Manager', 'Compliance Officer']::TEXT[];

    ELSIF verlust >= threshold_l1 THEN
        RETURN QUERY SELECT
            1::INTEGER,
            'Relevantes Ereignis: Verlust >= ' || threshold_l1 || ' EUR'::TEXT,
            ARRAY['Abteilungsleitung', 'Operational Risk Team']::TEXT[];

    ELSE
        RETURN QUERY SELECT
            0::INTEGER,
            'Keine Eskalation erforderlich'::TEXT,
            ARRAY[]::TEXT[];
    END IF;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- ARCHIVIERUNGSPROZEDUR
-- ============================================================================

CREATE OR REPLACE FUNCTION fn_archive_old_data(years_to_keep INTEGER DEFAULT 7)
RETURNS TABLE (
    tabelle TEXT,
    archivierte_datensaetze INTEGER
) AS $$
DECLARE
    cutoff_date DATE;
    archived_count INTEGER;
BEGIN
    cutoff_date := CURRENT_DATE - (years_to_keep * INTERVAL '1 year');

    -- Audit Trail archivieren (in separater Archiv-Tabelle)
    CREATE TABLE IF NOT EXISTS audit_trail_archiv (LIKE audit_trail INCLUDING ALL);

    INSERT INTO audit_trail_archiv
    SELECT * FROM audit_trail
    WHERE aenderung_zeitpunkt < cutoff_date;

    GET DIAGNOSTICS archived_count = ROW_COUNT;
    RETURN QUERY SELECT 'audit_trail'::TEXT, archived_count;

    DELETE FROM audit_trail WHERE aenderung_zeitpunkt < cutoff_date;

    -- Alte KRI-Messwerte archivieren
    CREATE TABLE IF NOT EXISTS kri_messwerte_archiv (LIKE kri_messwerte INCLUDING ALL);

    INSERT INTO kri_messwerte_archiv
    SELECT * FROM kri_messwerte
    WHERE mess_datum < cutoff_date;

    GET DIAGNOSTICS archived_count = ROW_COUNT;
    RETURN QUERY SELECT 'kri_messwerte'::TEXT, archived_count;

    DELETE FROM kri_messwerte WHERE mess_datum < cutoff_date;

    -- Abgeschlossene Ereignisse als archiviert markieren
    UPDATE risiko_ereignisse
    SET status = 'ARCHIVIERT'
    WHERE status = 'ABGESCHLOSSEN'
      AND meldedatum < cutoff_date;

    GET DIAGNOSTICS archived_count = ROW_COUNT;
    RETURN QUERY SELECT 'risiko_ereignisse (markiert)'::TEXT, archived_count;
END;
$$ LANGUAGE plpgsql;
