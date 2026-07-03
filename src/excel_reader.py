import re
import zipfile
import tempfile
from pathlib import Path

import pandas as pd


INVALID_EXCEL_STYLE_MARKERS = (
    b'numFmtId="undefined"',
    b'fontId="undefined"',
    b'fillId="undefined"',
    b'borderId="undefined"',
    b'xfId="undefined"',
)


def normalize_column(name: str) -> str:
    name = str(name).strip().lower()
    name = re.sub(r"[áàäâ]", "a", name)
    name = re.sub(r"[éèëê]", "e", name)
    name = re.sub(r"[íìïî]", "i", name)
    name = re.sub(r"[óòöô]", "o", name)
    name = re.sub(r"[úùüû]", "u", name)
    name = re.sub(r"ñ", "n", name)
    name = re.sub(r"[^a-z0-9_]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "columna_sin_nombre"


def _deduplicate_columns(columns: list[str]) -> list[str]:
    """Evita columnas repetidas después de normalizar nombres."""
    seen = {}
    result = []
    for col in columns:
        base = normalize_column(col)
        count = seen.get(base, 0)
        if count == 0:
            result.append(base)
        else:
            result.append(f"{base}_{count + 1}")
        seen[base] = count + 1
    return result


def _repair_xlsx_styles(original_path: Path, logger=None) -> Path:
    """
    Crea una copia temporal del .xlsx corrigiendo estilos inválidos.

    Algunos exportadores generan xl/styles.xml con atributos como:
        numFmtId="undefined"
    openpyxl espera enteros y truena antes de leer datos. Esta función NO toca
    el archivo original; solo reempaca una copia temporal con esos valores en 0.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp_path = Path(tmp.name)
    tmp.close()

    replacements = {
        b'numFmtId="undefined"': b'numFmtId="0"',
        b'fontId="undefined"': b'fontId="0"',
        b'fillId="undefined"': b'fillId="0"',
        b'borderId="undefined"': b'borderId="0"',
        b'xfId="undefined"': b'xfId="0"',
    }

    with zipfile.ZipFile(original_path, "r") as zin, zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/styles.xml":
                original_data = data
                for old, new in replacements.items():
                    data = data.replace(old, new)
                if logger and data != original_data:
                    logger.warning(f"Estilos inválidos reparados en copia temporal: {original_path.name}")
            zout.writestr(item, data)

    return tmp_path


def _open_excel_safely(path: Path, logger=None):
    """Abre un Excel; si openpyxl falla por styles.xml inválido, usa copia reparada."""
    temp_path = None
    try:
        excel = pd.ExcelFile(path, engine="openpyxl")
        return excel, path, temp_path
    except TypeError as e:
        msg = str(e).lower()
        if "expected <class 'int'>" not in msg and "expected <class" not in msg:
            raise
        if logger:
            logger.warning(f"{path.name}: openpyxl rechazó estilos del archivo. Intentando reparación temporal...")
        temp_path = _repair_xlsx_styles(path, logger)
        excel = pd.ExcelFile(temp_path, engine="openpyxl")
        return excel, temp_path, temp_path
    except ValueError as e:
        msg = str(e).lower()
        if "undefined" not in msg:
            raise
        if logger:
            logger.warning(f"{path.name}: estilo 'undefined' detectado. Intentando reparación temporal...")
        temp_path = _repair_xlsx_styles(path, logger)
        excel = pd.ExcelFile(temp_path, engine="openpyxl")
        return excel, temp_path, temp_path



def _make_dataframe_columns_unique(df: pd.DataFrame) -> pd.DataFrame:
    """Garantiza nombres únicos en el DataFrame completo después de concatenar archivos."""
    if df.empty:
        return df
    df = df.copy()
    df.columns = _deduplicate_columns([str(c) for c in df.columns])
    return df


def read_excel_files(files: list[str], sheet_names: list[str] | None = None, logger=None) -> pd.DataFrame:
    frames = []

    for file in files:
        path = Path(file)
        temp_path = None

        if logger:
            logger.info(f"Leyendo archivo: {path.name}")

        try:
            excel, readable_path, temp_path = _open_excel_safely(path, logger)
            sheets = sheet_names if sheet_names else excel.sheet_names

            for sheet in sheets:
                if sheet not in excel.sheet_names:
                    if logger:
                        logger.warning(f"Hoja no encontrada: {sheet} en {path.name}")
                    continue

                df = pd.read_excel(readable_path, sheet_name=sheet, dtype=object, engine="openpyxl")
                df.columns = _deduplicate_columns(list(df.columns))
                df = df.dropna(how="all")

                if df.empty:
                    if logger:
                        logger.warning(f"Hoja vacía omitida: {sheet} en {path.name}")
                    continue

                df["_archivo_origen"] = path.name
                df["_hoja_origen"] = sheet
                frames.append(df)

        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    if not frames:
        return pd.DataFrame()

    data = pd.concat(frames, ignore_index=True, sort=False)
    data = _make_dataframe_columns_unique(data)
    data = data.where(pd.notnull(data), None)
    return data
