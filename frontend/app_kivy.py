import kivy
from huggingface_hub import hf_hub_download
from kivy.app import App
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.lang import Builder
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.uix.screenmanager import ScreenManager, Screen
import cv2
import numpy as np
from ultralytics import YOLO
import requests
from kivy.storage.jsonstore import JsonStore
from endpoints import endpoints
from flask import jsonify
import os
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url
import time
from datetime import datetime, timedelta
from threading import Thread
from threading import Lock

load_dotenv()

kivy.require('2.0.0')

cloudinary.config(
    cloud_name= os.environ.get('CLOUDINARY_NAME'),
    api_key = os.environ.get('CLOUDINARY_API_KEY'),
    api_secret = os.environ.get('CLOUDINARY_API_SECRET'),
    secure = True
)

# Es la pantalla principal donde se inicia la aplicacion si no se tiene el local.json
class InicioSesionScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.horarios_iniciados = {}
        self.horarios_procesados_cierre = {}
        self.app = App.get_running_app()

    # Esta funcion se ejecuta cuando se da click en el boton de guardar, y tambien en local guarda el salon y el horario actual
    def validar_y_abrir_camara(self):
        self.storage = JsonStore('local.json')

        salon_ingresado = self.ids.salon_input.text.strip()
        codigo_ingresado = self.ids.codigo_admin_input.text.strip()

        if not salon_ingresado and not codigo_ingresado:
            self.mostrar_popup("Error", "Por favor, ingrese el salón y el código de administrador.")
        elif not salon_ingresado:
            self.mostrar_popup("Error", "Por favor, ingrese el salón.")
        elif not codigo_ingresado:
            self.mostrar_popup("Error", "Por favor, ingrese el código de administrador.")
        else:
            try:
                response = requests.post(endpoints["salon"], json={"salon": salon_ingresado})
                if response.status_code == 200 and codigo_ingresado == "admin":
                    self.storage.put("salon",salon = salon_ingresado)
                    self.storage.put("horario",horario = response.json())
                    self.actualizar_horario_dia()
                    self.mostrar_popup("Éxito", "Configuración guardada correctamente.")
                    self.go_to_camara()
                else:
                    self.mostrar_popup("Error", "El salón no existe.")
                    return
            except requests.exceptions.RequestException as e:
                self.mostrar_popup("Error", f"Error al conectar con el servidor: {e}")
                return

    def go_to_camara(self):
        self.app.root.current = 'camara_screen'

    def mostrar_popup(self, title, content):
        popup = Popup(
        title=title,
        size_hint=(0.8, 0.4),
        auto_dismiss=True,
        )
        box = BoxLayout(orientation='vertical')
        label = Label(text=content)
        close_button = Button(
            text="Cerrar",
            size_hint_y=None,
            height=dp(40),
            on_press=popup.dismiss
        )
        box.add_widget(label)
        box.add_widget(close_button)
        popup.content = box
        popup.open()

    def obtener_dia_semana(self):
        dia_ingles = datetime.now().strftime('%A').lower()
        dias_espanol = {
            'monday': 'lunes',
            'tuesday': 'martes',
 'wednesday': 'miércoles',
            'thursday': 'jueves',
            'friday': 'viernes',
            'saturday': 'sábado',
            'sunday': 'domingo'
        }
        return dias_espanol.get(dia_ingles, 'Día no reconocido')

    def actualizar_horario_dia(self):
        self.storage = JsonStore('local.json')

        dia_semana = self.obtener_dia_semana()
        horarios = self.storage.get('horario')['horario']['horarios']
        horarios_dia = [horario for horario in horarios if horario['dia_semana'] == dia_semana]
        self.storage.put('horario_dia',horario_dia = horarios_dia)

