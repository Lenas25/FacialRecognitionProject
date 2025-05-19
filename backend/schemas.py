from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, BigInteger, String, Integer, Time, Date, ForeignKey, Enum
from sqlalchemy.orm import relationship
from database import db

class Salon(db.Model):
    __tablename__ = 'salon'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    etiqueta = Column(String(20))
    piso = Column(Integer)
    pabellon = Column(String(50))
    
    horarios = relationship("Horario", back_populates="salon")
    
class Horario(db.Model):
    __tablename__ = 'horario'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    dia_semana = Column(Enum('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'), name='dia_semana')
    hora_inicio = Column(Time)
    hora_fin = Column(Time)
    id_salon = Column(BigInteger, ForeignKey('salon.id'))
    id_curso = Column(BigInteger, ForeignKey('curso.id'))
    
    
    salon = relationship("Salon", back_populates="horarios")
    curso = relationship("Curso", back_populates="horarios")
    asistencia_alumnos = relationship("AsistenciaAlumno", back_populates="horario")
    asistencia_profesores = relationship("AsistenciaProfesor", back_populates="horario")
    desconocidos = relationship("Desconocido",back_populates="horario")
    matriculas = relationship("Matricula", back_populates="horario")

class Matricula(db.Model):
    id_horario = Column(BigInteger, ForeignKey('horario.id'), primary_key=True)
    id_alumno = Column(BigInteger, ForeignKey('alumno.id'), primary_key=True)
    
    horario = relationship("Horario", back_populates="matriculas")
    alumno = relationship("Alumno", back_populates="matriculas")

class Curso(db.Model):
    __tablename__ = 'curso'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre = Column(String(50))
    
    horarios = relationship("Horario", back_populates="curso")

class Desconocido(db.Model):
    __tablename__ = 'desconocido'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    id_horario = Column(BigInteger, ForeignKey('horario.id'))
    url_img = Column(String(255))
    fecha = Column(Date)
    
    horario = relationship("Horario", back_populates="desconocidos")
    
class Alumno(db.Model):
    __tablename__ = 'alumno'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre = Column(String(50))
    apellido = Column(String(50))
    codigo_universitario = Column(String(20))
    url_img = Column(String(255))
    contacto = Column(String(50))
    
    asistencia = relationship("AsistenciaAlumno", back_populates="alumno")
    matriculas = relationship("Matricula", back_populates="alumno")

class Profesor(db.Model):
    __tablename__ = 'profesor'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre = Column(String(50))
    apellido = Column(String(50))
    correo = Column(String(50))
    url_img = Column(String(255))
    contrasena = Column(String(255))
    codigo = Column(String(20))
    
    asistencia = relationship("AsistenciaProfesor", back_populates="profesor")

class AsistenciaAlumno(db.Model):
    __tablename__ = 'asistencia_alumno'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    id_horario = Column(BigInteger, ForeignKey('horario.id'))
    id_alumno = Column(BigInteger, ForeignKey('alumno.id'))
    fecha = Column(Date)
    estado = Column(Enum('presente', 'ausente', 'tarde'))
    
    horario = relationship("Horario", back_populates="asistencia_alumnos")
    alumno = relationship("Alumno", back_populates="asistencia")

class AsistenciaProfesor(db.Model):
    __tablename__ = 'asistencia_profesor'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    id_horario = Column(BigInteger, ForeignKey('horario.id'))
    id_profesor = Column(BigInteger, ForeignKey('profesor.id'))
    fecha = Column(Date)
    estado = Column(Enum('presente', 'ausente', 'tarde'))
    
    horario = relationship("Horario", back_populates="asistencia_profesores")
    profesor = relationship("Profesor", back_populates="asistencia")