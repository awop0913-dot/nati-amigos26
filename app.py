from flask import (
    Flask, render_template, request, redirect,
    session, send_file
)
import sqlite3
import hashlib
import os
import shutil
from datetime import datetime

# ==============================
# CONFIGURACIÓN GENERAL
# ==============================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "cooperativa.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

SECRET_KEY = "clave_super_segura_2025"

app = Flask(__name__)
app.secret_key = SECRET_KEY


# ==============================
# UTILIDADES
# ==============================

def db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def inicializar_db():
    conn = db()
    cur = conn.cursor()

    # Tabla de socios (para login web)
    cur.execute("""CREATE TABLE IF NOT EXISTS socios_web (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero_socio TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        password_hash TEXT NOT NULL
    )""")

    # Tabla admins
    cur.execute("""CREATE TABLE IF NOT EXISTS admin (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        nombre TEXT NOT NULL
    )""")

    # Tabla aportes
    cur.execute("""CREATE TABLE IF NOT EXISTS aportes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        socio_id INTEGER NOT NULL,
        fecha TEXT NOT NULL,
        monto REAL NOT NULL,
        frecuencia TEXT,
        FOREIGN KEY (socio_id) REFERENCES socios_web(id)
    )""")

    # Tabla retiros
    cur.execute("""CREATE TABLE IF NOT EXISTS retiros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        socio_id INTEGER NOT NULL,
        fecha TEXT NOT NULL,
        monto REAL NOT NULL,
        motivo TEXT,
        FOREIGN KEY (socio_id) REFERENCES socios_web(id)
    )""")

    # Tabla préstamos
    cur.execute("""CREATE TABLE IF NOT EXISTS prestamos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        socio_id INTEGER NOT NULL,
        fecha_inicio TEXT NOT NULL,
        fecha_fin TEXT,
        monto REAL NOT NULL,
        tasa_interes REAL,
        tipo_interes TEXT,
        saldo_pendiente REAL,
        estado TEXT,
        FOREIGN KEY (socio_id) REFERENCES socios_web(id)
    )""")

    # Tabla pagos de préstamo
    cur.execute("""CREATE TABLE IF NOT EXISTS pagos_prestamo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prestamo_id INTEGER NOT NULL,
        fecha TEXT NOT NULL,
        monto_principal REAL,
        monto_interes REAL,
        monto_multa REAL,
        FOREIGN KEY (prestamo_id) REFERENCES prestamos(id)
    )""")

    # Crear admin por defecto si no existe
    cur.execute("SELECT COUNT(*) FROM admin")
    count_admin = cur.fetchone()[0]
    if count_admin == 0:
        usuario = "admin"
        password = "A$vsm2050"
        nombre = "Administrador General"
        cur.execute(
            "INSERT INTO admin (usuario, password_hash, nombre) VALUES (?,?,?)",
            (usuario, hash_password(password), nombre)
        )

    conn.commit()
    conn.close()


# ==============================
# DECORADORES
# ==============================

def login_required(f):
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def admin_required(f):
    def wrapper(*args, **kwargs):
        if "admin_id" not in session:
            return redirect("/admin/login")
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


# ==============================
# RUTAS BÁSICAS
# ==============================

@app.route("/")
def index():
    if session.get("admin_id"):
        return redirect("/admin/panel")
    if session.get("user_id"):
        return redirect("/dashboard")
    return redirect("/login")


# ==============================
# LOGIN SOCIO
# ==============================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        numero = request.form.get("numero")
        password = request.form.get("password")

        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT id, numero_socio, nombre, password_hash FROM socios_web WHERE numero_socio = ?", (numero,))
        row = cur.fetchone()
        conn.close()

        if row and row["password_hash"] == hash_password(password):
            session.clear()
            session["user_id"] = row["id"]
            session["numero_socio"] = row["numero_socio"]
            session["nombre"] = row["nombre"]
            return redirect("/dashboard")
        else:
            return render_template("login.html", error="Credenciales incorrectas")

    return render_template("login.html")


