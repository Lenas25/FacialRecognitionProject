import mysql.connector  # type: ignore
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import pyautogui
import time
from datetime import datetime
import socket

# Función para obtener el nombre de la computadora
def obtener_nombre_computadora():
    return socket.gethostname()  # Obtiene el nombre de la computadora

# Función para obtener el salón desde la base de datos usando el nombre de la computadora
def obtener_salon_desde_bd(nombre_computadora):
    cursor.execute("""
        SELECT salon FROM computadoras WHERE nombre_computadora = %s
    """, (nombre_computadora,))
    resultado = cursor.fetchone()
    if resultado:
        return resultado[0]
    else:
        return None

# Conectarse a la base de datos
conexion = mysql.connector.connect(
    host="localhost",
    user="root",
    password="teamomama123",
    database="optia"
)

cursor = conexion.cursor()

# Obtener la hora actual
current_time = datetime.now()
current_time_str = current_time.strftime("%H:%M")
print(f"Hora actual: {current_time_str}")

# Obtener el nombre de la computadora
nombre_computadora = obtener_nombre_computadora()
print(f"Computadora detectada: {nombre_computadora}")

# Obtener el salón correspondiente a esta computadora
salon_detectado = obtener_salon_desde_bd(nombre_computadora)

if not salon_detectado:
    print("No se pudo detectar el salón de la computadora. Saliendo...")
    exit()

print(f"Salón detectado: {salon_detectado}")

# Seleccionar los cursos y los profesores que están en el horario actual para el salón detectado
cursor.execute("""
    SELECT c.nombre, h.hora_inicio, h.hora_fin, p.correo, p.contrasena, s.etiqueta
    FROM horario h
    JOIN curso c ON h.id_curso = c.id
    JOIN profesor p ON h.id_profesor = p.id
    JOIN salon s ON h.id_salon = s.id
    WHERE STR_TO_DATE(h.hora_inicio, '%H:%i') <= STR_TO_DATE(%s, '%H:%i')
    AND STR_TO_DATE(h.hora_fin, '%H:%i') >= STR_TO_DATE(%s, '%H:%i')
    AND s.etiqueta = %s
""", (current_time_str, current_time_str, salon_detectado))

# Recuperar todos los resultados
resultados = cursor.fetchall()

# Filtrar por el salón detectado
curso_seleccionado = None
for resultado in resultados:
    curso_nombre, hora_inicio, hora_fin, correo, contrasena, salon_etiqueta = resultado
    if salon_etiqueta == salon_detectado:  # Usar el salón detectado
        curso_seleccionado = (curso_nombre, correo, contrasena)
        break

if curso_seleccionado:
    curso_nombre, correo, contrasena = curso_seleccionado
    print(f"Curso encontrado: {curso_nombre} ({hora_inicio} - {hora_fin})")
    print(f"Profesor: {correo}")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service)
    driver.maximize_window()
    print("Ventana de Chrome maximizada.")

    try:
        driver.get("https://class.utp.edu.pe")
        time.sleep(5)

        # Login
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

            # Buscar botón con texto 'Unirse al zoom' sin importar clase
            print("Buscando botón 'Unirse al Zoom'...")
            botones = driver.find_elements(By.TAG_NAME, "button")
            boton_zoom = None

            for boton in botones:
                if "Unirse al zoom" in boton.text:
                    boton_zoom = boton
                    break

            if boton_zoom:
                boton_zoom.click()
                print("Se hizo clic en el botón 'Unirse al Zoom'.")
                
                # Espera a que aparezca el diálogo externo de Chrome para abrir Zoom
                time.sleep(3)  # Ajusta si es necesario

                # Controlar el diálogo externo con pyautogui
                pyautogui.press('tab')    # mueve foco a "Recordar mi elección"
                pyautogui.press('space')  # marca la casilla
                pyautogui.press('tab')    # mueve foco a botón "Abrir Zoom Meetings"
                pyautogui.press('enter')  # acepta abrir Zoom
                
                print("Confirmación de abrir Zoom enviada.")
                time.sleep(10)  # espera a que Zoom abra
                
            else:
                print("No se encontró ningún botón con el texto 'Unirse al zoom'.")

        except Exception as e:
            print(f"Error al interactuar con el curso o Zoom: {e}")
            with open("error_page.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("HTML guardado para depuración en 'error_page.html'.")

    except Exception as e:
        print(f"Error durante la navegación: {e}")
    finally:
        driver.quit()
else:
    print("No se encontró un curso en el horario actual o el salón no tiene clases asignadas.")

# Cerrar conexión
cursor.close()
conexion.close()
