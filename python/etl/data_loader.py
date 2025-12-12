"""
Daten-Loader für verschiedene Quelldatenformate
"""

import csv
import json
import logging
from pathlib import Path
from typing import Generator, Any
from datetime import datetime
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings

logger = logging.getLogger(__name__)


class DataLoader:
    """Universeller Daten-Loader für CSV, JSON, Excel und Datenbank-Quellen"""

    def __init__(self):
        self.config = settings.etl
        self.encoding = self.config.source_encoding
        self.date_format = self.config.date_format
        self.batch_size = self.config.batch_size

    def load_csv(
        self,
        file_path: Path | str,
        delimiter: str = ";",
        has_header: bool = True,
        column_mapping: dict = None
    ) -> Generator[dict, None, None]:
        """
        Lädt Daten aus einer CSV-Datei

        Args:
            file_path: Pfad zur CSV-Datei
            delimiter: Trennzeichen
            has_header: Hat die Datei eine Kopfzeile
            column_mapping: Mapping von Quell- zu Zielspalten

        Yields:
            Dict mit Zeilendaten
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"CSV-Datei nicht gefunden: {file_path}")

        logger.info(f"Lade CSV-Datei: {file_path}")

        with open(file_path, "r", encoding=self.encoding) as f:
            if has_header:
                reader = csv.DictReader(f, delimiter=delimiter)
            else:
                reader = csv.reader(f, delimiter=delimiter)

            row_count = 0
            for row in reader:
                if column_mapping and has_header:
                    row = {column_mapping.get(k, k): v for k, v in row.items()}
                elif column_mapping and not has_header:
                    row = {column_mapping.get(i, f"col_{i}"): v for i, v in enumerate(row)}

                row_count += 1
                yield row

            logger.info(f"CSV-Datei geladen: {row_count} Zeilen")

    def load_json(
        self,
        file_path: Path | str,
        json_path: str = None
    ) -> Generator[dict, None, None]:
        """
        Lädt Daten aus einer JSON-Datei

        Args:
            file_path: Pfad zur JSON-Datei
            json_path: JSONPath zum Array (z.B. "data.events")

        Yields:
            Dict mit Objektdaten
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"JSON-Datei nicht gefunden: {file_path}")

        logger.info(f"Lade JSON-Datei: {file_path}")

        with open(file_path, "r", encoding=self.encoding) as f:
            data = json.load(f)

        # JSONPath navigieren falls angegeben
        if json_path:
            for key in json_path.split("."):
                data = data[key]

        if isinstance(data, list):
            for item in data:
                yield item
        else:
            yield data

    def load_excel(
        self,
        file_path: Path | str,
        sheet_name: str | int = 0,
        column_mapping: dict = None,
        skip_rows: int = 0
    ) -> Generator[dict, None, None]:
        """
        Lädt Daten aus einer Excel-Datei

        Args:
            file_path: Pfad zur Excel-Datei
            sheet_name: Name oder Index des Sheets
            column_mapping: Mapping von Quell- zu Zielspalten
            skip_rows: Anzahl zu überspringender Zeilen

        Yields:
            Dict mit Zeilendaten
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Excel-Datei nicht gefunden: {file_path}")

        logger.info(f"Lade Excel-Datei: {file_path}, Sheet: {sheet_name}")

        df = pd.read_excel(
            file_path,
            sheet_name=sheet_name,
            skiprows=skip_rows
        )

        if column_mapping:
            df = df.rename(columns=column_mapping)

        for _, row in df.iterrows():
            yield row.to_dict()

    def load_from_database(
        self,
        query: str,
        connection_string: str = None,
        params: dict = None
    ) -> Generator[dict, None, None]:
        """
        Lädt Daten aus einer Datenbank

        Args:
            query: SQL-Query
            connection_string: Datenbankverbindung
            params: Query-Parameter

        Yields:
            Dict mit Zeilendaten
        """
        from sqlalchemy import create_engine, text

        conn_str = connection_string or settings.database.connection_string
        engine = create_engine(conn_str)

        logger.info(f"Führe Query aus: {query[:100]}...")

        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})

            for row in result:
                yield dict(row._mapping)

    def load_batched(
        self,
        data_generator: Generator,
        batch_size: int = None
    ) -> Generator[list[dict], None, None]:
        """
        Gruppiert Daten in Batches

        Args:
            data_generator: Generator mit Einzeldatensätzen
            batch_size: Batch-Größe

        Yields:
            Liste mit Batch-Daten
        """
        batch_size = batch_size or self.batch_size
        batch = []

        for item in data_generator:
            batch.append(item)
            if len(batch) >= batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

    def parse_date(self, value: Any, format_str: str = None) -> datetime | None:
        """Parst einen Datumswert"""
        if value is None or value == "":
            return None

        if isinstance(value, datetime):
            return value

        format_str = format_str or self.date_format

        try:
            return datetime.strptime(str(value), format_str)
        except ValueError:
            # Alternative Formate versuchen
            for fmt in ["%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    return datetime.strptime(str(value), fmt)
                except ValueError:
                    continue

            logger.warning(f"Konnte Datum nicht parsen: {value}")
            return None

    def parse_decimal(self, value: Any) -> float | None:
        """Parst einen Dezimalwert"""
        if value is None or value == "":
            return None

        if isinstance(value, (int, float)):
            return float(value)

        try:
            # Tausendertrennzeichen und Dezimaltrennzeichen normalisieren
            value_str = str(value)
            value_str = value_str.replace(self.config.thousand_separator, "")
            value_str = value_str.replace(",", ".")
            return float(value_str)
        except ValueError:
            logger.warning(f"Konnte Dezimalwert nicht parsen: {value}")
            return None


class IncrementalLoader(DataLoader):
    """Loader für inkrementelle Datenladungen"""

    def __init__(self, watermark_file: Path = None):
        super().__init__()
        self.watermark_file = watermark_file or Path("data/.watermark")
        self._watermarks = self._load_watermarks()

    def _load_watermarks(self) -> dict:
        """Lädt gespeicherte Wasserzeichen"""
        if self.watermark_file.exists():
            with open(self.watermark_file, "r") as f:
                return json.load(f)
        return {}

    def _save_watermarks(self):
        """Speichert Wasserzeichen"""
        self.watermark_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.watermark_file, "w") as f:
            json.dump(self._watermarks, f, indent=2, default=str)

    def get_watermark(self, source_name: str) -> datetime | None:
        """Gibt das letzte Wasserzeichen für eine Quelle zurück"""
        wm = self._watermarks.get(source_name)
        if wm:
            return datetime.fromisoformat(wm)
        return None

    def set_watermark(self, source_name: str, value: datetime):
        """Setzt das Wasserzeichen für eine Quelle"""
        self._watermarks[source_name] = value.isoformat()
        self._save_watermarks()

    def load_incremental(
        self,
        source_name: str,
        query_template: str,
        timestamp_column: str = "updated_at"
    ) -> Generator[dict, None, None]:
        """
        Lädt nur neue/geänderte Daten seit dem letzten Lauf

        Args:
            source_name: Name der Datenquelle
            query_template: SQL-Query mit {watermark} Platzhalter
            timestamp_column: Name der Zeitstempel-Spalte

        Yields:
            Dict mit Zeilendaten
        """
        watermark = self.get_watermark(source_name)

        if watermark:
            query = query_template.format(watermark=watermark.isoformat())
            logger.info(f"Inkrementelle Ladung seit {watermark}")
        else:
            # Erstes Laden - alle Daten
            query = query_template.format(watermark="1900-01-01")
            logger.info("Initiale Volladung")

        max_timestamp = watermark

        for row in self.load_from_database(query):
            row_ts = row.get(timestamp_column)
            if row_ts and (max_timestamp is None or row_ts > max_timestamp):
                max_timestamp = row_ts
            yield row

        if max_timestamp and max_timestamp != watermark:
            self.set_watermark(source_name, max_timestamp)
            logger.info(f"Neues Wasserzeichen: {max_timestamp}")
