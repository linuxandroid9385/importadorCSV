from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import (
    TimeoutException,
    InvalidSessionIdException,
    NoSuchWindowException,
    StaleElementReferenceException,
)
from webdriver_manager.chrome import ChromeDriverManager

import mysql.connector
from datetime import datetime
import time
import re
import traceback
import random
import unicodedata

# R4tatouill3*2024
URL_WORK_REQUESTS = (
    "https://cloud.plex.com/Maintenance/WorkRequests?"
    "__asid=250ca3e391604eea827d5e0af75d0d17"
    "&CloudApplicationActionKey=12946"
    "&IsExternal=false"
    "&Text=Work%20Requests"
    "&Url=%2FMaintenance%2FWorkRequests%3F"
    "__asid%3D250ca3e391604eea827d5e0af75d0d17"
    "&Icon=plex-menu-icon-work_requests"
    "&BackgroundColorClass=plex-icon-bg-green"
    "&IconColor=%23fff"
    "&IsMenuLink=false"
    "&ParentMenuNodeKey=85"
    "&MenuNodeKey=-1"
    "&SortOrder=10"
)

PERFIL_CHROME = r"C:\Users\HUNTER\selenium_plex_profile"

MYSQL_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "12345",
    "database": "tpm_database",
    "port": 3306,
}

ASIGNADO_A_BUSQUEDA = "mant"
ASIGNADO_A_FINAL = "Mantenimiento, Planta I"

TIPO_BUSQUEDA = "man"
TIPO_MANTENIMIENTO = "Mantenimiento Correctivo"

FECHA_INICIO = "01/01/2026"  # formato DD/MM/AAAA
FECHA_FIN = "25/01/2026"     # formato DD/MM/AAAA

TIEMPO_ESPERA = 15

NOTA_SIN_DESCRIPCION = (
    "orden de mantenimiento sin descripción de falla "
    "se procede a cerrar"
)


# ============================================================
# DRIVEr R4tatouill3*2024
# ============================================================

def iniciar_driver():
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument(f"--user-data-dir={PERFIL_CHROME}")

    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )


def esperar_pagina(driver, segundos=90):
    WebDriverWait(driver, segundos).until(
        lambda d: d.execute_script(
            "return document.readyState"
        ) == "complete"
    )


def sesion_activa(driver):
    try:
        _ = driver.current_url
        return True
    except (
        InvalidSessionIdException,
        NoSuchWindowException,
        Exception,
    ):
        return False


# ============================================================
# MYSQL
# ============================================================

def conectar_mysql():
    return mysql.connector.connect(**MYSQL_CONFIG)


# ============================================================
# FUNCIONES GENERALES DE PICKERS
# ============================================================

def obtener_modal_visible(driver, segundos=TIEMPO_ESPERA):
    """
    Devuelve el modal que realmente está visible.
    No depende de que tenga style='display: block'.
    """

    def buscar_modal(d):
        modales = d.find_elements(By.CSS_SELECTOR, "div.modal")

        visibles = []

        for modal in modales:
            try:
                if modal.is_displayed():
                    visibles.append(modal)
            except StaleElementReferenceException:
                continue

        return visibles[-1] if visibles else False

    return WebDriverWait(driver, segundos).until(buscar_modal)


def esperar_cierre_modal(driver, modal, segundos=TIEMPO_ESPERA):
    try:
        WebDriverWait(driver, segundos).until(
            EC.staleness_of(modal)
        )
        return
    except TimeoutException:
        pass

    WebDriverWait(driver, segundos).until(
        lambda d: not modal.is_displayed()
    )


def obtener_contenedor_picker(campo):
    return campo.find_element(
        By.XPATH,
        "./ancestor::div[contains(@class,'plex-picker-control')]"
    )


def obtener_textos_seleccionados(contenedor):
    textos = []

    elementos = contenedor.find_elements(
        By.CSS_SELECTOR,
        ".plex-picker-selected-items .plex-picker-item-text"
    )

    for elemento in elementos:
        try:
            texto = elemento.text.strip()

            if texto:
                textos.append(texto)
        except StaleElementReferenceException:
            continue

    return textos


def limpiar_picker(driver, input_id):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    campo = wait.until(
        EC.presence_of_element_located((By.ID, input_id))
    )

    contenedor = obtener_contenedor_picker(campo)

    removers = contenedor.find_elements(
        By.CSS_SELECTOR,
        ".plex-picker-item-remove"
    )

    for remover in removers:
        try:
            if remover.is_displayed():
                driver.execute_script(
                    "arguments[0].click();",
                    remover,
                )
                time.sleep(0.8)
        except StaleElementReferenceException:
            continue


def abrir_picker(driver, input_id):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    campo = wait.until(
        EC.presence_of_element_located((By.ID, input_id))
    )

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        campo,
    )

    contenedor = obtener_contenedor_picker(campo)

    icono = contenedor.find_element(
        By.CSS_SELECTOR,
        "a.plex-picker-icon"
    )

    wait.until(
        lambda d: icono.is_displayed() and icono.is_enabled()
    )

    driver.execute_script(
        "arguments[0].click();",
        icono,
    )

    return obtener_modal_visible(driver)


