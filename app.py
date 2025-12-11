from flask import Flask, request
import requests
import os
from supabase import create_client, Client
from openai import OpenAI
import json

app = Flask(__name__)

# ===============================================================
#  CONFIGURACIÓN
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
#  IMÁGENES Y RECURSOS (Punto 7) 🖼️
# ===============================================================
# Aquí pones el link directo de tu imagen promocional (debe terminar en .jpg o .png)
# Puedes subirla a "Supabase Storage" y obtener la URL pública.
URL_IMAGEN_PROMO = "https://images.unsplash.com/photo-1531482615713-2afd69097998?q=80&w=2070&auto=format&fit=crop"

# ===============================================================
#  SYSTEM PROMPT "ESTÉTICO" (Punto 2) 🎨
# ===============================================================
SYSTEM_PROMPT = """
Eres el Asistente Virtual de 'Verified Tech Solutions' (VTS).
Tu objetivo es vender soluciones de Chatbots IA y Ciencia de Datos.

REGLAS DE FORMATO (ESTRICTO):
1. Usa **negritas** para resaltar precios y conceptos clave (Ej: **$4,500 MXN**).
2. Usa emojis profesionales para dar estructura (📌, 💡, 🚀, 💰, ✅).
3. Si listas servicios, usa listas con viñetas o guiones.
4. Mantén los párrafos cortos y legibles.

DATOS DEL NEGOCIO:
- Producto: Chatbots con IA para WhatsApp.
- Precio Base: **$4,500 MXN/mes** (Inversión Inicial).
- Beneficio: Atención 24/7 y reducción de carga operativa.
- Horario: Lun-Vie (Consultar disponibilidad específica).

Si te preguntan algo fuera de tu tema, responde cortésmente que solo hablas de soluciones VTS.
"""

# ===============================================================
#  FUNCIONES (Supabase, OpenAI, Envíos)
# ===============================================================
def guardar_mensaje(telefono, rol, contenido):
    try:
        supabase.table("mensajes").insert({"telefono": telefono, "rol": rol, "contenido": contenido}).execute()
    except: pass

def obtener_historial(telefono):
    try:
        resp = supabase.table("mensajes").select("rol, contenido").eq("telefono", telefono).order("created_at", desc=True).limit(6).execute()
        return [{"role": m["rol"], "content": m["contenido"]} for m in resp.data[::-1]]
    except: return []

def consultar_chatgpt(historial):
    try:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + historial
        # Temperature 0.5 para balancear creatividad y precisión
        resp = client_ai.chat.completions.create(model="gpt-4o-mini", messages=msgs, temperature=0.5)
        return resp.choices[0].message.content
    except: return "⚠️ Error de conexión neuronal."

def obtener_usuario(telefono):
    try:
        res = supabase.table("clientes").select("*").eq("telefono", telefono).execute()
        if res.data: return res.data[0]
        nuevo = {"telefono": telefono, "estado_flujo": "INICIO"}
        supabase.table("clientes").insert(nuevo).execute()
        return nuevo
    except: return {"telefono": telefono, "estado_flujo": "INICIO"}

def actualizar_estado(telefono, estado, nombre=None):
    try:
        data = {"estado_flujo": estado}
        if nombre: data["nombre"] = nombre
        supabase.table("clientes").update(data).eq("telefono", telefono).execute()
    except: pass

# --- FUNCIONES DE ENVÍO DE WHATSAPP ---
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

def enviar_imagen(telefono, link, caption=""):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {
        "messaging_product": "whatsapp", "to": telefono, "type": "image",
        "image": {"link": link, "caption": caption}
    }
    requests.post(url, headers=headers, json=data)

# ===============================================================
#  WEBHOOK PRINCIPAL
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
            entry = body["entry"][0]["changes"][0]["value"]
            if "messages" in entry:
                msg = entry["messages"][0]
                numero = msg["from"]
                if numero.startswith("521"): numero = numero.replace("521", "52", 1)

                usuario = obtener_usuario(numero)
                estado = usuario.get("estado_flujo", "INICIO")

                # Detectar contenido
                texto = ""
                es_boton = False
                if msg["type"] == "text": texto = msg["text"]["body"]
                elif msg["type"] == "interactive": 
                    texto = msg["interactive"]["button_reply"]["title"]
                    es_boton = True

                print(f"📩 {numero}: {texto}")
                texto_lower = texto.lower()

                # --- LÓGICA HÍBRIDA (MENU + IMÁGENES + IA) ---

                # 1. SI ES UN SALUDO -> Mandamos Imagen + Menú (Punto 1)
                if "hola" in texto_lower or "inicio" in texto_lower or "menu" in texto_lower or "menú" in texto_lower:
                    # Primero la imagen (Promoción Mercantil)
                    enviar_imagen(numero, URL_IMAGEN_PROMO, "🚀 *Bienvenido a Verified Tech Solutions*")
                    # Luego los botones
                    enviar_botones(numero, "Selecciona una opción o escribe tu duda directamente:", ["💰 Ver Precios", "📅 Agendar Cita", "🤖 Sobre Nosotros"])
                    return "OK", 200

                # 2. CAPTURA DE DATOS (Nombre)
                if estado == 'ESPERANDO_NOMBRE':
                    actualizar_estado(numero, 'INICIO', nombre=texto)
                    enviar_botones(numero, f"Gracias {texto}. ¿Cómo procedemos?", ["💰 Ver Precios", "📅 Agendar Cita"])
                    return "OK", 200

                # 3. BOTONES ESPECÍFICOS
                if es_boton:
                    if "Precios" in texto:
                        # Aquí la IA ya sabe los precios, pero podemos forzar un formato bonito
                        enviar_mensaje(numero, "💰 **Plan Inicial VTS:**\n\n- **$4,500 MXN/mes**\n- Atención 24/7\n- Infraestructura incluida\n\n¿Te interesa una demo?")
                    elif "Agendar" in texto:
                        actualizar_estado(numero, 'ESPERANDO_NOMBRE')
                        enviar_mensaje(numero, "📝 Para coordinar la reunión, por favor escribe tu **nombre completo**:")
                    elif "Sobre Nosotros" in texto:
                        # Dejamos que la IA responda esto con su System Prompt
                        historial = obtener_historial(numero)
                        resp = consultar_chatgpt(historial)
                        enviar_mensaje(numero, resp)
                    
                    guardar_mensaje(numero, "user", f"[Botón: {texto}]")

                # 4. INTELIGENCIA ARTIFICIAL (Para todo lo demás)
                else:
                    guardar_mensaje(numero, "user", texto)
                    historial = obtener_historial(numero)
                    resp = consultar_chatgpt(historial)
                    enviar_mensaje(numero, resp)
                    guardar_mensaje(numero, "assistant", resp)

            return "EVENT_RECEIVED", 200
    except Exception as e:
        print(f"Error: {e}")
        return "EVENT_RECEIVED", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 3000)))