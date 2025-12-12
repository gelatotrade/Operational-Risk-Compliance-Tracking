"""
Daten-Transformatoren für verschiedene Entitätstypen
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, date
from decimal import Decimal
from typing import Any
import hashlib

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings, BASEL_EVENT_TYPES

logger = logging.getLogger(__name__)


class BaseTransformer(ABC):
    """Abstrakte Basis-Klasse für Transformatoren"""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.transformed_count = 0
        self.error_count = 0

    @abstractmethod
    def transform(self, record: dict) -> dict | None:
        """Transformiert einen einzelnen Datensatz"""
        pass

    def transform_batch(self, records: list[dict]) -> list[dict]:
        """Transformiert einen Batch von Datensätzen"""
        results = []
        for record in records:
            try:
                transformed = self.transform(record)
                if transformed:
                    results.append(transformed)
                    self.transformed_count += 1
            except Exception as e:
                self.error_count += 1
                self.errors.append({
                    "record": record,
                    "error": str(e)
                })
                logger.error(f"Transformationsfehler: {e}")
        return results

    def _clean_string(self, value: Any) -> str | None:
        """Bereinigt Stringwerte"""
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def _parse_date(self, value: Any) -> date | None:
        """Parst Datumswerte"""
        if value is None or value == "":
            return None
        if isinstance(value, (date, datetime)):
            return value if isinstance(value, date) else value.date()
        try:
            return datetime.strptime(str(value), settings.etl.date_format).date()
        except ValueError:
            for fmt in ["%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"]:
                try:
                    return datetime.strptime(str(value), fmt).date()
                except ValueError:
                    continue
        return None

    def _parse_decimal(self, value: Any) -> Decimal | None:
        """Parst Dezimalwerte"""
        if value is None or value == "":
            return None
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        try:
            s = str(value).replace(",", ".").replace(" ", "")
            return Decimal(s)
        except Exception:
            return None


class RiskEventTransformer(BaseTransformer):
    """Transformator für Risikoereignisse"""

    # Mapping von Quell-Ereignistypen zu Standard-Typen
    EVENT_TYPE_MAPPING = {
        "fraud": "Betrug",
        "betrug": "Betrug",
        "internal fraud": "Interner Betrug",
        "external fraud": "Externer Betrug",
        "system": "Systemausfall",
        "systemausfall": "Systemausfall",
        "it failure": "Systemausfall",
        "compliance": "Compliance-Verstoß",
        "compliance violation": "Compliance-Verstoß",
        "process": "Prozessfehler",
        "prozessfehler": "Prozessfehler",
        "human error": "Menschlicher Fehler",
        "external": "Externes Ereignis"
    }

    # Mapping zu BASEL-Kategorien
    BASEL_MAPPING = {
        "Interner Betrug": "IF",
        "Externer Betrug": "EF",
        "Betrug": "EF",
        "Systemausfall": "BDSF",
        "Compliance-Verstoß": "CPBP",
        "Prozessfehler": "EDPM",
        "Menschlicher Fehler": "EDPM",
        "Externes Ereignis": "DPA"
    }

    def transform(self, record: dict) -> dict | None:
        """
        Transformiert einen Risikoereignis-Datensatz

        Args:
            record: Quelldatensatz

        Returns:
            Transformierter Datensatz oder None bei Fehler
        """
        # Ereignistyp normalisieren
        source_type = self._clean_string(record.get("ereignis_typ") or record.get("event_type", ""))
        ereignis_typ = self.EVENT_TYPE_MAPPING.get(
            source_type.lower() if source_type else "",
            source_type
        )

        if not ereignis_typ:
            self.warnings.append(f"Fehlender Ereignistyp: {record}")
            ereignis_typ = "Sonstiges"

        # BASEL-Kategorie bestimmen
        basel_code = self.BASEL_MAPPING.get(ereignis_typ)

        # Verlustbetrag verarbeiten
        verlust = self._parse_decimal(
            record.get("verlust_betrag") or
            record.get("loss_amount") or
            record.get("verlust")
        )

        # Währung normalisieren
        waehrung = self._clean_string(
            record.get("verlust_waehrung") or
            record.get("currency") or
            "EUR"
        )
        if waehrung:
            waehrung = waehrung.upper()[:3]

        # Schwere bestimmen
        schwere = self._determine_severity(verlust, ereignis_typ)

        # Near-Miss Check
        ist_near_miss = (
            bool(record.get("ist_near_miss") or record.get("is_near_miss")) or
            (verlust is None or verlust == 0) and
            self._parse_decimal(record.get("potentieller_verlust") or record.get("potential_loss"))
        )

        return {
            "ereignis_referenz": self._clean_string(record.get("ereignis_referenz") or record.get("reference")),
            "meldedatum": self._parse_date(record.get("meldedatum") or record.get("report_date")),
            "entdeckungsdatum": self._parse_date(
                record.get("entdeckungsdatum") or
                record.get("discovery_date") or
                record.get("meldedatum") or
                record.get("report_date")
            ),
            "ereignis_beginn": self._parse_date(record.get("ereignis_beginn") or record.get("event_start")),
            "ereignis_ende": self._parse_date(record.get("ereignis_ende") or record.get("event_end")),
            "ereignis_typ": ereignis_typ,
            "basel_kategorie_code": basel_code,
            "risiko_schwere": schwere,
            "geschaeftsbereich": self._clean_string(
                record.get("geschaeftsbereich") or
                record.get("business_unit") or
                record.get("abteilung")
            ),
            "prozess": self._clean_string(record.get("prozess") or record.get("process")),
            "standort": self._clean_string(record.get("standort") or record.get("location")),
            "verlust_betrag": verlust,
            "verlust_waehrung": waehrung,
            "wiederherstellung_betrag": self._parse_decimal(
                record.get("wiederherstellung_betrag") or record.get("recovery_amount")
            ),
            "versicherungs_erstattung": self._parse_decimal(
                record.get("versicherungs_erstattung") or record.get("insurance_recovery")
            ),
            "potentieller_verlust": self._parse_decimal(
                record.get("potentieller_verlust") or record.get("potential_loss")
            ),
            "ist_near_miss": ist_near_miss,
            "root_cause": self._clean_string(record.get("root_cause") or record.get("ursache")),
            "root_cause_kategorie": self._clean_string(
                record.get("root_cause_kategorie") or record.get("cause_category")
            ),
            "corrective_actions": self._clean_string(
                record.get("corrective_actions") or record.get("massnahmen")
            ),
            "status": self._clean_string(record.get("status")) or "GEMELDET",
            "bemerkungen": self._clean_string(record.get("bemerkungen") or record.get("comments"))
        }

    def _determine_severity(self, verlust: Decimal | None, ereignis_typ: str) -> str:
        """Bestimmt die Risikoschwere basierend auf Verlust und Typ"""
        if verlust is None:
            return "LOW"

        verlust_float = float(verlust)

        # Schwellwerte aus Konfiguration
        if verlust_float >= settings.risk.escalation_l3:
            return "CRITICAL"
        elif verlust_float >= settings.risk.escalation_l2:
            return "HIGH"
        elif verlust_float >= settings.risk.escalation_l1:
            return "MEDIUM"
        else:
            return "LOW"


class KRITransformer(BaseTransformer):
    """Transformator für Key Risk Indicators"""

    def transform(self, record: dict) -> dict | None:
        """Transformiert einen KRI-Messwert"""

        ist_wert = self._parse_decimal(
            record.get("ist_wert") or
            record.get("actual_value") or
            record.get("value")
        )

        if ist_wert is None:
            self.warnings.append(f"Fehlender Ist-Wert: {record}")
            return None

        ziel_wert = self._parse_decimal(
            record.get("ziel_wert") or
            record.get("target_value")
        )

        # Trend berechnen
        vorperiode = self._parse_decimal(
            record.get("vorperiode_wert") or
            record.get("previous_value")
        )
        trend = self._calculate_trend(ist_wert, vorperiode)

        # Ampelstatus bestimmen
        toleranz_unten = self._parse_decimal(record.get("toleranz_band_unten"))
        toleranz_oben = self._parse_decimal(record.get("toleranz_band_oben"))
        kritisch = self._parse_decimal(record.get("kritischer_wert"))

        ampel = self._determine_traffic_light(
            ist_wert, ziel_wert, toleranz_unten, toleranz_oben, kritisch
        )

        return {
            "kri_referenz": self._clean_string(record.get("kri_referenz") or record.get("kri_id")),
            "mess_datum": self._parse_date(
                record.get("mess_datum") or
                record.get("measurement_date") or
                date.today()
            ),
            "ist_wert": ist_wert,
            "ziel_wert": ziel_wert,
            "vorperiode_wert": vorperiode,
            "abweichung_absolut": ist_wert - ziel_wert if ziel_wert else None,
            "abweichung_prozent": (
                ((ist_wert - ziel_wert) / ziel_wert * 100)
                if ziel_wert and ziel_wert != 0 else None
            ),
            "trend": trend,
            "ampel_status": ampel,
            "kommentar": self._clean_string(record.get("kommentar") or record.get("comment")),
            "massnahmen": self._clean_string(record.get("massnahmen") or record.get("actions"))
        }

    def _calculate_trend(self, aktuell: Decimal, vorher: Decimal | None) -> str:
        """Berechnet den Trend basierend auf Veränderung"""
        if vorher is None:
            return "STABIL"

        diff_pct = (aktuell - vorher) / abs(vorher) * 100 if vorher != 0 else 0

        if diff_pct > 5:
            return "VERSCHLECHTERT"
        elif diff_pct < -5:
            return "VERBESSERT"
        else:
            return "STABIL"

    def _determine_traffic_light(
        self,
        ist: Decimal,
        ziel: Decimal | None,
        tol_unten: Decimal | None,
        tol_oben: Decimal | None,
        kritisch: Decimal | None
    ) -> str:
        """Bestimmt den Ampelstatus"""
        # Kritischer Wert überschritten
        if kritisch and ist >= kritisch:
            return "ROT"

        # Außerhalb Toleranzband
        if tol_unten and ist < tol_unten:
            return "ROT"
        if tol_oben and ist > tol_oben:
            return "ROT"

        # Zielwert als Referenz
        if ziel:
            abweichung = abs((ist - ziel) / ziel * 100) if ziel != 0 else 0
            if abweichung > 20:
                return "ROT"
            elif abweichung > 10:
                return "GELB"

        return "GRUEN"


class ComplianceTransformer(BaseTransformer):
    """Transformator für Compliance-Vorschriften"""

    REG_WERK_MAPPING = {
        "mifid": "MiFID II",
        "mifid2": "MiFID II",
        "mifid ii": "MiFID II",
        "emir": "EMIR",
        "gdpr": "GDPR",
        "dsgvo": "GDPR",
        "sox": "SOX",
        "basel": "BASEL III",
        "basel3": "BASEL III",
        "basel iii": "BASEL III",
        "dora": "DORA"
    }

    STATUS_MAPPING = {
        "compliant": "ERFUELLT",
        "erfüllt": "ERFUELLT",
        "open": "OFFEN",
        "offen": "OFFEN",
        "violated": "VERLETZT",
        "verletzt": "VERLETZT",
        "in progress": "IN_BEARBEITUNG",
        "in bearbeitung": "IN_BEARBEITUNG",
        "n/a": "NICHT_ANWENDBAR",
        "nicht anwendbar": "NICHT_ANWENDBAR"
    }

    def transform(self, record: dict) -> dict | None:
        """Transformiert einen Compliance-Datensatz"""

        # Regulatorisches Werk normalisieren
        reg_werk_raw = self._clean_string(
            record.get("reg_werk") or
            record.get("regulation") or
            record.get("framework")
        )

        if not reg_werk_raw:
            self.warnings.append(f"Fehlendes regulatorisches Werk: {record}")
            return None

        reg_werk = self.REG_WERK_MAPPING.get(
            reg_werk_raw.lower(),
            reg_werk_raw.upper()
        )

        # Status normalisieren
        status_raw = self._clean_string(record.get("status")) or "OFFEN"
        status = self.STATUS_MAPPING.get(status_raw.lower(), status_raw.upper())

        return {
            "vorschrift_referenz": self._clean_string(
                record.get("vorschrift_referenz") or
                record.get("requirement_id")
            ),
            "reg_werk": reg_werk,
            "reg_artikel": self._clean_string(
                record.get("reg_artikel") or
                record.get("article")
            ),
            "anforderung": self._clean_string(
                record.get("anforderung") or
                record.get("requirement") or
                record.get("description")
            ),
            "anforderung_kurz": self._clean_string(
                record.get("anforderung_kurz") or
                record.get("short_description")
            ),
            "deadline": self._parse_date(
                record.get("deadline") or
                record.get("due_date")
            ),
            "status": status,
            "erfuellungsgrad": self._parse_decimal(
                record.get("erfuellungsgrad") or
                record.get("completion_rate")
            ),
            "verantwortlicher_name": self._clean_string(
                record.get("verantwortlicher_name") or
                record.get("owner") or
                record.get("responsible")
            ),
            "abteilung": self._clean_string(
                record.get("abteilung") or
                record.get("department")
            ),
            "risiko_bei_nichterfuellung": self._clean_string(
                record.get("risiko_bei_nichterfuellung") or
                record.get("risk_level")
            ),
            "potentielle_strafe": self._parse_decimal(
                record.get("potentielle_strafe") or
                record.get("potential_fine")
            ),
            "bemerkungen": self._clean_string(
                record.get("bemerkungen") or
                record.get("comments")
            )
        }


class CurrencyTransformer(BaseTransformer):
    """Transformator für Währungsumrechnungen"""

    def __init__(self):
        super().__init__()
        self._fx_cache = {}

    def transform(self, record: dict) -> dict | None:
        """Transformiert einen Wechselkurs-Datensatz"""

        von = self._clean_string(record.get("von_waehrung") or record.get("from_currency"))
        nach = self._clean_string(record.get("nach_waehrung") or record.get("to_currency"))
        kurs = self._parse_decimal(record.get("wechselkurs") or record.get("rate"))

        if not all([von, nach, kurs]):
            return None

        return {
            "von_waehrung": von.upper()[:3],
            "nach_waehrung": nach.upper()[:3],
            "kurs_datum": self._parse_date(
                record.get("kurs_datum") or
                record.get("rate_date") or
                date.today()
            ),
            "wechselkurs": kurs,
            "kurs_typ": self._clean_string(record.get("kurs_typ") or "SPOT"),
            "quelle": self._clean_string(record.get("quelle") or record.get("source"))
        }

    def convert_amount(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        rate_date: date = None
    ) -> Decimal:
        """
        Konvertiert einen Betrag zwischen Währungen

        Args:
            amount: Ursprungsbetrag
            from_currency: Quellwährung
            to_currency: Zielwährung
            rate_date: Datum für Wechselkurs

        Returns:
            Konvertierter Betrag
        """
        if from_currency == to_currency:
            return amount

        rate_date = rate_date or date.today()
        cache_key = f"{from_currency}_{to_currency}_{rate_date}"

        if cache_key not in self._fx_cache:
            # Wechselkurs aus DB laden (Platzhalter)
            # In Produktion: DB-Query
            self._fx_cache[cache_key] = Decimal("1.0")

        return amount * self._fx_cache[cache_key]