def buscar_dentro_modal(driver, modal, texto):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    campo_busqueda = wait.until(
        lambda d: next(
            (
                elemento
                for elemento in modal.find_elements(
                    By.CSS_SELECTOR,
                    ".plex-picker-search input[type='text']"
                )
                if elemento.is_displayed()
                and elemento.is_enabled()
            ),
            None,
        )
    )

    campo_busqueda.click()
    campo_busqueda.clear()
    campo_busqueda.send_keys(texto)

    boton_buscar = wait.until(
        lambda d: next(
            (
                boton
                for boton in modal.find_elements(
                    By.XPATH,
                    ".//button[normalize-space()='Buscar']"
                )
                if boton.is_displayed()
                and boton.is_enabled()
            ),
            None,
        )
    )

    driver.execute_script(
        "arguments[0].click();",
        boton_buscar,
    )

    time.sleep(2)


def seleccionar_fila_exacta(driver, modal, texto_exacto):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    xpath_fila = (
        ".//tr["
        ".//td[normalize-space(.)="
        f"'{texto_exacto}'"
        "]"
        "]"
    )

    fila = wait.until(
        lambda d: next(
            (
                elemento
                for elemento in modal.find_elements(
                    By.XPATH,
                    xpath_fila,
                )
                if elemento.is_displayed()
            ),
            None,
        )
    )

    checkbox = fila.find_element(
        By.CSS_SELECTOR,
        "input[type='checkbox']"
    )

    if not checkbox.is_selected():
        driver.execute_script(
            "arguments[0].click();",
            checkbox,
        )

    time.sleep(1)


def confirmar_modal(
    driver,
    modal,
    texto_preferido,
    texto_alternativo=None,
):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    textos = [texto_preferido]

    if texto_alternativo:
        textos.append(texto_alternativo)

    boton = None

    for texto in textos:
        try:
            boton = wait.until(
                lambda d: next(
                    (
                        elemento
                        for elemento in modal.find_elements(
                            By.XPATH,
                            f".//button[normalize-space()='{texto}']"
                            f" | .//a[normalize-space()='{texto}']"
                        )
                        if elemento.is_displayed()
                        and elemento.is_enabled()
                    ),
                    None,
                )
            )

            if boton:
                break

        except TimeoutException:
            boton = None

    if boton is None:
        raise RuntimeError(
            "No encontré el botón "
            f"{texto_preferido!r} en el modal."
        )

    driver.execute_script(
        "arguments[0].click();",
        boton,
    )

    esperar_cierre_modal(driver, modal)


def seleccionar_en_picker(
    driver,
    input_id,
    texto_busqueda,
    texto_exacto,
    confirmar_con="Aceptar",
    confirmar_alternativo=None,
    omitir_si_ya_esta=True,
):
    """
    Flujo robusto:

    1. Comprueba si el valor ya está seleccionado.
    2. Limpia el picker.
    3. Abre explícitamente la lupa.
    4. Busca dentro del modal.
    5. Marca el checkbox exacto.
    6. Pulsa Aplicar o Aceptar.
    """

    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    campo = wait.until(
        EC.presence_of_element_located((By.ID, input_id))
    )

    contenedor = obtener_contenedor_picker(campo)

    if omitir_si_ya_esta:
        seleccionados = obtener_textos_seleccionados(
            contenedor
        )

        if texto_exacto in seleccionados:
            print(
                f"Ya estaba seleccionado: {texto_exacto}"
            )
            return

    limpiar_picker(driver, input_id)

    modal = abrir_picker(driver, input_id)

    buscar_dentro_modal(
        driver,
        modal,
        texto_busqueda,
    )

    seleccionar_fila_exacta(
        driver,
        modal,
        texto_exacto,
    )

    confirmar_modal(
        driver,
        modal,
        confirmar_con,
        confirmar_alternativo,
    )

    time.sleep(2)


# ============================================================
# FILTROS DE CONSULTA
# ============================================================

def escribir_asignado_a(driver):
    print("Preparando filtro Asignado a...")

    seleccionar_en_picker(
        driver=driver,
        input_id="autoID24",
        texto_busqueda=ASIGNADO_A_BUSQUEDA,
        texto_exacto=ASIGNADO_A_FINAL,
        confirmar_con="Aceptar",
        omitir_si_ya_esta=True,
    )


def seleccionar_tipo_mantenimiento(driver):
    print("Preparando Tipo de mantenimiento...")

    seleccionar_en_picker(
        driver=driver,
        input_id="autoID39",
        texto_busqueda=TIPO_BUSQUEDA,
        texto_exacto=TIPO_MANTENIMIENTO,
        confirmar_con="Aceptar",
        omitir_si_ya_esta=True,
    )


