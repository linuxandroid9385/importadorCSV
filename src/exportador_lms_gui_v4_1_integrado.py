from __future__ import annotations

import queue
import threading
import time
from datetime import date, datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

try:
    from tkcalendar import DateEntry
except ImportError as exc:
    raise SystemExit(
        "Falta instalar tkcalendar.\n"
        "Ejecuta: py -m pip install selenium tkcalendar"
    ) from exc

URL_LOGIN = "http://mxsrvlms2/Ex_LMS/Login.aspx"
URL_ESTADO_MAQUINA = "http://mxsrvlms2/Ex_LMS/TableroEstadoMaquina.aspx"
TIMEOUT = 60
TIMEOUT_CONSULTA = 240
TIMEOUT_EXPORTACION = 1800

COLUMNAS_EXPORTACION = [
    "Equipo Name",
    "Start Time",
    "End Time",
    "Duración",
    "Nivel 1",
    "Nivel 2",
    "Nivel 3",
    "Nivel 4",
]


class LMSApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Exportador LMS - Estado de máquina")
        self.geometry("820x680")
        self.minsize(760, 620)

        self.driver: webdriver.Chrome | None = None
        self.eventos: queue.Queue[tuple[str, str]] = queue.Queue()
        self.en_proceso = False

        self._crear_estilos()
        self._crear_interfaz()
        self.after(150, self._procesar_eventos)

    def _crear_estilos(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Titulo.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Subtitulo.TLabel", font=("Segoe UI", 10))
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Accion.TButton", font=("Segoe UI", 10, "bold"))

    def _crear_interfaz(self) -> None:
        principal = ttk.Frame(self, padding=18)
        principal.pack(fill="both", expand=True)

        ttk.Label(principal, text="Exportador LMS", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(
            principal,
            text="Login → Estado de máquina → Consulta → Exportación CSV",
            style="Subtitulo.TLabel",
        ).pack(anchor="w", pady=(0, 14))

        credenciales = ttk.LabelFrame(principal, text="Credenciales", padding=12)
        credenciales.pack(fill="x")
        credenciales.columnconfigure(1, weight=1)

        ttk.Label(credenciales, text="Usuario:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        self.usuario_var = tk.StringVar()
        ttk.Entry(credenciales, textvariable=self.usuario_var).grid(row=0, column=1, sticky="ew", pady=5)

        ttk.Label(credenciales, text="Contraseña:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        self.password_var = tk.StringVar()
        ttk.Entry(credenciales, textvariable=self.password_var, show="●").grid(row=1, column=1, sticky="ew", pady=5)

        rango = ttk.LabelFrame(principal, text="Rango de consulta", padding=12)
        rango.pack(fill="x", pady=12)
        rango.columnconfigure(1, weight=1)
        rango.columnconfigure(3, weight=1)

        ttk.Label(rango, text="Fecha inicial:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        self.fecha_inicio = DateEntry(rango, date_pattern="dd/mm/yyyy", locale="es_MX", width=18)
        self.fecha_inicio.set_date(date(2026, 1, 1))
        self.fecha_inicio.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=5)

        ttk.Label(rango, text="Hora inicial:").grid(row=0, column=2, sticky="w", padx=(0, 8), pady=5)
        self.hora_inicio_var = tk.StringVar(value="00:00")
        ttk.Combobox(
            rango,
            textvariable=self.hora_inicio_var,
            values=self._generar_horas(),
            state="readonly",
            width=12,
        ).grid(row=0, column=3, sticky="ew", pady=5)

        ttk.Label(rango, text="Fecha final:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        self.fecha_fin = DateEntry(rango, date_pattern="dd/mm/yyyy", locale="es_MX", width=18)
        self.fecha_fin.set_date(date(2026, 7, 12))
        self.fecha_fin.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=5)

        ttk.Label(rango, text="Hora final:").grid(row=1, column=2, sticky="w", padx=(0, 8), pady=5)
        self.hora_fin_var = tk.StringVar(value="23:59")
        ttk.Combobox(
            rango,
            textvariable=self.hora_fin_var,
            values=self._generar_horas(incluir_2359=True),
            state="readonly",
            width=12,
        ).grid(row=1, column=3, sticky="ew", pady=5)

        exportacion = ttk.LabelFrame(principal, text="Exportación", padding=12)
        exportacion.pack(fill="x")
        exportacion.columnconfigure(1, weight=1)

        ttk.Label(exportacion, text="Nombre CSV:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        self.nombre_var = tk.StringVar(value="estado_maquina")
        ttk.Entry(exportacion, textvariable=self.nombre_var).grid(row=0, column=1, sticky="ew", pady=5)

        ttk.Label(exportacion, text="Carpeta:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        self.carpeta_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        ttk.Entry(exportacion, textvariable=self.carpeta_var).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Button(exportacion, text="Examinar...", command=self._elegir_carpeta).grid(row=1, column=2, padx=(8, 0), pady=5)

        acciones = ttk.Frame(principal)
        acciones.pack(fill="x", pady=14)

        self.iniciar_btn = ttk.Button(
            acciones,
            text="Iniciar consulta y exportar",
            style="Accion.TButton",
            command=self._iniciar,
        )
        self.iniciar_btn.pack(side="left")
        ttk.Button(acciones, text="Cerrar navegador", command=self._cerrar_driver).pack(side="left", padx=8)

        self.progreso = ttk.Progressbar(acciones, mode="indeterminate")
        self.progreso.pack(side="right", fill="x", expand=True, padx=(20, 0))

        log_frame = ttk.LabelFrame(principal, text="Registro", padding=8)
        log_frame.pack(fill="both", expand=True)

        self.log = tk.Text(log_frame, height=16, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scroll.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scroll.set)

        self.protocol("WM_DELETE_WINDOW", self._salir)

    @staticmethod
    def _generar_horas(incluir_2359: bool = False) -> list[str]:
        horas = [f"{hora:02d}:{minuto:02d}" for hora in range(24) for minuto in (0, 15, 30, 45)]
        if incluir_2359:
            horas.append("23:59")
        return horas

    def _elegir_carpeta(self) -> None:
        carpeta = filedialog.askdirectory(initialdir=self.carpeta_var.get())
        if carpeta:
            self.carpeta_var.set(carpeta)

    def _log(self, mensaje: str) -> None:
        self.eventos.put(("log", mensaje))

    def _procesar_eventos(self) -> None:
        try:
            while True:
                tipo, mensaje = self.eventos.get_nowait()
                if tipo == "log":
                    self.log.configure(state="normal")
                    self.log.insert("end", mensaje + "\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif tipo == "ok":
                    self._terminar_proceso()
                    messagebox.showinfo("Proceso terminado", mensaje)
                elif tipo == "error":
                    self._terminar_proceso()
                    messagebox.showerror("Error", mensaje)
        except queue.Empty:
            pass
        self.after(150, self._procesar_eventos)

    def _terminar_proceso(self) -> None:
        self.en_proceso = False
        self.iniciar_btn.configure(state="normal")
        self.progreso.stop()

    def _validar_datos(self) -> tuple[datetime, datetime, Path]:
        if not self.usuario_var.get().strip():
            raise ValueError("Captura el usuario LMS.")
        if not self.password_var.get():
            raise ValueError("Captura la contraseña LMS.")

        inicio = datetime.combine(
            self.fecha_inicio.get_date(),
            datetime.strptime(self.hora_inicio_var.get(), "%H:%M").time(),
        )
        fin = datetime.combine(
            self.fecha_fin.get_date(),
            datetime.strptime(self.hora_fin_var.get(), "%H:%M").time(),
        )

        if fin <= inicio:
            raise ValueError("La fecha y hora final debe ser posterior a la inicial.")

        carpeta = Path(self.carpeta_var.get()).expanduser()
        if not carpeta.exists():
            raise ValueError("La carpeta de descarga no existe.")
        if not self.nombre_var.get().strip():
            raise ValueError("Captura el nombre del archivo CSV.")

        return inicio, fin, carpeta

    def _iniciar(self) -> None:
        if self.en_proceso:
            return
        try:
            inicio, fin, carpeta = self._validar_datos()
        except Exception as exc:
            messagebox.showwarning("Datos incompletos", str(exc))
            return

        self.en_proceso = True
        self.iniciar_btn.configure(state="disabled")
        self.progreso.start(10)
        self._log("=" * 58)
        self._log(f"Rango: {inicio:%d/%m/%Y %H:%M} → {fin:%d/%m/%Y %H:%M}")

        threading.Thread(
            target=self._ejecutar_automatizacion,
            args=(inicio, fin, carpeta),
            daemon=True,
        ).start()

    def _crear_driver(self, carpeta: Path) -> webdriver.Chrome:
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        options.add_experimental_option(
            "prefs",
            {
                "download.default_directory": str(carpeta.resolve()),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True,
            },
        )
        return webdriver.Chrome(options=options)

    def _ejecutar_automatizacion(self, inicio: datetime, fin: datetime, carpeta: Path) -> None:
        try:
            self.driver = self._crear_driver(carpeta)
            driver = self.driver
            wait = WebDriverWait(driver, TIMEOUT)

            self._login(driver, wait)
            self._abrir_tablero(driver, wait)
            self._configurar_consulta(driver, wait, inicio, fin)
            equipos = self._preparar_todos_los_equipos(driver, wait)
            self._consultar(driver)
            self._abrir_modal_csv(driver, wait)
            self._configurar_exportacion(driver, wait)
            archivo = self._exportar_csv(driver, carpeta)
            self._log("Importando CSV a MySQL...")
            try:
                from downtime_simatic_importer import importar_csv
                resultado = importar_csv(str(archivo))
                self._log(f"Importación OK: {resultado}")
                try:
                    archivo.unlink()
                    self._log("CSV eliminado.")
                except Exception as e:
                    self._log(f"No se pudo eliminar el CSV: {e}")
            except ModuleNotFoundError:
                self._log("No se encontró downtime_simatic_importer.py. Integra ese archivo junto a este programa.")
            except Exception as e:
                self._log(f"Error durante la importación: {e}")

            self.eventos.put(("ok", f"Exportación terminada correctamente.\n\nEquipos incluidos: {len(equipos)}\nArchivo: {archivo}"))
        except Exception as exc:
            self._log(f"ERROR: {type(exc).__name__}: {exc}")
            self.eventos.put(("error", f"{type(exc).__name__}: {exc}"))

    def _login(self, driver: webdriver.Chrome, wait: WebDriverWait) -> None:
        self._log("Abriendo Login.aspx...")
        driver.get(URL_LOGIN)

        usuario = wait.until(EC.visibility_of_element_located((By.ID, "ContentLogin_TxtUserName")))
        password = wait.until(EC.visibility_of_element_located((By.ID, "ContentLogin_TxtPassword")))
        usuario.clear()
        usuario.send_keys(self.usuario_var.get().strip())
        password.clear()
        password.send_keys(self.password_var.get())
        wait.until(EC.element_to_be_clickable((By.ID, "ContentLogin_BtnLogIn"))).click()
        wait.until(lambda d: "Home.aspx" in d.current_url)
        self._log("OK - Login correcto")

    def _abrir_tablero(self, driver: webdriver.Chrome, wait: WebDriverWait) -> None:
        self._log("Abriendo TableroEstadoMaquina.aspx...")
        driver.get(URL_ESTADO_MAQUINA)
        wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolder1_turnos")))
        self._log("OK - Tablero de estado de máquina cargado")

    def _configurar_consulta(
        self,
        driver: webdriver.Chrome,
        wait: WebDriverWait,
        inicio: datetime,
        fin: datetime,
    ) -> None:
        self._log("Esperando que se carguen los turnos...")

        # El select aparece primero con una sola opción y después JavaScript
        # agrega Turno 1, Turno 2, Turno 3 y Personalizado.
        wait_turnos = WebDriverWait(driver, 120)

        def opcion_personalizado_disponible(drv):
            try:
                elemento = drv.find_element(
                    By.ID,
                    "ContentPlaceHolder1_turnos",
                )
                opciones = Select(elemento).options
                return any(
                    (opcion.get_attribute("value") or "").strip().lower()
                    == "personalizado"
                    or opcion.text.strip().lower() == "personalizado"
                    for opcion in opciones
                )
            except Exception:
                return False

        wait_turnos.until(opcion_personalizado_disponible)

        # Se vuelve a obtener el elemento porque el sitio puede reemplazarlo
        # mientras termina de cargar las opciones.
        turno_elemento = driver.find_element(
            By.ID,
            "ContentPlaceHolder1_turnos",
        )
        turno_select = Select(turno_elemento)

        opciones = [
            {
                "text": opcion.text.strip(),
                "value": (
                    opcion.get_attribute("value") or ""
                ).strip(),
            }
            for opcion in turno_select.options
        ]

        opcion_objetivo = next(
            (
                opcion
                for opcion in turno_select.options
                if (
                    (
                        opcion.get_attribute("value") or ""
                    ).strip().lower()
                    == "personalizado"
                    or opcion.text.strip().lower()
                    == "personalizado"
                )
            ),
            None,
        )

        if opcion_objetivo is None:
            raise RuntimeError(
                "No se encontró la opción Personalizado. "
                f"Opciones disponibles: {opciones}"
            )

        valor_personalizado = (
            opcion_objetivo.get_attribute("value") or ""
        )

        turno_select.select_by_value(valor_personalizado)

        # El onchange llama a SeleccionarTurno(); se dispara explícitamente
        # para asegurar que se habiliten/configuren los campos de fecha.
        driver.execute_script(
            """
            const el = arguments[0];
            el.dispatchEvent(
                new Event('input', {bubbles:true})
            );
            el.dispatchEvent(
                new Event('change', {bubbles:true})
            );
            """,
            turno_elemento,
        )

        wait_turnos.until(
            lambda d: (
                d.find_element(
                    By.ID,
                    "ContentPlaceHolder1_turnos",
                ).get_attribute("value")
                == valor_personalizado
            )
        )

        self._log(
            "OK - Turno seleccionado: Personalizado"
        )

        # Esperar a que los dos campos de fecha estén disponibles.
        wait_turnos.until(
            EC.presence_of_element_located(
                (
                    By.ID,
                    "ContentPlaceHolder1_fechaInicio",
                )
            )
        )
        wait_turnos.until(
            EC.presence_of_element_located(
                (
                    By.ID,
                    "ContentPlaceHolder1_fechaFinal",
                )
            )
        )

        for element_id, valor in (
            (
                "ContentPlaceHolder1_fechaInicio",
                inicio.strftime("%Y-%m-%d %H:%M"),
            ),
            (
                "ContentPlaceHolder1_fechaFinal",
                fin.strftime("%Y-%m-%d %H:%M"),
            ),
        ):
            resultado = driver.execute_script(
                """
                const el = document.getElementById(
                    arguments[0]
                );
                const valor = arguments[1];

                if (!el) {
                    return {
                        ok:false,
                        motivo:'Elemento no encontrado'
                    };
                }

                if (el._flatpickr) {
                    el._flatpickr.setDate(
                        valor,
                        true,
                        'Y-m-d H:i'
                    );
                } else {
                    el.removeAttribute('readonly');
                    el.value = valor;
                    el.dispatchEvent(
                        new Event(
                            'input',
                            {bubbles:true}
                        )
                    );
                    el.dispatchEvent(
                        new Event(
                            'change',
                            {bubbles:true}
                        )
                    );
                }

                return {
                    ok:true,
                    value:el.value
                };
                """,
                element_id,
                valor,
            )

            if not resultado or not resultado.get("ok"):
                raise RuntimeError(
                    f"No se pudo establecer {element_id}: "
                    f"{resultado}"
                )

            self._log(
                f"OK - {element_id}: "
                f"{resultado.get('value')}"
            )

        self._log(
            "OK - Turno Personalizado y rango configurados"
        )

    def _preparar_todos_los_equipos(
        self,
        driver: webdriver.Chrome,
        wait: WebDriverWait,
    ) -> list[dict[str, str]]:
        """
        Obtiene todos los equipos de Equipos0, omite Ninguno y prepara
        Equipos0...EquiposN en el DOM.

        El exportador nativo ExporAll('csv') recorre esos selects usando
        la variable global CantidadLineas, por lo que el servidor genera
        un solo CSV con los registros de todos los equipos.
        """
        self._log("Esperando que se cargue la lista de equipos...")

        wait_equipos = WebDriverWait(driver, 120)

        def lista_equipos_disponible(drv):
            try:
                elemento = drv.find_element(By.ID, "Equipos0")
                opciones = Select(elemento).options
                validas = [
                    opcion
                    for opcion in opciones
                    if (
                        opcion.text.strip().lower()
                        not in {"ninguno", ""}
                        and (
                            opcion.get_attribute("value") or ""
                        ).strip()
                        not in {"", "Administrador"}
                    )
                ]
                return len(validas) > 0
            except Exception:
                return False

        wait_equipos.until(lista_equipos_disponible)

        equipo_base = driver.find_element(By.ID, "Equipos0")
        opciones = Select(equipo_base).options

        equipos: list[dict[str, str]] = []
        valores_vistos: set[str] = set()

        for opcion in opciones:
            texto = opcion.text.strip()
            valor = (
                opcion.get_attribute("value") or ""
            ).strip()

            if (
                texto.lower() in {"ninguno", ""}
                or valor in {"", "Administrador"}
                or valor in valores_vistos
            ):
                continue

            valores_vistos.add(valor)
            equipos.append(
                {
                    "value": valor,
                    "text": texto,
                }
            )

        if not equipos:
            raise RuntimeError(
                "No se encontró ningún equipo válido."
            )

        resultado = driver.execute_script(
            """
            const equipos = arguments[0];
            const contenedor =
                document.getElementById('add');
            const base =
                document.getElementById('Equipos0');

            if (!contenedor || !base) {
                return {
                    ok:false,
                    motivo:
                        'No se encontró #add o #Equipos0'
                };
            }

            // Limpiar elementos creados por ejecuciones anteriores.
            for (
                const nodo of Array.from(
                    document.querySelectorAll(
                        '[data-lms-equipo-generado="1"]'
                    )
                )
            ) {
                nodo.remove();
            }

            // Seleccionar el primer equipo en el control visible.
            base.value = equipos[0].value;
            base.dispatchEvent(
                new Event('change', {bubbles:true})
            );

            // Crear únicamente los selects que ExporAll necesita.
            for (let i = 1; i < equipos.length; i++) {
                const wrapper =
                    document.createElement('div');

                wrapper.setAttribute(
                    'data-lms-equipo-generado',
                    '1'
                );
                wrapper.style.display = 'none';

                const select =
                    document.createElement('select');

                select.id = 'Equipos' + i;
                select.name = 'Equipos' + i;

                select.add(
                    new Option(
                        equipos[i].text,
                        equipos[i].value,
                        true,
                        true
                    )
                );

                wrapper.appendChild(select);
                contenedor.appendChild(wrapper);
            }

            // OpenModal y ExporAll recorren desde 0 hasta CantidadLineas.
            window.CantidadLineas =
                equipos.length - 1;

            return {
                ok:true,
                cantidad:equipos.length,
                primero:equipos[0].text,
                ultimo:
                    equipos[equipos.length - 1].text
            };
            """,
            equipos,
        )

        if not resultado or not resultado.get("ok"):
            raise RuntimeError(
                "No fue posible preparar todos los equipos: "
                f"{resultado}"
            )

        self._log(
            "OK - Equipos preparados para exportación: "
            f"{resultado['cantidad']}"
        )
        self._log(
            f"     Primero: {resultado['primero']}"
        )
        self._log(
            f"     Último: {resultado['ultimo']}"
        )
        self._log(
            "INFO - El CSV contendrá todos los equipos "
            "en un solo archivo."
        )

        return equipos

    def _consultar(self, driver: webdriver.Chrome) -> None:
        self._log("Ejecutando consulta. Esto puede tardar...")

        # Evitar que ChromeDriver espere a que Seed() termine.
        driver.execute_script("""
            window.setTimeout(function(){
                if(typeof Seed==='function'){
                    Seed();
                }
            },0);
        """)

        wait_largo = WebDriverWait(driver, TIMEOUT_EXPORTACION)
        ultimo = -1

        while True:
            graficas = driver.find_elements(By.CSS_SELECTOR, "#addGraf svg")
            cantidad = len(graficas)

            if cantidad != ultimo:
                ultimo = cantidad
                self._log(f"Gráficas detectadas: {cantidad}")

            cargando = driver.execute_script("""
                const e=document.getElementById('cardando');
                if(!e) return false;
                const s=getComputedStyle(e);
                return s.display!=='none' && s.visibility!=='hidden';
            """)

            if cantidad > 0 and not cargando:
                break

            wait_largo._driver.implicitly_wait(0)
            time.sleep(2)

        self._log("OK - Consulta terminada")

    def _abrir_modal_csv(self, driver: webdriver.Chrome, wait: WebDriverWait) -> None:
        driver.execute_script(
            "if (typeof OpenModal !== 'function') throw new Error('OpenModal no disponible'); OpenModal('CSV');"
        )
        wait.until(EC.visibility_of_element_located((By.ID, "exportModal")))
        self._log("OK - Modal CSV abierto")

    def _configurar_exportacion(self, driver: webdriver.Chrome, wait: WebDriverWait) -> None:
        nombre = wait.until(EC.visibility_of_element_located((By.ID, "ContentPlaceHolder1_nameExport")))
        nombre.clear()
        nombre.send_keys(self.nombre_var.get().strip())

        resultado = driver.execute_script(
            """
            const orden = arguments[0];
            const disponible = document.getElementById('available-select');
            const seleccionado = document.getElementById('selected-select');
            if (!disponible || !seleccionado) return {ok:false,motivo:'No se encontraron los selectores'};
            const mapa = new Map();
            for (const option of [...disponible.options, ...seleccionado.options]) {
                mapa.set(option.value, {value:option.value, text:option.text});
            }
            disponible.innerHTML = '';
            seleccionado.innerHTML = '';
            for (const columna of orden) {
                const dato = mapa.get(columna);
                if (!dato) return {ok:false,motivo:'No existe la columna '+columna};
                seleccionado.add(new Option(dato.text, dato.value));
            }
            seleccionado.dispatchEvent(new Event('change',{bubbles:true}));
            return {ok:true,columnas:[...seleccionado.options].map(x=>x.value)};
            """,
            COLUMNAS_EXPORTACION,
        )
        if not resultado or not resultado.get("ok"):
            raise RuntimeError(f"No se pudieron ordenar columnas: {resultado}")
        self._log("OK - Columnas preparadas: " + ", ".join(resultado["columnas"]))

    def _exportar_csv(self, driver: webdriver.Chrome, carpeta: Path) -> Path:
        archivos_antes = set(carpeta.glob("*.csv"))
        self._log("Iniciando exportación CSV de todos los equipos...")
        driver.execute_script(
            "if (typeof ExporAll !== 'function') throw new Error('ExporAll no disponible'); ExporAll('csv');"
        )
        limite = time.time() + TIMEOUT_EXPORTACION
        while time.time() < limite:
            nuevos = set(carpeta.glob("*.csv")) - archivos_antes
            temporales = list(carpeta.glob("*.crdownload"))
            if nuevos and not temporales:
                archivo = max(nuevos, key=lambda p: p.stat().st_mtime)
                self._log(f"OK - Archivo descargado: {archivo}")
                return archivo
            time.sleep(1)
        raise TimeoutException("No se confirmó la descarga del CSV.")

    def _cerrar_driver(self) -> None:
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            finally:
                self.driver = None
                self._log("Navegador cerrado")

    def _salir(self) -> None:
        self._cerrar_driver()
        self.destroy()


if __name__ == "__main__":
    LMSApp().mainloop()
