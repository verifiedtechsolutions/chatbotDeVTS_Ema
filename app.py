from flask import Flask, request
import requests
import os
import json
from supabase import create_client, Client
from openai import OpenAI
from datetime import datetime
import pytz

app = Flask(__name__)

# ===============================================================
#  1. CONFIGURACIÓN Y CREDENCIALES
# ===============================================================
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
NUMERO_ADMIN = os.environ.get("NUMERO_ADMIN")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
client_ai = OpenAI(api_key=OPENAI_API_KEY)

# ===============================================================
#  2. DEFINICIÓN DE IDENTIDAD CORPORATIVA (System Prompt) ⚖️
# ===============================================================
# Aquí se define la personalidad formal y los datos reales del negocio.

SYSTEM_PROMPT = """
Eres el Asistente Virtual Oficial de 'Verified Tech Solutions' (VTS).
Tu función es brindar atención comercial preliminar sobre soluciones de Inteligencia Artificial y Ciencia de Datos.

DIRECTRICES DE TONO Y PERSONALIDAD:
- Tu tono debe ser **FORMAL, PROFESIONAL Y DISTANTE PERO CORTÉS** (similar a un abogado o consultor senior).
- Evita el uso excesivo de exclamaciones o emojis, salvo en los menús predefinidos.
- Utiliza un vocabulario preciso y técnico.
- No prometas disponibilidad inmediata fuera de los horarios establecidos.

INFORMACIÓN DEL NEGOCIO (VTS):
1.  **Giro:** Desarrollo de soluciones de IA, Ciencia de Datos y Chatbots Empresariales.
2.  **Producto Estrella (Chatbots):**
    -   Ofrecemos "Sistemas de Atención Automatizada 24/7" (Chatbots IA).
    -   **Inversión Inicial:** Planes desde $4,500 MXN mensuales (Estrategia de penetración).
    -   **Beneficio:** Reducción de carga operativa y atención inmediata.
3.  **Modalidad:** Los servicios se prestan en modalidad 100% remota.

HORARIOS DE ATENCIÓN ADMINISTRATIVA (Zona Horaria México):
-   Lunes y Martes: 12:00 a 17:00 horas.
-   Miércoles a Viernes: 10:00 a 17:30 horas.
-   Fines de Semana: Sin atención administrativa.
*Nota: Si el usuario solicita contacto fuera de este horario, infórmale formalmente que su solicitud será procesada en el siguiente bloque hábil.*

REGLAS DE INTERACCIÓN:
1.  Si preguntan precios, cita el plan base de $4,500 MXN como "inversión inicial sugerida".
2.  Si solicitan una reunión, invítalos a usar el botón 'Agendar Cita' para formalizar la solicitud.
3.  Mantén las respuestas concisas (máximo 60 palabras) para facilitar la lectura en móviles.
"""

# ===============================================================
#  3. GESTIÓN DE MEMORIA (Supabase) 🧠
# ===============================================================

def guardar_mensaje(telefono, rol, contenido):
    """Registra la interacción en la base de datos para fines de auditoría y contexto."""
    try:
        data = {"telefono": telefono, "rol": rol, "contenido": contenido}
        supabase.table("mensajes").insert(data).execute()
    except Exception as e:
        print(f"Error de registro en DB: {e}")

def obtener_historial(telefono, limite=6):
    """Recupera el contexto reciente de la conversación."""
    try:
        response = supabase.table("mensajes")\
            .select("rol, contenido")\
            .eq("telefono", telefono)\
            .order("created_at", desc=True)\
            .limit(limite)\
            .execute()
        
        historial = response.data[::-1] 
        return [{"role": m["rol"], "content": m["contenido"]} for m in historial]
    except Exception as e:
        return []

# ===============================================================
#  4. INTELIGENCIA ARTIFICIAL (OpenAI)
# ===============================================================
def consultar_chatgpt(historial_chat):
    try:
        mensajes_para_enviar = [{"role": "system", "content": SYSTEM_PROMPT}]
        mensajes_para_enviar.extend(historial_chat)
        
        completion = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=mensajes_para_enviar,
            temperature=0.3 # Temperatura baja para ser más formal y menos "creativo"
        )
        return completion.choices[0].message.content
    except Exception as e:
        return "Estimado usuario, momentáneamente presento una intermitencia en mis sistemas de procesamiento. Por favor, intente nuevamente en breve."

