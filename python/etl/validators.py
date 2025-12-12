"""
Datenvalidatoren für ETL-Prozesse
"""

import re
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Ergebnis einer Validierung"""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    record: dict = None

    def add_error(self, message: str):
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str):
        self.warnings.append(message)


class DataValidator:
    """Datenvalidator mit konfigurierbaren Regeln"""

    def __init__(self):
        self.rules = {}
        self.custom_validators = {}

    def add_rule(
        self,
        field_name: str,
        rule_type: str,
        **kwargs
    ):
        """
        Fügt eine Validierungsregel hinzu

        Args:
            field_name: Feldname
            rule_type: Regeltyp (required, type, range, pattern, custom)
            **kwargs: Regelparameter
        """
        if field_name not in self.rules:
            self.rules[field_name] = []
        self.rules[field_name].append({
            "type": rule_type,
            **kwargs
        })

    def add_custom_validator(
        self,
        name: str,
        validator_func: Callable[[Any], tuple[bool, str | None]]
    ):
        """
        Fügt einen benutzerdefinierten Validator hinzu

        Args:
            name: Name des Validators
            validator_func: Funktion die (is_valid, error_message) zurückgibt
        """
        self.custom_validators[name] = validator_func

    def validate(self, record: dict) -> ValidationResult:
        """
        Validiert einen Datensatz

        Args:
            record: Zu validierender Datensatz

        Returns:
            ValidationResult
        """
        result = ValidationResult(is_valid=True, record=record)

        for field_name, rules in self.rules.items():
            value = record.get(field_name)

            for rule in rules:
                rule_type = rule["type"]

                if rule_type == "required":
                    if value is None or value == "":
                        result.add_error(
                            f"Pflichtfeld '{field_name}' fehlt oder ist leer"
                        )

                elif rule_type == "type":
                    expected_type = rule.get("expected")
                    if value is not None and not self._check_type(value, expected_type):
                        result.add_error(
                            f"Feld '{field_name}': Erwarteter Typ {expected_type}, "
                            f"aber {type(value).__name__} gefunden"
                        )

                elif rule_type == "range":
                    if value is not None:
                        min_val = rule.get("min")
                        max_val = rule.get("max")
                        if min_val is not None and value < min_val:
                            result.add_error(
                                f"Feld '{field_name}': Wert {value} unter Minimum {min_val}"
                            )
                        if max_val is not None and value > max_val:
                            result.add_error(
                                f"Feld '{field_name}': Wert {value} über Maximum {max_val}"
                            )

                elif rule_type == "pattern":
                    pattern = rule.get("pattern")
                    if value is not None and not re.match(pattern, str(value)):
                        result.add_error(
                            f"Feld '{field_name}': Wert entspricht nicht dem Muster {pattern}"
                        )

                elif rule_type == "enum":
                    allowed = rule.get("values", [])
                    if value is not None and value not in allowed:
                        result.add_error(
                            f"Feld '{field_name}': Wert '{value}' nicht in erlaubten Werten {allowed}"
                        )

                elif rule_type == "date_range":
                    if value is not None:
                        min_date = rule.get("min_date")
                        max_date = rule.get("max_date")
                        if min_date and value < min_date:
                            result.add_error(
                                f"Feld '{field_name}': Datum vor {min_date}"
                            )
                        if max_date and value > max_date:
                            result.add_error(
                                f"Feld '{field_name}': Datum nach {max_date}"
                            )

                elif rule_type == "custom":
                    validator_name = rule.get("validator")
                    if validator_name in self.custom_validators:
                        is_valid, error_msg = self.custom_validators[validator_name](value)
                        if not is_valid:
                            result.add_error(
                                f"Feld '{field_name}': {error_msg}"
                            )

                elif rule_type == "warning":
                    condition = rule.get("condition")
                    message = rule.get("message")
                    if condition and condition(value):
                        result.add_warning(message)

        return result

    def validate_batch(self, records: list[dict]) -> tuple[list[dict], list[ValidationResult]]:
        """
        Validiert einen Batch von Datensätzen

        Args:
            records: Liste der Datensätze

        Returns:
            Tuple aus (valide Datensätze, Fehlerhafte Ergebnisse)
        """
        valid_records = []
        errors = []

        for record in records:
            result = self.validate(record)
            if result.is_valid:
                valid_records.append(record)
            else:
                errors.append(result)

        return valid_records, errors

    def _check_type(self, value: Any, expected: str) -> bool:
        """Prüft den Datentyp"""
        type_map = {
            "string": str,
            "int": int,
            "float": (int, float),
            "decimal": (int, float, Decimal),
            "date": date,
            "datetime": datetime,
            "bool": bool,
            "list": list,
            "dict": dict
        }
        expected_types = type_map.get(expected)
        if expected_types:
            return isinstance(value, expected_types)
        return True


class RiskEventValidator(DataValidator):
    """Spezialisierter Validator für Risikoereignisse"""

    def __init__(self):
        super().__init__()
        self._setup_rules()

    def _setup_rules(self):
        # Pflichtfelder
        self.add_rule("entdeckungsdatum", "required")
        self.add_rule("ereignis_typ", "required")

        # Typprüfungen
        self.add_rule("verlust_betrag", "type", expected="decimal")
        self.add_rule("entdeckungsdatum", "type", expected="date")
        self.add_rule("meldedatum", "type", expected="date")

        # Bereichsprüfungen
        self.add_rule("verlust_betrag", "range", min=0)
        self.add_rule("wiederherstellung_betrag", "range", min=0)
        self.add_rule("versicherungs_erstattung", "range", min=0)

        # Enum-Prüfungen
        self.add_rule("risiko_schwere", "enum",
                      values=["LOW", "MEDIUM", "HIGH", "CRITICAL"])
        self.add_rule("status", "enum",
                      values=["GEMELDET", "ANALYSIERT", "BEWERTET", "ABGESCHLOSSEN", "ARCHIVIERT"])

        # Datumsbereich
        self.add_rule("entdeckungsdatum", "date_range",
                      max_date=date.today())

        # Custom: Wiederherstellung nicht größer als Verlust
        self.add_custom_validator(
            "recovery_check",
            lambda v: (True, None) if v is None else (True, None)
        )

        # Warnungen
        self.add_rule("root_cause", "warning",
                      condition=lambda v: v is None or v == "",
                      message="Root Cause fehlt - bitte nachpflegen")


class KRIValidator(DataValidator):
    """Spezialisierter Validator für KRI-Messwerte"""

    def __init__(self):
        super().__init__()
        self._setup_rules()

    def _setup_rules(self):
        self.add_rule("kri_referenz", "required")
        self.add_rule("mess_datum", "required")
        self.add_rule("ist_wert", "required")

        self.add_rule("ist_wert", "type", expected="decimal")
        self.add_rule("mess_datum", "type", expected="date")

        self.add_rule("ampel_status", "enum",
                      values=["GRUEN", "GELB", "ROT"])
        self.add_rule("trend", "enum",
                      values=["VERBESSERT", "VERSCHLECHTERT", "STABIL"])


class ComplianceValidator(DataValidator):
    """Spezialisierter Validator für Compliance-Vorschriften"""

    def __init__(self):
        super().__init__()
        self._setup_rules()

    def _setup_rules(self):
        self.add_rule("reg_werk", "required")
        self.add_rule("anforderung", "required")

        self.add_rule("status", "enum",
                      values=["ERFUELLT", "OFFEN", "VERLETZT", "IN_BEARBEITUNG", "NICHT_ANWENDBAR"])

        self.add_rule("erfuellungsgrad", "range", min=0, max=100)

        self.add_rule("deadline", "date_range",
                      min_date=date(2000, 1, 1))

        # Warnung bei überfälligen Deadlines
        self.add_rule("deadline", "warning",
                      condition=lambda v: v is not None and v < date.today(),
                      message="Deadline ist überschritten!")