# ==============================
# LOGIN ADMIN
# ==============================

@app.route("/admin/login", methods=["GET", "POST"])
def login_admin():
    if request.method == "POST":
        usuario = request.form.get("usuario")
        password = request.form.get("password")

        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT id, usuario, password_hash, nombre FROM admin WHERE usuario = ?", (usuario,))
        row = cur.fetchone()
        conn.close()

        if row and row["password_hash"] == hash_password(password):
            session.clear()
            session["admin_id"] = row["id"]
            session["admin_nombre"] = row["nombre"]
            return redirect("/admin/panel")
        else:
            return render_template("admin_login.html", error="Credenciales incorrectas")

    return render_template("admin_login.html")


# ==============================
# LOGOUT
# ==============================

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ==============================
# DASHBOARD SOCIO
# ==============================

def calcular_resumen_socio(socio_id: int):
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COALESCE(SUM(monto),0) FROM aportes WHERE socio_id = ?", (socio_id,))
    total_aportes = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(monto),0) FROM retiros WHERE socio_id = ?", (socio_id,))
    total_retiros = cur.fetchone()[0]

    cur.execute("""SELECT COALESCE(SUM(monto),0)
                FROM prestamos
                WHERE socio_id = ?""", (socio_id,))
    total_prestamos = cur.fetchone()[0]

    cur.execute("""SELECT COALESCE(SUM(monto_principal),0),
                           COALESCE(SUM(monto_interes),0),
                           COALESCE(SUM(monto_multa),0)
                    FROM pagos_prestamo pp
                    JOIN prestamos p ON pp.prestamo_id = p.id
                    WHERE p.socio_id = ?""", (socio_id,))
    fila = cur.fetchone()
    total_pag_principal = fila[0]
    total_pag_interes = fila[1]
    total_pag_multa = fila[2]

    conn.close()

    saldo_ahorro = total_aportes - total_retiros
    return {
        "total_aportes": total_aportes,
        "total_retiros": total_retiros,
        "total_prestamos": total_prestamos,
        "total_pag_principal": total_pag_principal,
        "total_pag_interes": total_pag_interes,
        "total_pag_multa": total_pag_multa,
        "saldo_ahorro": saldo_ahorro
    }


@app.route("/dashboard")
@login_required
def dashboard():
    socio_id = session["user_id"]
    resumen = calcular_resumen_socio(socio_id)
    return render_template("dashboard.html", nombre=session["nombre"], resumen=resumen)


@app.route("/aportes")
@login_required
def ver_aportes():
    socio_id = session["user_id"]
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT fecha, monto, frecuencia FROM aportes WHERE socio_id = ? ORDER BY fecha DESC", (socio_id,))
    rows = cur.fetchall()
    conn.close()
    return render_template("aportes.html", rows=rows)


@app.route("/retiros")
@login_required
def ver_retiros():
    socio_id = session["user_id"]
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT fecha, monto, motivo FROM retiros WHERE socio_id = ? ORDER BY fecha DESC", (socio_id,))
    rows = cur.fetchall()
    conn.close()
    return render_template("retiros.html", rows=rows)


@app.route("/prestamos")
@login_required
def ver_prestamos():
    socio_id = session["user_id"]
    conn = db()
    cur = conn.cursor()
    cur.execute("""SELECT fecha_inicio, fecha_fin, monto, tasa_interes,
                          tipo_interes, saldo_pendiente, estado
                 FROM prestamos
                 WHERE socio_id = ?
                 ORDER BY fecha_inicio DESC""", (socio_id,))
    rows = cur.fetchall()
    conn.close()
    return render_template("prestamos.html", rows=rows)


