"""
Metadaten-Modelle (Kalender, Benutzer, Audit, etc.)
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, Date, DateTime, Numeric,
    ForeignKey, Text, ARRAY, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base, TimestampMixin


class Kalender(Base):
    """Geschäftskalender mit Feiertagen und Perioden"""
    __tablename__ = "kalender"

    datum = Column(Date, primary_key=True)
    jahr = Column(Integer, nullable=False)
    quartal = Column(Integer, nullable=False)
    monat = Column(Integer, nullable=False)
    woche = Column(Integer, nullable=False)
    tag_im_monat = Column(Integer, nullable=False)
    tag_im_jahr = Column(Integer, nullable=False)
    wochentag = Column(String(20), nullable=False)
    ist_geschaeftstag = Column(Boolean, default=True)
    ist_feiertag = Column(Boolean, default=False)
    feiertag_name = Column(String(100))
    ist_monatsende = Column(Boolean, default=False)
    ist_quartalsende = Column(Boolean, default=False)
    ist_jahresende = Column(Boolean, default=False)
    geschaeftstag_nummer = Column(Integer)
    periode_id = Column(String(10))  # YYYY-MM
    created_at = Column(DateTime, default=func.current_timestamp())


class Waehrungsumrechnung(Base):
    """Wechselkurse für Währungsumrechnung"""
    __tablename__ = "waehrungsumrechnung"

    id = Column(Integer, primary_key=True)
    von_waehrung = Column(String(3), nullable=False)
    nach_waehrung = Column(String(3), nullable=False)
    kurs_datum = Column(Date, nullable=False)
    wechselkurs = Column(Numeric(18, 8), nullable=False)
    kurs_typ = Column(String(20), default="SPOT")
    quelle = Column(String(100))
    created_at = Column(DateTime, default=func.current_timestamp())


class Benutzer(Base, TimestampMixin):
    """Benutzer des Systems"""
    __tablename__ = "benutzer"

    benutzer_id = Column(Integer, primary_key=True)
    benutzername = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    vorname = Column(String(100))
    nachname = Column(String(100))
    abteilung = Column(String(100))
    kostenstelle = Column(String(50))
    ist_aktiv = Column(Boolean, default=True)
    letzter_login = Column(DateTime)

    # Relationships
    rollen = relationship("BenutzerRolle", back_populates="benutzer")

    @property
    def voller_name(self) -> str:
        return f"{self.vorname or ''} {self.nachname or ''}".strip()


class Rolle(Base):
    """Benutzerrollen mit Berechtigungen"""
    __tablename__ = "rollen"

    rolle_id = Column(Integer, primary_key=True)
    rolle_name = Column(String(100), unique=True, nullable=False)
    beschreibung = Column(Text)
    berechtigung_level = Column(Integer, default=1)
    kann_lesen = Column(Boolean, default=True)
    kann_schreiben = Column(Boolean, default=False)
    kann_loeschen = Column(Boolean, default=False)
    kann_freigeben = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.current_timestamp())

    # Relationships
    benutzer_rollen = relationship("BenutzerRolle", back_populates="rolle")


class BenutzerRolle(Base):
    """Zuordnung von Benutzern zu Rollen"""
    __tablename__ = "benutzer_rollen"

    id = Column(Integer, primary_key=True)
    benutzer_id = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    rolle_id = Column(Integer, ForeignKey("rollen.rolle_id"))
    geschaeftsbereich = Column(String(100))
    gueltig_von = Column(Date, default=func.current_date())
    gueltig_bis = Column(Date)
    zugewiesen_von = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    created_at = Column(DateTime, default=func.current_timestamp())

    # Relationships
    benutzer = relationship("Benutzer", foreign_keys=[benutzer_id], back_populates="rollen")
    rolle = relationship("Rolle", back_populates="benutzer_rollen")


class AuditTrail(Base):
    """SOX-konformes Audit-Log"""
    __tablename__ = "audit_trail"

    audit_id = Column(Integer, primary_key=True)
    tabellen_name = Column(String(100), nullable=False)
    datensatz_id = Column(Integer, nullable=False)
    aktion = Column(String(20), nullable=False)  # INSERT, UPDATE, DELETE
    alte_werte = Column(JSON)
    neue_werte = Column(JSON)
    geaenderte_felder = Column(ARRAY(Text))
    benutzer_id = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    benutzer_name = Column(String(100))
    ip_adresse = Column(String(45))
    session_id = Column(String(100))
    aenderung_zeitpunkt = Column(DateTime, default=func.current_timestamp())
    bemerkung = Column(Text)


class Geschaeftsbereich(Base):
    """Organisatorische Geschäftsbereiche"""
    __tablename__ = "geschaeftsbereiche"

    bereich_id = Column(Integer, primary_key=True)
    bereich_code = Column(String(20), unique=True, nullable=False)
    bereich_name = Column(String(200), nullable=False)
    bereich_typ = Column(String(50))
    parent_bereich_id = Column(Integer, ForeignKey("geschaeftsbereiche.bereich_id"))
    kostentraeger = Column(String(50))
    leiter_benutzer_id = Column(Integer, ForeignKey("benutzer.benutzer_id"))
    ist_aktiv = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.current_timestamp())

    # Self-referential relationship
    parent = relationship("Geschaeftsbereich", remote_side=[bereich_id])
    children = relationship("Geschaeftsbereich")


class SystemKonfiguration(Base):
    """Systemweite Konfigurationsparameter"""
    __tablename__ = "system_konfiguration"

    config_id = Column(Integer, primary_key=True)
    config_schluessel = Column(String(100), unique=True, nullable=False)
    config_wert = Column(Text)
    config_typ = Column(String(20), default="STRING")
    beschreibung = Column(Text)
    ist_sensitiv = Column(Boolean, default=False)
    zuletzt_geaendert = Column(DateTime, default=func.current_timestamp())
    geaendert_von = Column(Integer, ForeignKey("benutzer.benutzer_id"))

    def get_typed_value(self):
        """Gibt den Wert im korrekten Typ zurück"""
        if self.config_wert is None:
            return None

        if self.config_typ == "INTEGER":
            return int(self.config_wert)
        elif self.config_typ == "DECIMAL":
            return float(self.config_wert)
        elif self.config_typ == "BOOLEAN":
            return self.config_wert.lower() in ("true", "1", "yes")
        elif self.config_typ == "JSON":
            import json
            return json.loads(self.config_wert)
        else:
            return self.config_wert


class BaselRisikokategorie(Base):
    """BASEL II Risikokategorien"""
    __tablename__ = "basel_risikokategorien"

    kategorie_id = Column(Integer, primary_key=True)
    kategorie_code = Column(String(10), unique=True, nullable=False)
    kategorie_name_de = Column(String(200), nullable=False)
    kategorie_name_en = Column(String(200))
    beschreibung = Column(Text)
    level_1 = Column(String(100))
    level_2 = Column(String(100))
    ist_aktiv = Column(Boolean, default=True)
