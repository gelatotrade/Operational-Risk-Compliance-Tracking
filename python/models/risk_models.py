"""
Risikomanagement-Modelle (Ereignisse, Kontrollen, Compliance, etc.)
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, Date, DateTime, Numeric,
    ForeignKey, Text, ARRAY, JSON, Interval, Computed
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from decimal import Decimal

from .base import Base, TimestampMixin


class RisikoEreignis(Base, TimestampMixin):
    """Operationelle Risikoereignisse"""
    __tablename__ = "risiko_ereignisse"

    ereignis_id = Column(Integer, primary_key=True)
    ereignis_referenz = Column(String(50), unique=True)

    # Zeitliche Angaben
    meldedatum = Column(Date, nullable=False, default=func.current_date())
    entdeckungsdatum = Column(Date, nullable=False)
    ereignis_beginn = Column(Date)
    ereignis_ende = Column(Date)

    # Klassifizierung
    ereignis_typ = Column(String(50), nullable=False)
    basel_kategorie_id = Column(Integer, ForeignKey("basel_risikokategorien.kategorie_id"))
    risiko_schwere = Column(String(20), default="MEDIUM")

    # Organisatorische Zuordnung
    geschaeftsbereich_id = Column(Integer, ForeignKey("geschaeftsbereiche.bereich_id"))
    geschaeftsbereich = Column(String(100))
    prozess = Column(String(200))
    standort = Column(String(100))

    # Finanzielle Auswirkung
    verlust_betrag = Column(Numeric(18, 2), default=0)
    verlust_waehrung = Column(String(3), default="EUR")
    verlust_betrag_eur = Column(Numeric(18, 2))
    wiederherstellung_betrag = Column(Numeric(18, 2), default=0)
    versicherungs_erstattung = Column(Numeric(18, 2), default=0)

    # Potentieller Verlust für Near-Misses
    potentieller_verlust = Column(Numeric(18, 2))
    ist_near_miss = Column(Boolean, default=False)

    # Ursachenanalyse
    root_cause = Column(Text)
    root_cause_kategorie = Column(String(50))
    contributing_factors = Column(ARRAY(Text))

    # Korrekturmaßnahmen
    corrective_actions = Column(Text)
    preventive_actions = Column(Text)
    action_owner = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    action_deadline = Column(Date)
    action_status = Column(String(30), default="OFFEN")

    # Status und Workflow
    status = Column(String(30), default="GEMELDET")
    ist_extern_gemeldet = Column(Boolean, default=False)
    externe_meldung_datum = Column(Date)

    # Freigabe (4-Augen-Prinzip)
    erfasst_von = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    freigegeben_von = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    freigabe_datum = Column(DateTime)

    # Metadaten
    bemerkungen = Column(Text)
    anhaenge_pfad = Column(Text)

    # Relationships
    basel_kategorie = relationship("BaselRisikokategorie")
    geschaeftsbereich_rel = relationship("Geschaeftsbereich")
    incident_responses = relationship("IncidentResponse", back_populates="ereignis")

    @property
    def netto_verlust(self) -> Decimal:
        """Berechnet den Nettoverlust"""
        verlust = self.verlust_betrag or Decimal(0)
        wiederherstellung = self.wiederherstellung_betrag or Decimal(0)
        versicherung = self.versicherungs_erstattung or Decimal(0)
        return verlust - wiederherstellung - versicherung

    @property
    def ist_kritisch(self) -> bool:
        """Prüft ob das Ereignis kritisch ist"""
        return self.risiko_schwere == "CRITICAL" or (self.verlust_betrag_eur or 0) >= 1_000_000


class KontrolleMechanismen(Base, TimestampMixin):
    """Kontrollmechanismen und deren Effektivität"""
    __tablename__ = "kontrolle_mechanismen"

    kontrolle_id = Column(Integer, primary_key=True)
    kontrolle_referenz = Column(String(50), unique=True)
    kontrolle_name = Column(String(200), nullable=False)
    kontrolle_beschreibung = Column(Text)

    # Klassifizierung
    kontrolle_typ = Column(String(30), nullable=False)  # PREVENTIV, DETEKTIV, KORREKTIV
    kontrolle_kategorie = Column(String(50))  # MANUAL, AUTOMATED, SEMI_AUTOMATED
    risiko_kategorie = Column(String(50))

    # Zuständigkeit
    zustaendiger_id = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    zustaendiger_name = Column(String(200))
    abteilung = Column(String(100))

    # Testing
    test_frequenz = Column(String(30))
    letzter_test = Column(Date)
    naechster_test = Column(Date)
    test_ergebnis = Column(String(30))
    test_bemerkung = Column(Text)

    # Bewertung
    effektivitaets_score = Column(Numeric(5, 2))  # 0-100%
    design_effektivitaet = Column(String(30))
    operative_effektivitaet = Column(String(30))
    maturity_level = Column(Integer)  # 1-5

    # Kosten-Nutzen
    jaehrliche_kosten = Column(Numeric(18, 2))
    risiko_reduktion_prozent = Column(Numeric(5, 2))

    # Verknüpfungen
    abgedeckte_risiken = Column(ARRAY(Text))
    verknuepfte_vorschriften = Column(ARRAY(Text))

    # Status
    ist_aktiv = Column(Boolean, default=True)
    einfuehrungsdatum = Column(Date)
    ausserbetriebnahme_datum = Column(Date)

    # Dokumentation
    dokumentations_pfad = Column(Text)

    @property
    def ist_test_faellig(self) -> bool:
        """Prüft ob der Test fällig ist"""
        from datetime import date
        return self.naechster_test and self.naechster_test <= date.today()

    @property
    def gap_to_target(self) -> float:
        """Berechnet die Lücke zum Zielwert (90%)"""
        return 90.0 - (float(self.effektivitaets_score) if self.effektivitaets_score else 0)


class ComplianceVorschrift(Base, TimestampMixin):
    """Regulatorische Compliance-Anforderungen"""
    __tablename__ = "compliance_vorschriften"

    vorschrift_id = Column(Integer, primary_key=True)
    vorschrift_referenz = Column(String(50), unique=True)

    # Regulatorischer Rahmen
    reg_werk = Column(String(50), nullable=False)
    reg_artikel = Column(String(100))
    anforderung = Column(Text, nullable=False)
    anforderung_kurz = Column(String(500))

    # Zeitliche Aspekte
    inkrafttreten = Column(Date)
    deadline = Column(Date)
    naechste_pruefung = Column(Date)

    # Status
    status = Column(String(30), default="OFFEN")
    erfuellungsgrad = Column(Numeric(5, 2))

    # Zuständigkeit
    verantwortlicher_id = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    verantwortlicher_name = Column(String(200))
    abteilung = Column(String(100))

    # Bewertung
    risiko_bei_nichterfuellung = Column(String(20))
    potentielle_strafe = Column(Numeric(18, 2))
    strafe_waehrung = Column(String(3), default="EUR")

    # Dokumentation
    dokumentations_pfad = Column(Text)
    nachweis_dokumente = Column(ARRAY(Text))

    # Prüfungen
    letzte_pruefung = Column(Date)
    pruefer = Column(String(200))
    pruef_ergebnis = Column(Text)

    # Metadaten
    bemerkungen = Column(Text)
    ist_aktiv = Column(Boolean, default=True)

    @property
    def ist_ueberfaellig(self) -> bool:
        """Prüft ob die Deadline überschritten ist"""
        from datetime import date
        return (
            self.deadline and
            self.deadline < date.today() and
            self.status not in ("ERFUELLT", "NICHT_ANWENDBAR")
        )

    @property
    def tage_bis_deadline(self) -> int | None:
        """Berechnet Tage bis zur Deadline"""
        from datetime import date
        if self.deadline:
            return (self.deadline - date.today()).days
        return None


class IncidentResponse(Base, TimestampMixin):
    """Incident Response zu Risikoereignissen"""
    __tablename__ = "incident_response"

    response_id = Column(Integer, primary_key=True)
    ereignis_id = Column(Integer, ForeignKey("risiko_ereignisse.ereignis_id"))

    # Response Team
    response_team = Column(ARRAY(Text))
    response_lead_id = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    response_lead_name = Column(String(200))

    # Eskalation
    eskalations_level = Column(Integer, default=1)
    eskalations_pfad = Column(ARRAY(Text))
    eskaliert_an = Column(ARRAY(Text))

    # Zeitliche Aspekte
    response_start = Column(DateTime, default=func.current_timestamp())
    erstreaktion_zeit = Column(Interval)
    loesungs_zeit = Column(Interval)
    abschluss_datum = Column(DateTime)

    # Maßnahmen
    sofort_massnahmen = Column(Text)
    eingeleitete_massnahmen = Column(Text)
    massnahmen_status = Column(String(30), default="LAUFEND")

    # Kommunikation
    interne_kommunikation = Column(Text)
    externe_kommunikation = Column(Text)
    kommunikations_log = Column(JSON)

    # Abschluss
    lessons_learned = Column(Text)
    follow_up_actions = Column(ARRAY(Text))
    abschluss_bestaetigt_von = Column(Integer, ForeignKey("benutzer.benutzer_id"))

    # Relationships
    ereignis = relationship("RisikoEreignis", back_populates="incident_responses")

    @property
    def ist_abgeschlossen(self) -> bool:
        return self.abschluss_datum is not None


class KeyRiskIndicator(Base, TimestampMixin):
    """Key Risk Indicators (KRIs)"""
    __tablename__ = "key_risk_indicators"

    kri_id = Column(Integer, primary_key=True)
    kri_referenz = Column(String(50), unique=True)
    kri_name = Column(String(200), nullable=False)
    kri_beschreibung = Column(Text)

    # Kategorisierung
    risiko_kategorie = Column(String(50))
    geschaeftsbereich = Column(String(100))

    # Messparameter
    einheit = Column(String(50))
    aggregations_methode = Column(String(30))
    datenquelle = Column(String(200))
    berechnungs_formel = Column(Text)

    # Schwellwerte
    ziel_wert = Column(Numeric(18, 4))
    toleranz_band_unten = Column(Numeric(18, 4))
    toleranz_band_oben = Column(Numeric(18, 4))
    kritischer_wert = Column(Numeric(18, 4))

    # Verantwortlichkeit
    owner_id = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    owner_name = Column(String(200))

    # Frequenz
    mess_frequenz = Column(String(30))

    # Status
    ist_aktiv = Column(Boolean, default=True)

    # Relationships
    messwerte = relationship("KRIMesswert", back_populates="kri", order_by="desc(KRIMesswert.mess_datum)")


class KRIMesswert(Base):
    """KRI-Messwerte (historisch)"""
    __tablename__ = "kri_messwerte"

    messwert_id = Column(Integer, primary_key=True)
    kri_id = Column(Integer, ForeignKey("key_risk_indicators.kri_id"))
    mess_datum = Column(Date, nullable=False)

    # Werte
    ist_wert = Column(Numeric(18, 4), nullable=False)
    ziel_wert = Column(Numeric(18, 4))
    vorperiode_wert = Column(Numeric(18, 4))

    # Berechnung
    abweichung_absolut = Column(Numeric(18, 4))
    abweichung_prozent = Column(Numeric(10, 4))

    # Trend und Status
    trend = Column(String(20))  # VERBESSERT, VERSCHLECHTERT, STABIL
    ampel_status = Column(String(10))  # GRUEN, GELB, ROT

    # Kontext
    kommentar = Column(Text)
    massnahmen = Column(Text)

    # Metadaten
    erfasst_von = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    created_at = Column(DateTime, default=func.current_timestamp())

    # Relationships
    kri = relationship("KeyRiskIndicator", back_populates="messwerte")


class ScenarioAnalysis(Base, TimestampMixin):
    """Szenarioanalysen für Kapitalberechnung"""
    __tablename__ = "scenario_analysis"

    scenario_id = Column(Integer, primary_key=True)
    scenario_referenz = Column(String(50), unique=True)
    scenario_name = Column(String(200), nullable=False)
    scenario_beschreibung = Column(Text)

    # Klassifizierung
    scenario_typ = Column(String(50))
    risiko_kategorie = Column(String(50))
    geschaeftsbereich = Column(String(100))

    # Bewertung
    wahrscheinlichkeit = Column(Numeric(10, 6))
    wahrscheinlichkeit_klasse = Column(String(20))
    auswirkung = Column(Numeric(18, 2))
    auswirkung_klasse = Column(String(20))

    # Berechnete Werte
    erwarteter_verlust = Column(Numeric(18, 2))
    value_at_risk = Column(Numeric(18, 2))
    unexpected_loss = Column(Numeric(18, 2))

    # Kontrollen und Residualrisiko
    bestehende_kontrollen = Column(ARRAY(Text))
    kontroll_effektivitaet = Column(Numeric(5, 2))
    brutto_risiko = Column(Numeric(18, 2))
    residual_risiko_nach_controls = Column(Numeric(18, 2))

    # Versicherung
    versicherungsschutz = Column(Numeric(18, 2))
    residual_nach_versicherung = Column(Numeric(18, 2))

    # Validierung
    expertenvalidierung = Column(Boolean, default=False)
    validiert_von = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    validierung_datum = Column(Date)
    validierung_bemerkung = Column(Text)

    # Status
    status = Column(String(30), default="ENTWURF")
    gueltig_von = Column(Date)
    gueltig_bis = Column(Date)

    # Metadaten
    erstellt_von = Column(Integer, ForeignKey("benutzer.benutzer_id"))

    @property
    def capital_charge(self) -> Decimal:
        """Berechnet die Kapitalanforderung"""
        residual = self.residual_nach_versicherung or Decimal(0)
        factor = Decimal("1.2") if not self.expertenvalidierung else Decimal("1.0")
        return max(residual, Decimal(0)) * factor


class RiskAppetite(Base):
    """Risk Appetite Statement"""
    __tablename__ = "risk_appetite"

    appetite_id = Column(Integer, primary_key=True)
    gueltigkeits_jahr = Column(Integer, nullable=False)

    # Quantitative Limits
    max_einzelverlust = Column(Numeric(18, 2))
    max_jahresverlust = Column(Numeric(18, 2))
    max_verlust_pro_ereignis_typ = Column(JSON)

    # Qualitative Statements
    risiko_toleranz_beschreibung = Column(Text)
    null_toleranz_bereiche = Column(ARRAY(Text))

    # Approval
    genehmigt_von = Column(String(200))
    genehmigung_datum = Column(Date)

    # Status
    ist_aktiv = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.current_timestamp())


class RiskAppetiteMonitoring(Base):
    """Risk Appetite Monitoring"""
    __tablename__ = "risk_appetite_monitoring"

    monitoring_id = Column(Integer, primary_key=True)
    appetite_id = Column(Integer, ForeignKey("risk_appetite.appetite_id"))
    periode = Column(String(10))  # YYYY-MM

    # Aktuelle Werte
    kumulierter_verlust = Column(Numeric(18, 2))
    max_einzelverlust_periode = Column(Numeric(18, 2))
    anzahl_ereignisse = Column(Integer)

    # Auslastung
    auslastung_prozent = Column(Numeric(5, 2))

    # Status
    status = Column(String(30))
    eskalation_erforderlich = Column(Boolean, default=False)

    # Metadaten
    berechnet_am = Column(DateTime, default=func.current_timestamp())