def convertir_fecha_configurada(fecha_texto, nombre_variable):
    try:
        return datetime.strptime(fecha_texto.strip(), "%d/%m/%Y")
    except ValueError as error:
        raise ValueError(
            f"{nombre_variable} debe tener formato DD/MM/AAAA. "
            f"Valor recibido: {fecha_texto!r}"
        ) from error


def _parsear_mes_anio(texto):
    texto_normalizado = normalizar_comparacion(texto)

    meses = {
        "january": 1, "enero": 1,
        "february": 2, "febrero": 2,
        "march": 3, "marzo": 3,
        "april": 4, "abril": 4,
        "may": 5, "mayo": 5,
        "june": 6, "junio": 6,
        "july": 7, "julio": 7,
        "august": 8, "agosto": 8,
        "september": 9, "septiembre": 9,
        "october": 10, "octubre": 10,
        "november": 11, "noviembre": 11,
        "december": 12, "diciembre": 12,
    }

    anio_match = re.search(r"\b(20\d{2})\b", texto_normalizado)
    if not anio_match:
        return None

    for nombre_mes, numero_mes in meses.items():
        if nombre_mes in texto_normalizado:
            return int(anio_match.group(1)), numero_mes

    return None


def _obtener_tablas_calendario(modal):
    tablas = []

    for tabla in modal.find_elements(By.CSS_SELECTOR, "table"):
        try:
            if not tabla.is_displayed():
                continue

            celdas_dia = tabla.find_elements(
                By.XPATH,
                ".//td[contains(@class,'day') or normalize-space(text()) != '']"
            )
            encabezados = tabla.find_elements(
                By.CSS_SELECTOR,
                "th.datepicker-switch, th.switch, .datepicker-switch"
            )

            if celdas_dia and encabezados:
                tablas.append(tabla)
        except StaleElementReferenceException:
            continue

    return tablas


def _seleccionar_fecha_en_panel(driver, modal, fecha_objetivo, indice_panel):
    objetivo_meses = fecha_objetivo.year * 12 + fecha_objetivo.month

    for _ in range(48):
        tablas = _obtener_tablas_calendario(modal)

        if not tablas:
            raise RuntimeError("No se encontraron las tablas del calendario.")

        panel = tablas[min(indice_panel, len(tablas) - 1)]

        encabezado = next(
            (
                elemento
                for elemento in panel.find_elements(
                    By.CSS_SELECTOR,
                    "th.datepicker-switch, th.switch, .datepicker-switch"
                )
                if elemento.is_displayed() and elemento.text.strip()
            ),
            None,
        )

        if encabezado is None:
            raise RuntimeError("No se pudo leer el mes visible del calendario.")

        mes_anio = _parsear_mes_anio(encabezado.text)
        if mes_anio is None:
            raise RuntimeError(
                f"No se pudo interpretar el encabezado del calendario: {encabezado.text!r}"
            )

        anio_actual, mes_actual = mes_anio
        actual_meses = anio_actual * 12 + mes_actual

        if actual_meses == objetivo_meses:
            celdas = panel.find_elements(
                By.XPATH,
                f".//td[normalize-space()='{fecha_objetivo.day}' "
                "and not(contains(@class,'old')) "
                "and not(contains(@class,'new')) "
                "and not(contains(@class,'disabled'))]"
            )

            celda = next(
                (
                    elemento
                    for elemento in celdas
                    if elemento.is_displayed() and elemento.is_enabled()
                ),
                None,
            )

            if celda is None:
                raise RuntimeError(
                    f"No se encontró el día {fecha_objetivo.day} en el calendario."
                )

            driver.execute_script("arguments[0].click();", celda)
            time.sleep(0.8)
            return

        selector = "th.next, .next" if actual_meses < objetivo_meses else "th.prev, .prev"
        boton = next(
            (
                elemento
                for elemento in panel.find_elements(By.CSS_SELECTOR, selector)
                if elemento.is_displayed() and elemento.is_enabled()
            ),
            None,
        )

        if boton is None:
            raise RuntimeError("No se encontró el botón para cambiar de mes.")

        driver.execute_script("arguments[0].click();", boton)
        time.sleep(0.5)

    raise RuntimeError("No se pudo llegar al mes configurado en el calendario.")


def obtener_contenedor_calendario_visible(driver, segundos=TIEMPO_ESPERA):
    """Localiza el selector de rango de fechas visible de Plex.

    El calendario de Plex no siempre se renderiza como ``div.modal``;
    en algunas sesiones aparece como panel flotante. Por eso se busca
    por su estructura real: tablas de calendario visibles y botón Aceptar.
    """

    def buscar_contenedor(d):
        candidatos = d.find_elements(
            By.XPATH,
            "//*[.//table and (.//button[normalize-space()='Aceptar'] or .//a[normalize-space()='Aceptar'])]"
        )

        visibles = []
        for elemento in candidatos:
            try:
                if not elemento.is_displayed():
                    continue

                tablas_visibles = [
                    tabla for tabla in elemento.find_elements(By.CSS_SELECTOR, "table")
                    if tabla.is_displayed()
                ]

                if tablas_visibles:
                    visibles.append(elemento)
            except StaleElementReferenceException:
                continue

        if not visibles:
            return False

        # Se elige el contenedor visible más pequeño para evitar tomar body/html.
        return min(
            visibles,
            key=lambda e: e.size.get("width", 999999) * e.size.get("height", 999999)
        )

    return WebDriverWait(driver, segundos).until(buscar_contenedor)


