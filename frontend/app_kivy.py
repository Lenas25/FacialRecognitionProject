import kivy
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
import requests
from kivy.storage.jsonstore import JsonStore
from endpoints import endpoints
import datetime
import locale

kivy.require('2.0.0')

class InicioSesionScreen(Screen):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app = App.get_running_app()
        self.storage = JsonStore('local.json')

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
                if response.status_code == 200 and codigo_ingresado:
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
        self.detectar_rostro = False
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

    def actualizar_hora(self, dt):
        now = datetime.datetime.now()
        current_time_str = now.strftime('%H:%M:%S')
        self.hora_label.text = current_time_str
        minuto_actual = now.minute

        if minuto_actual != self.ultimo_minuto_verificado:
            self.verificar_horario(now, 5, 5)
            self.ultimo_minuto_verificado = minuto_actual

    def verificar_horario(self, hora_actual, minutos_antes=5, minutos_despues=5):
        # hora actual 15:30
        horarios_hoy = self.storage.get('horario_dia')['horario_dia']
        
        for horario in horarios_hoy:
            hora_antes = (horario["hora_inicio"] - datetime.timedelta(minutes=minutos_antes)).strftime("%H:%M:%S")
            hora_despues = (horario["hora_fin"] + datetime.timedelta(minutes=minutos_despues)).strftime("%H:%M:%S")
            # si la hora actual esta entre ese rango entonces sigue detectando rostros
            if hora_actual.strftime("%H:%M:%S") >= hora_antes and hora_actual.strftime("%H:%M:%S") <= hora_despues:
                self.detectar_rostro = True
                print("En el rando, detectando rostro...")
                break
            else:
                self.detectar_rostro = False
                # self.guardar_asistencia(horario['id'])
                # self.enviar_reporte(horario['id'])
                print("Fuera del rango, guardando asistencia y enviando reporte...")
                break
    
    def guardar_asistencia(self, instance):
        # calcular tiempo de el json que se esta guardando
        #[{ id: 1, hora_detectado: "12:00", rol:0}
        #{ id: 1, hora_detectado: "14:00", rol:0}
        #{ id: 1, hora_detectado: "14:30", rol:0}
        #{ id: 1, hora_detectado: "16:00", rol:0}
        #{ id: 2, hora_detectado: "12:00", rol:1}
        #{ id: 1, hora_detectado: "14:00", rol:0}]
        
        
        #{ id: 1, tiempo: "40", rol:0}
        #{ id: 2, tiempo: "30", rol:1}
        
        
        
        
        
        pass
    
    def enviar_reporte(self, instance):
        # se ejecuta e enviar reporte y mensaje en el mismo
        
        pass
        
    def reconocer_rostro(self, personas):
        # Aquí puedes implementar la lógica para reconocer el rostro, cada que se registra se va a ir colocando en un storage a paarte quien va ingresando y saliendo
        # cada que se detecta un rostro se guarda en el json
        # detectados
        
        pass
    
    def guardar_desconocido(self, frame):
        # Aquí puedes implementar la lógica para guardar el rostro desconocido
        # si en reconocer rostro no se encuentra a nadie entonces se guarda el rostro desconocido, mandnando un frame a la funcion guardar_desconocido
        # y se manda a la base de datos subiendo la imagen a cloudinary
        
        
        
        pass
    
    
    # falta calcular en memoria el tiempo que paran en clase y mandarlo calculr y colocar su estado

class ReconocimientoFacialApp(App):
    def __init__(self, **kwargs): # add the __init__
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