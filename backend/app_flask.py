# backend/app_flask.py
from flask import Flask, jsonify, request
from schemas import Salon, AsistenciaAlumno, AsistenciaProfesor, Horario, Desconocido, Matricula, Curso, Alumno, Profesor
from database import db
import os
import pandas as pd
import cv2  # For image processing if needed, DeepFace uses it
# from deepface import DeepFace
import tempfile  # For temporarily storing the uploaded image
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from twilio.rest import Client
import datetime
from dotenv import load_dotenv
import urllib.request
from concurrent.futures import ThreadPoolExecutor  # Para descarga concurrente

load_dotenv()

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:root@localhost:5432/db_reconocimiento'

db.init_app(app)

lista_personas = []

RUTA_CARPETA_IMAGENES = 'imagenes_temporales'

if not os.path.exists(RUTA_CARPETA_IMAGENES):
    os.makedirs(RUTA_CARPETA_IMAGENES)

# Modelos populares: "VGG-Face", "Facenet", "Facenet512", "ArcFace", "SFace"
MODEL_NAME = "Facenet"
DISTANCE_THRESHOLD = 0.6  # Ejemplo para Facenet. Reduce para mayor certeza.
# 'opencv', 'ssd', 'dlib', 'mtcnn', 'retinaface', 'mediapipe'
DETECTOR_BACKEND = 'mtcnn'

# sirve para consultar si el salon existe para guardar la configuracion y para consultar el horario de acuerdo al salon y devolver todos los horarios para verificar que curso se encuentra dando en este momento, esto se llama luego de que se haya guardado la configuracion y al iniciar el reconocimiento
@app.route('/salon', methods=['POST'])
def obtener_salones():
    data = request.get_json()

    if not data or 'salon' not in data:
        return jsonify({"message": "El campo 'salon' es requerido."}), 400

    salon_etiqueta = data['salon']

    salon = Salon.query.filter_by(etiqueta=salon_etiqueta).first()

    if salon:
        salon_db = Salon.query.filter_by(id=salon.id).first()
        horarios = salon_db.horarios
        if not horarios:
            return jsonify({"message": "No hay horarios registrados para este salon."}), 404

        horarios_list = []

        for horario in horarios:
            horarios_list.append({
                "id": horario.id,
                "dia_semana": horario.dia_semana,
                "hora_inicio": horario.hora_inicio.strftime("%H:%M"),
                "hora_fin": horario.hora_fin.strftime("%H:%M"),
                "curso": horario.curso.nombre,
                "id_curso": horario.id_curso
            })

        return jsonify({
            "mensaje": "Horarios encontrados.",
            "horarios": horarios_list
        }), 200

    else:
        return jsonify({"message": "Salon no encontrado."}), 404


@app.route('/reconocimiento', methods=['GET'])
def reconocimiento_facial(salon, imagen):
    # consultar a base de datos enviando una imagen, verificar los horrios de acuerdo a salon, luego descarta por la hora de inicio de 15 minutos antes y de la tabla matricula del id dell horario se hallan los id de alumnos y envia la lista de id de posibles alumnos al modelo de IA y todos los profesores segun el id de horario
    # retorna un id y si es profesor o alumno o si no se encuentra en la base de datos

    return 0


