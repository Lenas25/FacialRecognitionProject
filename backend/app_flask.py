# backend/app_flask.py
from flask import Flask, jsonify, request
from schemas import Salon, AsistenciaAlumno, AsistenciaProfesor, Horario, Desconocido, Matricula, Curso, Alumno, Profesor, Computadora
from database import db
import os
import pandas as pd
import cv2  # For image processing if needed, DeepFace uses it
from deepface import DeepFace
import tempfile  # For temporarily storing the uploaded image
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from twilio.rest import Client
from datetime import datetime, timedelta
import shutil
import os
import re # For a more robust parsing
from dotenv import load_dotenv
import urllib.request
from concurrent.futures import ThreadPoolExecutor  # Para descarga concurrent
import asyncio
import psycopg2
load_dotenv()

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI')

db.init_app(app)


RUTA_CARPETA_IMAGENES = 'imagenes_temporales'
RUTA_DESCONOCIDOS_CLASE_ACTUAL = 'desconocidos_clase_actual'

MODEL_NAME = "VGG-Face"
DETECTOR_BACKEND = "opencv" # O "ssd", "dlib", "mtcnn", "retinaface", "mediapipe", "yolov8", "yunet", "fastmtcnn"
DISTANCE_METRIC = 'cosine' # 'cosine', 'euclidean', 'euclidean_l2'
DISTANCE_THRESHOLD = 0.60 # Umbral de distancia. Ajusta esto según tus pruebas. Para VGG-Face y cosine.

if not os.path.exists(RUTA_CARPETA_IMAGENES):
    os.makedirs(RUTA_CARPETA_IMAGENES)

# Modelos populares: "VGG-Face", "Facenet", "Facenet512", "ArcFace", "SFace"
# MODEL_NAME = "Facenet"
#DISTANCE_THRESHOLD = 0.6  # Ejemplo para Facenet. Reduce para mayor certeza.
## 'opencv', 'ssd', 'dlib', 'mtcnn', 'retinaface', 'mediapipe'
#DETECTOR_BACKEND = 'mtcnn'

def execute_automatization(id_profesor):
    pass

def execute_automatization_close(id_profesor):
    pass


def parse_identity_filename(filename):
    """
    Parses a filename to extract user ID and role.
    Expected format: "persona_{id}_tipo_{tipo}.jpg"
    Returns (user_id, user_rol) or (None, None) if parsing fails.
    """
    # Example: "persona_123_tipo_0.jpg"
    #          "persona_45_tipo_1.png" (extension might vary, handle it)

    base_name = os.path.splitext(filename)[0] # Remove extension (e.g., .jpg, .png)
    parts = base_name.split('_')

    # Expected structure: ["persona", "{id}", "tipo", "{tipo_num}"]
    if len(parts) == 4 and parts[0] == "persona" and parts[2] == "tipo":
        try:
            user_id = int(parts[1])
            tipo_num = int(parts[3])

            if tipo_num == 0:
                user_rol = "alumno"
            elif tipo_num == 1:
                user_rol = "profesor"
            else:
                app.logger.warning(f"Tipo desconocido '{tipo_num}' en el nombre de archivo: {filename}")
                return None, None

            return str(user_id), user_rol # Return ID as string to match "id" field type in response
        except ValueError:
            app.logger.error(f"Error al parsear ID o tipo de '{filename}'. No son números válidos.")
            return None, None
    else:
        # Alternative more robust parsing using regex, handles variations better
        # e.g. persona_123_tipo_0.jpg, persona_123_tipo_0_extra_info.jpg
        match = re.match(r"persona_(\d+)_tipo_([01])(?:_.*)?", base_name)
        if match:
            try:
                user_id = str(match.group(1)) # Keep as string
                tipo_num = int(match.group(2))

                if tipo_num == 0:
                    user_rol = "alumno"
                elif tipo_num == 1:
                    user_rol = "profesor"
                else: # Should not happen due to regex [01]
                    app.logger.warning(f"Tipo desconocido '{tipo_num}' en el nombre de archivo (regex): {filename}")
                    return None, None

                return user_id, user_rol
            except Exception as e:
                app.logger.error(f"Error al parsear con regex ID o tipo de '{filename}': {e}")
                return None, None

        app.logger.warning(f"Formato de nombre de archivo no reconocido: {filename}. No se pudo extraer ID/Rol.")
        return None, None

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

