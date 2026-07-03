from configparser import ConfigParser
from pathlib import Path

class ConfigManager:
    def __init__(self, path: str = "config.ini"):
        self.path = Path(path)
        self.config = ConfigParser()
        if not self.path.exists():
            raise FileNotFoundError(f"No existe config.ini en: {self.path.resolve()}")
        self.config.read(self.path, encoding="utf-8")

    def mysql(self) -> dict:
        c = self.config["mysql"]
        return {
            "host": c.get("host", "127.0.0.1"),
            "port": c.getint("port", 3306),
            "user": c.get("user", "root"),
            "password": c.get("password", ""),
            "database": c.get("database", ""),
        }

    def table(self) -> str:
        return self.config["mysql"].get("table", "")

    def unique_keys(self) -> list[str]:
        raw = self.config["import"].get("unique_keys", "")
        return [x.strip() for x in raw.split(",") if x.strip()]

    def sheet_names(self) -> list[str]:
        raw = self.config["import"].get("sheet_names", "")
        return [x.strip() for x in raw.split(",") if x.strip()]

    def auto_create_columns(self) -> bool:
        return self.config["import"].getboolean("auto_create_columns", fallback=True)

    def batch_size(self) -> int:
        return self.config["import"].getint("batch_size", fallback=500)

    def log_file(self) -> str:
        return self.config["logging"].get("log_file", "logs/importador.log")

    def log_level(self) -> str:
        return self.config["logging"].get("level", "INFO")