def esperar_cierre_calendario(driver, contenedor, segundos=TIEMPO_ESPERA):
    try:
        WebDriverWait(driver, segundos).until(EC.staleness_of(contenedor))
        return
    except TimeoutException:
        pass

    WebDriverWait(driver, segundos).until(
        lambda d: not contenedor.is_displayed()
    )


def escribir_fecha_vencimiento(driver):
    """Captura el rango directamente en autoID63.

    Plex enlaza este control mediante Knockout. Escribir el rango en el
    input y disparar sus eventos es más estable que depender de la
    estructura interna del calendario flotante, la cual cambia entre
    sesiones y versiones.
    """
    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    fecha_inicio = convertir_fecha_configurada(FECHA_INICIO, "FECHA_INICIO")
    fecha_fin = convertir_fecha_configurada(FECHA_FIN, "FECHA_FIN")

    if fecha_inicio > fecha_fin:
        raise ValueError("FECHA_INICIO no puede ser posterior a FECHA_FIN.")

    rango_plex = (
        f"{fecha_inicio.month}/{fecha_inicio.day}/{fecha_inicio.year} - "
        f"{fecha_fin.month}/{fecha_fin.day}/{fecha_fin.year}"
    )

    campo = wait.until(
        EC.presence_of_element_located((By.ID, "autoID63"))
    )

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        campo,
    )

    # Quitar el rango anterior guardado por Plex, si existe.
    try:
        contenedor = campo.find_element(
            By.XPATH,
            "./ancestor::div[contains(@class,'plex-picker-control')]",
        )

        botones_quitar = contenedor.find_elements(
            By.CSS_SELECTOR,
            ".plex-picker-item-remove",
        )

        for boton_quitar in botones_quitar:
            if boton_quitar.is_displayed():
                driver.execute_script(
                    "arguments[0].click();",
                    boton_quitar,
                )
                time.sleep(0.8)
    except Exception:
        pass

    campo = wait.until(
        EC.element_to_be_clickable((By.ID, "autoID63"))
    )

    campo.click()
    campo.clear()
    campo.send_keys(rango_plex)

    # Notificar a Knockout/Plex para que actualice el valor enlazado.
    driver.execute_script(
        """
        const campo = arguments[0];
        campo.dispatchEvent(new KeyboardEvent('keyup', {
            bubbles: true,
            key: 'Tab',
            code: 'Tab'
        }));
        campo.dispatchEvent(new Event('input', { bubbles: true }));
        campo.dispatchEvent(new Event('change', { bubbles: true }));
        campo.dispatchEvent(new Event('blur', { bubbles: true }));
        """,
        campo,
    )

    time.sleep(2)

    # Validar usando tanto el valor del input como el texto mostrado por Plex.
    def rango_quedo_aplicado(d):
        try:
            actual = d.find_element(By.ID, "autoID63")
            valor = (actual.get_attribute("value") or "").strip()

            contenedor_actual = actual.find_element(
                By.XPATH,
                "./ancestor::div[contains(@class,'plex-picker-control')]",
            )
            texto_visible = (contenedor_actual.text or "").strip()
            titulos = " ".join(
                (elemento.get_attribute("title") or "")
                for elemento in contenedor_actual.find_elements(
                    By.CSS_SELECTOR,
                    "[title]",
                )
            )

            combinado = f"{valor} {texto_visible} {titulos}"
            return (
                str(fecha_inicio.year) in combinado
                and str(fecha_fin.year) in combinado
                and str(fecha_inicio.day) in combinado
                and str(fecha_fin.day) in combinado
            )
        except StaleElementReferenceException:
            return False

    try:
        WebDriverWait(driver, 8).until(rango_quedo_aplicado)
    except TimeoutException as error:
        driver.save_screenshot("error_rango_fechas.png")
        raise RuntimeError(
            "Plex no conservó el rango escrito en autoID63. "
            f"Valor intentado: {rango_plex}"
        ) from error

    print(
        "Rango de fechas seleccionado: "
        f"{fecha_inicio.strftime('%d/%m/%Y')} - "
        f"{fecha_fin.strftime('%d/%m/%Y')}"
    )
    time.sleep(2)


