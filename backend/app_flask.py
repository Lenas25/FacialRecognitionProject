# backend/app_flask.py
from flask import Flask, jsonify, request
from schemas import Salon, AsistenciaAlumno, AsistenciaProfesor, Horario, Desconocido
from database import db
import os
import pandas as pd
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from twilio.rest import Client
import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:root@localhost:5432/db_reconocimiento'

db.init_app(app)

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

@app.route('/desconocido/<id_horario>', methods=['POST'])
def registrar_desconocido(id_horario):
    # se recibe en el formato {
    #"id_horario":11,
    #"url_imagen":"",
    #}
    
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
        alumnos = AsistenciaAlumno.query.filter_by(id_horario=id_horario).all()
        profesores = AsistenciaProfesor.query.filter_by(id_horario=id_horario).all() 
        desconocidos = Desconocido.query.filter_by(id_horario=id_horario).all()
        
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
            df_desconocidos.to_excel(writer, sheet_name='Desconocidos', index=False)
        
            worksheet_alumnos = writer.sheets['Alumnos']
            worksheet_docentes = writer.sheets['Docentes']
            worksheet_desconocidos = writer.sheets['Desconocidos']

            for i, col in enumerate(df_alumnos.columns):
                column_len = max(df_alumnos[col].astype(str).map(len).max(), len(col))
                worksheet_alumnos.set_column(i, i, column_len + 2)

            for i, col in enumerate(df_docentes.columns):
                column_len = max(df_docentes[col].astype(str).map(len).max(), len(col))
                worksheet_docentes.set_column(i, i, column_len + 2)

            for i, col in enumerate(df_desconocidos.columns):
                column_len = max(df_desconocidos[col].astype(str).map(len).max(), len(col))
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
        parte_adjunta = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        parte_adjunta.set_payload(adjunto.read())
        encoders.encode_base64(parte_adjunta)
        parte_adjunta.add_header('Content-Disposition', f'attachment; filename="{excel_filename}"')
        mensaje.attach(parte_adjunta)

        # Conectar al servidor SMTP y enviar el correo
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as servidor:
            servidor.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            servidor.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, mensaje.as_string())

        adjunto.close()
        os.remove(excel_filename)

        return jsonify({'mensaje': 'Reporte generado y enviado con éxito'}), 200

    except Exception as e:
        print(f"Error al generar y enviar el reporte: {e}") #Loggear el error
        return jsonify({'mensaje': f'Error al generar el reporte: {str(e)}'}), 500  # Devuelve un error 500

# enviar mensaje a contactos de quienes tienen una falta en su asistencia
@app.route('/mensaje/<id_horario>', methods=['POST'])
def enviar_mensaje(id_horario):
    TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
    
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        raise ValueError("Las variables de entorno de Twilio (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER) deben estar configuradas.")

    cliente = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    
    alumnos_ausentes = AsistenciaAlumno.query.filter(AsistenciaAlumno.id_horario == id_horario, AsistenciaAlumno.estado == 'ausente').all()
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

    
if __name__ == '__main__':
    app.run(debug=True)

    with app.app_context():
        db.create_all()