@app.route("/pagos")
@login_required
def ver_pagos():
    socio_id = session["user_id"]
    conn = db()
    cur = conn.cursor()
    cur.execute("""SELECT pp.fecha, pp.monto_principal, pp.monto_interes, pp.monto_multa
                 FROM pagos_prestamo pp
                 JOIN prestamos p ON pp.prestamo_id = p.id
                 WHERE p.socio_id = ?
                 ORDER BY pp.fecha DESC""", (socio_id,))
    rows = cur.fetchall()
    conn.close()
    return render_template("pagos.html", rows=rows)


# ==============================
# PANEL ADMIN
# ==============================

@app.route("/admin/panel")
@admin_required
def admin_panel():
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM socios_web")
    total_socios = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(monto),0) FROM aportes")
    total_aportes = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(monto),0) FROM retiros")
    total_retiros = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(monto),0) FROM prestamos")
    total_prestamos = cur.fetchone()[0]

    conn.close()

    saldo_neto = total_aportes - total_retiros

    return render_template(
        "admin_panel.html",
        total_socios=total_socios,
        total_aportes=total_aportes,
        total_retiros=total_retiros,
        total_prestamos=total_prestamos,
        saldo_neto=saldo_neto
    )


# ==============================
# ADMIN: GESTIÓN DE SOCIOS
# ==============================

@app.route("/admin/socios")
@admin_required
def admin_socios():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, numero_socio, nombre FROM socios_web ORDER BY numero_socio")
    socios = cur.fetchall()
    conn.close()
    return render_template("admin_socios_lista.html", socios=socios)


@app.route("/admin/socios/nuevo", methods=["GET", "POST"])
@admin_required
def admin_socio_nuevo():
    error = None
    if request.method == "POST":
        numero = request.form.get("numero_socio")
        nombre = request.form.get("nombre")
        password = request.form.get("password")

        if not numero or not nombre or not password:
            error = "Todos los campos son obligatorios."
        else:
            try:
                conn = db()
                cur = conn.cursor()
                cur.execute("""INSERT INTO socios_web (numero_socio, nombre, password_hash)
                            VALUES (?,?,?)""", (numero, nombre, hash_password(password)))
                conn.commit()
                conn.close()
                return redirect("/admin/socios")
            except Exception:
                error = "Error: el número de socio ya existe."

    return render_template("admin_socio_form.html", modo="nuevo", error=error, socio=None)


@app.route("/admin/socios/<int:socio_id>/editar", methods=["GET", "POST"])
@admin_required
def admin_socio_editar(socio_id):
    conn = db()
    cur = conn.cursor()

    if request.method == "POST":
        numero = request.form.get("numero_socio")
        nombre = request.form.get("nombre")
        cur.execute("""UPDATE socios_web
                    SET numero_socio = ?, nombre = ?
                    WHERE id = ?""", (numero, nombre, socio_id))
        conn.commit()
        conn.close()
        return redirect("/admin/socios")

    cur.execute("SELECT id, numero_socio, nombre FROM socios_web WHERE id = ?", (socio_id,))
    socio = cur.fetchone()
    conn.close()
    return render_template("admin_socio_form.html", modo="editar", socio=socio, error=None)


@app.route("/admin/socios/<int:socio_id>/password", methods=["GET", "POST"])
@admin_required
def admin_socio_password(socio_id):
    error = None
    if request.method == "POST":
        password = request.form.get("password")
        if not password:
            error = "La contraseña no puede estar vacía."
        else:
            conn = db()
            cur = conn.cursor()
            cur.execute("UPDATE socios_web SET password_hash = ? WHERE id = ?", (hash_password(password), socio_id))
            conn.commit()
            conn.close()
            return redirect("/admin/socios")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, numero_socio, nombre FROM socios_web WHERE id = ?", (socio_id,))
    socio = cur.fetchone()
    conn.close()
    return render_template("admin_socio_password.html", socio=socio, error=error)