def presionar_buscar(driver):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    print("Localizando botón Buscar principal...")

    # Esperar a que no quede ningún modal visible
    wait.until(
        lambda d: not any(
            modal.is_displayed()
            for modal in d.find_elements(By.CSS_SELECTOR, "div.modal")
        )
    )

    # Buscar únicamente dentro del formulario principal
    formulario = wait.until(
        EC.presence_of_element_located((By.ID, "workRequestFilter"))
    )

    boton = wait.until(
        lambda d: next(
            (
                elemento
                for elemento in formulario.find_elements(
                    By.XPATH,
                    ".//button[normalize-space()='Buscar']"
                )
                if elemento.is_displayed()
                and elemento.is_enabled()
            ),
            None,
        )
    )

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        boton,
    )

    time.sleep(1)

    try:
        boton.click()
    except Exception:
        driver.execute_script(
            "arguments[0].click();",
            boton,
        )

    print("Clic ejecutado en Buscar principal.")

    # Esperar a que Plex actualice la cuadrícula
    wait.until(
        EC.presence_of_element_located(
            (By.ID, "workRequestGrid")
        )
    )

    time.sleep(8)

# ============================================================
# TABLA DE RESULTADOS
# ============================================================

def obtener_links_work_requests(driver):
    WebDriverWait(driver, TIEMPO_ESPERA).until(
        EC.presence_of_element_located(
            (By.ID, "workRequestGrid")
        )
    )

    links = driver.find_elements(
        By.XPATH,
        "//div[@id='workRequestGrid']"
        "//a[contains(@href,'ViewWorkRequestForm')"
        " and starts-with(normalize-space(),'W')]"
    )

    ordenes = []
    encontrados = set()

    for link in links:
        numero = link.text.strip()
        url = link.get_attribute("href")

        if (
            numero
            and url
            and numero not in encontrados
        ):
            encontrados.add(numero)

            ordenes.append(
                {
                    "numero": numero,
                    "url": url,
                }
            )

    return ordenes


# ============================================================
# DATOS DE LA ORDEN
# ============================================================

def leer_fecha_reportada(driver):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    campo = wait.until(
        EC.presence_of_element_located(
            (By.ID, "autoID79")
        )
    )

    contenedor = campo.find_element(
        By.XPATH,
        "./ancestor::div[contains(@class,"
        "'plex-picker-control')]"
    )

    texto = contenedor.text.strip()

    texto = texto.replace("\xa0", " ")
    texto = texto.replace("a. m.", "AM")
    texto = texto.replace("p. m.", "PM")
    texto = texto.replace("a.m.", "AM")
    texto = texto.replace("p.m.", "PM")

    patron = (
        r"\d{1,2}/\d{1,2}/\d{4}"
        r"\s+\d{1,2}:\d{2}\s*(AM|PM)"
    )

    match = re.search(
        patron,
        texto,
        re.IGNORECASE,
    )

    if not match:
        raise RuntimeError(
            "No pude leer la fecha reportada. "
            f"Texto encontrado: {texto!r}"
        )

    fecha_txt = match.group(0)

    return datetime.strptime(
        fecha_txt,
        "%m/%d/%Y %I:%M %p",
    )


def obtener_turno_por_hora(fecha_hora):
    hora = fecha_hora.time()

    inicio_turno_1 = datetime.strptime(
        "06:00",
        "%H:%M",
    ).time()

    inicio_turno_2 = datetime.strptime(
        "14:00",
        "%H:%M",
    ).time()

    inicio_turno_3 = datetime.strptime(
        "21:30",
        "%H:%M",
    ).time()

    if inicio_turno_1 <= hora < inicio_turno_2:
        return 1

    if inicio_turno_2 <= hora < inicio_turno_3:
        return 2

    return 3