# registrar la asistencia de un grupo de alumnos y profesores, este se llama al finalizar la clase para el registro de los datos segun este en el local , desde del front recibiendo el id del horario y la lista de alumnos y profesores en formato
# [
#     {
#         "id": 1,
#         "tipo": 0,
#         "fecha": "2023-10-01",
#         "estado": "A"/"F"
#     }
@app.route('/asistencia/<id_horario>', methods=['POST'])
def registrar_asistencia(id_horario):
    data = request.get_json()

    if not data:
        return jsonify({"message": "Es necesario información."}), 400

    horario = Horario.query.filter_by(id=id_horario).first()
    if not horario:
        return jsonify({"message": "Horario no encontrado."}), 404

    new_asistencias_alumnos = []
    new_asistencias_profesores = []
    # si es alumno 0 y si es profesor 1
    for item in data:
        fecha = datetime.strptime(item["fecha"], '%Y-%m-%d').date()
        if item['tipo'] == 0:
            new_asistencias_alumnos.append(AsistenciaAlumno(
                id_horario=id_horario,
                id_alumno=item['id'],
                fecha=fecha,
                estado=item['estado'],
            ))
        elif item['tipo'] == 1:
            new_asistencias_profesores.append(AsistenciaProfesor(
                id_horario=id_horario,
                id_profesor=item['id'],
                fecha=fecha,
                estado=item['estado'],
            ))
    try:
        db.session.add_all(new_asistencias_alumnos)
        db.session.add_all(new_asistencias_profesores)
        db.session.commit()
        return jsonify({'message': f'{len(new_asistencias_alumnos)} y {len(new_asistencias_profesores)} asistencias agregadas en grupo exitosamente'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error al insertar el grupo de asistencias: {str(e)}'}), 500

# registrar la imagen de un desconocido en la base de datos considerando la fecha de registro


@app.route('/desconocido/<id_horario>', methods=['POST'])
def registrar_desconocido(id_horario):
    # se recibe en el formato {
    # "id_horario":11,
    # "url_imagen":"",
    # }

    data = request.get_json()
    print(data)
    if not data:
        return jsonify({"message": "Es necesario información."}), 400

    horario = Horario.query.filter_by(id=id_horario).first()
    if not horario:
        return jsonify({"message": "Horario no encontrado."}), 404

    new_desconocido = Desconocido(
        id_horario=id_horario,
        url_img=data['url_img'],
        fecha=datetime.datetime.now().strftime("%Y-%m-%d"),
    )

    try:
        db.session.add(new_desconocido)
        db.session.commit()
        return jsonify({'message': 'Desconocido agregado exitosamente'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error al insertar el desconocido: {str(e)}'}), 500

# exportar la asistencia en un excel con la lista de alumnos y profesores, y la lista de desconocidos


@app.route('/reporte/<salon>/<id_horario>', methods=['POST'])
def enviar_reporte(salon, id_horario):

    EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
    RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')

    try:
        alumnos = AsistenciaAlumno.query.filter(
            id_horario == id_horario,
            AsistenciaAlumno.fecha == datetime.datetime.now().date()
        ).all()
        profesores = AsistenciaProfesor.query.filter(
            id_horario == id_horario,
            AsistenciaAlumno.fecha == datetime.datetime.now().date()
        ).all()
        desconocidos = Desconocido.query.filter(
            id_horario == id_horario,
            Desconocido.fecha == datetime.datetime.now().date()
        ).all()

        df_desconocidos = pd.DataFrame([(d.id_horario, d.url_img, d.fecha) for d in desconocidos],
                                       columns=['Seccion', 'Imagen', 'Fecha de Detección'])
        df_alumnos = pd.DataFrame([(a.id, a.id_horario, a.id_alumno, a.estado, a.fecha) for a in alumnos],
                                  columns=['ID', 'Seccion', 'Código', 'Estado', 'Fecha de Detección'])
        df_docentes = pd.DataFrame([(d.id, d.id_horario, d.id_profesor, d.estado, d.fecha) for d in profesores],
                                   columns=['ID', 'Seccion', 'Código de Profesor', 'Estado', 'Fecha de Detección'])

        excel_filename = 'reporte_asistencia.xlsx'

        with pd.ExcelWriter(excel_filename, engine="xlsxwriter") as writer:
            df_alumnos.to_excel(writer, sheet_name='Alumnos', index=False)
            df_docentes.to_excel(writer, sheet_name='Docentes', index=False)
            df_desconocidos.to_excel(
                writer, sheet_name='Desconocidos', index=False)

            worksheet_alumnos = writer.sheets['Alumnos']
            worksheet_docentes = writer.sheets['Docentes']
            worksheet_desconocidos = writer.sheets['Desconocidos']

            for i, col in enumerate(df_alumnos.columns):
                column_len = max(df_alumnos[col].astype(
                    str).map(len).max(), len(col))
                worksheet_alumnos.set_column(i, i, column_len + 2)

            for i, col in enumerate(df_docentes.columns):
                column_len = max(df_docentes[col].astype(
                    str).map(len).max(), len(col))
                worksheet_docentes.set_column(i, i, column_len + 2)

            for i, col in enumerate(df_desconocidos.columns):
                column_len = max(df_desconocidos[col].astype(
                    str).map(len).max(), len(col))
                worksheet_desconocidos.set_column(i, i, column_len + 2)

        mensaje = MIMEMultipart()
        mensaje['From'] = EMAIL_ADDRESS
        mensaje['To'] = RECIPIENT_EMAIL
        mensaje['Subject'] = f'Reporte de Asistencia del salon - {salon} con seccion - {id_horario}'

        # Cuerpo del correo (texto plano)
        cuerpo_texto = """
        Buenas tardes estimado,
        
        El presente correo es para poder enviarle la lista de alumnos y docente que asistieron a la clase del dia de hoy. Asimismo
        adjunto se encuentra el archivo excel con los detalles correspondientes y el tiempo de permanencia de cada persona.
        
        Saludos Cordiales,
        Equipo tecnico.
        """
        mensaje.attach(MIMEText(cuerpo_texto, 'plain'))

        # Adjuntar el archivo Excel
        adjunto = open(excel_filename, 'rb')
        parte_adjunta = MIMEBase(
            'application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        parte_adjunta.set_payload(adjunto.read())
        encoders.encode_base64(parte_adjunta)
        parte_adjunta.add_header(
            'Content-Disposition', f'attachment; filename="{excel_filename}"')
        mensaje.attach(parte_adjunta)

        # Conectar al servidor SMTP y enviar el correo
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as servidor:
            servidor.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            servidor.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL,
                              mensaje.as_string())

        adjunto.close()
        os.remove(excel_filename)

        return jsonify({'mensaje': 'Reporte generado y enviado con éxito'}), 200

    except Exception as e:
        print(f"Error al generar y enviar el reporte: {e}")  # Loggear el error
        return jsonify({'mensaje': f'Error al generar el reporte: {str(e)}'}), 500


# enviar mensaje a contactos de quienes tienen una falta en su asistencia
@app.route('/mensaje/<id_horario>', methods=['POST'])
def enviar_mensaje(id_horario):
    TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        raise ValueError(
            "Las variables de entorno de Twilio (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER) deben estar configuradas.")

    cliente = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    alumnos_ausentes = AsistenciaAlumno.query.filter(
        AsistenciaAlumno.id_horario == id_horario, AsistenciaAlumno.estado == 'ausente').all()
    for alumno_ausente in alumnos_ausentes:
        alumno = alumno_ausente.alumno
        if alumno.contacto:
            mensaje_texto = f"Estimado, se le informa que el alumno, {alumno.nombre} {alumno.apellido}, tiene una falta en la clase de hoy. Por favor, tener en cuenta que el alumno tiene que justificar su falta."
            try:
                mensaje = cliente.messages.create(
                    to=alumno.contacto,
                    from_=TWILIO_PHONE_NUMBER,
                    body=mensaje_texto
                )
                return jsonify({'mensaje': f"Mensaje enviado a {alumno.nombre} {alumno.apellido} ({alumno.codigo_universitario}): {mensaje.sid}"}), 200
            except Exception as e:
                return jsonify({'mensaje': f"Error al enviar mensaje a {alumno.nombre} {alumno.apellido} ({alumno.codigo_universitario}): {e}"}), 400
        else:
            return jsonify({'mensaje': f"No se puede enviar mensaje a {alumno.nombre} {alumno.apellido} ({alumno.codigo_universitario}): No tiene número de teléfono registrado."}), 400


@app.route('/ia/<int:id_horario>', methods=['POST'])
def ia_recognize_face(id_horario):
    pass
    # if 'image_file' not in request.files:
    #     return jsonify({"error": "No image file provided"}), 400

    # image_file = request.files['image_file']
    # if image_file.filename == '':
    #     return jsonify({"error": "No selected file"}), 400

    # # 1. Guardar la imagen capturada temporalmente
    # # Usar un nombre de archivo temporal seguro
    # fd, captured_face_path = tempfile.mkstemp(suffix=".jpg")
    # os.close(fd) # Cerramos el descriptor de archivo para que save() pueda usar la ruta

    # try:
    #     image_file.save(captured_face_path)
    #     app.logger.info(f"Imagen capturada guardada en: {captured_face_path}")

    #     # 2. Obtener usuarios (alumnos del horario, todos los profesores)
    #     # Alumnos para el horario dado
    #     matriculas = Matricula.query.filter_by(id_horario=id_horario).all()
    #     alumnos_horario_db = [m.alumno for m in matriculas if m.alumno and m.alumno.url_img]

    #     # Todos los profesores (asumiendo que cualquier profesor puede estar en cualquier clase)
    #     profesores_todos_db = Profesor.query.filter(Profesor.url_img.isnot(None)).all()

    #     known_faces_to_check = []

    #     # Preparar lista de caras conocidas para este horario
    #     for alumno_db in alumnos_horario_db:
    #         # ASUNCIÓN: alumno_db.url_img es una ruta relativa como "students/id_123.jpg"
    #         # o "students/nombre_apellido.jpg"
    #         local_image_path = os.path.join(BASE_KNOWN_FACES_DIR, alumno_db.url_img)
    #         if os.path.exists(local_image_path):
    #             known_faces_to_check.append({
    #                 "id": alumno_db.id,
    #                 "rol": 0, # 0 para alumno
    #                 "nombre": f"{alumno_db.nombre} {alumno_db.apellido}",
    #                 "db_image_path": local_image_path
    #             })
    #         else:
    #             app.logger.warning(f"Ruta de imagen no encontrada para alumno {alumno_db.id}: {local_image_path}")

    #     for profesor_db in profesores_todos_db:
    #         # ASUNCIÓN: profesor_db.url_img es una ruta relativa como "professors/id_abc.jpg"
    #         local_image_path = os.path.join(BASE_KNOWN_FACES_DIR, profesor_db.url_img)
    #         if os.path.exists(local_image_path):
    #             known_faces_to_check.append({
    #                 "id": profesor_db.id,
    #                 "rol": 1, # 1 para profesor
    #                 "nombre": f"{profesor_db.nombre} {profesor_db.apellido}",
    #                 "db_image_path": local_image_path
    #             })
    #         else:
    #             app.logger.warning(f"Ruta de imagen no encontrada para profesor {profesor_db.id}: {local_image_path}")

    #     if not known_faces_to_check:
    #         app.logger.info("No hay caras conocidas con imágenes para comparar en este horario o sistema.")
    #         return jsonify({"id": 0, "message": "No hay caras conocidas con imágenes para comparar."}), 200

    #     best_match_info = None
    #     lowest_distance = float('inf')

    #     # 3. Comparar con las caras conocidas
    #     for user_data in known_faces_to_check:
    #         candidate_db_image_path = user_data["db_image_path"]
    #         try:
    #             # enforce_detection=True: DeepFace intentará detectar caras en ambas imágenes.
    #             # Si tus imágenes en BASE_KNOWN_FACES_DIR ya son caras recortadas y alineadas,
    #             # podrías poner enforce_detection=False para candidate_db_image_path,
    #             # o usar un detector_backend='skip' para esa parte.
    #             # Para la imagen capturada (captured_face_path), es más seguro usar enforce_detection=True.
    #             result = DeepFace.verify(img1_path=captured_face_path,
    #                                      img2_path=candidate_db_image_path,
    #                                      model_name=MODEL_NAME,
    #                                      distance_metric='cosine', # o 'euclidean', 'euclidean_l2'
    #                                      enforce_detection=True, # True es más seguro para la imagen capturada
    #                                      detector_backend=DETECTOR_BACKEND,
    #                                      align=True # Importante para la precisión
    #                                     )

    #             distance = result.get("distance", float('inf'))
    #             # 'verified' de DeepFace se basa en umbrales internos del modelo,
    #             # pero nosotros usaremos nuestro propio DISTANCE_THRESHOLD.
    #             # verified_by_model = result.get("verified", False)

    #             app.logger.debug(f"Comparando con {user_data['nombre']} (ID: {user_data['id']}, Rol: {user_data['rol']}) usando {candidate_db_image_path}: Distancia={distance:.4f}")

    #             if distance < lowest_distance:
    #                 lowest_distance = distance
    #                 # Solo consideramos un match si está por debajo de nuestro umbral
    #                 if distance < DISTANCE_THRESHOLD:
    #                     best_match_info = {
    #                         "id": user_data["id"],
    #                         "rol": user_data["rol"],
    #                         "nombre": user_data["nombre"],
    #                         "distance": round(lowest_distance, 4)
    #                     }
    #                 # else: # Si la distancia más baja encontrada aún es muy alta, reseteamos best_match_info
    #                 #     best_match_info = None # Esto asegura que solo devolvamos si está BAJO el umbral

    #         except ValueError as ve: # DeepFace a veces tira ValueError si no encuentra cara
    #             app.logger.warning(f"DeepFace ValueError con {candidate_db_image_path}: {ve}. Podría ser 'Face could not be detected...'.")
    #             continue
    #         except Exception as e:
    #             app.logger.error(f"Error en DeepFace.verify con {candidate_db_image_path}: {e}")
    #             continue

    #     # 4. Preparar respuesta
    #     if best_match_info and best_match_info["distance"] < DISTANCE_THRESHOLD : # Doble chequeo por si lowest_distance no fue actualizada a best_match_info
    #         app.logger.info(f"✅ Mejor coincidencia: {best_match_info['nombre']} (ID: {best_match_info['id']}), Distancia: {best_match_info['distance']:.4f}")
    #         return jsonify(best_match_info), 200
    #     else:
    #         app.logger.info(f"❌ No se encontró ninguna cara suficientemente similar. Distancia más baja: {lowest_distance:.4f}")
    #         return jsonify({"id": 0, "message": "Persona desconocida o similitud demasiado baja."}), 200

    # except Exception as e:
    #     app.logger.error(f"Error general en el endpoint /ia: {e}", exc_info=True)
    #     return jsonify({"error": f"Ocurrió un error interno: {str(e)}"}), 500
    # finally:
    #     # 5. Limpiar el archivo temporal
    #     if os.path.exists(captured_face_path):
    #         try:
    #             os.remove(captured_face_path)
    #             app.logger.info(f"Archivo temporal eliminado: {captured_face_path}")
    #         except Exception as e_rm:
    #             app.logger.error(f"Error eliminando archivo temporal {captured_face_path}: {e_rm}")

def descargar_imagen(url, nombre_archivo):
    """
    Descarga una imagen desde una URL y la guarda con un nombre de archivo.
    Maneja los errores de descarga.
    """
    try:
        # Añade un encabezado User-Agent para evitar problemas con algunos servidores que bloquean descargas de scripts.
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            with open(nombre_archivo, 'wb') as f:
                f.write(response.read())
        print(f"Imagen descargada: {nombre_archivo}")
        return True
    except Exception as e:
        print(f"Error al descargar la imagen {url}: {e}")
        return False

def descargar_imagenes_concurrente(lista_personas):
    """
    Descarga las imágenes de los alumnos de forma concurrente usando un ThreadPoolExecutor.
    """
    print("Iniciando descarga de imágenes...")
    # Limita el número de hilos para no saturar el sistema
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for persona in lista_personas:
            # Obtén la URL de la imagen, maneja el caso de que no exista
            url_imagen = persona.get('url_img', '')
            if url_imagen:
                nombre_archivo = os.path.join(
                    # Usa .jpg
                    RUTA_CARPETA_IMAGENES, f"persona_{persona['id']}_tipo_{persona["tipo"]}.jpg")
                futures.append(executor.submit(
                    descargar_imagen, url_imagen, nombre_archivo))

        # Espera a que todas las descargas se completen y verifica si hubo errores
        all_downloads_successful = all(
            futures[i].result() for i in range(len(futures)))

        if all_downloads_successful:
            print("Todas las imágenes descargadas exitosamente.")
        else:
            print("Algunas descargas de imágenes fallaron.")
    print("Descarga de imágenes completada.")

# Obtener la lista de usuarios (alumnos y profesores) de un horario específico
@app.route('/usuarios/<id_horario>', methods=['GET'])
def obtener_usuarios(id_horario):
    """
    Obtiene la lista de alumnos y profesores para un horario,
    guarda la información en la variable global y descarga las imágenes.
    """
    global lista_personas
    try:
        alumnos = Matricula.query.filter_by(id_horario=id_horario).all()
        profesores = Profesor.query.all()

        print(alumnos)

        usuarios_list = []

        for alumno in alumnos:
            usuarios_list.append({
                "id": alumno.id_alumno,
                "url_img": alumno.alumno.url_img,
                "tipo": 0  # 0 para alumnos
            })

        for profesor in profesores:
            usuarios_list.append({
                "id": profesor.id,
                "url_img": profesor.url_img,
                "tipo": 1  # 1 para profesores
            })

        lista_personas = usuarios_list  # Guarda en la variable global
        descargar_imagenes_concurrente(lista_personas)  # Descarga las imágenes

        return jsonify({"usuarios": usuarios_list}), 200
    except Exception as e:
        return jsonify({'mensaje': f'Error al obtener usuarios: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True)

    with app.app_context():
        db.create_all()