@app.route("/admin/socios/<int:socio_id>/eliminar", methods=["POST"])
@admin_required
def admin_socio_eliminar(socio_id):
    conn = db()
    cur = conn.cursor()

    # borrar pagos de préstamos del socio
    cur.execute("SELECT id FROM prestamos WHERE socio_id = ?", (socio_id,))
    prestamos_ids = [r["id"] for r in cur.fetchall()]
    if prestamos_ids:
        cur.execute(
            "DELETE FROM pagos_prestamo WHERE prestamo_id IN ({})".format(
                ",".join("?" * len(prestamos_ids))
            ),
            prestamos_ids
        )
    # borrar préstamos, aportes, retiros y el socio
    cur.execute("DELETE FROM prestamos WHERE socio_id = ?", (socio_id,))
    cur.execute("DELETE FROM aportes WHERE socio_id = ?", (socio_id,))
    cur.execute("DELETE FROM retiros WHERE socio_id = ?", (socio_id,))
    cur.execute("DELETE FROM socios_web WHERE id = ?", (socio_id,))

    conn.commit()
    conn.close()
    return redirect("/admin/socios")


# ==============================
# ADMIN: REGISTRO DE MOVIMIENTOS
# ==============================

@app.route("/admin/aportes/nuevo", methods=["GET", "POST"])
@admin_required
def admin_aporte_nuevo():
    error = None
    if request.method == "POST":
        numero = request.form.get("numero_socio")
        fecha = request.form.get("fecha")
        monto = request.form.get("monto")
        frecuencia = request.form.get("frecuencia")

        try:
            monto_float = float(monto)
        except:
            error = "Monto inválido."
            return render_template("admin_aporte_nuevo.html", error=error)

        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM socios_web WHERE numero_socio = ?", (numero,))
        row = cur.fetchone()
        if not row:
            conn.close()
            error = "No existe un socio con ese número."
            return render_template("admin_aporte_nuevo.html", error=error)
        socio_id = row["id"]

        cur.execute("""INSERT INTO aportes (socio_id, fecha, monto, frecuencia)
                    VALUES (?,?,?,?)""", (socio_id, fecha, monto_float, frecuencia))
        conn.commit()
        conn.close()
        return redirect("/admin/panel")

    return render_template("admin_aporte_nuevo.html", error=error)


@app.route("/admin/retiros/nuevo", methods=["GET", "POST"])
@admin_required
def admin_retiro_nuevo():
    error = None
    if request.method == "POST":
        numero = request.form.get("numero_socio")
        fecha = request.form.get("fecha")
        monto = request.form.get("monto")
        motivo = request.form.get("motivo")

        try:
            monto_float = float(monto)
        except:
            error = "Monto inválido."
            return render_template("admin_retiro_nuevo.html", error=error)

        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM socios_web WHERE numero_socio = ?", (numero,))
        row = cur.fetchone()
        if not row:
            conn.close()
            error = "No existe un socio con ese número."
            return render_template("admin_retiro_nuevo.html", error=error)
        socio_id = row["id"]

        cur.execute("""INSERT INTO retiros (socio_id, fecha, monto, motivo)
                    VALUES (?,?,?,?)""", (socio_id, fecha, monto_float, motivo))
        conn.commit()
        conn.close()
        return redirect("/admin/panel")

    return render_template("admin_retiro_nuevo.html", error=error)


