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

def send_message(chat_id, text):
    requests.post(f'{TELEGRAM_URL}/sendMessage', json={
        'chat_id': chat_id,
        'text': text
    })

def extract_gasto(texto):
    hoy = datetime.now().strftime('%Y-%m-%d')
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
    raw = res.json()['choices'][0]['message']['content'].strip()
    return json.loads(raw)

def calcular_resumen(comando):
    filas = get_all_rows()
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
    return f'{etiqueta}: ${total:,.0f} ({count} gastos)'

@app.route(f'/webhook/{TOKEN}', methods=['POST'])
def webhook():
    data = request.json
    message = data.get('message', {})
    chat_id = message.get('chat', {}).get('id')
    texto = message.get('text', '').strip()

    if not texto or not chat_id:
        return 'ok'

    # Comandos de resumen
    if texto in ['/diario', '/semanal', '/mensual', '/anual']:
        resumen = calcular_resumen(texto)
        send_message(chat_id, resumen)
        return 'ok'

    # Captura de gasto
    try:
        gasto = extract_gasto(texto)
        append_row(gasto['fecha'], gasto['monto'], gasto['concepto'], gasto['categoria'])
        send_message(chat_id,
            f"Guardado ✓\n{gasto['concepto']} — ${gasto['monto']}\n"
            f"Categoría: {gasto['categoria']}\nFecha: {gasto['fecha']}"
        )
    except Exception as e:
        send_message(chat_id, 'No pude entender ese gasto, intenta de nuevo.')
        print(f'Error: {e}')

    return 'ok'

@app.route('/set-webhook')
def set_webhook():
    url = request.args.get('url')
    res = requests.get(f'{TELEGRAM_URL}/setWebhook?url={url}/webhook/{TOKEN}')
    return res.json()

@app.route('/')
def health():
    return 'Bot activo ✓', 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
