# ScriptAutomatizadoprofesor.py
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import pyautogui
import cv2
import time
import threading
import os
from datetime import datetime

app = Flask(__name__)

def esperar_inicio_clase(hora_inicio_time):
    print(f"Esperando a que inicie la clase a las {hora_inicio_time.strftime('%H:%M')}...")
    while True:
        ahora = datetime.now().time()
        if ahora >= hora_inicio_time:
            print("Hora de inicio alcanzada. Iniciando proceso.")
            break
        time.sleep(30)

def esperar_fin_clase(hora_fin_time):
    print(f"Clase en curso. Esperando hasta las {hora_fin_time.strftime('%H:%M')} para finalizar...")
    while True:
        ahora = datetime.now().time()
        if ahora >= hora_fin_time:
            print("Hora de fin alcanzada. Cerrando sesión.")
            os.system("shutdown /l")
            break
        time.sleep(30)

def iniciar_clase_automatizada(datos):
    curso_nombre = datos['curso']
    correo = datos['correo']
    contrasena = datos['contrasena']
    hora_inicio_str = datos['hora_inicio']
    hora_fin_str = datos['hora_fin']

    hora_inicio_time = datetime.strptime(hora_inicio_str, "%H:%M").time()
    hora_fin_time = datetime.strptime(hora_fin_str, "%H:%M").time()

    print(f"Iniciando clase de {curso_nombre} para {correo}...")

    esperar_inicio_clase(hora_inicio_time)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service)
    driver.maximize_window()

    try:
        driver.get("https://class.utp.edu.pe")
        time.sleep(5)

        driver.find_element(By.ID, "username").send_keys(correo)
        driver.find_element(By.ID, "password").send_keys(contrasena)
        driver.find_element(By.ID, "kc-login").click()

        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        xpath = f"//a[@data-testid='course-card-container'][.//div[contains(normalize-space(), '{curso_nombre}')]]"
        card = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
        card.click()
        time.sleep(5)

        xpath_zoom = "//span[@class='sb-tab--text' and text()='Zoom']"
        zoom_button = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, xpath_zoom))
        )
        zoom_button.click()
        time.sleep(5)

        print("Buscando botón 'Unirse al Zoom'...")
        botones = driver.find_elements(By.TAG_NAME, "button")
        boton_zoom = next((b for b in botones if "Unirse al zoom" in b.text), None)

        if boton_zoom:
            boton_zoom.click()
            time.sleep(3)

            pyautogui.press('tab')
            pyautogui.press('space')
            pyautogui.press('tab')
            pyautogui.press('enter')
            time.sleep(16)

            ruta_imagen = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_compartido.PNG")
            imagen = cv2.imread(ruta_imagen)
            if imagen is not None:
                boton_audio = pyautogui.locateCenterOnScreen(ruta_imagen, confidence=0.8)
                if boton_audio:
                    pyautogui.click(boton_audio)
                    print("Se hizo clic en 'Unirse con el audio compartido'.")
                else:
                    print("No se encontró el botón de audio compartido.")
            else:
                print(f"No se pudo cargar la imagen desde {ruta_imagen}")
        else:
            print("No se encontró el botón 'Unirse al zoom'.")

    except Exception as e:
        print(f"Error durante el proceso: {e}")
        with open("error_page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)

    esperar_fin_clase(hora_fin_time)
    driver.quit()

@app.route('/iniciar', methods=['POST'])
def recibir_datos():
    datos = request.json
    print("Datos recibidos:", datos)

    threading.Thread(target=iniciar_clase_automatizada, args=(datos,)).start()
    return jsonify({"status": "ok", "mensaje": "Script iniciado correctamente"}), 200

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