@app.route("/admin/prestamos/nuevo", methods=["GET", "POST"])
@admin_required
def admin_prestamo_nuevo():
    error = None
    if request.method == "POST":
        numero = request.form.get("numero_socio")
        fecha_inicio = request.form.get("fecha_inicio")
        fecha_fin = request.form.get("fecha_fin")
        monto = request.form.get("monto")
        tasa = request.form.get("tasa_interes")
        tipo = request.form.get("tipo_interes")
        estado = request.form.get("estado")

        try:
            monto_float = float(monto)
            tasa_float = float(tasa)
        except:
            error = "Monto o tasa inválidos."
            return render_template("admin_prestamo_nuevo.html", error=error)

        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM socios_web WHERE numero_socio = ?", (numero,))
        row = cur.fetchone()
        if not row:
            conn.close()
            error = "No existe un socio con ese número."
            return render_template("admin_prestamo_nuevo.html", error=error)
        socio_id = row["id"]

        cur.execute("""INSERT INTO prestamos (
                        socio_id, fecha_inicio, fecha_fin, monto,
                        tasa_interes, tipo_interes, saldo_pendiente, estado
                    ) VALUES (?,?,?,?,?,?,?,?)""",
                    (socio_id, fecha_inicio, fecha_fin, monto_float,
                     tasa_float, tipo, monto_float, estado))
        conn.commit()
        conn.close()
        return redirect("/admin/panel")

    return render_template("admin_prestamo_nuevo.html", error=error)


@app.route("/admin/pagos/nuevo", methods=["GET", "POST"])
@admin_required
def admin_pago_nuevo():
    error = None
    conn = db()
    cur = conn.cursor()

    if request.method == "POST":
        prestamo_id = request.form.get("prestamo_id")
        fecha = request.form.get("fecha")
        monto_p = request.form.get("monto_principal")
        monto_i = request.form.get("monto_interes")
        monto_m = request.form.get("monto_multa") or "0"

        try:
            monto_p_f = float(monto_p)
            monto_i_f = float(monto_i)
            monto_m_f = float(monto_m)
        except:
            error = "Montos inválidos."
        else:
            cur.execute("""INSERT INTO pagos_prestamo
                        (prestamo_id, fecha, monto_principal, monto_interes, monto_multa)
                        VALUES (?,?,?,?,?)""", (prestamo_id, fecha, monto_p_f, monto_i_f, monto_m_f))

            # actualizar saldo
            cur.execute("SELECT saldo_pendiente FROM prestamos WHERE id = ?", (prestamo_id,))
            row = cur.fetchone()
            if row:
                saldo = row["saldo_pendiente"] - monto_p_f
                if saldo < 0:
                    saldo = 0
                cur.execute("UPDATE prestamos SET saldo_pendiente = ? WHERE id = ?", (saldo, prestamo_id))

            conn.commit()
            conn.close()
            return redirect("/admin/panel")

    # GET o error: cargar préstamos
    cur.execute("""SELECT p.id, s.numero_socio, s.nombre, p.monto, p.saldo_pendiente
                 FROM prestamos p
                 JOIN socios_web s ON p.socio_id = s.id
                 ORDER BY s.numero_socio""")
    prestamos = cur.fetchall()
    conn.close()
    return render_template("admin_pago_nuevo.html", prestamos=prestamos, error=error)


# ==============================
# BACKUPS
# ==============================

@app.route("/admin/backup_db")
@admin_required
def backup_db():
    try:
        filename = "backup_" + datetime.now().strftime("%Y%m%d_%H%M") + ".db"
        backup_path = os.path.join(BACKUP_DIR, filename)
        shutil.copy(DATABASE, backup_path)
        return send_file(backup_path, as_attachment=True)
    except Exception as e:
        return f"Error generando backup: {str(e)}"


@app.route("/admin/restore", methods=["GET", "POST"])
@admin_required
def admin_restore():
    msg_error = None
    msg_ok = None

    if request.method == "POST":
        file = request.files.get("backup_file")
        if not file or not file.filename.endswith(".db"):
            msg_error = "Debe seleccionar un archivo .db válido."
        else:
            try:
                temp_path = os.path.join(BACKUP_DIR, "restore_temp.db")
                file.save(temp_path)
                shutil.copy(temp_path, DATABASE)
                msg_ok = "Restauración completada correctamente."
            except Exception as e:
                msg_error = f"Error al restaurar: {str(e)}"

    return render_template("admin_restore.html", error=msg_error, success=msg_ok)


# ==============================
# INICIO
# ==============================

if __name__ == "__main__":
    inicializar_db()
    app.run(debug=True)