# Pantalla de la cámara que muestra la imagen en vivo y hay un boton para cambiar a la pantalla de inicio de sesión
class CamaraScreen(Screen):
    cap = None
    texture = None
    event = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lock_envio_profesor = Lock()
        self.procesando_reconocimiento = False
        self.app = App.get_running_app()
        self.asistencias = []
        self.detectar_rostro = False
        self.orientation = 'horizontal'
        self.padding = dp(10)
        self.spacing = dp(10)
        self.horarios_procesados_cierre = {}
        self._popup_carga = None

        self.layout_botones_imagen = BoxLayout(orientation='vertical', spacing=dp(10))

        self.boton_cambiar_configuracion = Button(text="Cambiar Configuración", size_hint_y=None, height=dp(50), on_press=self.volver_a_inicio)
        self.layout_botones_imagen.add_widget(self.boton_cambiar_configuracion)

        self.hora_label = Label(text="Cargando hora...", size_hint_y=None, width=dp(100), height=dp(20))
        self.layout_botones_imagen.add_widget(self.hora_label)

        self.camera_image = Image(size_hint=(1, 1))
        self.layout_botones_imagen.add_widget(self.camera_image)

        self.add_widget(self.layout_botones_imagen)

        Clock.schedule_interval(self.actualizar_hora, 1)

        self.model_path = hf_hub_download(repo_id="arnabdhar/YOLOv8-Face-Detection", filename="model.pt")
        self.yolo_model = YOLO(self.model_path)
        self.centro_x_imagen = 0.5
        self.tolerancia_x = 0.2
        self.varianza_laplace_minima = 0.1

    def calcular_varianza_laplace(self, imagen):
        gray = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        varianza = np.var(laplacian)
        return varianza

    def detectar_cara_centrada(self, frame):
        resultados = self.yolo_model.predict(frame)
        if len(resultados) > 0 and len(resultados[0].boxes.xywh) > 0:
            x_cara, y_cara, ancho_cara, alto_cara = resultados[0].boxes.xywh[0]
            centro_x_cara = (x_cara + ancho_cara / 2) / frame.shape[1]
            if abs(centro_x_cara - self.centro_x_imagen) <= self.tolerancia_x:
                return True
        return False

    def on_pre_enter(self, *args):
        self.start_camera()

    def on_leave(self, *args):
        self.stop_camera()

    def start_camera(self):
        self.cap = cv2.VideoCapture(0)
        self.event = Clock.schedule_interval(self.update_frame, 1.0 / 30.0)

    def stop_camera(self):
        if self.event:
            Clock.unschedule(self.event)
            self.event = None
        if self.cap and self.cap.isOpened():
            self.cap.release()
            self.cap = None

    def update_frame(self, dt):
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                varianza_laplace = self.calcular_varianza_laplace(frame_rgb)

                if self.detectar_rostro and not self.procesando_reconocimiento and self.detectar_cara_centrada(frame_rgb) and varianza_laplace > self.varianza_laplace_minima:
                    self.procesando_reconocimiento = True
                    self.detectar_rostro = False
                    # Crear una copia del frame para el hilo
                    frame_copy = frame_rgb.copy()
                    # Iniciar el reconocimiento en un hilo
                    thread = Thread(target=self.reconocer_rostro, args=(frame_copy,))
                    thread.start()

                buf = cv2.flip(frame_rgb, -1).tobytes()
                image_texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt='rgb')
                image_texture.blit_buffer(buf, bufferfmt='ubyte')
                self.camera_image.texture = image_texture

    def volver_a_inicio(self, instance):
        self.stop_camera()
        self.app.root.current = 'inicio_sesion_screen'

    def actualizar_hora(self, dt):
        self.storage = JsonStore('local.json')
        now = datetime.now()
        current_time_str = now.strftime('%H:%M:%S')
        self.hora_label.text = current_time_str

        if self.storage.exists('horario_dia'):
            self.verificar_horario(now, 0, 2)

    def verificar_horario(self, hora_actual, minutos_antes=2, minutos_despues=2):
        self.storage = JsonStore('local.json')
        self.storage_asistencia = JsonStore('asistencia.json')

        if not self.storage.exists('horario_dia'):
            return

        horarios_hoy = self.storage.get('horario_dia')['horario_dia']
        mejor_horario = None
        mejor_inicio = None
        mejor_fin = None

        for horario in horarios_hoy:
            hora_inicio_str = horario["hora_inicio"]
            hora_fin_str = horario["hora_fin"]

            try:
                # Intenta primero con el formato que incluye segundos
                hora_inicio = datetime.strptime(hora_inicio_str, "%H:%M:%S").time()
            except ValueError:
                # Si falla, intenta con el formato sin segundos
                hora_inicio = datetime.strptime(hora_inicio_str, "%H:%M").time()

            try:
                # Haz lo mismo para la hora de fin
                hora_fin = datetime.strptime(hora_fin_str, "%H:%M:%S").time()
            except ValueError:
                hora_fin = datetime.strptime(hora_fin_str, "%H:%M").time()

            fecha_hoy = hora_actual.date()
            hora_inicio_dt = datetime.combine(fecha_hoy, hora_inicio)
            hora_fin_dt = datetime.combine(fecha_hoy, hora_fin)

            hora_antes_dt = hora_inicio_dt - timedelta(minutes=minutos_antes)
            hora_despues_dt = hora_fin_dt + timedelta(minutes=minutos_despues)

            if hora_antes_dt <= hora_actual <= hora_despues_dt:
                if mejor_inicio is None or hora_inicio_dt < mejor_inicio:
                    mejor_horario = horario
                    mejor_inicio = hora_inicio_dt
                    mejor_fin = hora_fin_dt

        if mejor_horario:
            id_horario = mejor_horario['id']
            self.storage.put("horario_actual", horario=mejor_horario)

            if not hasattr(self, 'horarios_procesados_inicio'):
                self.horarios_procesados_inicio = {}
            if not hasattr(self, 'horarios_procesados_cierre'):
                self.horarios_procesados_cierre = {}

            # INICIO DE CLASE
            if hora_actual >= mejor_inicio - timedelta(minutes=minutos_antes) and not self.horarios_procesados_inicio.get(id_horario, False):
                self.horarios_procesados_inicio[id_horario] = True
                # Ejecutar en hilo para no bloquear
                thread = Thread(target=self.iniciar_clase, args=(id_horario,))
                thread.start()

            # DURANTE LA CLASE
            elif mejor_inicio <= hora_actual <= mejor_fin:
                if not self.detectar_rostro and not self.procesando_reconocimiento:
                    self.detectar_rostro = True

            # FIN DE CLASE
            elif mejor_fin < hora_actual <= mejor_fin + timedelta(minutes=minutos_despues):
                if not self.horarios_procesados_cierre.get(id_horario, False):
                    self.horarios_procesados_cierre[id_horario] = True
                    self.detectar_rostro = False
                    # Ejecutar en hilo para no bloquear
                    thread = Thread(target=self.finalizar_clase, args=(id_horario,))
                    thread.start()

    def iniciar_clase(self, id_horario):
        # Mostrar popup de carga desde el hilo principal de Kivy
        Clock.schedule_once(lambda dt: self.mostrar_popup_carga("Iniciando Clase", "Cargando lista de alumnos..."))

        self.actualizar_lista_alumnos(id_horario)

        # Simular descarga de imágenes (puedes reemplazar esto con tu lógica real)
        time.sleep(3) # Simulación de descarga

        # Cerrar popup y activar detección
        Clock.schedule_once(lambda dt: self.cerrar_popup_carga())
        Clock.schedule_once(lambda dt: self.mostrar_popup("Clase Iniciada", "Puede comenzar a registrar asistencia."))
        self.detectar_rostro = True

    def finalizar_clase(self, id_horario):
        # Mostrar popup de carga
        Clock.schedule_once(lambda dt: self.mostrar_popup_carga("Finalizando Clase", "Guardando asistencia y enviando reporte..."))

        self.guardar_asistencia(id_horario)
        self.guardar_desconocidos(id_horario)
        self.enviar_reporte(id_horario)
        self.eliminar_imagenes()
        self.storage_asistencia.clear()

        # Cerrar popup y mostrar mensaje final
        Clock.schedule_once(lambda dt: self.cerrar_popup_carga())
        Clock.schedule_once(lambda dt: self.mostrar_popup("Reporte Enviado", f"La asistencia para el horario {id_horario} ha sido procesada."))

    def actualizar_lista_alumnos(self, id_horario):
        try:
            response = requests.get(f'{endpoints["usuarios"]}/{id_horario}')
            if response.status_code == 200:
                usuarios = response.json()
                print(f"Lista de alumnos actualizada: {usuarios}")
                # Aquí podrías guardar la lista de alumnos en JsonStore si es necesario
            else:
                print(f"Error al obtener la lista de alumnos: {response.json()}")
        except Exception as e:
            print(f"Excepción al actualizar lista de alumnos: {e}")

    def eliminar_imagenes(self):
        folder_path = ["imagenes_temporales", "desconocidos_clase_actual"]
        for folder in folder_path:
            if os.path.exists(folder):
                for filename in os.listdir(folder):
                    if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                        file_path = os.path.join(folder, filename)
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            print(f"Error al eliminar {file_path}: {e}")

    def reconocer_rostro(self, frame):
        # Mostrar popup de "Validando..."
        Clock.schedule_once(lambda dt: self.mostrar_popup_carga("Reconociendo", "Validando rostro..."))

        datos_respuesta = None
        try:
            api_url = endpoints.get("ia")
            if not api_url:
                raise ValueError("Endpoint 'ia' no configurado.")

            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            _, encoded_image = cv2.imencode('.jpg', frame)
            files_to_send = {'image_file': ('captured_frame.jpg', encoded_image.tobytes(), 'image/jpeg')}

            response = requests.post(api_url, files=files_to_send, timeout=15)
            response.raise_for_status()
            datos_respuesta = response.json()

            if datos_respuesta.get('clasificado') is True:
                self.guardar_asistencia_local(datos_respuesta)
                if datos_respuesta.get('rol') == 'profesor':
                    if self.storage.exists("horario_actual"):
                        horario_actual = self.storage.get("horario_actual")["horario"]
                        hilo_envio = Thread(target=self.enviar_datos_profesor, args=(datos_respuesta, horario_actual))
                        hilo_envio.start()

        except Exception as e:
            print(f"Error en reconocer_rostro: {e}")
            datos_respuesta = {'message': "Vuelve a intentarlo, por favor"}
        finally:
            # Programar el cierre del popup y el manejo del resultado en el hilo principal
            Clock.schedule_once(lambda dt: self.cerrar_popup_carga())
            if datos_respuesta:
                Clock.schedule_once(lambda dt: self.mostrar_popup_resultado(datos_respuesta))
            # Reactivar la detección
            self.procesando_reconocimiento = False
            self.detectar_rostro = True

    def mostrar_popup_resultado(self, datos):
        title = "Resultado del Reconocimiento"
        content = datos.get('message', 'No se recibió mensaje.')
        self.mostrar_popup(title, content)

    def enviar_datos_profesor(self, datos_profesor, horario):
        with self.lock_envio_profesor:
            try:
                self.storage = JsonStore('local.json')
                salon = self.storage.get("salon")["salon"]
                print(f"DEBUG: Nombre del salón recuperado = {salon}")

                ip_computadora = self.obtener_ip_computadora(salon)
                print(f"DEBUG: IP recibida desde backend = {ip_computadora}")

                if not ip_computadora:
                    print("ERROR: No se encontró la computadora del salón. Por favor, solicite asistencia técnica.")
                    self.mostrar_popup("Error", "No se encontró la computadora del salón. Por favor, solicite asistencia técnica.")
                    return

                # 🗓️ Incluir fecha en la clave del horario
                from datetime import datetime
                fecha_hoy = datetime.now().strftime("%Y-%m-%d")
                clave_horario = f"{fecha_hoy}_{horario['hora_inicio']}_{horario['hora_fin']}"

                if self.storage.exists("envios_realizados"):
                    ya_enviados = self.storage.get("envios_realizados")["horarios"]
                    if clave_horario in ya_enviados:
                        print(f"INFO: Ya se enviaron los parámetros para el horario {clave_horario}, no se enviará de nuevo.")
                        return
                else:
                    self.storage.put("envios_realizados", horarios=[])

                payload = {
                    "correo": datos_profesor.get("correo"),
                    "contrasena": datos_profesor.get("contrasena"),
                    "curso": horario.get("curso"),
                    "hora_inicio": horario.get("hora_inicio"),
                    "hora_fin": horario.get("hora_fin")
                }

                print(f"DEBUG: Payload a enviar = {payload}")
                url = f"http://{ip_computadora}:5000/iniciar"

                max_retries = 3
                delay = 3
                for intento in range(max_retries):
                    try:
                        print(f"DEBUG: Intento {intento+1} de conexión a {url}")
                        response = requests.post(url, json=payload, timeout=10)
                        if response.status_code == 200:
                            print(f"DEBUG: Respuesta del servidor: {response.status_code} - {response.text}")
                            # ✅ Marcar como enviado
                            ya_enviados = self.storage.get("envios_realizados")["horarios"]
                            ya_enviados.append(clave_horario)
                            self.storage.put("envios_realizados", horarios=ya_enviados)
                            return
                    except requests.exceptions.ConnectionError:
                        print("INFO: La computadora de automatización no está disponible. Reintentando...")
                        time.sleep(delay)
                    except Exception as e:
                        print(f"ERROR: Fallo inesperado durante envío: {e}")
                        return

                print("ERROR: No se logró conectar tras múltiples intentos.")

            except Exception as e:
                import traceback
                print("ERROR: Excepción durante el envío al servidor.")
                traceback.print_exc()

    def obtener_ip_computadora(self, salon):
        try:
            response = requests.get(f"{endpoints['ip_computadora']}/{salon}", timeout=5)
            if response.status_code == 200:
                ip = response.json().get("ip")
                print(f"DEBUG: IP recibida desde backend: {ip}")
                return ip
            else:
                print(f"ERROR: IP no encontrada para el salón {salon}")
                return None
        except Exception as e:
            print(f"ERROR: Excepción al obtener IP: {e}")
            return None

    def calcular_asistencia(self, minutos):
        self.storage_asistencia = JsonStore('asistencia.json')
        """
        Calcula el tiempo de asistencia de cada usuario (estudiante o profesor)
        basándose en una lista de registros de entrada y salida.
        """
        print("Calculando asistencia...")

        try:
            # Es mejor convertir a float directamente para que coincida con el tipo de 'tiempo_total'
            minutes = float(minutos)
        except (ValueError, TypeError):
            # Si el valor en .env no es un número, se usará un default y se mostrará una advertencia.
            print(f"ADVERTENCIA: El valor de MINUTES_DELAY ('{minutos}') no es un número válido. Usando 15 minutos por defecto.")
            minutes = 15.0

        if not self.storage_asistencia.exists("asistencia"):
            print("No hay registros de asistencia para calcular.")
            return []
        tiempos_por_usuario = {}
        for registro in self.storage_asistencia.get("asistencia")["asistencia"]:
            usuario_id = registro['id']
            rol = registro['rol']
            hora_detectado = datetime.strptime(registro['hora_detectado'], "%H:%M:%S")

            if usuario_id not in tiempos_por_usuario:
                tiempos_por_usuario[usuario_id] = {'rol': rol, 'ingreso': None, 'tiempo_total': 0}

            if tiempos_por_usuario[usuario_id]['ingreso'] is None:
                tiempos_por_usuario[usuario_id]['ingreso'] = hora_detectado
            else:
                salida = hora_detectado
                ingreso = tiempos_por_usuario[usuario_id]['ingreso']
                tiempo_en_clase = (salida - ingreso).total_seconds() / 60  # en minutos
                tiempos_por_usuario[usuario_id]['tiempo_total'] += tiempo_en_clase
                tiempos_por_usuario[usuario_id]['ingreso'] = None  # Reiniciar para el próximo ingreso-salida

        # Crear la lista de resultado
        resultado = []
        for usuario_id, datos in tiempos_por_usuario.items():
            # Solo incluir a los usuarios que completaron al menos una entrada y una salida
            if datos['ingreso'] is None:
                resultado.append({
                    'id': usuario_id,
                    'tiempo': round(datos['tiempo_total']),  # Redondear a minutos enteros
                    'estado': 'presente' if datos['tiempo_total'] >= minutes else 'ausente',
                    'rol': 0 if datos['rol'] == "alumno" else 1  # Asignar rol como string
                })
            # Manejar el caso de un registro de entrada sin salida (usuario ausente)
            elif datos['ingreso'] is not None:
                resultado.append({
                    'id': usuario_id,
                    'tiempo': 0,  # Tiempo de asistencia 0 si solo hay entrada
                    'estado': 'ausente',
                    'rol': 0 if datos['rol'] == "alumno" else 1  # Asignar rol como string
                })
        return resultado

    # esta funcion guarda la asistencia de varios usuarios en la base de datos, recibe el id del horario y envia los datos calculados por calcular_asistencia
    def guardar_asistencia(self, id_horario):
        self.storage_asistencia = JsonStore('asistencia.json')
        minutes = os.getenv('MINUTES_DELAY', '15')
        datos = self.calcular_asistencia(minutes)
        print(f"Guardando asistencia para el horario {id_horario} con los siguientes datos: {datos}")
        response = requests.post(f'{endpoints["asistencia"]}/{id_horario}', json=datos)
        if response.status_code == 200:
            print("Asistencia guardada correctamente")
        else:
            print(f"Error al guardar asistencia: {response}")

    def guardar_asistencia_local(self, datos):
        self.storage_asistencia = JsonStore('asistencia.json')
        datos["hora_detectado"] = datetime.now().strftime("%H:%M:%S")
        self.asistencias = self.storage_asistencia.get("asistencia")["asistencia"] if self.storage_asistencia.exists("asistencia") else []
        self.asistencias.append(datos)
        self.storage_asistencia.put("asistencia", asistencia=self.asistencias)

    # esta funcion se encarga de enviar el reporte y el mensaje al servidor, recibe el id del horario y envia el reporte y mensaje
    def enviar_reporte(self, id_horario):
        self.storage = JsonStore('local.json')

        # se ejecuta e enviar reporte y mensaje en el mismo
        try:
            response = requests.post(f'{endpoints["reporte"]}/{self.storage.get("salon")["salon"]}/{id_horario}')
            print(f"Enviando reporte para el horario {id_horario}...")
            print(response.json())
            if response.status_code == 200:
                print("Reporte enviado correctamente")
            else:
                print(response.json())
        except requests.exceptions.RequestException as e:
            print(f"Error al enviar el reporte: {e}")

        try:
            response2 = requests.post(f'{endpoints["mensaje"]}/{id_horario}')
            if response2.status_code == 200:
                print("Mensaje enviado correctamente")
            else:
                print(response2.json())
        except requests.exceptions.RequestException as e:
            print(f"Error al enviar el mensaje: {e}")


    # esta funcion se encarga de guardar un desconocido, recibe el frame de la imagen y el id del horario, lo convierte a imagen, lo guarda en Cloudinary y guarda el link en la base de datos
    def guardar_desconocidos(self, id_horario):
        try:
            folder = "desconocidos_clase_actual"
            urls = []

            # Recorre todos los archivos de imagen en el directorio
            for filename in os.listdir(folder):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    file_path = os.path.join(folder, filename)
                    # Lee la imagen y súbela a Cloudinary
                    with open(file_path, "rb") as img_file:
                        upload_result = cloudinary.uploader.upload(img_file, resource_type="image")
                        imagen_url = upload_result['secure_url']
                        urls.append(imagen_url)
                        print(f"Imagen subida a Cloudinary: {imagen_url}")

            # Envía la lista de URLs al backend
            if urls:
                response = requests.post(
                    f'{endpoints["desconocido"]}/{id_horario}',
                    json={"url_img": urls}
                )
                if response.status_code == 200:
                    print('Desconocidos guardados correctamente')
                else:
                    print('Error al guardar desconocidos')
            else:
                print("No se encontraron imágenes para subir.")

        except Exception as e:
            print(f'Error al guardar desconocidos: {str(e)}')

    def mostrar_popup_carga(self, title, content):
        """Muestra un popup de carga no descartable."""
        if self._popup_carga:
            self._popup_carga.dismiss()

        box = BoxLayout(orientation='vertical', padding=dp(10), spacing=dp(10))
        box.add_widget(Label(text=content))

        self._popup_carga = Popup(
            title=title,
            content=box,
            size_hint=(0.7, 0.3),
            auto_dismiss=False
        )
        self._popup_carga.open()

    def cerrar_popup_carga(self):
        """Cierra el popup de carga si está abierto."""
        if self._popup_carga:
            self._popup_carga.dismiss()
            self._popup_carga = None

    def mostrar_popup(self, title, content):
        """Muestra un popup de información general que se cierra automáticamente."""
        # Cierra cualquier popup de carga primero
        self.cerrar_popup_carga()

        popup = Popup(
            title=title,
            size_hint=(0.8, 0.4),
            auto_dismiss=True
        )
        box = BoxLayout(orientation='vertical', padding=dp(10))
        label = Label(text=content, size_hint_y=0.8)
        close_button = Button(
            text="Cerrar",
            size_hint_y=0.2,
            on_press=popup.dismiss
        )
        box.add_widget(label)
        box.add_widget(close_button)
        popup.content = box
        popup.open()
        # Cierra el popup después de 5 segundos
        Clock.schedule_once(lambda dt: popup.dismiss(), 5)


class ReconocimientoFacialApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.storage = JsonStore('local.json')
        self.storage_asistencia = JsonStore('asistencia.json')

    def build(self):
        # Asegúrate de que el archivo .kv se cargue si lo tienes
        Builder.load_file('frontend/main.kv')
        self.sm = ScreenManager()
        inicio_sesion_widget = InicioSesionScreen(name='inicio_sesion_screen')
        camara_ventana_widget = CamaraScreen(name='camara_screen')

        self.sm.add_widget(inicio_sesion_widget)
        self.sm.add_widget(camara_ventana_widget)
        self.sm.current = 'inicio_sesion_screen'
        return self.sm

    def on_start(self):
        super().on_start()
        if self.storage.count() != 0:
            if self.storage.exists('salon') and self.storage.exists('horario'):
                self.actualizar_horario_dia()
                print("Configuración existente encontrada. Cargando pantalla de cámara...")
                self.sm.current = 'camara_screen'
            else:
                self.sm.current = 'inicio_sesion_screen'
        else:
            print("No se encontró configuración previa. Cargando pantalla de inicio de sesión...")
            self.sm.current = 'inicio_sesion_screen'

    def obtener_dia_semana(self):
        dia_ingles = datetime.now().strftime('%A').lower()
        dias_espanol = {
            'monday': 'lunes', 'tuesday': 'martes', 'wednesday': 'miércoles',
            'thursday': 'jueves', 'friday': 'viernes', 'saturday': 'sábado', 'sunday': 'domingo'
        }
        return dias_espanol.get(dia_ingles, 'Día no reconocido')

    def actualizar_horario_dia(self):
        try:
            dia_semana = self.obtener_dia_semana()
            response = requests.post(endpoints["salon"], json={"salon": self.storage.get('salon')['salon']})
            if response.status_code == 200:
                self.storage.put("horario", horario=response.json())

            horarios = self.storage.get('horario')['horario']['horarios']
            horarios_dia = [h for h in horarios if h['dia_semana'] == dia_semana]
            self.storage.put('horario_dia', horario_dia=horarios_dia)
        except Exception as e:
            print(f"Error al actualizar horario: {e}")

    def on_stop(self):
        if self.storage:
            self.storage.close()
        if self.storage_asistencia:
            self.storage_asistencia.close()

if __name__ == '__main__':
    ReconocimientoFacialApp().run()
