import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from pathlib import Path

from config_manager import ConfigManager
from logger_setup import setup_logger
from excel_reader import read_excel_files
from mysql_importer import MySQLImporter

class ImportadorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Importador Universal MySQL")
        self.geometry("920x620")
        self.files = []
        self.cfg = ConfigManager("config.ini")
        self.logger = setup_logger(self.cfg.log_file(), self.cfg.log_level())
        self.build_ui()

    def build_ui(self):
        header = tk.Label(self, text="Importador Universal MySQL", font=("Segoe UI", 18, "bold"))
        header.pack(pady=12)

        info = tk.Frame(self)
        info.pack(fill="x", padx=15)

        self.lbl_config = tk.Label(
            info,
            text=f"DB: {self.cfg.mysql()['database']} | Tabla: {self.cfg.table()} | Unique keys: {', '.join(self.cfg.unique_keys())}",
            anchor="w"
        )
        self.lbl_config.pack(fill="x")

        buttons = tk.Frame(self)
        buttons.pack(fill="x", padx=15, pady=10)

        tk.Button(buttons, text="Seleccionar Excel", command=self.select_files, height=2).pack(side="left", padx=5)
        tk.Button(buttons, text="Iniciar importación", command=self.start_import, height=2).pack(side="left", padx=5)
        tk.Button(buttons, text="Limpiar lista", command=self.clear_files, height=2).pack(side="left", padx=5)

        self.file_list = tk.Listbox(self, height=8)
        self.file_list.pack(fill="x", padx=15, pady=5)

        tk.Label(self, text="Logs", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=15, pady=(10, 0))
        self.log_box = scrolledtext.ScrolledText(self, height=18)
        self.log_box.pack(fill="both", expand=True, padx=15, pady=10)

    def ui_log(self, msg: str):
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.update_idletasks()

    def select_files(self):
        files = filedialog.askopenfilenames(
            title="Seleccionar archivos Excel",
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("Todos", "*.*")]
        )
        for file in files:
            if file not in self.files:
                self.files.append(file)
                self.file_list.insert("end", Path(file).name)
        self.ui_log(f"Archivos seleccionados: {len(self.files)}")

    def clear_files(self):
        self.files.clear()
        self.file_list.delete(0, "end")
        self.ui_log("Lista limpiada")

    def start_import(self):
        if not self.files:
            messagebox.showwarning("Sin archivos", "Selecciona al menos un archivo Excel.")
            return
        threading.Thread(target=self.run_import, daemon=True).start()

    def run_import(self):
        importer = None
        try:
            self.ui_log("Iniciando lectura de Excel...")
            df = read_excel_files(self.files, self.cfg.sheet_names(), self.logger)
            self.ui_log(f"Filas detectadas: {len(df)} | Columnas: {len(df.columns)}")
            self.ui_log("Columnas: " + ", ".join(df.columns))

            importer = MySQLImporter(self.cfg.mysql(), self.cfg.table(), self.logger)
            importer.connect()
            total = importer.import_dataframe(
                df=df,
                unique_keys=self.cfg.unique_keys(),
                batch_size=self.cfg.batch_size(),
                auto_create_columns=self.cfg.auto_create_columns()
            )
            self.ui_log(f"IMPORTACIÓN FINALIZADA. Registros procesados: {total}")
            messagebox.showinfo("OK", f"Importación finalizada. Registros procesados: {total}")
        except Exception as e:
            self.logger.exception("Error durante importación")
            self.ui_log(f"ERROR: {e}")
            messagebox.showerror("Error", str(e))
        finally:
            if importer:
                importer.close()

if __name__ == "__main__":
    app = ImportadorApp()
    app.mainloop()