# registrar la asistencia de un grupo de alumnos y profesores, este se llama al finalizar la clase para el registro de los datos segun este en el local , desde del front recibiendo el id del horario y la lista de alumnos y profesores en formato
# [
#     {
#         "id": 1,
#         "tipo": 0,
#         "fecha": "2023-10-01",
#         "estado": "A"/"F"
#     }
@app.route('/asistencia/<id_horario>', methods=['POST'])
async def registrar_asistencia(id_horario):
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
        fecha = datetime.now().strftime('%Y-%m-%d')
        if item['rol'] == 0:
            new_asistencias_alumnos.append(AsistenciaAlumno(
                id_horario=id_horario,
                id_alumno=item['id'],
                fecha=fecha,
                estado=item['estado'],
                tiempo_permanencia=str(item["tiempo"])
            ))
        elif item['rol'] == 1:
            new_asistencias_profesores.append(AsistenciaProfesor(
                id_horario=id_horario,
                id_profesor=item['id'],
                fecha=fecha,
                estado=item['estado'],
                tiempo_permanencia=str(item["tiempo"])
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
async def registrar_desconocido(id_horario):
    # recibe un array de url_img
    data = request.get_json()
    if not data:
        return jsonify({"message": "Es necesario información."}), 400

    horario = Horario.query.filter_by(id=id_horario).first()
    if not horario:
        return jsonify({"message": "Horario no encontrado."}), 404

    new_desconocidos = []

    for url in data["url_img"]:
        new_desconocidos.append(Desconocido(
            id_horario=id_horario,
            url_img=url,
            fecha=datetime.now().strftime("%Y-%m-%d"),
            )
        )

    try:
        db.session.add_all(new_desconocidos)
        db.session.commit()
        return jsonify({'message': 'Desconocido agregado exitosamente'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error al insertar el desconocido: {str(e)}'}), 500

# exportar la asistencia en un excel con la lista de alumnos y profesores, y la lista de desconocidos
@app.route('/reporte/<salon>/<id_horario>', methods=['POST'])
async def enviar_reporte(salon, id_horario):

    EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
    RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')


    TEMP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp_reports')
    os.makedirs(TEMP_FOLDER, exist_ok=True) # Crea la carpeta si no existe


    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_filename = f'reporte_asistencia_{salon}_{id_horario}_{timestamp}.xlsx'
    excel_filepath = os.path.join(TEMP_FOLDER, excel_filename)

    try:
        alumnos = AsistenciaAlumno.query.filter(
            id_horario == id_horario,
            AsistenciaAlumno.fecha == datetime.now().date()
        ).all()
        profesores = AsistenciaProfesor.query.filter(
            id_horario == id_horario,
            AsistenciaAlumno.fecha == datetime.now().date()
        ).all()
        desconocidos = Desconocido.query.filter(
            id_horario == id_horario,
            Desconocido.fecha == datetime.now().date()
        ).all()

        df_desconocidos = pd.DataFrame([(d.id_horario, d.url_img, d.fecha.strftime('%Y-%m-%d')) for d in desconocidos],
                                       columns=['Seccion', 'Imagen', 'Fecha de Detección'])
        df_alumnos = pd.DataFrame([(a.id, a.id_horario, a.id_alumno, a.estado, a.fecha.strftime('%Y-%m-%d'), a.tiempo_permanencia) for a in alumnos],
                                  columns=['ID', 'Seccion', 'Código', 'Estado', 'Fecha de Detección', 'Tiempo Asistencia (min)'])
        df_docentes = pd.DataFrame([(d.id, d.id_horario, d.id_profesor, d.estado, d.fecha.strftime('%Y-%m-%d'), d.tiempo_permanencia) for d in profesores],
                                   columns=['ID', 'Seccion', 'Código de Profesor', 'Estado', 'Fecha de Detección', 'Tiempo Asistencia (min)'])

        with pd.ExcelWriter(excel_filepath, engine="xlsxwriter") as writer:
            df_alumnos.to_excel(writer, sheet_name='Alumnos', index=False)
            df_docentes.to_excel(writer, sheet_name='Docentes', index=False)
            df_desconocidos.to_excel(writer, sheet_name='Desconocidos', index=False)

            workbook = writer.book

            # Formato para encabezados: fondo azul claro, texto blanco, negrita, bordes
            header_format = workbook.add_format({
                'bold': True,
                'bg_color': '#B50D30',
                'font_color': 'white',
                'border': 1,
                'align': 'center'
            })
            # Formato para celdas normales: bordes
            cell_format = workbook.add_format({'border': 1})

            # Formatear cada hoja
            for sheet_name, df in zip(['Alumnos', 'Docentes', 'Desconocidos'],
                                    [df_alumnos, df_docentes, df_desconocidos]):
                worksheet = writer.sheets[sheet_name]

                # Ajustar ancho de columnas y aplicar formato de encabezado
                for i, col in enumerate(df.columns):
                    column_len = max(df[col].astype(str).map(len).max(), len(col))
                    worksheet.set_column(i, i, column_len + 2, cell_format)
                    worksheet.write(0, i, col, header_format)  # Encabezado con formato

                # Aplicar formato de borde a todas las celdas de datos
                for row in range(1, len(df) + 1):
                    for col in range(len(df.columns)):
                        worksheet.write(row, col, df.iloc[row - 1, col], cell_format)

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

        with open(excel_filepath, 'rb') as adjunto:
            parte_adjunta = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            parte_adjunta.set_payload(adjunto.read())
            encoders.encode_base64(parte_adjunta)
            parte_adjunta.add_header('Content-Disposition', f'attachment; filename="{excel_filename}"')
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

    finally:
        # 5. Asegurarse de eliminar el archivo SIEMPRE, incluso si hay un error
        if os.path.exists(excel_filepath):
            os.remove(excel_filepath)


# enviar mensaje a contactos de quienes tienen una falta en su asistencia
@app.route('/mensaje/<id_horario>', methods=['POST'])
async def enviar_mensaje(id_horario):
    TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        raise ValueError(
            "Las variables de entorno de Twilio (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER) deben estar configuradas.")

    cliente = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    alumnos_ausentes = AsistenciaAlumno.query.filter(
        AsistenciaAlumno.id_horario == id_horario,
        AsistenciaAlumno.estado == 'ausente',
        AsistenciaAlumno.fecha == datetime.now().date()
        ).all()
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

    return jsonify({'mensaje': 'No hay alumnos ausentes para notificar.'}), 200


@app.route('/ia', methods=['POST'])
async def ia_recognize_face(): # id_horario no se usa en el nuevo flujo, pero lo mantengo si lo necesitas para otra cosa
    if 'image_file' not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    image_file = request.files['image_file']
    if image_file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    fd, captured_face_path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)

    best_match_response = {
        "id": "unknown",
        "rol": "NA",
        "clasificado": False,
        "distance": float('inf') # Inicializar con infinito para la distancia
    }

    try:
        image_file.save(captured_face_path)
        app.logger.info(f"Imagen capturada guardada temporalmente en: {captured_face_path}")

        # 1. Anti-spoofing test
        try:
            app.logger.info("Iniciando prueba anti-spoofing...")
            # Nota: extract_faces puede encontrar múltiples caras.
            # Aquí asumimos que la imagen capturada debería tener predominantemente una cara real.
            face_objs = DeepFace.extract_faces(
                img_path=captured_face_path,
                detector_backend=DETECTOR_BACKEND,
                enforce_detection=True, # Asegura que se detecte al menos una cara
                anti_spoofing=True,
                align=True
            )

            if not face_objs: # No se detectaron caras
                app.logger.warning("Anti-spoofing: No se detectaron caras en la imagen.")
                # Si no hay caras, no podemos clasificar, pero no necesariamente es un error de spoofing
                # Podríamos considerarlo "unknown" o un error específico.
                # Por ahora, lo tratamos como "unknown" y se guardará en desconocidos.
                best_match_response["message"] = "No se detectó ninguna cara real."

            elif not all(face_obj.get("is_real", False) for face_obj in face_objs):
                app.logger.warning("Anti-spoofing: Se detectó una posible imagen falsa (spoof).")
                best_match_response["message"] = "La imagen parece ser un intento de spoofing (falsa)."
                # Para un intento de spoof, no procedemos a DeepFace.find
                return jsonify(best_match_response), 200 # O un 403 Forbidden si es más apropiado
            else:
                app.logger.info("Anti-spoofing: La imagen parece ser real.")
                best_match_response["message"] = "La imagen parece ser real."

        except ValueError as ve: # DeepFace puede lanzar ValueError si no detecta cara
            if "Face could not be detected" in str(ve):
                app.logger.warning(f"Anti-spoofing: No se pudo detectar cara en la imagen: {ve}")
                best_match_response["message"] = "No se pudo detectar el rostro correctamente"
                # No se procede con find si no hay cara
            else:
                app.logger.error(f"Anti-spoofing: ValueError durante extract_faces: {ve}")
                best_match_response["message"] = "No se pudo detectar el rostro correctamente"


            best_match_response["message"] = "No se pudo detectar el rostro correctamente"
            return jsonify(best_match_response), 400 # O un 403 Forbidden si es más apropiado

        except Exception as e:
            app.logger.error(f"Error inesperado durante anti-spoofing: {e}", exc_info=True)
            best_match_response["message"] = "No se pudo detectar el rostro correctamente"
            # No se procede con find y se guarda en desconocidos.

        # Solo proceder a DeepFace.find si el anti-spoofing fue exitoso (o no concluyente pero sin error grave)
        # y si no hay un mensaje de error previo que indique no continuar.
        if "message" not in best_match_response or "La imagen parece ser real." in best_match_response.get("message", ""):
            # 2. Usar DeepFace.find para encontrar coincidencias
            app.logger.info(f"Buscando coincidencias en: {RUTA_CARPETA_IMAGENES}")
            if not os.path.exists(RUTA_CARPETA_IMAGENES) or not os.listdir(RUTA_CARPETA_IMAGENES):
                app.logger.warning(f"El directorio de caras conocidas '{RUTA_CARPETA_IMAGENES}' no existe o está vacío.")
                best_match_response["message"] = "La base de datos de caras conocidas está vacía o no se encuentra."
            else:
                try:
                    # DeepFace.find devuelve una lista de DataFrames.
                    # Si la imagen de entrada (captured_face_path) tiene múltiples caras,
                    # habrá un DataFrame por cada cara detectada en la imagen de entrada.
                    # Asumimos que nos interesa la primera (o única) cara detectada en la imagen de entrada.
                    dfs = DeepFace.find(
                        img_path=captured_face_path,
                        db_path=RUTA_CARPETA_IMAGENES,
                        model_name=MODEL_NAME,
                        distance_metric=DISTANCE_METRIC,
                        enforce_detection=True, # Asegura que se detecte cara en img_path
                        detector_backend=DETECTOR_BACKEND,
                        align=True,
                        silent=True # Para menos output en consola de DeepFace
                    )

                    # dfs es una lista de dataframes. Usualmente, si solo hay una cara en img_path, dfs tendrá 1 elemento.
                    if dfs and not dfs[0].empty:
                        # Tomamos el primer DataFrame (correspondiente a la primera cara detectada en captured_face_path)
                        # y de ese DataFrame, la primera fila (la coincidencia más cercana)
                        best_match_candidate_df = dfs[0]

                        # La columna de distancia se nombra usualmente como 'model_metric', e.g., 'VGG-Face_cosine'
                        # o puede ser simplemente 'distance' si se usa un wrapper o una versión específica.
                        # Intentemos obtenerla dinámicamente o usar una columna conocida.
                        # distance_col_name = f"{MODEL_NAME}_{DISTANCE_METRIC}"
                        distance_col_name = "distance"
                        if distance_col_name not in best_match_candidate_df.columns:
                             # DeepFace a veces usa solo la métrica como nombre de columna si el modelo es obvio por el contexto
                             # o si usa un nombre genérico. Hay que revisar la salida exacta.
                             # Si no encuentra la columna específica, intentamos con 'distance' o la primera numérica después de 'identity'
                             # Por ahora, asumimos que la columna existe o DeepFace usa un default conocido.
                             # Si es cosine, euclidean, euclidean_l2 y está en columnas, la tomamos.
                            if DISTANCE_METRIC in best_match_candidate_df.columns:
                                distance_col_name = DISTANCE_METRIC
                            else: # Fallback a un nombre genérico si la construcción falla
                                app.logger.warning(f"Columna de distancia '{distance_col_name}' no encontrada. Verifique las columnas: {best_match_candidate_df.columns}")
                                # Buscamos una columna que pueda ser de distancia
                                possible_dist_cols = [col for col in best_match_candidate_df.columns if col not in ['identity', 'target_x', 'target_y', 'target_w', 'target_h', 'source_x', 'source_y', 'source_w', 'source_h']]
                                if possible_dist_cols:
                                    distance_col_name = possible_dist_cols[0] # Tomar la primera como heurística
                                    app.logger.warning(f"Usando heurística para columna de distancia: '{distance_col_name}'")
                                else:
                                    raise KeyError(f"No se pudo determinar la columna de distancia en el DataFrame. Cols: {best_match_candidate_df.columns}")

                        # El DataFrame ya viene ordenado por distancia por DeepFace.find
                        top_match = best_match_candidate_df.iloc[0]
                        identity_path = top_match['identity']
                        distance = top_match[distance_col_name]

                        app.logger.info(f"Mejor candidato encontrado: {identity_path} con distancia: {distance:.4f}")

                        if distance < DISTANCE_THRESHOLD:
                            filename_only = os.path.basename(identity_path)
                            user_id, user_rol = parse_identity_filename(filename_only)

                            if user_id is not None and user_rol is not None:
                                best_match_response["id"] = user_id
                                best_match_response["rol"] = user_rol
                                best_match_response["clasificado"] = True
                                best_match_response["distance"] = round(float(distance), 4)
                                best_match_response["message"] = "Se identificó correctamente al usuario."
                                app.logger.info(f"✅ Persona clasificada: ID={user_id}, Rol={user_rol}, Distancia={distance:.4f}")

                                # ✅ Solo si es profesor, buscar datos adicionales
                                if user_rol == 'profesor':
                                    try:
                                        profesor = db.session.query(Profesor, Horario, Curso).join(Horario, Profesor.id == Horario.id_profesor).join(Curso, Horario.id_curso == Curso.id).filter(Profesor.id == int(user_id)).first()
                                        if profesor:
                                            p, h, c = profesor
                                            best_match_response["correo"] = p.codigo
                                            best_match_response["contrasena"] = p.contrasena
                                            app.logger.info(f"📤 Datos del profesor añadidos: correo={p.correo}, curso={c.nombre}")
                                        else:
                                            app.logger.warning(f"⚠️ No se encontraron datos del profesor con ID {user_id} en la base de datos.")
                                    except Exception as db_error:
                                        app.logger.error(f"❌ Error consultando datos del profesor en la BD: {db_error}", exc_info=True)



                                best_match_response["message"] = "Se identifico correctamente al usuario."
                            else:
                                app.logger.warning(f"Formato de nombre de archivo no reconocido para {identity_path}. No se pudo extraer ID/Rol.")
                                best_match_response["message"] = "No se reconoce al usuario."
                                best_match_response["distance"] = round(float(distance), 4) # Aún así informamos la distancia
                        else:
                            best_match_response["clasificado"] = True
                            app.logger.info(f"❌ Coincidencia encontrada ({identity_path}) pero la distancia ({distance:.4f}) supera el umbral ({DISTANCE_THRESHOLD}).")
                            best_match_response["message"] = "Vuelve a intentar, por favor."
                            best_match_response["distance"] = round(float(distance), 4)
                    else:
                        app.logger.info("No se encontraron coincidencias en la base de datos de caras conocidas.")
                        best_match_response["message"] = "No se encontro al usuario (posible desconocido)."

                except ValueError as ve: # DeepFace.find puede lanzar ValueError si no detecta cara en img_path
                    if "Face could not be detected" in str(ve) or "model instance" in str(ve).lower(): # A veces es "model instance is not built"
                        app.logger.warning(f"DeepFace.find: No se pudo detectar cara en la imagen de entrada: {ve}")
                        best_match_response["message"] = "No se encontro al usuario."
                    else:
                        app.logger.error(f"DeepFace.find: ValueError: {ve}", exc_info=True)
                        best_match_response["message"] = "No se encontro al usuario."
                except Exception as e:
                    app.logger.error(f"Error durante DeepFace.find: {e}", exc_info=True)
                    best_match_response["message"] = "No se encontro al usuario."

        # 3. Si no se clasificó, guardar la imagen en la carpeta de desconocidos
        if not best_match_response["clasificado"]:
            try:
                os.makedirs(RUTA_DESCONOCIDOS_CLASE_ACTUAL, exist_ok=True)
                # Usar un nombre único para la imagen guardada
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                unknown_filename = f"unknown_{timestamp}.jpg"
                destination_path = os.path.join(RUTA_DESCONOCIDOS_CLASE_ACTUAL, unknown_filename)
                shutil.copy(captured_face_path, destination_path)
                app.logger.info(f"Imagen no clasificada guardada en: {destination_path}")
                if "message" not in best_match_response: # Si no hay un mensaje más específico
                    best_match_response["message"] = "Es un desconocido, imagen guardada."
                best_match_response["saved_unknown_path"] = destination_path # Opcional: informar dónde se guardó
            except Exception as e_save:
                app.logger.error(f"Error guardando imagen desconocida: {e_save}", exc_info=True)

        # Si hay un mensaje pero no distancia (porque no se llegó a find), quitar la distancia infinita
        if best_match_response["distance"] == float('inf') and "message" in best_match_response:
             del best_match_response["distance"]


        return jsonify(best_match_response), 200

    except Exception as e:
        app.logger.error(f"Error general en el endpoint /ia: {e}", exc_info=True)
        return jsonify({"error": f"Ocurrió un error interno: {str(e)}", "clasificado": False}), 500
    finally:
        # 4. Limpiar el archivo temporal
        if os.path.exists(captured_face_path):
            try:
                os.remove(captured_face_path)
                app.logger.info(f"Archivo temporal eliminado: {captured_face_path}")
            except Exception as e_rm:
                app.logger.error(f"Error eliminando archivo temporal {captured_face_path}: {e_rm}")

@app.route('/computadora-ip/<nombre>', methods=['GET'])
def obtener_ip_por_nombre(nombre):
    try:
        computadora = Computadora.query.filter_by(nombre=nombre).first()
        if computadora:
            return jsonify({"ip": computadora.ip}), 200
        else:
            return jsonify({"error": "No se encontró la computadora"}), 404

    except Exception as e:
        return jsonify({'mensaje': f'Error al obtener IP: {str(e)}'}), 500

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
            print(f"Procesando persona: {persona['id']} con tipo {persona['tipo']} y URL: {url_imagen}")
            if url_imagen:
                nombre_archivo = os.path.join(
                    # Usa .jpg
                    RUTA_CARPETA_IMAGENES, f"persona_{persona['id']}_tipo_{persona['tipo']}.jpg")
                print(f"Preparando descarga de imagen: {nombre_archivo} desde {url_imagen}")
                futures.append(executor.submit(
                    descargar_imagen, url_imagen, nombre_archivo))
                print(f"Descarga programada para: {nombre_archivo}")

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
async def obtener_usuarios(id_horario):
    """
    Obtiene la lista de alumnos y profesores para un horario,
    guarda la información en la variable global y descarga las imágenes.
    """
    try:
        alumnos = Matricula.query.filter_by(id_horario=id_horario).all()
        profesores = Profesor.query.all()

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

        descargar_imagenes_concurrente(usuarios_list)  # Descarga las imágenes
        return jsonify({"usuarios": usuarios_list}), 200
    except Exception as e:
        return jsonify({'mensaje': f'Error al obtener usuarios: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
