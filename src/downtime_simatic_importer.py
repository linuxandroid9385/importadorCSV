import csv
import hashlib
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Iterable

import mysql.connector


DOWNTIME_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS `downtime_simatic` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `planta` VARCHAR(50),
    `linea` VARCHAR(120),
    `equipo` VARCHAR(120),
    `fecha_inicio` DATETIME,
    `fecha_fin` DATETIME,
    `downtime_min` DECIMAL(10,2),
    `nivel1` VARCHAR(120),
    `nivel2` VARCHAR(150),
    `nivel3` VARCHAR(200),
    `nivel4` VARCHAR(200),
    `archivo_origen` VARCHAR(255),
    `fecha_importacion` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `hash_registro` CHAR(64) NOT NULL,
    UNIQUE KEY `uk_hash` (`hash_registro`),
    INDEX `idx_equipo` (`equipo`),
    INDEX `idx_linea` (`linea`),
    INDEX `idx_fecha_inicio` (`fecha_inicio`),
    INDEX `idx_fecha_fin` (`fecha_fin`),
    INDEX `idx_nivel1` (`nivel1`),
    INDEX `idx_nivel2` (`nivel2`),
    INDEX `idx_nivel3` (`nivel3`),
    INDEX `idx_nivel4` (`nivel4`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""".strip()


INSERT_SQL = """
INSERT IGNORE INTO `downtime_simatic` (
    `planta`, `linea`, `equipo`, `fecha_inicio`, `fecha_fin`, `downtime_min`,
    `nivel1`, `nivel2`, `nivel3`, `nivel4`, `archivo_origen`, `hash_registro`
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
""".strip()


def clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def nullable_text(value, max_len: int | None = None):
    text = clean_text(value)
    if not text:
        return None
    if max_len is not None and len(text) > max_len:
        return text[:max_len]
    return text


def normalize_linea(value: str) -> str:
    """Replica NormalizeLinea de VBA: LINEA9 -> LINEA 9."""
    text = clean_text(value)
    if text.upper().startswith("LINEA"):
        for idx, ch in enumerate(text):
            if ch.isdigit():
                if idx > 0 and text[idx - 1] != " ":
                    return text[:idx] + " " + text[idx:]
                return text
    return text


def parse_minutes_to_decimal(value: str) -> Decimal:
    """Convierte valores como '.13 Min', '2 Min', '5,89 Min' a Decimal(10,2)."""
    text = clean_text(value)
    text = re.sub(r"\s*min\s*$", "", text, flags=re.IGNORECASE).strip()
    text = text.replace(",", ".")
    if not text:
        return Decimal("0.00")
    try:
        return Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def parse_dmy_or_mdy(date_part: str) -> tuple[int, int, int]:
    """
    Regla del VBA:
    - si el primer número > 12 => dd/mm/yyyy
    - si no => mm/dd/yyyy
    """
    tokens = re.split(r"[/-]", clean_text(date_part))
    if len(tokens) < 3:
        raise ValueError(f"Fecha inválida: {date_part}")

    a = int(float(tokens[0]))
    b = int(float(tokens[1]))
    c = int(float(tokens[2]))

    year = c + 2000 if c < 100 else c
    if a > 12:
        day, month = a, b
    else:
        month, day = a, b
    return day, month, year


def parse_time_part(time_part: str) -> tuple[int, int, int]:
    text = clean_text(time_part).upper()
    is_pm = "PM" in text
    is_am = "AM" in text
    text = text.replace("AM", "").replace("PM", "").strip()

    if not text:
        return 0, 0, 0

    parts = text.split(":")
    hour = int(float(parts[0])) if len(parts) >= 1 and parts[0] else 0
    minute = int(float(parts[1])) if len(parts) >= 2 and parts[1] else 0
    second = int(float(parts[2])) if len(parts) >= 3 and parts[2] else 0

    if is_pm and hour < 12:
        hour += 12
    elif is_am and hour == 12:
        hour = 0
    return hour, minute, second


def parse_datetime_smart(raw: str):
    """
    Parser equivalente al VBA ParseDateTimeSmart.
    Acepta ejemplos como:
    - 02/05/2026 22:37
    - 1/27/2026 8:31:06 PM
    - 27/01/2026 20:16
    - 01/12/2026
    """
    text = " ".join(clean_text(raw).split())
    if not text:
        return None

    try:
        if " " in text:
            date_part, time_part = text.split(" ", 1)
        else:
            date_part, time_part = text, ""

        day, month, year = parse_dmy_or_mdy(date_part)
        hour, minute, second = parse_time_part(time_part)
        return datetime(year, month, day, hour, minute, second)
    except Exception:
        return None


def split_equipo_name(equipo_name: str) -> tuple[str | None, str | None, str | None]:
    text = clean_text(equipo_name)
    if not text:
        return None, None, None

    parts = [p.strip() for p in text.split("/")]
    if len(parts) >= 3:
        planta = parts[0]
        linea = normalize_linea(parts[1])
        equipo = "/".join(parts[2:]).strip()
    else:
        planta = ""
        linea = ""
        equipo = text

    return nullable_text(planta, 50), nullable_text(linea, 120), nullable_text(equipo, 120)


def build_hash(row_tuple: tuple) -> str:
    """Hash estable para evitar duplicados entre archivos importados."""
    planta, linea, equipo, fecha_inicio, fecha_fin, downtime_min, nivel1, nivel2, nivel3, nivel4, _archivo = row_tuple
    parts = [
        planta or "",
        linea or "",
        equipo or "",
        fecha_inicio.strftime("%Y-%m-%d %H:%M:%S") if fecha_inicio else "",
        fecha_fin.strftime("%Y-%m-%d %H:%M:%S") if fecha_fin else "",
        str(downtime_min or Decimal("0.00")),
        nivel1 or "",
        nivel2 or "",
        nivel3 or "",
        nivel4 or "",
    ]
    raw = "|".join(parts).encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def parse_simatic_csv_row(row: list[str], archivo_origen: str):
    """
    Lee por posición A:H para soportar encabezados con acentos o columna vacía final:
    A Equipo Name, B Start Time, C End Time, D Duración, E-H Nivel 1..4.
    """
    if len(row) < 4:
        return None

    equipo_name = clean_text(row[0])
    if not equipo_name or equipo_name.lower() in {"equipo name", "equipo", "equipment name"}:
        return None

    planta, linea, equipo = split_equipo_name(equipo_name)
    fecha_inicio = parse_datetime_smart(row[1] if len(row) > 1 else "")
    fecha_fin = parse_datetime_smart(row[2] if len(row) > 2 else "")
    downtime_min = parse_minutes_to_decimal(row[3] if len(row) > 3 else "")

    record = (
        planta,
        linea,
        equipo,
        fecha_inicio,
        fecha_fin,
        downtime_min,
        nullable_text(row[4], 120) if len(row) > 4 else None,
        nullable_text(row[5], 150) if len(row) > 5 else None,
        nullable_text(row[6], 200) if len(row) > 6 else None,
        nullable_text(row[7], 200) if len(row) > 7 else None,
        nullable_text(archivo_origen, 255),
    )
    return record + (build_hash(record),)


def open_csv_text(path: Path):
    """Intenta encodings comunes en exportaciones Windows/Excel."""
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            fh = path.open("r", encoding=encoding, newline="")
            fh.readline()
            fh.seek(0)
            return fh
        except UnicodeDecodeError:
            try:
                fh.close()
            except Exception:
                pass
    return path.open("r", encoding="latin1", newline="")


class DowntimeSimaticImporter:
    def __init__(self, mysql_config: dict, logger=None, table: str = "downtime_simatic"):
        self.mysql_config = mysql_config
        self.logger = logger
        self.table = table
        self.cn = None

    def connect(self):
        self.cn = mysql.connector.connect(**self.mysql_config)
        if self.logger:
            self.logger.info("Conexión MySQL OK para downtime_simatic")

    def close(self):
        if self.cn and self.cn.is_connected():
            self.cn.close()

    def ensure_table(self):
        cur = self.cn.cursor()
        try:
            cur.execute(DOWNTIME_TABLE_DDL)
            self.cn.commit()
        finally:
            cur.close()

    def import_csv_files(
        self,
        files: Iterable[str],
        batch_size: int = 2000,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict:
        self.ensure_table()

        total_read = 0
        total_valid = 0
        total_inserted = 0
        total_errors = 0

        cur = self.cn.cursor()
        batch = []
        try:
            for file in files:
                path = Path(file)
                archivo_origen = path.name
                file_read = 0
                file_valid = 0
                file_inserted_before = total_inserted

                if progress_callback:
                    progress_callback(f"Leyendo CSV Simatic: {archivo_origen}")
                if self.logger:
                    self.logger.info(f"Leyendo CSV Simatic: {path}")

                with open_csv_text(path) as fh:
                    reader = csv.reader(fh)
                    for row in reader:
                        file_read += 1
                        total_read += 1
                        try:
                            parsed = parse_simatic_csv_row(row, archivo_origen)
                            if not parsed:
                                continue
                            batch.append(parsed)
                            file_valid += 1
                            total_valid += 1
                        except Exception as e:
                            total_errors += 1
                            if self.logger:
                                self.logger.warning(f"Fila omitida en {archivo_origen}, línea {file_read}: {e}")
                            continue

                        if len(batch) >= batch_size:
                            cur.executemany(INSERT_SQL, batch)
                            self.cn.commit()
                            total_inserted += max(cur.rowcount, 0)
                            if progress_callback:
                                progress_callback(
                                    f"Importadas/ignoradas por hash: leídas {total_read}, válidas {total_valid}, nuevas {total_inserted}"
                                )
                            batch.clear()

                if batch:
                    cur.executemany(INSERT_SQL, batch)
                    self.cn.commit()
                    total_inserted += max(cur.rowcount, 0)
                    batch.clear()

                file_inserted = total_inserted - file_inserted_before
                if progress_callback:
                    progress_callback(
                        f"Archivo terminado: {archivo_origen} | filas leídas {file_read} | válidas {file_valid} | nuevas {file_inserted}"
                    )

            return {
                "read": total_read,
                "valid": total_valid,
                "inserted": total_inserted,
                "duplicates_or_ignored": max(total_valid - total_inserted, 0),
                "errors": total_errors,
            }
        finally:
            cur.close()
