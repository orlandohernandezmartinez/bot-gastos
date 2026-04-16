import os
import json
import requests
from datetime import datetime, timedelta
from flask import Flask, request
from dotenv import load_dotenv
from sheets import append_row, get_all_rows

load_dotenv()

app = Flask(__name__)

TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
TELEGRAM_URL = f'https://api.telegram.org/bot{TOKEN}'

# ── Arranque: verificar variables ──────────────────────────
print(f"[BOOT] TOKEN cargado: {'SI' if TOKEN else 'NO'}")
print(f"[BOOT] OPENAI_KEY cargada: {'SI' if OPENAI_KEY else 'NO'}")
print(f"[BOOT] TELEGRAM_URL: {TELEGRAM_URL[:40]}...")

def send_message(chat_id, text):
    print(f"[SEND] Enviando mensaje a {chat_id}: {text[:50]}")
    r = requests.post(f'{TELEGRAM_URL}/sendMessage', json={
        'chat_id': chat_id,
        'text': text
    })
    print(f"[SEND] Respuesta Telegram: {r.status_code} {r.text[:100]}")

def extract_gasto(texto):
    hoy = datetime.now().strftime('%Y-%m-%d')
    print(f"[OPENAI] Extrayendo gasto de: {texto}")
    prompt = f"""Extrae el gasto del siguiente texto.
Devuelve SOLO un objeto JSON con: fecha (YYYY-MM-DD, hoy es {hoy} si no se menciona),
monto (número), concepto (texto corto),
categoria (comida, transporte, entretenimiento, salud, hogar, ropa, educacion, otro).
Texto: {texto}"""

    res = requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers={'Authorization': f'Bearer {OPENAI_KEY}'},
        json={
            'model': 'gpt-4o-mini',
            'max_tokens': 200,
            'messages': [
                {'role': 'system', 'content': 'Devuelve SOLO JSON, sin markdown ni backticks.'},
                {'role': 'user', 'content': prompt}
            ]
        }
    )
    print(f"[OPENAI] Status: {res.status_code}")
    raw = res.json()['choices'][0]['message']['content'].strip()
    print(f"[OPENAI] Respuesta: {raw}")
    return json.loads(raw)

def calcular_resumen(comando):
    print(f"[RESUMEN] Calculando: {comando}")
    filas = get_all_rows()
    print(f"[RESUMEN] Filas obtenidas: {len(filas)}")
    ahora = datetime.now()
    hoy = ahora.strftime('%Y-%m-%d')
    hace7 = ahora - timedelta(days=7)

    if comando == '/diario':
        filtradas = [f for f in filas if f.get('fecha') == hoy]
        etiqueta = 'Hoy'
    elif comando == '/semanal':
        filtradas = [f for f in filas if datetime.strptime(f.get('fecha','2000-01-01'), '%Y-%m-%d') >= hace7]
        etiqueta = 'Últimos 7 días'
    elif comando == '/mensual':
        filtradas = [f for f in filas if f.get('fecha','')[:7] == ahora.strftime('%Y-%m')]
        etiqueta = 'Este mes'
    elif comando == '/anual':
        filtradas = [f for f in filas if f.get('fecha','')[:4] == str(ahora.year)]
        etiqueta = f'Año {ahora.year}'
    else:
        return None

    total = sum(float(f.get('monto', 0)) for f in filtradas)
    count = len(filtradas)
    resultado = f'{etiqueta}: ${total:,.0f} ({count} gastos)'
    print(f"[RESUMEN] Resultado: {resultado}")
    return resultado

# ── Ruta fija en lugar de dinámica con TOKEN ───────────────
@app.route('/webhook', methods=['POST'])
def webhook():
    print(f"[WEBHOOK] Request recibido")
    try:
        data = request.json
        print(f"[WEBHOOK] Data: {json.dumps(data)[:200]}")
        message = data.get('message', {})
        chat_id = message.get('chat', {}).get('id')
        texto = message.get('text', '').strip()
        print(f"[WEBHOOK] chat_id: {chat_id}, texto: {texto}")

        if not texto or not chat_id:
            print("[WEBHOOK] Sin texto o chat_id, ignorando")
            return 'ok'

        if texto in ['/diario', '/semanal', '/mensual', '/anual']:
            resumen = calcular_resumen(texto)
            send_message(chat_id, resumen)
            return 'ok'

        try:
            gasto = extract_gasto(texto)
            append_row(gasto['fecha'], gasto['monto'], gasto['concepto'], gasto['categoria'])
            send_message(chat_id,
                f"Guardado ✓\n{gasto['concepto']} — ${gasto['monto']}\n"
                f"Categoría: {gasto['categoria']}\nFecha: {gasto['fecha']}"
            )
        except Exception as e:
            print(f"[ERROR] Extracción fallida: {e}")
            send_message(chat_id, 'No pude entender ese gasto, intenta de nuevo.')

    except Exception as e:
        print(f"[ERROR] Webhook general: {e}")

    return 'ok'

@app.route('/set-webhook')
def set_webhook():
    base_url = request.args.get('url')
    webhook_url = f"{base_url}/webhook"
    print(f"[SETUP] Registrando webhook: {webhook_url}")
    res = requests.get(f'{TELEGRAM_URL}/setWebhook?url={webhook_url}')
    print(f"[SETUP] Respuesta: {res.text}")
    return res.json()

@app.route('/')
def health():
    print("[HEALTH] Health check OK")
    return f'Bot activo ✓ | TOKEN: {"OK" if TOKEN else "FALTA"} | OPENAI: {"OK" if OPENAI_KEY else "FALTA"}', 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"[BOOT] Arrancando en puerto {port}")
    app.run(host='0.0.0.0', port=port)
