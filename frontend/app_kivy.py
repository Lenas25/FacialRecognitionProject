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
import datetime
from flask import jsonify
import os
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url

load_dotenv()

kivy.require('2.0.0')

cloudinary.config(
    cloud_name= os.environ.get('CLOUDINARY_NAME'),
    api_key = os.environ.get('CLOUDINARY_API_KEY'),
    api_secret = os.environ.get('CLOUDINARY_API_SECRET'),
    secure = True
)

# es la pantalla principal donde se inicia la aplicacion si no se tiene el local.json
class InicioSesionScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app = App.get_running_app()
        self.storage = JsonStore('local.json')

    # Esta funcion se ejecuta cuando se da click en el boton de guardar, y tambien en local guarda el salon y el horario actual
    def validar_y_abrir_camara(self):
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
        dia_ingles = datetime.datetime.now().strftime('%A').lower()
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
        dia_semana = self.obtener_dia_semana()
        horarios = self.storage.get('horario')['horario']['horarios']
        horarios_dia = [horario for horario in horarios if horario['dia_semana'] == dia_semana]
        self.storage.put('horario_dia',horario_dia = horarios_dia)

# Pantalla de la cámara que muestra la imagen en vivo y hay un boton para cambiar a la pantalla de inicio de sesión
class CamaraScreen(Screen):
    """
    Pantalla para mostrar la cámara usando OpenCV.
    """
    cap = None
    texture = None
    event = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app = App.get_running_app()
        self.storage = JsonStore('local.json')
        self.storage_asistencia = JsonStore('asistencia.json')
        self.asistencias = []
        self.detectar_rostro = True
        self.orientation = 'horizontal'
        self.padding = dp(10)
        self.spacing = dp(10)

        self.layout_botones_imagen = BoxLayout(orientation='vertical', spacing=dp(10))

        self.boton_cambiar_configuracion = Button(text="Cambiar Configuración", size_hint_y=None, height=dp(50), on_press=self.volver_a_inicio)
        self.layout_botones_imagen.add_widget(self.boton_cambiar_configuracion)
        
        self.hora_label = Label(text="Cargando hora...", size_hint_y=None, width=dp(100), height=dp(20))
        self.layout_botones_imagen.add_widget(self.hora_label)
        
        self.camera_image = Image(size_hint=(1, 1))
        self.layout_botones_imagen.add_widget(self.camera_image)

        self.add_widget(self.layout_botones_imagen)
        Clock.schedule_interval(self.actualizar_hora, 1)
        self.ultimo_minuto_verificado = -1

        self.model_path = hf_hub_download(repo_id="arnabdhar/YOLOv8-Face-Detection", filename="model.pt")
        self.yolo_model = YOLO(self.model_path)
        self.centro_x_imagen = 0.5
        self.tolerancia_x = 0.2
        self.varianza_laplace_minima = 0.5

    def calcular_varianza_laplace(self, imagen):
        """
        Calcula la varianza del Laplaciano de una imagen para estimar su nitidez.

        Args:
            imagen: La imagen en formato OpenCV (array de NumPy).

        Returns:
            La varianza del Laplaciano (un valor flotante).
        """
        gray = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        varianza = np.var(laplacian)
        return varianza

    def detectar_cara_centrada(self, frame):
        """
        Detecta si una cara está centrada en el frame utilizando YOLOv8.

        Args:
            frame: El frame de la cámara en formato OpenCV (array de NumPy).

        Returns:
            True si se detecta una cara centrada, False en caso contrario.
        """
        resultados = self.yolo_model.predict(frame)  # Detecta caras en el frame
        if len(resultados) > 0 and len(resultados[0].boxes.xywh) > 0:
            # Al menos una cara detectada
            x_cara, y_cara, ancho_cara, alto_cara = resultados[0].boxes.xywh[0]  # Obtiene la primera cara detectada
            centro_x_cara = (x_cara + ancho_cara / 2) / frame.shape[1]  # Calcula el centro de la cara en porcentaje del ancho de la imagen
            # Verifica si el centro de la cara está dentro de la tolerancia permitida
            if abs(centro_x_cara - self.centro_x_imagen) <= self.tolerancia_x:
                return True
        return False

    def on_pre_enter(self, *args):
        self.start_camera()

    def on_leave(self, *args):
        self.stop_camera()

    # Inicia la cámara y comienza a capturar frames
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

    """
    LENIN AQUI ES DONDE SE HACE LA ACTUALIACION POR FRAME, la funcion de reconocer rostro debe obtener los usuarios del horario puedes usar el endpoint usuarios para obtener el array de usuarios y profesores con su respectico id, link y rol, la pregunta es en que momento se le mandara esos datos
    """
    def update_frame(self, dt):
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                varianza_laplace = self.calcular_varianza_laplace(frame_rgb) #calcula nitidez

                if self.detectar_rostro and self.detectar_cara_centrada(frame_rgb) and varianza_laplace > self.varianza_laplace_minima:
                    # La detección de rostro está activa, la cara está centrada y la imagen es nítida
                    # Aquí se llamaría a la función de reconocimiento facial
                    persona = self.reconocer_rostro(frame_rgb)
                    self.reconocer_rostro(persona)
                    print("Cara centrada y nítida detectada. Enviando a reconocimiento...")
                    # pass  # Reemplaza esto con tu llamada a la función de reconocimiento facial

                buf = cv2.flip(frame_rgb, -1).tobytes()
                image_texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt='rgb')
                image_texture.blit_buffer(buf, bufferfmt='ubyte')
                self.camera_image.texture = image_texture
            else:
                print("Error reading frame")
        else:
            print("Camera is not open")

    def volver_a_inicio(self, instance):
        self.stop_camera()
        self.app.root.current = 'inicio_sesion_screen'

    # esta funcion sirve para poder actualizar la hora cada segundo y cada minuto se verifica si la hora actual se encuentra o no en el rango de la clase del dia de hoy
    def actualizar_hora(self, dt):
        now = datetime.datetime.now()
        current_time_str = now.strftime('%H:%M:%S')
        self.hora_label.text = current_time_str
        minuto_actual = now.minute

        if minuto_actual != self.ultimo_minuto_verificado:
            self.verificar_horario(now, 5, 5)
            self.ultimo_minuto_verificado = minuto_actual

    # esta funcion verifica si la hora actual se encuentra en el rango de horario del dia de hoy, si es asi se activa la deteccion de rostro, si no y esta en la final de hora se envia el reporte de la clase y se guarda la asistencia calculada por local
    def verificar_horario(self, hora_actual, minutos_antes=5, minutos_despues=5):
        # hora actual 15:30
        horarios_hoy = self.storage.get('horario_dia')['horario_dia']
        for horario in horarios_hoy:
            hora_inicio_str = horario["hora_inicio"]
            hora_fin_str = horario["hora_fin"]

            try:
                hora_inicio = datetime.datetime.strptime(hora_inicio_str, "%H:%M:%S").time()
            except ValueError:
                hora_inicio = datetime.datetime.strptime(hora_inicio_str, "%H:%M").time()
            try:
                hora_fin = datetime.datetime.strptime(hora_fin_str, "%H:%M:%S").time()
            except ValueError:
                hora_fin = datetime.datetime.strptime(hora_fin_str, "%H:%M").time()

            fecha_hoy = hora_actual.date()
            hora_inicio_dt = datetime.datetime.combine(fecha_hoy, hora_inicio)
            hora_fin_dt = datetime.datetime.combine(fecha_hoy, hora_fin)
            hora_antes = (hora_inicio_dt - datetime.timedelta(minutes=minutos_antes)).strftime("%H:%M:%S")
            hora_despues = (hora_fin_dt + datetime.timedelta(minutes=minutos_despues)).strftime("%H:%M:%S")
            # si la hora actual esta entre ese rango entonces sigue detectando rostros
            print(f"Verificando horario: {horario['id']} de {hora_antes} a {hora_despues}")
            if hora_actual.strftime("%H:%M:%S") >= hora_antes and hora_actual.strftime("%H:%M:%S") < hora_despues:
                self.detectar_rostro = True
                print("En el rando, detectando rostro...")
                break
            elif hora_actual.strftime("%H:%M:%S") == hora_despues:
                self.detectar_rostro = False
                # self.guardar_asistencia(horario['id'])
                self.enviar_reporte(horario['id'])
                print("Fuera del rango, guardando asistencia y enviando reporte...")
                break
        
    def reconocer_rostro(self, frame):
        """
        Lenin, necesito que hagas que esta funcion se este ejecutando cada rato y establece la logica para en que momento recibir todos los datos de la base de datos tanto usuarios como profesores ya que habra links y de esos links se va a comparar la imagen, simula un array de imagenes, el modelo debe retornar lo siguiente:
        si es un conocido, llamar a la funcion guardar_asistencia_local
        {
            id: 1,
            rol: 0, # 0 = alumno, 1 = profesor
        }
        si es un desconcido y llamar a la funcion guardar_desconocido y enviar la imagen para que sea guardada
        {
            id: 0, o null
        }
        
        """
        # if not self.current_horario_id:
        #     print("No hay horario activo para el reconocimiento.")
        #     return

        # try:
        #     # 1. Encode the frame
        #     _, img_encoded = cv2.imencode('.jpg', frame)
        #     img_bytes = img_encoded.tobytes()

        #     # 2. Prepare files for the request
        #     files = {'image_file': ('frame.jpg', img_bytes, 'image/jpeg')}
            
        #     # 3. Send to backend IA endpoint
        #     # Assuming endpoints["IA"] is correctly defined
        #     ia_endpoint = endpoints["IA"]
        #     response = requests.post(ia_endpoint, files=files)
        #     response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)

        #     # 4. Process response
        #     data = response.json()
            
        #     if data.get('id') and data.get('id') != 0 and data.get('id') is not None: # Known person
        #         # Expected: { "id": 1, "rol": 0, "nombre": "Juan Perez" (optional for popup)}
        #         user_id = data['id']
        #         user_rol = data.get('rol', 0) # Default to 0 if rol is not present
        #         user_name = data.get('nombre', f"ID {user_id}") # Use name if available

        #         self.guardar_asistencia_local({'id': user_id, 'rol': user_rol})
        #         self.mostrar_popup_temporal("Rostro Conocido", f"Asistencia registrada para: {user_name}", 2)
        #         print(f"Conocido: ID={user_id}, Rol={user_rol}")
        #     else: # Unknown person or error from backend logic
        #         # Expected: { "id": 0 } or { "id": null } or some other indicator
        #         self.guardar_desconocido(frame, self.current_horario_id)
        #         self.mostrar_popup_temporal("Rostro Desconocido", "Rostro desconocido detectado y guardado.", 2)
        #         print("Desconocido detectado.")

        # except requests.exceptions.RequestException as e:
        #     print(f"Error en reconocer_rostro (conexión/servidor): {e}")
        #     # Optionally show an error popup to the user
        #     self.mostrar_popup_temporal("Error de Red", "No se pudo conectar con el servidor de IA.", 3)
        # except ValueError as e: # Includes JSONDecodeError
        #     print(f"Error en reconocer_rostro (respuesta JSON inválida): {e}")
        #     self.mostrar_popup_temporal("Error de Respuesta", "Respuesta inválida del servidor de IA.", 3)
        # except Exception as e:
        #     print(f"Error inesperado en reconocer_rostro: {e}")
        #     self.mostrar_popup_temporal("Error Inesperado", "Ocurrió un error durante el reconocimiento.", 3)
        
    def calcular_asistencia(self, porcentaje_asistencia):
        #[{ id: 1, hora_detectado: "12:00", rol:0}
        #{ id: 1, hora_detectado: "14:00", rol:0}
        #{ id: 1, hora_detectado: "14:30", rol:0}
        #{ id: 1, hora_detectado: "16:00", rol:0}
        #{ id: 2, hora_detectado: "12:00", rol:1}
        #{ id: 1, hora_detectado: "14:00", rol:0}]
        
        # debe retornar
        #[{ id: 1, tiempo: "40", rol:0}
        #{ id: 2, tiempo: "30", rol:1}]
        
        
        """
        Lenin aqui necesito que simules que tienes datos y tienes que calcular asi sea de 2 o 3 uduarios con id unicos que verifique por id y rol si es estudiantte o preofesor cuanto tiempo en minutos han estado en clase considerando que cada registro es ingreso y otro salida, si el utimo que se registro es un ingreso y no una salida se considera ausente.
        """
        
        
        pass

    # esta funcion guarda la asistencia de varios usuarios en la base de datos, recibe el id del horario y envia los datos calculados por calcular_asistencia
    def guardar_asistencia(self, id_horario):
        datos = self.calcular_asistencia(0.8)
        response = requests.post(f'{endpoints["asistencia"]}/{id_horario}', json=datos)
        if response.status_code == 200:
            self.storage_asistencia.clear()
            print("Asistencia guardada correctamente")
        else:
            print(f"Error al guardar asistencia: {response.json()}")
        
    # esta funcion se ejecuta cuando se detecta un rostro conocido, guarda la asistencia localmente y se va acumulando hasta que se finalice la clase
    def guardar_asistencia_local(self, datos):
        # de datos se recibe solo la id y el rol
        datos["hora_detectado"] = datetime.datetime.now().strftime("%H:%M:%S")
        self.asistencias = self.storage_asistencia.get("asistencia")["asistencia"] if self.storage_asistencia.exists("asistencia") else []
        self.asistencias.append(datos)
        self.storage_asistencia.put("asistencia", asistencia=self.asistencias)
    
    # esta funcion se encarga de enviar el reporte y el mensaje al servidor, recibe el id del horario y envia el reporte y mensaje
    def enviar_reporte(self, id_horario):
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
                print(response.json())
        except requests.exceptions.RequestException as e:
            print(f"Error al enviar el mensaje: {e}")
        
    # esta funcion se encarga de guardar un desconocido, recibe el frame de la imagen y el id del horario, lo convierte a imagen, lo guarda en Cloudinary y guarda el link en la base de datos   
    def guardar_desconocido(self, frame, id_horario):
        try:
            _, img_encoded = cv2.imencode('.jpg', frame) 
            img_bytes = img_encoded.tobytes() 

            upload_result = cloudinary.uploader.upload(img_bytes, resource_type="image") 

            imagen_url = upload_result['secure_url']
            print(f"Imagen subida a Cloudinary: {imagen_url}")
            response = requests.post(f'{endpoints["desconocido"]}/{id_horario}', json={"url_img": imagen_url})
            if response.status_code == 200:
                return jsonify({'mensaje': 'Desconocido guardado correctamente'}), 200
            else:
                return jsonify({'mensaje': 'Error al guardar desconocido'}), 500
            
        except Exception as e:
            return jsonify({'mensaje': f'Error al guardar desconocido: {str(e)}'}), 500
    
    def on_stop(self):
        self.storage_asistencia.close()
    
    # esta funcion servira cuando se se detectte se mostrara un pop up pero por 2 segundos y se mostrara el mensaje de que se ha detectado un rostro conocido o desconocido
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

class ReconocimientoFacialApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.storage = JsonStore('local.json')
    
    def build(self):
        Builder.load_file('frontend/main.kv')
        self.sm = ScreenManager()
        inicio_sesion_widget = InicioSesionScreen(name='inicio_sesion_screen')
        camara_ventana_widget = CamaraScreen(name='camara_screen')

        self.sm.add_widget(inicio_sesion_widget)
        self.sm.add_widget(camara_ventana_widget)
        self.sm.current = 'inicio_sesion_screen' 
        return self.sm

    # verificar si ya se ha realizado la configuracion del salon y el horario
    def on_start(self):
        super().on_start()
        if self.storage.exists('salon') and self.storage.exists('horario'):
            self.actualizar_horario_dia()
            self.sm.current = 'camara_screen'
        else:
            self.sm.current = 'inicio_sesion_screen'
    
    def obtener_dia_semana(self):
        dia_ingles = datetime.datetime.now().strftime('%A').lower()
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
        dia_semana = self.obtener_dia_semana()
        response  = requests.post(endpoints["salon"], json={"salon": self.storage.get('salon')['salon']})
        if response.status_code == 200:
            self.storage.put("horario",horario = response.json())
        horarios = self.storage.get('horario')['horario']['horarios']
        horarios_dia = [horario for horario in horarios if horario['dia_semana'] == dia_semana]
        self.storage.put('horario_dia',horario_dia = horarios_dia)
        
            
    def on_stop(self):
        self.storage.close()

if __name__ == '__main__':
    ReconocimientoFacialApp().run()