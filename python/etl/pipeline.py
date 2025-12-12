"""
ETL-Pipeline für Operational Risk & Compliance Tracking System
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Generator, Type
from dataclasses import dataclass, field
import traceback

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings
from python.etl.data_loader import DataLoader, IncrementalLoader
from python.etl.transformers import (
    BaseTransformer,
    RiskEventTransformer,
    KRITransformer,
    ComplianceTransformer,
    CurrencyTransformer
)
from python.etl.validators import (
    DataValidator,
    RiskEventValidator,
    KRIValidator,
    ComplianceValidator
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Ergebnis eines Pipeline-Laufs"""
    pipeline_name: str
    start_time: datetime
    end_time: datetime = None
    status: str = "RUNNING"

    records_read: int = 0
    records_transformed: int = 0
    records_validated: int = 0
    records_loaded: int = 0
    records_rejected: int = 0

    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0

    @property
    def success_rate(self) -> float:
        if self.records_read == 0:
            return 0
        return self.records_loaded / self.records_read * 100

    def to_dict(self) -> dict:
        return {
            "pipeline_name": self.pipeline_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "records_read": self.records_read,
            "records_transformed": self.records_transformed,
            "records_validated": self.records_validated,
            "records_loaded": self.records_loaded,
            "records_rejected": self.records_rejected,
            "success_rate": self.success_rate,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings)
        }


