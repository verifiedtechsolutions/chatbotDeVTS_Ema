from flask import Flask, request
import requests
import json
import os

app = Flask(__name__)

# ===============================================================
#  CONFIGURACIÓN
# ===============================================================
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
NUMERO_ADMIN = os.environ.get("NUMERO_ADMIN")
# ===============================================================

MEMORIA = {}

# --- CARGAMOS EL MENÚ ---
try:
    with open('datg.json', 'r', encoding='utf-8') as f:
        DATOS_NEGOCIO = json.load(f)
    print("✅ Datos cargados.", flush=True)
except:
    DATOS_NEGOCIO = {"mensaje_error": "Error config.", "botones_menu": ["Error"]}

# --- FUNCIONES DE ENVÍO (AHORA CON LOGS DETALLADOS) ---
def enviar_mensaje_texto(telefono, texto):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": telefono, "type": "text", "text": {"body": texto}}
    
    response = requests.post(url, headers=headers, json=data)
    
    # EL CHISMOSO 🕵️‍♂️: Imprimimos qué pasó
    print(f"📤 TEXTO a {telefono} | Code: {response.status_code} | FB dice: {response.text}", flush=True)

def enviar_mensaje_botones(telefono, texto_cuerpo, botones):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    lista_botones = []
    for i, boton_titulo in enumerate(botones):
        lista_botones.append({"type": "reply", "reply": {"id": f"btn_{i}", "title": boton_titulo}})
    data = {"messaging_product": "whatsapp", "to": telefono, "type": "interactive", "interactive": {"type": "button", "body": {"text": texto_cuerpo}, "action": {"buttons": lista_botones}}}
    
    response = requests.post(url, headers=headers, json=data)
    print(f"📤 BOTONES a {telefono} | Code: {response.status_code}", flush=True)

def enviar_mensaje_imagen(telefono, link_imagen, caption):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": telefono, "type": "image", "image": {"link": link_imagen, "caption": caption}}
    
    requests.post(url, headers=headers, json=data)

# --- VERIFICACIÓN ---
@app.route('/webhook', methods=['GET'])
def verificar_token():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        return request.args.get('hub.challenge'), 200
    return "Error", 403

# --- RECEPCIÓN ---
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

                tipo_mensaje = message["type"]
                texto_usuario = ""
                if tipo_mensaje == "text":
                    texto_usuario = message["text"]["body"]
                elif tipo_mensaje == "interactive":
                    texto_usuario = message["interactive"]["button_reply"]["title"]

                texto_usuario_lower = texto_usuario.lower()
                print(f"<-- RECIBÍ: {texto_usuario} de {numero}", flush=True)

                # ==================================================
                # MÁQUINA DE ESTADOS
                # ==================================================
                if numero not in MEMORIA:
                    MEMORIA[numero] = {'estado': 'INICIO', 'nombre_guardado': ''}

                estado_actual = MEMORIA[numero]['estado']
                
                # --- FLUJO: AGENDAR CITA ---
                if estado_actual == 'ESPERANDO_NOMBRE':
                    MEMORIA[numero]['nombre_guardado'] = texto_usuario.title()
                    MEMORIA[numero]['estado'] = 'ESPERANDO_SERVICIO' 
                    enviar_mensaje_botones(numero, f"Gusto en saludarte, {MEMORIA[numero]['nombre_guardado']}. ¿Qué servicio te interesa?", ["Consultoría", "Desarrollo Web", "Soporte"])
                
                elif estado_actual == 'ESPERANDO_SERVICIO':
                    nombre_cliente = MEMORIA[numero]['nombre_guardado']
                    servicio_elegido = texto_usuario
                    
                    # 1. Al Cliente
                    enviar_mensaje_texto(numero, f"¡Listo {nombre_cliente}! Agendamos tu interés en: {servicio_elegido}.")
                    
                    # 2. Al Admin (INTENTO DE NOTIFICACIÓN)
                    if NUMERO_ADMIN:
                        print(f"🔔 Intentando notificar al Admin: {NUMERO_ADMIN}...", flush=True)
                        mensaje_admin = f"🔔 *NUEVA VENTA*\nCliente: {nombre_cliente}\nTel: {numero}"
                        enviar_mensaje_texto(NUMERO_ADMIN, mensaje_admin)
                    else:
                        print("⚠️ No hay NUMERO_ADMIN configurado.", flush=True)
                    
                    MEMORIA[numero]['estado'] = 'INICIO'

                # --- FLUJO NORMAL ---
                else:
                    if "agendar" in texto_usuario_lower:
                        MEMORIA[numero]['estado'] = 'ESPERANDO_NOMBRE'
                        enviar_mensaje_texto(numero, "📝 Para agendar, primero necesito tu nombre.")
                    
                    elif "hola" in texto_usuario_lower or "menu" in texto_usuario_lower:
                        enviar_mensaje_botones(numero, DATOS_NEGOCIO["mensaje_bienvenida"], ["💰 Precios", "📍 Ubicación", "📅 Agendar Cita"])
                    
                    elif "precios" in texto_usuario_lower:
                        info = DATOS_NEGOCIO["respuesta_precios"]
                        enviar_mensaje_imagen(numero, info["imagen"], info["caption"])
                        
                    elif "ubicacion" in texto_usuario_lower:
                        enviar_mensaje_texto(numero, DATOS_NEGOCIO["respuesta_ubicacion"])

                    else:
                        enviar_mensaje_texto(numero, DATOS_NEGOCIO["mensaje_error"])

            return "EVENT_RECEIVED", 200
    except Exception as e:
        print(f"Error: {e}", flush=True)
        return "EVENT_RECEIVED", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port, debug=True)