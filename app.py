from flask import Flask, request
import requests
import os
from supabase import create_client, Client
from openai import OpenAI

app = Flask(__name__)

# ===============================================================
#  1. CONFIGURACIÓN
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
#  2. PROMPT DEL SISTEMA (SANDBOX VTS)
# ===============================================================
SYSTEM_PROMPT = """
Eres el asistente de 'VTS Demo'. 
Responde dudas sobre servicios tecnológicos basándote en el contexto de la charla.

DATOS:
- Consultoría: $50 USD.
- Web: $300 USD.
- Soporte: $20/h.

REGLAS:
- Sé breve y amable.
- Si preguntan precios, dalos.
- Si el usuario se refiere a algo anterior (ej: "eso", "el primero"), usa el historial para entender.
"""

# ===============================================================
#  3. FUNCIONES DE MEMORIA (NUEVO) 🧠
# ===============================================================

def guardar_mensaje(telefono, rol, contenido):
    """Guarda un mensaje en Supabase (user o assistant)."""
    try:
        data = {"telefono": telefono, "rol": rol, "contenido": contenido}
        supabase.table("mensajes").insert(data).execute()
    except Exception as e:
        print(f"⚠️ Error guardando memoria: {e}")

def obtener_historial(telefono, limite=6):
    """Recupera los últimos N mensajes para dar contexto a la IA."""
    try:
        # Traemos los últimos mensajes ordenados por fecha
        response = supabase.table("mensajes")\
            .select("rol, contenido")\
            .eq("telefono", telefono)\
            .order("created_at", desc=True)\
            .limit(limite)\
            .execute()
        
        # Supabase los devuelve del más nuevo al más viejo, hay que invertirlos
        historial = response.data[::-1] 
        
        # Formateamos para OpenAI
        mensajes_formateados = [{"role": m["rol"], "content": m["contenido"]} for m in historial]
        return mensajes_formateados
    except Exception as e:
        print(f"⚠️ Error leyendo memoria: {e}")
        return []

# ===============================================================
#  4. CEREBRO IA (CON MEMORIA)
# ===============================================================
def consultar_chatgpt(historial_chat):
    """Envía el historial completo a OpenAI."""
    try:
        # 1. Ponemos el System Prompt primero
        mensajes_para_enviar = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # 2. Le pegamos el historial de la conversación
        mensajes_para_enviar.extend(historial_chat)
        
        completion = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=mensajes_para_enviar
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Error OpenAI: {e}")
        return "Disculpa, me perdí un poco. ¿Podrías repetir?"

# ===============================================================
#  5. FUNCIONES DB USUARIO & ENVÍO
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
#  6. WEBHOOK PRINCIPAL
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

                usuario = obtener_usuario(numero) # Asegura que el cliente exista
                estado = usuario.get("estado_flujo", "INICIO")

                # --- EXTRAER TEXTO ---
                texto = ""
                es_boton = False
                if message["type"] == "text":
                    texto = message["text"]["body"]
                elif message["type"] == "interactive":
                    texto = message["interactive"]["button_reply"]["title"]
                    es_boton = True

                print(f"📩 {numero}: {texto}")

                # --- CASO 1: FLUJO DE CITAS (Sin IA) ---
                if estado == 'ESPERANDO_NOMBRE':
                    # Aquí NO guardamos en memoria de chat para no ensuciarla con datos logísticos
                    actualizar_estado(numero, 'INICIO', nombre=texto)
                    enviar_botones(numero, f"Gracias {texto}. ¿Cómo te ayudo?", ["Precios", "Hablar con IA", "Agendar"])
                    return "OK", 200

                # --- CASO 2: MENSAJE NORMAL (Con IA) ---
                if not es_boton:
                    # A) Guardamos lo que dijo el usuario
                    guardar_mensaje(numero, "user", texto)
                    
                    # B) Recuperamos contexto
                    historial = obtener_historial(numero)
                    
                    # C) Consultamos a la IA con contexto
                    respuesta_ia = consultar_chatgpt(historial)
                    
                    # D) Enviamos y guardamos la respuesta
                    enviar_mensaje(numero, respuesta_ia)
                    guardar_mensaje(numero, "assistant", respuesta_ia)

                # --- CASO 3: BOTONES ---
                else:
                    # Los botones rompen el flujo de chat, así que reiniciamos contexto o respondemos directo
                    if "Precios" in texto:
                        enviar_mensaje(numero, "💰 Consultoría: $50 | Web: $300 | Soporte: $20/h")
                    elif "Agendar" in texto:
                        actualizar_estado(numero, 'ESPERANDO_NOMBRE')
                        enviar_mensaje(numero, "¿A nombre de quién registro la cita?")
                    elif "IA" in texto:
                        enviar_mensaje(numero, "Soy todo oídos. ¿Qué necesitas saber?")
                    
                    # Opcional: Guardar también la acción del botón en el historial
                    guardar_mensaje(numero, "user", f"[Presionó botón: {texto}]")

            return "EVENT_RECEIVED", 200
    except Exception as e:
        print(f"Error: {e}")
        return "EVENT_RECEIVED", 200

@app.route("/")
def home(): return "Bot VTS con Memoria Activo 🧠💾", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port, debug=True)