class ETLPipeline:
    """Orchestriert den ETL-Prozess"""

    def __init__(
        self,
        name: str,
        loader: DataLoader = None,
        transformer: BaseTransformer = None,
        validator: DataValidator = None
    ):
        self.name = name
        self.loader = loader or DataLoader()
        self.transformer = transformer
        self.validator = validator
        self.result = None

        # Callbacks
        self.on_record_loaded = None
        self.on_batch_complete = None
        self.on_error = None

    def run(
        self,
        source: Path | str | Generator,
        target_table: str,
        batch_size: int = None,
        dry_run: bool = False
    ) -> PipelineResult:
        """
        Führt die ETL-Pipeline aus

        Args:
            source: Datenquelle (Pfad, Query oder Generator)
            target_table: Zieltabelle
            batch_size: Batch-Größe
            dry_run: Nur validieren, nicht laden

        Returns:
            PipelineResult
        """
        self.result = PipelineResult(
            pipeline_name=self.name,
            start_time=datetime.now()
        )

        try:
            logger.info(f"Pipeline '{self.name}' gestartet")

            # Daten extrahieren
            if isinstance(source, (Path, str)):
                source_path = Path(source)
                if source_path.suffix == ".csv":
                    data_gen = self.loader.load_csv(source_path)
                elif source_path.suffix == ".json":
                    data_gen = self.loader.load_json(source_path)
                elif source_path.suffix in (".xlsx", ".xls"):
                    data_gen = self.loader.load_excel(source_path)
                else:
                    raise ValueError(f"Unbekanntes Dateiformat: {source_path.suffix}")
            else:
                data_gen = source

            # In Batches verarbeiten
            batch_size = batch_size or settings.etl.batch_size

            for batch in self.loader.load_batched(data_gen, batch_size):
                self._process_batch(batch, target_table, dry_run)

            self.result.status = "COMPLETED"
            logger.info(
                f"Pipeline '{self.name}' abgeschlossen: "
                f"{self.result.records_loaded}/{self.result.records_read} Datensätze geladen"
            )

        except Exception as e:
            self.result.status = "FAILED"
            self.result.errors.append({
                "type": "PIPELINE_ERROR",
                "message": str(e),
                "traceback": traceback.format_exc()
            })
            logger.error(f"Pipeline-Fehler: {e}")

            if self.on_error:
                self.on_error(e)

        finally:
            self.result.end_time = datetime.now()

        return self.result

    def _process_batch(
        self,
        batch: list[dict],
        target_table: str,
        dry_run: bool
    ):
        """Verarbeitet einen Batch von Datensätzen"""
        self.result.records_read += len(batch)

        # Transformieren
        if self.transformer:
            transformed = self.transformer.transform_batch(batch)
            self.result.records_transformed += len(transformed)
            self.result.warnings.extend(self.transformer.warnings)
            self.transformer.warnings = []
        else:
            transformed = batch
            self.result.records_transformed += len(batch)

        # Validieren
        if self.validator:
            valid_records, validation_errors = self.validator.validate_batch(transformed)
            self.result.records_validated += len(valid_records)
            self.result.records_rejected += len(validation_errors)

            for error in validation_errors:
                self.result.errors.append({
                    "type": "VALIDATION_ERROR",
                    "errors": error.errors,
                    "record": error.record
                })
        else:
            valid_records = transformed
            self.result.records_validated += len(transformed)

        # Laden (wenn nicht dry_run)
        if not dry_run and valid_records:
            loaded_count = self._load_to_database(valid_records, target_table)
            self.result.records_loaded += loaded_count
        elif dry_run:
            self.result.records_loaded += len(valid_records)

        # Callback
        if self.on_batch_complete:
            self.on_batch_complete(len(valid_records))

    def _load_to_database(
        self,
        records: list[dict],
        target_table: str
    ) -> int:
        """
        Lädt Datensätze in die Datenbank

        Args:
            records: Zu ladende Datensätze
            target_table: Zieltabelle

        Returns:
            Anzahl geladener Datensätze
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        if not records:
            return 0

        # Spaltennamen aus erstem Record
        columns = list(records[0].keys())
        columns_str = ", ".join(columns)
        placeholders = ", ".join([f":{col}" for col in columns])

        insert_sql = f"""
            INSERT INTO {target_table} ({columns_str})
            VALUES ({placeholders})
            ON CONFLICT DO NOTHING
        """

        try:
            with get_db_context() as db:
                for record in records:
                    # None-Werte für DB vorbereiten
                    clean_record = {
                        k: v if v != "" else None
                        for k, v in record.items()
                    }
                    db.execute(text(insert_sql), clean_record)

                    if self.on_record_loaded:
                        self.on_record_loaded(record)

            return len(records)

        except Exception as e:
            logger.error(f"Datenbankfehler beim Laden: {e}")
            self.result.errors.append({
                "type": "DATABASE_ERROR",
                "message": str(e)
            })
            return 0


class RiskEventPipeline(ETLPipeline):
    """Spezialisierte Pipeline für Risikoereignisse"""

    def __init__(self):
        super().__init__(
            name="risk_events",
            transformer=RiskEventTransformer(),
            validator=RiskEventValidator()
        )

    def run_from_csv(self, file_path: Path, dry_run: bool = False) -> PipelineResult:
        """Lädt Risikoereignisse aus CSV"""
        return self.run(file_path, "risiko_ereignisse", dry_run=dry_run)


class KRIPipeline(ETLPipeline):
    """Spezialisierte Pipeline für KRI-Messwerte"""

    def __init__(self):
        super().__init__(
            name="kri_values",
            transformer=KRITransformer(),
            validator=KRIValidator()
        )

    def run_from_csv(self, file_path: Path, dry_run: bool = False) -> PipelineResult:
        """Lädt KRI-Messwerte aus CSV"""
        return self.run(file_path, "kri_messwerte", dry_run=dry_run)


class CompliancePipeline(ETLPipeline):
    """Spezialisierte Pipeline für Compliance-Vorschriften"""

    def __init__(self):
        super().__init__(
            name="compliance",
            transformer=ComplianceTransformer(),
            validator=ComplianceValidator()
        )

    def run_from_csv(self, file_path: Path, dry_run: bool = False) -> PipelineResult:
        """Lädt Compliance-Vorschriften aus CSV"""
        return self.run(file_path, "compliance_vorschriften", dry_run=dry_run)


class ETLOrchestrator:
    """Orchestriert mehrere ETL-Pipelines"""

    def __init__(self):
        self.pipelines: dict[str, ETLPipeline] = {}
        self.results: list[PipelineResult] = []

    def register_pipeline(self, pipeline: ETLPipeline):
        """Registriert eine Pipeline"""
        self.pipelines[pipeline.name] = pipeline

    def run_all(
        self,
        sources: dict[str, Path],
        dry_run: bool = False
    ) -> list[PipelineResult]:
        """
        Führt alle registrierten Pipelines aus

        Args:
            sources: Dict von Pipeline-Name zu Quelldatei
            dry_run: Nur validieren

        Returns:
            Liste der Pipeline-Ergebnisse
        """
        self.results = []

        for name, pipeline in self.pipelines.items():
            if name in sources:
                logger.info(f"Starte Pipeline: {name}")
                result = pipeline.run(
                    sources[name],
                    self._get_target_table(name),
                    dry_run=dry_run
                )
                self.results.append(result)

        return self.results

    def _get_target_table(self, pipeline_name: str) -> str:
        """Mappt Pipeline-Namen zu Zieltabellen"""
        mapping = {
            "risk_events": "risiko_ereignisse",
            "kri_values": "kri_messwerte",
            "compliance": "compliance_vorschriften",
            "controls": "kontrolle_mechanismen",
            "scenarios": "scenario_analysis",
            "fx_rates": "waehrungsumrechnung"
        }
        return mapping.get(pipeline_name, pipeline_name)

    def get_summary(self) -> dict:
        """Gibt eine Zusammenfassung aller Pipeline-Läufe zurück"""
        total_read = sum(r.records_read for r in self.results)
        total_loaded = sum(r.records_loaded for r in self.results)
        total_errors = sum(len(r.errors) for r in self.results)

        return {
            "total_pipelines": len(self.results),
            "successful": sum(1 for r in self.results if r.status == "COMPLETED"),
            "failed": sum(1 for r in self.results if r.status == "FAILED"),
            "total_records_read": total_read,
            "total_records_loaded": total_loaded,
            "total_errors": total_errors,
            "overall_success_rate": total_loaded / total_read * 100 if total_read > 0 else 0,
            "pipelines": [r.to_dict() for r in self.results]
        }


# Convenience-Funktion für den Start
def run_daily_etl(data_dir: Path = None) -> dict:
    """
    Führt den täglichen ETL-Prozess aus

    Args:
        data_dir: Verzeichnis mit Quelldateien

    Returns:
        ETL-Zusammenfassung
    """
    data_dir = data_dir or Path("data/staging")

    orchestrator = ETLOrchestrator()

    # Pipelines registrieren
    orchestrator.register_pipeline(RiskEventPipeline())
    orchestrator.register_pipeline(KRIPipeline())
    orchestrator.register_pipeline(CompliancePipeline())

    # Quellen definieren
    sources = {}
    for pipeline_name in ["risk_events", "kri_values", "compliance"]:
        csv_file = data_dir / f"{pipeline_name}.csv"
        if csv_file.exists():
            sources[pipeline_name] = csv_file

    # Ausführen
    orchestrator.run_all(sources)

    return orchestrator.get_summary()
