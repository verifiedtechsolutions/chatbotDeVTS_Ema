from flask import Flask, request
import requests
import json
import os  # <--- IMPORTANTE: Necesario para leer las variables de Render

app = Flask(__name__)

# ===============================================================
#  CONFIGURACIÓN DE ENTORNO (VARIABLES OCULTAS)
# ===============================================================
# Ahora el código busca estos valores en la configuración de Render.
# Asegúrate de que en Render las llames EXACTAMENTE así:
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
# ===============================================================

# 🧠 MEMORIA A CORTO PLAZO (DICCIONARIO)
MEMORIA = {}

# --- CARGAMOS EL MENÚ ---
try:
    with open('datg.json', 'r', encoding='utf-8') as f:
        DATOS_NEGOCIO = json.load(f)
    print("✅ Datos cargados.", flush=True)
except:
    DATOS_NEGOCIO = {"mensaje_error": "Error config.", "botones_menu": ["Error"]}

# --- FUNCIONES DE ENVÍO ---
def enviar_mensaje_texto(telefono, texto):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": telefono, "type": "text", "text": {"body": texto}}
    requests.post(url, headers=headers, json=data)

def enviar_mensaje_botones(telefono, texto_cuerpo, botones):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    lista_botones = []
    for i, boton_titulo in enumerate(botones):
        lista_botones.append({"type": "reply", "reply": {"id": f"btn_{i}", "title": boton_titulo}})
    data = {"messaging_product": "whatsapp", "to": telefono, "type": "interactive", "interactive": {"type": "button", "body": {"text": texto_cuerpo}, "action": {"buttons": lista_botones}}}
    requests.post(url, headers=headers, json=data)

def enviar_mensaje_imagen(telefono, link_imagen, caption):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": telefono, "type": "image", "image": {"link": link_imagen, "caption": caption}}
    requests.post(url, headers=headers, json=data)

# --- VERIFICACIÓN ---
@app.route('/webhook', methods=['GET'])
def verificar_token():
    # Meta envía el token en la URL, nosotros lo comparamos con el de Render
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        return request.args.get('hub.challenge'), 200
    return "Error de Verificación", 403

# --- RECEPCIÓN DE MENSAJES ---
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
                if numero.startswith("521"):
                    numero = numero.replace("521", "52", 1)

                # OBTENER TEXTO
                tipo_mensaje = message["type"]
                texto_usuario = ""
                if tipo_mensaje == "text":
                    texto_usuario = message["text"]["body"].lower()
                elif tipo_mensaje == "interactive":
                    texto_usuario = message["interactive"]["button_reply"]["title"].lower()

                print(f"<-- RECIBÍ: {texto_usuario} de {numero}", flush=True)

                # ==================================================
                # 🧠 MÁQUINA DE ESTADOS (STATE MACHINE)
                # ==================================================
                
                # 1. RECUPERAR ESTADO ACTUAL (Si no existe, es 'INICIO')
                estado_actual = MEMORIA.get(numero, 'INICIO')
                
                # --- FLUJO: AGENDAR CITA ---
                
                if estado_actual == 'ESPERANDO_NOMBRE':
                    MEMORIA[numero] = 'ESPERANDO_SERVICIO' 
                    enviar_mensaje_botones(numero, f"Gusto en saludarte, {texto_usuario.capitalize()}. ¿Qué servicio te interesa?", ["Consultoría", "Desarrollo Web", "Soporte"])
                
                elif estado_actual == 'ESPERANDO_SERVICIO':
                    enviar_mensaje_texto(numero, f"¡Perfecto! Hemos agendado una cita para: {texto_usuario.capitalize()}.\nNos pondremos en contacto pronto.")
                    MEMORIA[numero] = 'INICIO'

                # --- FLUJO NORMAL (MENÚ PRINCIPAL) ---
                else:
                    if "agendar" in texto_usuario or "cita" in texto_usuario:
                        MEMORIA[numero] = 'ESPERANDO_NOMBRE'
                        enviar_mensaje_texto(numero, "📝 Para agendar, primero necesito tu nombre completo. ¿Cómo te llamas?")
                    
                    elif "hola" in texto_usuario or "menu" in texto_usuario:
                        enviar_mensaje_botones(numero, DATOS_NEGOCIO["mensaje_bienvenida"], ["💰 Precios", "📍 Ubicación", "📅 Agendar Cita"])
                    
                    elif "precios" in texto_usuario:
                        info = DATOS_NEGOCIO["respuesta_precios"]
                        enviar_mensaje_imagen(numero, info["imagen"], info["caption"])
                        
                    elif "ubicacion" in texto_usuario or "ubicación" in texto_usuario:
                        enviar_mensaje_texto(numero, DATOS_NEGOCIO["respuesta_ubicacion"])

                    else:
                        enviar_mensaje_texto(numero, DATOS_NEGOCIO["mensaje_error"])

            return "EVENT_RECEIVED", 200
    except Exception as e:
        print(f"Error: {e}", flush=True)
        return "EVENT_RECEIVED", 200

if __name__ == '__main__':
    # Usamos el puerto que diga el sistema o el 3000 por defecto
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port, debug=True)