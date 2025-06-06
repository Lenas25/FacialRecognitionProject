import psycopg2
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import pyautogui
import cv2
import time
from datetime import datetime
import socket
import os


# Función para obtener el nombre de la computadora
def obtener_nombre_computadora():
    return socket.gethostname()

# Función para obtener la etiqueta del salón desde la base de datos
def obtener_salon_desde_bd(nombre_computadora):
    cursor.execute("""
        SELECT s.etiqueta
        FROM computadora c
        JOIN salon s ON c.id_salon = s.id
        WHERE c.nombre = %s
    """, (nombre_computadora,))
    resultado = cursor.fetchone()
    return resultado[0] if resultado else None

# Esperar hasta que inicie la clase
def esperar_inicio_clase(hora_inicio_time):
    print(f"Esperando a que inicie la clase a las {hora_inicio_time.strftime('%H:%M')}...")
    while True:
        ahora = datetime.now().time()
        if ahora >= hora_inicio_time:
            print("Hora de inicio alcanzada. Iniciando proceso.")
            break
        time.sleep(30)

# Esperar hasta que finalice la clase
def esperar_fin_clase(hora_fin_time):
    print(f"Clase en curso. Esperando hasta las {hora_fin_time.strftime('%H:%M')} para finalizar...")
    while True:
        ahora = datetime.now().time()
        if ahora >= hora_fin_time:
            print("Hora de fin alcanzada. Cerrando sesión.")
            os.system("shutdown /l")  # Cierra sesión en Windows
            break
        time.sleep(30)

# Función para buscar y esperar a que haya una clase activa
def buscar_y_esperar_clase():
    while True:
        current_time = datetime.now()
        current_time_str = current_time.strftime("%H:%M")
        dia_actual = current_time.strftime('%A').lower()
        dia_actual_bd = dias_traducidos.get(dia_actual, "")

        cursor.execute("""
            SELECT c.nombre, h.hora_inicio, h.hora_fin, p.correo, p.contrasena, s.etiqueta
            FROM horario h
            JOIN curso c ON h.id_curso = c.id
            JOIN profesor p ON h.id_profesor = p.id
            JOIN salon s ON h.id_salon = s.id
            WHERE h.hora_inicio::time <= %s::time
            AND h.hora_fin::time >= %s::time
            AND s.etiqueta = %s
            AND h.dia_semana = %s
        """, (current_time_str, current_time_str, salon_detectado, dia_actual_bd))

        resultados = cursor.fetchall()

        for resultado in resultados:
            curso_nombre, hora_inicio, hora_fin, correo, contrasena, salon_etiqueta = resultado
            if salon_etiqueta == salon_detectado:
                return (curso_nombre, correo, contrasena, hora_inicio, hora_fin)

        print(f"[{current_time_str}] No hay clases aún. Reintentando")
        time.sleep(1)


# Conexión a la base de datos PostgreSQL
try:
    conexion = psycopg2.connect(
        host="localhost",
        port=5432,
        user="postgres",
        password="teamomama123",
        dbname="db_reconocimiento"
    )
    cursor = conexion.cursor()
except Exception as e:
    print("Error al conectar con PostgreSQL:", e)
    exit()

# Diccionario para traducir día al formato de la BD
dias_traducidos = {
    "monday": "lunes",
    "tuesday": "martes",
    "wednesday": "miércoles",
    "thursday": "jueves",
    "friday": "viernes",
    "saturday": "sábado",
    "sunday": "domingo"
}

# Obtener el nombre de la computadora y el salón
nombre_computadora = obtener_nombre_computadora()
print(f"Computadora detectada: {nombre_computadora}")
salon_detectado = obtener_salon_desde_bd(nombre_computadora)

if not salon_detectado:
    print("No se pudo detectar el salón de la computadora. Saliendo...")
    cursor.close()
    conexion.close()
    exit()

print(f"Salón detectado: {salon_detectado}")

# Buscar y esperar a que haya clase
curso_seleccionado = buscar_y_esperar_clase()

# Si se encuentra curso, proceder
curso_nombre, correo, contrasena, hora_inicio, hora_fin = curso_seleccionado
print(f"Curso encontrado: {curso_nombre} ({hora_inicio} - {hora_fin})")
print(f"Profesor: {correo}")

# Asignar directamente (ya son datetime.time)
hora_inicio_time = hora_inicio
hora_fin_time = hora_fin

# Esperar inicio real
esperar_inicio_clase(hora_inicio_time)

# Lanzar navegador y entrar a la plataforma
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service)
driver.maximize_window()
print("Ventana de Chrome maximizada.")

try:
    driver.get("https://class.utp.edu.pe")
    time.sleep(5)

    driver.find_element(By.ID, "username").send_keys(correo)
    driver.find_element(By.ID, "password").send_keys(contrasena)
    driver.find_element(By.ID, "kc-login").click()
    print("Credenciales ingresadas y login ejecutado.")

    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

    try:
        xpath = f"//a[@data-testid='course-card-container'][.//div[contains(normalize-space(), '{curso_nombre}')]]"
        print(f"Buscando card del curso '{curso_nombre}'...")

        card = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
        card.click()
        print(f"Se hizo clic en el curso '{curso_nombre}'.")
        time.sleep(5)

        xpath_zoom = "//span[@class='sb-tab--text' and text()='Zoom']"
        zoom_button = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, xpath_zoom))
        )
        zoom_button.click()
        print("Se hizo clic en la pestaña 'Zoom'.")
        time.sleep(5)

        print("Buscando botón 'Unirse al Zoom'...")
        botones = driver.find_elements(By.TAG_NAME, "button")
        boton_zoom = next((b for b in botones if "Unirse al zoom" in b.text), None)

        if boton_zoom:
            boton_zoom.click()
            print("Se hizo clic en el botón 'Unirse al Zoom'.")
            time.sleep(3)

            pyautogui.press('tab')
            pyautogui.press('space')
            pyautogui.press('tab')
            pyautogui.press('enter')
            print("Confirmación de abrir Zoom enviada.")
            time.sleep(16)

            carpeta_actual = os.path.dirname(os.path.abspath(__file__))

            # Construir ruta relativa a la imagen dentro de esa carpeta
            ruta_imagen = os.path.join(carpeta_actual, "audio_compartido.PNG")

            # Ahora puedes usar ruta_imagen con cv2.imread()
            imagen = cv2.imread(ruta_imagen)
            print(f"Intentando cargar imagen desde: {ruta_imagen}")
            imagen = cv2.imread(ruta_imagen)
            if imagen is None:
                print(f"No se pudo cargar la imagen desde {ruta_imagen}. Revisa la ruta o el formato.")
            else:
                print("Imagen cargada correctamente, buscando en pantalla...")
                time.sleep(2)
                boton_audio = pyautogui.locateCenterOnScreen(ruta_imagen, confidence=0.8)
                if boton_audio:
                    pyautogui.click(boton_audio)
                    print("Se hizo clic en 'Unirse con el audio compartido'.")
                else:
                    print("No se encontró el botón 'Unirse con el audio compartido' en pantalla.")
        else:
            print("No se encontró ningún botón con el texto 'Unirse al zoom'.")

    except Exception as e:
        print(f"Error al interactuar con el curso o Zoom: {e}")
        with open("error_page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("HTML guardado para depuración en 'error_page.html'.")

except Exception as e:
    print(f"Error durante la navegación: {e}")

# Esperar hasta fin de clase
esperar_fin_clase(hora_fin_time)

# Ahora sí cerramos Chrome al terminar la clase
driver.quit()

# Cierre de recursos
cursor.close()
conexion.close()