# ===============================================================
#  5. FUNCIONES AUXILIARES
# ===============================================================
def obtener_usuario(telefono):
    try:
        response = supabase.table("clientes").select("*").eq("telefono", telefono).execute()
        if len(response.data) > 0: return response.data[0]
        else:
            nuevo = {"telefono": telefono, "estado_flujo": "INICIO"}
            supabase.table("clientes").insert(nuevo).execute()
            return nuevo
    except: return {"telefono": telefono, "estado_flujo": "INICIO"}

def actualizar_estado(telefono, nuevo_estado, nombre=None):
    try:
        data = {"estado_flujo": nuevo_estado}
        if nombre: data["nombre"] = nombre
        supabase.table("clientes").update(data).eq("telefono", telefono).execute()
    except: pass

def enviar_mensaje(telefono, texto):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": telefono, "type": "text", "text": {"body": texto}}
    requests.post(url, headers=headers, json=data)

def enviar_botones(telefono, texto, botones):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    lista = [{"type": "reply", "reply": {"id": f"btn_{i}", "title": b}} for i, b in enumerate(botones)]
    data = {
        "messaging_product": "whatsapp", "to": telefono, "type": "interactive",
        "interactive": {"type": "button", "body": {"text": texto}, "action": {"buttons": lista}}
    }
    requests.post(url, headers=headers, json=data)

# ===============================================================
#  6. CONTROLADOR PRINCIPAL (Webhook)
# ===============================================================
@app.route('/webhook', methods=['GET'])
def verificar():
    if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == VERIFY_TOKEN:
        return request.args.get('hub.challenge'), 200
    return "Error", 403

@app.route('/webhook', methods=['POST'])
def recibir():
    body = request.get_json()
    try:
        if body.get("object"):
            entry = body["entry"][0]
            changes = entry["changes"][0]
            value = changes["value"]
            
            if "messages" in value:
                message = value["messages"][0]
                numero = message["from"]
                if numero.startswith("521"): numero = numero.replace("521", "52", 1)

                usuario = obtener_usuario(numero)
                estado = usuario.get("estado_flujo", "INICIO")

                # --- EXTRACCIÓN DEL MENSAJE ---
                texto = ""
                es_boton = False
                if message["type"] == "text":
                    texto = message["text"]["body"]
                elif message["type"] == "interactive":
                    texto = message["interactive"]["button_reply"]["title"]
                    es_boton = True

                print(f"📩 VTS | {numero}: {texto}")

                # --- MÁQUINA DE ESTADOS (Lógica de Negocio) ---

                # CASO 1: CAPTURA DE NOMBRE PARA CITA
                if estado == 'ESPERANDO_NOMBRE':
                    actualizar_estado(numero, 'INICIO', nombre=texto)
                    # Respuesta formal
                    enviar_botones(numero, f"Agradezco la información, {texto}. Procederemos con su solicitud. ¿Cómo desea continuar?", ["Ver Servicios", "Consultar Costos", "Solicitar Asesoría"])
                    return "OK", 200

                # CASO 2: BOTONES (Navegación Rápida)
                if es_boton:
                    if "Costos" in texto or "Precios" in texto:
                        # Respuesta basada en tu archivo planRefinado.txt
                        enviar_mensaje(numero, "Nuestra inversión inicial para Chatbots IA comienza en $4,500 MXN mensuales. Esto incluye infraestructura y mantenimiento.")
                    elif "Asesoría" in texto or "Agendar" in texto:
                        actualizar_estado(numero, 'ESPERANDO_NOMBRE')
                        enviar_mensaje(numero, "Para formalizar su solicitud de asesoría, requiero que me proporcione su nombre completo:")
                    elif "Servicios" in texto:
                        enviar_mensaje(numero, "Verified Tech Solutions se especializa en:\n1. Chatbots con IA.\n2. Ciencia de Datos.\n3. Automatización de Procesos.")
                    else:
                        enviar_mensaje(numero, "Entendido. Procesando su selección.")
                    
                    guardar_mensaje(numero, "user", f"[Selección: {texto}]")

                # CASO 3: CONSULTA ABIERTA (Inteligencia Artificial)
                else:
                    # Guardamos
                    guardar_mensaje(numero, "user", texto)
                    # Pensamos (Con contexto)
                    historial = obtener_historial(numero)
                    respuesta_ia = consultar_chatgpt(historial)
                    # Respondemos
                    enviar_mensaje(numero, respuesta_ia)
                    guardar_mensaje(numero, "assistant", respuesta_ia)

            return "EVENT_RECEIVED", 200
    except Exception as e:
        print(f"Error Crítico: {e}")
        return "EVENT_RECEIVED", 200

@app.route("/")
def home(): return "Servidor VTS Operativo [Producción]", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port, debug=True)