def obtener_usuario_aleatorio(cn, fecha_hora):
    idturno = obtener_turno_por_hora(
        fecha_hora
    )

    cursor = cn.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT idusuario, nombre
            FROM usuario
            WHERE idgrupo = %s
            ORDER BY RAND()
            LIMIT 1
            """,
            (idturno,),
        )

        usuario = cursor.fetchone()

    finally:
        cursor.close()

    if not usuario:
        raise RuntimeError(
            f"No existen usuarios para el turno {idturno}."
        )

    return usuario


# ============================================================
# ASIGNACIÓN DENTRO DEL WORK REQUEST
# ============================================================
def normalizar_texto(texto):
    return " ".join(
        texto.replace("\xa0", " ")
        .strip()
        .lower()
        .split()
    )


def asignar_usuario_orden(driver, idusuario, nombre_tecnico):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    # Plex normalmente muestra:
    # 04411 FLOR, Marco
    texto_busqueda = f"{idusuario} {nombre_tecnico}".strip()

    print(f"Asignando técnico: {texto_busqueda}")

    # --------------------------------------------------------
    # 1. Limpiar selección anterior
    # --------------------------------------------------------
    limpiar_picker(driver, "autoID69")

    campo = wait.until(
        EC.element_to_be_clickable((By.ID, "autoID69"))
    )

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        campo,
    )

    campo.click()
    campo.clear()

    # Usamos principalmente el idusuario porque es único
    campo.send_keys(idusuario)

    time.sleep(1)

    # --------------------------------------------------------
    # 2. Abrir lupa del picker
    # --------------------------------------------------------
    contenedor = obtener_contenedor_picker(campo)

    icono = wait.until(
        lambda d: next(
            (
                elemento
                for elemento in contenedor.find_elements(
                    By.CSS_SELECTOR,
                    "a.plex-picker-icon"
                )
                if elemento.is_displayed()
                and elemento.is_enabled()
            ),
            None,
        )
    )

    driver.execute_script(
        "arguments[0].click();",
        icono,
    )

    modal = obtener_modal_visible(driver)

    print("Modal Asignado a abierto.")

    # --------------------------------------------------------
    # 3. Primero intentar seleccionar directamente de la lista
    # --------------------------------------------------------
    def buscar_fila_directa(d):
        filas = modal.find_elements(
            By.CSS_SELECTOR,
            "tbody tr.plex-grid-row.selectable"
        )

        for fila in filas:
            try:
                if not fila.is_displayed():
                    continue

                texto_fila = normalizar_texto(fila.text)

                if normalizar_texto(idusuario) in texto_fila:
                    return fila

            except StaleElementReferenceException:
                continue

        return False

    try:
        fila_tecnico = WebDriverWait(driver, 8).until(
            buscar_fila_directa
        )

    except TimeoutException:
        # ----------------------------------------------------
        # 4. Si no aparece, usar el buscador interno del modal
        # ----------------------------------------------------
        print("Técnico no visible todavía. Ejecutando búsqueda interna...")

        campo_busqueda = wait.until(
            lambda d: next(
                (
                    elemento
                    for elemento in modal.find_elements(
                        By.CSS_SELECTOR,
                        ".plex-picker-search input[type='text']"
                    )
                    if elemento.is_displayed()
                    and elemento.is_enabled()
                ),
                None,
            )
        )

        campo_busqueda.click()
        campo_busqueda.clear()
        campo_busqueda.send_keys(idusuario)

        boton_buscar = wait.until(
            lambda d: next(
                (
                    boton
                    for boton in modal.find_elements(
                        By.XPATH,
                        ".//button[normalize-space()='Buscar']"
                    )
                    if boton.is_displayed()
                    and boton.is_enabled()
                ),
                None,
            )
        )

        driver.execute_script(
            "arguments[0].click();",
            boton_buscar,
        )

        print("Búsqueda interna enviada.")

        fila_tecnico = wait.until(
            buscar_fila_directa
        )

    # --------------------------------------------------------
    # 5. Seleccionar fila
    # --------------------------------------------------------
    texto_encontrado = fila_tecnico.text.strip()

    print(f"Técnico encontrado: {texto_encontrado}")

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        fila_tecnico,
    )

    time.sleep(0.5)

    try:
        fila_tecnico.click()
    except Exception:
        driver.execute_script(
            "arguments[0].click();",
            fila_tecnico,
        )

    # El modal de selección única debe cerrarse automáticamente
    esperar_cierre_modal(driver, modal)

    print("Modal cerrado después de seleccionar técnico.")

    # --------------------------------------------------------
    # 6. Confirmar que el técnico quedó en autoID69
    # --------------------------------------------------------
    campo = wait.until(
        EC.presence_of_element_located((By.ID, "autoID69"))
    )

    contenedor = obtener_contenedor_picker(campo)

    wait.until(
        lambda d: any(
            normalizar_texto(idusuario) in normalizar_texto(texto)
            for texto in obtener_textos_seleccionados(contenedor)
        )
    )

    print(f"Técnico asignado correctamente: {texto_encontrado}")


def normalizar_comparacion(texto):
    texto = str(texto or "").strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )
    return " ".join(texto.split())


def escribir_control_plex(driver, elemento, texto):
    """Escribe y notifica a Knockout/Plex los cambios del control."""
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        elemento,
    )

    elemento.click()
    elemento.clear()
    elemento.send_keys(str(texto))

    driver.execute_script(
        """
        const elemento = arguments[0];
        elemento.dispatchEvent(new Event('input', { bubbles: true }));
        elemento.dispatchEvent(new Event('change', { bubbles: true }));
        elemento.dispatchEvent(new Event('blur', { bubbles: true }));
        """,
        elemento,
    )
    time.sleep(0.8)


def leer_descripcion_orden(driver):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)
    campo = wait.until(
        EC.presence_of_element_located((By.ID, "autoID113"))
    )
    valor = campo.get_attribute("value")
    if valor is None:
        valor = campo.text
    return (valor or "").strip()


def leer_equipment_id_orden(driver):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    grupo_equipo = wait.until(
        EC.presence_of_element_located((By.ID, "autoID37"))
    )

    etiquetas = grupo_equipo.find_elements(
        By.CSS_SELECTOR,
        "span.plex-readonly-label",
    )

    equipment_id = next(
        (
            etiqueta.text.strip()
            for etiqueta in etiquetas
            if etiqueta.is_displayed() and etiqueta.text.strip()
        ),
        "",
    )

    if not equipment_id:
        raise RuntimeError("El campo ID del equipo está vacío.")

    print(f"Equipo leído en Plex: {equipment_id}")
    return equipment_id


def obtener_historial_aleatorio_equipo(cn, equipment_id):
    cursor = cn.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                WorkRequestNo,
                Note,
                EquipmentGroup,
                EquipmentID
            FROM work_requests
            WHERE UPPER(TRIM(EquipmentID)) = UPPER(TRIM(%s))
              AND Note IS NOT NULL
              AND CHAR_LENGTH(
                    TRIM(
                        REPLACE(
                            REPLACE(
                                REPLACE(Note, CHAR(13), ''),
                                CHAR(10), ''
                            ),
                            CHAR(9), ''
                        )
                    )
                  ) > 0
              AND LOWER(TRIM(Note)) NOT IN ('null', 'none', 'n/a', 'na')
              AND EquipmentGroup IS NOT NULL
              AND TRIM(EquipmentGroup) <> ''
            ORDER BY RAND()
            LIMIT 1
            """,
            (equipment_id,),
        )
        registro = cursor.fetchone()
    finally:
        cursor.close()

    if not registro:
        raise RuntimeError(
            "No existe un registro histórico utilizable "
            f"para el equipo: {equipment_id}"
        )

    return registro


