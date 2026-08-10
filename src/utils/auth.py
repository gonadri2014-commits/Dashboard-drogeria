"""
auth.py — Sistema de autenticación local
- Login con usuario/contraseña
- Contraseñas hasheadas (no se guardan en texto plano)
- Roles: admin, analista, readonly
- Sesión persistente durante la ejecución de Streamlit
- Sin dependencias externas de nube — todo corre local
- Preparado para futura integración con LDAP/Active Directory (SAP)
"""
import hashlib
import json
import os
from datetime import datetime
from typing import Optional
import streamlit as st

USERS_FILE = "./data/usuarios.json"

# ── Roles y permisos ───────────────────────────────────────────────
PERMISOS = {
    "admin":    {"ver_todo": True,  "editar": True,  "exportar": True,  "usuarios": True},
    "analista": {"ver_todo": True,  "editar": True,  "exportar": True,  "usuarios": False},
    "readonly": {"ver_todo": True,  "editar": False, "exportar": False, "usuarios": False},
}

def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def _cargar_usuarios() -> dict:
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    # Usuarios por defecto
    usuarios_default = {
        "admin": {
            "password_hash": _hash("admin2025"),
            "rol":           "admin",
            "nombre":        "Administrador",
            "email":         "admin@drogdelsud.com",
            "activo":        True,
            "ultimo_login":  None,
        },
        "finanzas": {
            "password_hash": _hash("finanzas2025"),
            "rol":           "analista",
            "nombre":        "Gerente de Finanzas",
            "email":         "finanzas@drogdelsud.com",
            "activo":        True,
            "ultimo_login":  None,
        },
        "readonly": {
            "password_hash": _hash("readonly2025"),
            "rol":           "readonly",
            "nombre":        "Solo Lectura",
            "email":         "viewer@drogdelsud.com",
            "activo":        True,
            "ultimo_login":  None,
        },
    }
    _guardar_usuarios(usuarios_default)
    return usuarios_default

def _guardar_usuarios(usuarios: dict):
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, "w") as f:
        json.dump(usuarios, f, indent=2)

def verificar_login(username: str, password: str) -> Optional[dict]:
    """Verifica credenciales. Retorna datos del usuario o None."""
    usuarios = _cargar_usuarios()
    user = usuarios.get(username.lower().strip())
    if not user:
        return None
    if not user.get("activo", False):
        return None
    if user["password_hash"] != _hash(password):
        return None
    # Actualizar último login
    user["ultimo_login"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    usuarios[username] = user
    _guardar_usuarios(usuarios)
    return {"username": username, "rol": user["rol"],
            "nombre": user["nombre"], "email": user["email"]}

def tiene_permiso(permiso: str) -> bool:
    """Verifica si el usuario actual tiene un permiso específico."""
    if "usuario_actual" not in st.session_state:
        return False
    rol = st.session_state.usuario_actual.get("rol", "readonly")
    return PERMISOS.get(rol, {}).get(permiso, False)

def agregar_usuario(username: str, password: str, rol: str,
                    nombre: str, email: str) -> tuple[bool, str]:
    """Agrega un nuevo usuario. Solo admin puede hacer esto."""
    if rol not in PERMISOS:
        return False, f"Rol inválido. Opciones: {list(PERMISOS.keys())}"
    usuarios = _cargar_usuarios()
    if username.lower() in usuarios:
        return False, "El usuario ya existe"
    usuarios[username.lower()] = {
        "password_hash": _hash(password),
        "rol":           rol,
        "nombre":        nombre,
        "email":         email,
        "activo":        True,
        "ultimo_login":  None,
    }
    _guardar_usuarios(usuarios)
    return True, f"Usuario '{username}' creado correctamente"

def cambiar_password(username: str, password_nuevo: str) -> bool:
    usuarios = _cargar_usuarios()
    if username not in usuarios:
        return False
    usuarios[username]["password_hash"] = _hash(password_nuevo)
    _guardar_usuarios(usuarios)
    return True

def listar_usuarios() -> list:
    usuarios = _cargar_usuarios()
    return [
        {"username": k, "nombre": v["nombre"], "rol": v["rol"],
         "email": v["email"], "activo": v["activo"],
         "ultimo_login": v.get("ultimo_login", "Nunca")}
        for k, v in usuarios.items()
    ]

# ══════════════════════════════════════════════════════════════════════
# PANTALLA DE LOGIN (Streamlit)
# ══════════════════════════════════════════════════════════════════════

def mostrar_login() -> bool:
    """
    Muestra la pantalla de login.
    Retorna True si el usuario está autenticado.
    """
    if st.session_state.get("autenticado"):
        return True

    # Centrar el formulario
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""
        <div style="background:linear-gradient(135deg,#1F3864,#2E75B6);
                    padding:32px 28px;border-radius:14px;
                    text-align:center;margin-bottom:24px;
                    box-shadow:0 4px 20px rgba(0,0,0,0.3)">
            <div style="font-size:44px;margin-bottom:8px">💰</div>
            <div style="color:white;font-size:22px;font-weight:700;
                        letter-spacing:-0.5px">CashFlow Inteligente</div>
            <div style="color:#BDD7EE;font-size:13px;margin-top:6px">
                Droguería del Sud · Sistema Financiero
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("form_login", clear_on_submit=False):
            st.markdown("### Iniciar sesión")
            username = st.text_input("Usuario", placeholder="tu.usuario")
            password = st.text_input("Contraseña", type="password", placeholder="••••••••")
            submit  = st.form_submit_button("Ingresar →", use_container_width=True, type="primary")

        if submit:
            if not username or not password:
                st.error("Completá usuario y contraseña")
                return False
            user_data = verificar_login(username, password)
            if user_data:
                st.session_state.autenticado    = True
                st.session_state.usuario_actual = user_data
                st.success(f"Bienvenido, {user_data['nombre']}")
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos")
                return False

        st.markdown("""
        <div style="text-align:center;font-size:11px;color:#888;margin-top:16px">
            🔒 Acceso restringido — Solo personal autorizado<br>
            Sistema interno — No compartir credenciales
        </div>
        """, unsafe_allow_html=True)

    return False
