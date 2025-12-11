from flask import Flask, request
import requests
import os
from supabase import create_client, Client

app = Flask(__name__)

# ===============================================================
#  1. CONFIGURACIÓN Y CREDENCIALES
# ===============================================================
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
NUMERO_ADMIN = os.environ.get("NUMERO_ADMIN")

# Configuración de Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Iniciamos el cliente de Base de Datos
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ===============================================================
#  2. DATOS DEL NEGOCIO (Estáticos)
# ===============================================================
# Al estar aquí, ya no necesitas el archivo datg.json
DATOS_NEGOCIO = {
    "mensaje_bienvenida": "👋 ¡Hola! Bienvenido a nuestro servicio de asistencia automatizada.",
    "respuesta_ubicacion": "📍 Estamos ubicados en: Av. Siempre Viva 123, Ciudad de México.",
    "respuesta_precios": {
        "imagen": "https://images.unsplash.com/photo-1633158829585-23ba8f7c8caf?q=80&w=2070&auto=format&fit=crop", 
        "caption": "💰 *Lista de Precios*\n\n- Consultoría: $50 USD\n- Desarrollo Web: $300 USD\n- Soporte: $20 USD/hora"
    }
}

# ===============================================================
#  3. FUNCIONES DE BASE DE DATOS (El Cerebro Nuevo) 🧠
# ===============================================================

def obtener_usuario(telefono):
    """Busca al usuario en Supabase. Si no existe, lo crea."""
    try:
        # Buscamos si ya existe
        response = supabase.table("clientes").select("*").eq("telefono", telefono).execute()
        data = response.data
        
        if len(data) > 0:
            return data[0] # Retorna el usuario encontrado
        else:
            # Si no existe, lo creamos con valores por defecto
            nuevo_usuario = {"telefono": telefono, "estado_flujo": "INICIO"}
            supabase.table("clientes").insert(nuevo_usuario).execute()
            return nuevo_usuario
    except Exception as e:
        print(f"⚠️ Error DB (Lectura): {e}")
        # En caso de emergencia, devolvemos un usuario temporal en memoria
        return {"telefono": telefono, "estado_flujo": "INICIO", "nombre": ""}

def actualizar_estado(telefono, nuevo_estado, nombre=None):
    """Actualiza en qué paso va el usuario."""
    try:
        datos_a_actualizar = {"estado_flujo": nuevo_estado}
        if nombre:
            datos_a_actualizar["nombre"] = nombre
            
        supabase.table("clientes").update(datos_a_actualizar).eq("telefono", telefono).execute()
    except Exception as e:
        print(f"⚠️ Error DB (Escritura): {e}")

# ===============================================================
#  4. FUNCIONES DE ENVÍO DE WHATSAPP
# ===============================================================
def enviar_mensaje_texto(telefono, texto):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": telefono, "type": "text", "text": {"body": texto}}
    try:
        requests.post(url, headers=headers, json=data)
    except Exception as e:
        print(f"Error envío texto: {e}")

def enviar_mensaje_botones(telefono, texto_cuerpo, botones):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    lista_botones = [{"type": "reply", "reply": {"id": f"btn_{i}", "title": b}} for i, b in enumerate(botones)]
    
    data = {
        "messaging_product": "whatsapp", "to": telefono, "type": "interactive",
        "interactive": {"type": "button", "body": {"text": texto_cuerpo}, "action": {"buttons": lista_botones}}
    }
    try:
        requests.post(url, headers=headers, json=data)
    except Exception as e:
        print(f"Error envío botones: {e}")

def enviar_mensaje_imagen(telefono, link_imagen, caption):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": telefono, "type": "image", "image": {"link": link_imagen, "caption": caption}}
    try:
        requests.post(url, headers=headers, json=data)
    except Exception as e:
        print(f"Error envío imagen: {e}")

# ===============================================================
#  5. WEBHOOK (Lógica Principal)
# ===============================================================
@app.route('/webhook', methods=['GET'])
def verificar_token():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        return request.args.get('hub.challenge'), 200
    return "Error", 403

@app.route('/webhook', methods=['POST'])
def recibir_mensajes():
    body = request.get_json()
    try:
        if body.get("object"):
            entry = body["entry"][0]
            changes = entry["changes"][0]
            value = changes["value"]
            
            if "messages" in value:
                message = value["messages"][0]
                numero = message["from"]
                
                # PARCHE MÉXICO
                if numero.startswith("521"): numero = numero.replace("521", "52", 1)

                # --- 1. OBTENER USUARIO DE BASE DE DATOS ---
                usuario_db = obtener_usuario(numero)
                estado_actual = usuario_db.get("estado_flujo", "INICIO")
                nombre_guardado = usuario_db.get("nombre", "")

                # --- 2. DETECTAR CONTENIDO ---
                tipo_mensaje = message["type"]
                texto_usuario = ""
                if tipo_mensaje == "text":
                    texto_usuario = message["text"]["body"]
                elif tipo_mensaje == "interactive":
                    texto_usuario = message["interactive"]["button_reply"]["title"]

                texto_usuario_lower = texto_usuario.lower()
                print(f"📩 {numero} ({estado_actual}): {texto_usuario}", flush=True)
                
                # ==================================================
                #  MÁQUINA DE ESTADOS (CON SUPABASE)
                # ==================================================
                
                # --- CASO A: RECOLECTANDO DATOS PARA CITA ---
                if estado_actual == 'ESPERANDO_NOMBRE':
                    nuevo_nombre = texto_usuario.title()
                    actualizar_estado(numero, 'ESPERANDO_SERVICIO', nombre=nuevo_nombre)
                    enviar_mensaje_botones(numero, f"Gusto en saludarte, {nuevo_nombre}. ¿Qué servicio te interesa?", ["Consultoría", "Desarrollo Web", "Soporte"])
                
                elif estado_actual == 'ESPERANDO_SERVICIO':
                    servicio_elegido = texto_usuario
                    
                    enviar_mensaje_texto(numero, f"¡Listo {nombre_guardado}! Agendamos tu interés en: {servicio_elegido}.")
                    
                    if NUMERO_ADMIN:
                        enviar_mensaje_texto(NUMERO_ADMIN, f"🔔 *NUEVA CITA (DB)*\nCliente: {nombre_guardado}\nTel: {numero}\nServicio: {servicio_elegido}")
                    
                    actualizar_estado(numero, 'INICIO') # Reiniciamos ciclo

                # --- CASO B: MENÚ PRINCIPAL ---
                else:
                    if "agendar" in texto_usuario_lower:
                        actualizar_estado(numero, 'ESPERANDO_NOMBRE')
                        enviar_mensaje_texto(numero, "📝 Para agendar, por favor escribe tu *nombre completo*:")
                    
                    elif "precios" in texto_usuario_lower:
                        info = DATOS_NEGOCIO["respuesta_precios"]
                        enviar_mensaje_imagen(numero, info["imagen"], info["caption"])
                        
                    elif "ubicacion" in texto_usuario_lower or "ubicación" in texto_usuario_lower:
                        enviar_mensaje_texto(numero, DATOS_NEGOCIO["respuesta_ubicacion"])

                    else:
                        # Menú por defecto
                        enviar_mensaje_botones(numero, DATOS_NEGOCIO["mensaje_bienvenida"], ["💰 Precios", "📍 Ubicación", "📅 Agendar Cita"])

            return "EVENT_RECEIVED", 200
    except Exception as e:
        print(f"🔥 Error Crítico: {e}", flush=True)
        return "EVENT_RECEIVED", 200

@app.route("/")
def home():
    return "Bot VTS Activo y Conectado a DB 🟢", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port, debug=True)