def escribir_nota_orden(driver, texto):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)
    nota = wait.until(
        EC.element_to_be_clickable((By.ID, "autoID118"))
    )

    escribir_control_plex(driver, nota, texto)

    valor_final = (nota.get_attribute("value") or "").strip()
    if not valor_final:
        raise RuntimeError(
            "Plex no conservó el texto escrito en NoteArea."
        )

    print(f"Nota capturada: {valor_final}")


def seleccionar_equipment_group(driver, equipment_group):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)
    combo_elemento = wait.until(
        EC.element_to_be_clickable((By.ID, "autoID56"))
    )

    combo = Select(combo_elemento)
    valor_buscado = normalizar_comparacion(equipment_group)
    opcion_encontrada = None

    for opcion in combo.options:
        texto_opcion = opcion.text.strip()
        if normalizar_comparacion(texto_opcion) == valor_buscado:
            opcion_encontrada = texto_opcion
            break

    if opcion_encontrada is None:
        disponibles = [
            opcion.text.strip()
            for opcion in combo.options
            if opcion.text.strip()
        ]
        raise RuntimeError(
            f"EquipmentGroup {equipment_group!r} no coincide con "
            f"ninguna opción de autoID56. Opciones: {disponibles}"
        )

    combo.select_by_visible_text(opcion_encontrada)

    driver.execute_script(
        """
        arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
        arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));
        """,
        combo_elemento,
    )
    time.sleep(1)

    seleccionado = Select(combo_elemento).first_selected_option.text.strip()
    if normalizar_comparacion(seleccionado) != valor_buscado:
        raise RuntimeError(
            "Plex no conservó el tipo de falla seleccionado."
        )

    print(f"Tipo de falla seleccionado: {seleccionado}")


def capturar_tiempo_aleatorio(driver):
    """
    Genera de 6 a 89 minutos y los captura como horas decimales.
   
    """
    wait = WebDriverWait(driver, TIEMPO_ESPERA)
    minutos = random.randint(10, 89)
    horas = round(minutos / 60, 2)

    campo_horas = wait.until(
        EC.element_to_be_clickable((By.ID, "autoID106"))
    )

    escribir_control_plex(driver, campo_horas, f"{minutos}")

    valor_final = (campo_horas.get_attribute("value") or "").strip()
    if not valor_final:
        raise RuntimeError("Plex no conservó el valor de Hours.")

    print(
        f"Tiempo capturado: {minutos} minutos "
        f"({horas:.2f} horas)"
    )
    return minutos, horas


def completar_datos_orden(driver, cn):
    descripcion = leer_descripcion_orden(driver)
    print("Descripción:", descripcion if descripcion else "[VACÍA]")

    if not descripcion:
        escribir_nota_orden(driver, NOTA_SIN_DESCRIPCION)
        print("Orden sin descripción; se usó la nota fija.")
    else:
        equipment_id = leer_equipment_id_orden(driver)
        historial = obtener_historial_aleatorio_equipo(cn, equipment_id)

        print(
            "Registro histórico seleccionado:",
            historial["WorkRequestNo"],
        )
        print(
            "EquipmentGroup histórico:",
            historial["EquipmentGroup"],
        )

        escribir_nota_orden(driver, historial["Note"])
        seleccionar_equipment_group(
            driver,
            historial["EquipmentGroup"],
        )

    capturar_tiempo_aleatorio(driver)


def aplicar_y_completar_orden(driver):
    wait = WebDriverWait(driver, TIEMPO_ESPERA)

    boton_aplicar = wait.until(
        EC.element_to_be_clickable((By.ID, "autoID34"))
    )

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        boton_aplicar,
    )
    time.sleep(0.8)
    driver.execute_script("arguments[0].click();", boton_aplicar)
    print("Clic realizado en Apply, autoID34.")

    time.sleep(3)

    boton_completo = wait.until(
        EC.element_to_be_clickable((By.ID, "autoID13"))
    )

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        boton_completo,
    )
    time.sleep(0.8)

    url_antes = driver.current_url
    driver.execute_script("arguments[0].click();", boton_completo)
    print("Clic realizado en Completo, autoID13.")

    try:
        WebDriverWait(driver, TIEMPO_ESPERA).until(
            lambda d:
                d.current_url != url_antes
                or bool(d.find_elements(By.ID, "workRequestGrid"))
                or any(
                    banner.is_displayed() and banner.text.strip()
                    for banner in d.find_elements(
                        By.CSS_SELECTOR,
                        ".plex-banner",
                    )
                )
        )
    except TimeoutException:
        driver.save_screenshot("error_completar_orden.png")
        raise RuntimeError(
            "Se pulsaron Apply y Completo, pero Plex no mostró respuesta."
        )

    time.sleep(4)


