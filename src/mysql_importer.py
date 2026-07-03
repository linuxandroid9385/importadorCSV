import math
import re
import mysql.connector
import pandas as pd

MYSQL_TYPE_MAP = {
    "int": "BIGINT NULL",
    "float": "DOUBLE NULL",
    "datetime": "DATETIME NULL",
    "bool": "TINYINT(1) NULL",
    "object": "TEXT NULL",
}

AUTO_KEY_CANDIDATES = [
    "WorkRequestNo",
    "WorkRequestKey",
    "work_request_no",
    "work_request_key",
    "checklist_key",
    "request_key",
    "asset_no",
    "asset_no_from_key",
]

SYSTEM_COLUMNS = {"created_at", "updated_at"}


def comparable_name(name: str) -> str:
    """Convierte WorkRequestNo, work_request_no y work request no a workrequestno."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def looks_snake(name: str) -> bool:
    return "_" in str(name)


class MySQLImporter:
    def __init__(self, mysql_config: dict, table: str, logger=None):
        self.mysql_config = mysql_config
        self.table = table
        self.logger = logger
        self.cn = None

    def connect(self):
        self.cn = mysql.connector.connect(**self.mysql_config)
        if self.logger:
            self.logger.info("Conexión MySQL OK")

    def close(self):
        if self.cn and self.cn.is_connected():
            self.cn.close()

    def existing_columns_info(self) -> dict:
        sql = """
            SELECT COLUMN_NAME, DATA_TYPE, COLUMN_KEY, IS_NULLABLE, COLUMN_DEFAULT, EXTRA
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """
        cur = self.cn.cursor(dictionary=True)
        cur.execute(sql, (self.mysql_config["database"], self.table))
        rows = cur.fetchall()
        cur.close()
        return {row["COLUMN_NAME"]: row for row in rows}

    def existing_columns(self) -> set[str]:
        return set(self.existing_columns_info().keys())

    def infer_mysql_type(self, series: pd.Series) -> str:
        clean = series.dropna()
        if clean.empty:
            return "TEXT NULL"
        if pd.api.types.is_bool_dtype(clean):
            return MYSQL_TYPE_MAP["bool"]
        if pd.api.types.is_integer_dtype(clean):
            return MYSQL_TYPE_MAP["int"]
        if pd.api.types.is_float_dtype(clean):
            return MYSQL_TYPE_MAP["float"]
        if pd.api.types.is_datetime64_any_dtype(clean):
            return MYSQL_TYPE_MAP["datetime"]
        max_len = clean.astype(str).str.len().max()
        if max_len and max_len <= 500:
            return "VARCHAR(500) NULL"
        return "TEXT NULL"

    def _unique_in_order(self, items: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                result.append(item)
                seen.add(item)
        return result

    def choose_best_existing_column(self, excel_col: str, candidates: list[str], info: dict) -> str:
        """
        Si ya existe una tabla con columnas CamelCase y snake_case duplicadas,
        preferimos la columna real/canónica de MySQL. Ejemplo:
        work_request_no -> WorkRequestNo, porque WorkRequestNo es PRIMARY KEY.
        """
        if not candidates:
            return excel_col

        def score(col: str) -> tuple:
            meta = info.get(col, {})
            key = str(meta.get("COLUMN_KEY") or "")
            # Más alto = mejor
            is_primary = 1 if key == "PRI" else 0
            is_unique = 1 if key == "UNI" else 0
            not_system = 0 if col.lower() in SYSTEM_COLUMNS else 1
            not_snake = 1 if not looks_snake(col) else 0
            exact = 1 if col == excel_col else 0
            return (not_system, is_primary, is_unique, not_snake, exact, -len(col))

        return sorted(candidates, key=score, reverse=True)[0]

    def map_dataframe_to_existing_schema(self, df: pd.DataFrame) -> pd.DataFrame:
        info = self.existing_columns_info()
        if not info:
            return df

        by_comp = {}
        for col in info.keys():
            by_comp.setdefault(comparable_name(col), []).append(col)

        rename_map = {}
        for col in df.columns:
            comp = comparable_name(col)
            candidates = by_comp.get(comp, [])
            if candidates:
                target = self.choose_best_existing_column(col, candidates, info)
                if target != col:
                    rename_map[col] = target

        if rename_map:
            if self.logger:
                for src, dst in rename_map.items():
                    self.logger.info(f"Mapeo columna Excel -> MySQL: {src} -> {dst}")
            df = df.rename(columns=rename_map)

        # Si después del mapeo dos columnas caen al mismo nombre, consolidamos.
        # Prioridad: el primer valor no vacío por fila.
        if len(set(df.columns)) != len(df.columns):
            if self.logger:
                self.logger.warning("Columnas equivalentes detectadas; consolidando valores no vacíos.")
            new_df = pd.DataFrame()
            for col in self._unique_in_order(list(df.columns)):
                same = df.loc[:, df.columns == col]
                if same.shape[1] == 1:
                    new_df[col] = same.iloc[:, 0]
                else:
                    new_df[col] = same.bfill(axis=1).iloc[:, 0]
            df = new_df

        return df

    def create_missing_columns(self, df: pd.DataFrame):
        existing = self.existing_columns()
        missing = [c for c in self._unique_in_order(list(df.columns)) if c not in existing]
        if not missing:
            return

        cur = self.cn.cursor()
        try:
            for col in missing:
                if col.lower() in SYSTEM_COLUMNS:
                    continue
                col_type = self.infer_mysql_type(df[col])
                sql = f"ALTER TABLE `{self.table}` ADD COLUMN `{col}` {col_type}"
                if self.logger:
                    self.logger.info(f"Creando columna faltante: {col} {col_type}")
                try:
                    cur.execute(sql)
                    self.cn.commit()
                    existing.add(col)
                except mysql.connector.Error as e:
                    if getattr(e, "errno", None) == 1060:
                        if self.logger:
                            self.logger.warning(f"La columna ya existía en MySQL, se omite: {col}")
                        self.cn.rollback()
                        existing.add(col)
                        continue
                    self.cn.rollback()
                    raise
        finally:
            cur.close()

    def normalize_value(self, value):
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        if hasattr(value, "to_pydatetime"):
            return value.to_pydatetime()
        return value

    def resolve_unique_keys(self, df: pd.DataFrame, unique_keys: list[str]) -> list[str]:
        requested = [k for k in unique_keys if k and k.lower() != "auto"]
        if requested:
            # También soporta que config.ini diga work_request_no aunque la tabla use WorkRequestNo.
            comp_to_col = {comparable_name(c): c for c in df.columns}
            resolved = []
            missing = []
            for key in requested:
                if key in df.columns:
                    resolved.append(key)
                elif comparable_name(key) in comp_to_col:
                    resolved.append(comp_to_col[comparable_name(key)])
                else:
                    missing.append(key)
            if missing:
                available = ", ".join(df.columns)
                raise ValueError(
                    "Las columnas unique_keys no existen después del mapeo: "
                    f"{missing}. Columnas disponibles: {available}"
                )
            return resolved

        for candidate in AUTO_KEY_CANDIDATES:
            for col in df.columns:
                if comparable_name(candidate) == comparable_name(col) and df[col].notna().any():
                    if self.logger:
                        self.logger.info(f"Unique key automática seleccionada: {col}")
                    return [col]

        raise ValueError(
            "No pude detectar una unique key automáticamente. "
            "Configura unique_keys en config.ini con una columna real del Excel. "
            f"Columnas disponibles: {', '.join(df.columns)}"
        )

    def index_exists_for_columns(self, unique_keys: list[str]) -> bool:
        sql = """
            SELECT INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS cols, NON_UNIQUE
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            GROUP BY INDEX_NAME, NON_UNIQUE
        """
        cur = self.cn.cursor()
        cur.execute(sql, (self.mysql_config["database"], self.table))
        wanted = ",".join(unique_keys)
        exists = False
        for _idx, cols, non_unique in cur.fetchall():
            if int(non_unique) == 0 and cols == wanted:
                exists = True
                break
        cur.close()
        return exists

    def ensure_unique_index(self, unique_keys: list[str]):
        if self.index_exists_for_columns(unique_keys):
            return
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", "uk_" + "_".join(unique_keys))[:60]
        cols_sql = ", ".join(f"`{c}`" for c in unique_keys)
        sql = f"ALTER TABLE `{self.table}` ADD UNIQUE KEY `{clean_name}` ({cols_sql})"
        if self.logger:
            self.logger.info(f"Creando índice único para ON DUPLICATE KEY: {clean_name} ({cols_sql})")
        cur = self.cn.cursor()
        try:
            cur.execute(sql)
            self.cn.commit()
        except mysql.connector.Error as e:
            self.cn.rollback()
            raise RuntimeError(
                "No se pudo crear el índice único. Posible causa: ya tienes datos duplicados "
                f"en {unique_keys}. Detalle MySQL: {e}"
            ) from e
        finally:
            cur.close()

    def drop_rows_without_required_keys(self, df: pd.DataFrame, unique_keys: list[str]) -> pd.DataFrame:
        before = len(df)
        for key in unique_keys:
            df = df[df[key].notna() & (df[key].astype(str).str.strip() != "")]
        removed = before - len(df)
        if removed and self.logger:
            self.logger.warning(f"Filas omitidas por llave vacía {unique_keys}: {removed}")
        return df

    def import_dataframe(self, df: pd.DataFrame, unique_keys: list[str], batch_size: int = 500, auto_create_columns: bool = True) -> int:
        if df.empty:
            return 0

        # Mapeo fuerte contra estructura existente: work_request_no -> WorkRequestNo, etc.
        df = self.map_dataframe_to_existing_schema(df.copy())

        # Blindaje extra para encabezados realmente repetidos.
        if len(set(df.columns)) != len(df.columns):
            new_cols = []
            seen = {}
            for col in df.columns:
                base = str(col)
                count = seen.get(base, 0)
                new_cols.append(base if count == 0 else f"{base}_{count + 1}")
                seen[base] = count + 1
            df.columns = new_cols
            if self.logger:
                self.logger.warning("Se detectaron columnas repetidas; fueron renombradas automáticamente.")

        unique_keys = self.resolve_unique_keys(df, unique_keys)
        df = self.drop_rows_without_required_keys(df, unique_keys)
        if df.empty:
            return 0

        if auto_create_columns:
            self.create_missing_columns(df)

        self.ensure_unique_index(unique_keys)

        # Insertamos solo columnas reales de MySQL. Esto evita meter columnas antiguas snake_case
        # cuando la tabla ya tiene columnas canónicas CamelCase.
        existing = self.existing_columns()
        columns = [c for c in df.columns if c in existing and c.lower() not in SYSTEM_COLUMNS]

        # Si WorkRequestNo existe y es NOT NULL/PRIMARY, debe ir incluido cuando haya equivalente.
        if "WorkRequestNo" in existing and "WorkRequestNo" not in columns:
            raise RuntimeError("La tabla requiere WorkRequestNo, pero no se encontró/mapeó esa columna desde el Excel.")

        insert_cols = ", ".join(f"`{c}`" for c in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        update_cols = [c for c in columns if c not in unique_keys]
        if update_cols:
            update_sql = ", ".join(f"`{c}` = VALUES(`{c}`)" for c in update_cols)
        else:
            update_sql = f"`{unique_keys[0]}` = VALUES(`{unique_keys[0]}`)"

        sql = f"""
            INSERT INTO `{self.table}` ({insert_cols})
            VALUES ({placeholders})
            ON DUPLICATE KEY UPDATE {update_sql}
        """

        rows = [tuple(self.normalize_value(v) for v in row) for row in df[columns].itertuples(index=False, name=None)]
        cur = self.cn.cursor()
        total = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            cur.executemany(sql, batch)
            self.cn.commit()
            total += len(batch)
            if self.logger:
                self.logger.info(f"Lote importado: {total}/{len(rows)}")
        cur.close()
        return total