def procesar_orden(driver, cn, wr):
    print("=" * 60)
    print(f"Abriendo orden: {wr['numero']}")

    driver.get(wr["url"])
    esperar_pagina(driver)
    time.sleep(4)

    fecha_reportada = leer_fecha_reportada(driver)
    print(
        "Fecha reportada:",
        fecha_reportada.strftime("%d/%m/%Y %H:%M:%S"),
    )

    usuario = obtener_usuario_aleatorio(cn, fecha_reportada)
    print(
        "Técnico seleccionado desde MySQL:",
        usuario["idusuario"],
        "-",
        usuario["nombre"],
    )

    asignar_usuario_orden(
        driver,
        str(usuario["idusuario"]),
        usuario["nombre"],
    )

    completar_datos_orden(driver, cn)
    aplicar_y_completar_orden(driver)

    print(f"{wr['numero']} procesada y completada.")


def volver_a_resultados(driver):
    """
    Plex puede regresar automáticamente a la consulta
    después de Aceptar. Solo usa back si la tabla no está.
    """

    try:
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located(
                (By.ID, "workRequestGrid")
            )
        )

        print("Plex regresó automáticamente a resultados.")
        return

    except TimeoutException:
        pass

    print("Regresando manualmente a resultados...")

    driver.back()
    esperar_pagina(driver)

    WebDriverWait(driver, TIEMPO_ESPERA).until(
        EC.presence_of_element_located(
            (By.ID, "workRequestGrid")
        )
    )

    time.sleep(3)


# ============================================================
# MAIN
# ============================================================

def main():
    driver = None
    cn = None

    try:
        driver = iniciar_driver()
        cn = conectar_mysql()

        wait = WebDriverWait(
            driver,
            TIEMPO_ESPERA,
        )

        driver.get(URL_WORK_REQUESTS)
        esperar_pagina(driver)

        wait.until(
            EC.presence_of_element_located(
                (By.ID, "workRequestFilter")
            )
        )

        print("Página Work Requests cargada.")

        escribir_asignado_a(driver)
        print("Asignado a seleccionado.")

        seleccionar_tipo_mantenimiento(driver)
        print("Tipo de mantenimiento seleccionado.")

        escribir_fecha_vencimiento(driver)
        print("Fecha seleccionada.")

        presionar_buscar(driver)
        print("Búsqueda enviada.")

        while True:
            ordenes = obtener_links_work_requests(
                driver
            )

            if not ordenes:
                print(
                    "Ya no hay órdenes en este filtro."
                )
                break

            print(
                f"Órdenes encontradas: {len(ordenes)}"
            )

            for wr in ordenes:
                try:
                    procesar_orden(
                        driver,
                        cn,
                        wr,
                    )

                    volver_a_resultados(driver)

                except (
                    InvalidSessionIdException,
                    NoSuchWindowException,
                ):
                    print(
                        "La sesión de Chrome terminó."
                    )
                    raise

                except Exception as error:
                    print("=" * 60)
                    print(
                        f"ERROR EN {wr['numero']}"
                    )
                    print(
                        f"Tipo: {type(error).__name__}"
                    )
                    print(f"Detalle: {error}")

                    traceback.print_exc()

                    if sesion_activa(driver):
                        try:
                            driver.save_screenshot(
                                f"error_{wr['numero']}.png"
                            )
                        except Exception:
                            pass

                        try:
                            volver_a_resultados(driver)
                        except Exception:
                            print(
                                "No fue posible regresar "
                                "a resultados."
                            )
                    else:
                        raise

            print(
                "Revisando si quedan órdenes "
                "en el filtro actual..."
            )

            time.sleep(4)

    except InvalidSessionIdException:
        print(
            "Chrome fue cerrado o la sesión quedó inválida."
        )

    except NoSuchWindowException:
        print(
            "La ventana de Chrome fue cerrada."
        )

    except Exception as error:
        print("=" * 60)
        print("ERROR GENERAL")
        print(type(error).__name__, error)

        traceback.print_exc()

        if driver and sesion_activa(driver):
            try:
                driver.save_screenshot(
                    "error_general.png"
                )
            except Exception:
                pass

    finally:
        if cn:
            try:
                cn.close()
            except Exception:
                pass

        if driver and sesion_activa(driver):
            input(
                "Proceso detenido o terminado. "
                "Presiona ENTER para cerrar..."
            )

            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
