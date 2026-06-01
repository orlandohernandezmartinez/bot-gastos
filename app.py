import os
import json
import requests
from datetime import datetime, timedelta
from flask import Flask, request
from dotenv import load_dotenv
from sheets import append_row, get_all_rows

import unicodedata

MX_TZ = ZoneInfo("America/Mexico_City")

def fecha_hora_telegram_dt(message):
    timestamp = message.get('date')
    return datetime.fromtimestamp(timestamp, tz=MX_TZ)

def normalizar(texto):
    texto = texto.lower().strip()
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto

load_dotenv()

app = Flask(__name__)

TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
TELEGRAM_URL = f'https://api.telegram.org/bot{TOKEN}'

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
Devuelve SOLO un objeto JSON con estas claves:
- fecha: YYYY-MM-DD (hoy es {hoy} si no se menciona)
- monto: número sin símbolos
- concepto: copia EXACTAMENTE el texto del gasto tal como fue escrito, sin resumir ni modificar. 
  Excluye solo la fecha, el monto y el banco si están mencionados.
  Ejemplos: 
  "110 comida con melisa en la once mil" → "comida con melisa en la once mil"
  "230 drinks listening party amex" → "drinks listening party"
  "16/04/2026 77 pan green rhyno revolut" → "pan green rhyno"
- categoria: una de estas opciones exactas:
  * 'cafe' → café, capuchino, latte, americano, espresso, flat white, coffee
  * 'pan' → pan, panadería, croissant, baguette, dona, krispy kreme
  * 'comida' → restaurantes, tacos, super, aguacates, comida en general
  * 'bebida' → drinks, cervezas, chelas, cocteles, martini, negroni, mezcal, mezcales, agua, suero, electrolit, cocktail
  * 'transporte' → uber, taxi, gasolina, vuelos, metro
  * 'entretenimiento' → cine, netflix, spotify, conciertos, fiestas, eventos
  * 'salud' → médico, farmacia, doctor, gym
  * 'hogar' → renta, luz, agua, internet, muebles
  * 'ropa' → ropa, zapatos, tenis, accesorios
  * 'hormiga' → oxxo, seven eleven, chatarra, snacks
  * 'educacion' → cursos, libros, clases
  * 'trabajo' → claude, chatgpt, google workspace, software, celular, telcel, suscripciones de trabajo
  * 'credito' → pago de tarjeta de crédito, liquidación de deuda
  * 'gustito' → gastos personales de placer: perfume, revelado de rollo, caprichos
  * 'servicios' → lavandería, servicios domésticos, luz, agua, gas, internet
  * 'otro' → cualquier cosa que no encaje arriba
- banco: la fuente de fondos mencionada. Si no se menciona usa 'efectivo'. 
 * Si se menciona explícitamente úsalo: 'Amex', 'Revolut', 'Nu', 'Stori', 'BBVA'
  Ejemplos: 'cash', 'chash', 'efectivo' → 'efectivo'; 'nu', 'nubank' → 'Nu'; 
  'revolut' → 'Revolut'; 'bbva' → 'BBVA'; 'credito' → 'crédito'
- tag: si hay una coma "," en el mensaje, todo lo que viene DESPUÉS de la coma es el tag. 
  Ejemplos:
  "110 comida con melisa, viaje paris" → tag: "viaje paris"
  "230 drinks tonal, viaje oaxaca" → tag: "viaje oaxaca"
  "85 tacos" → tag: "" (sin coma = sin tag, devuelve string vacío)

Texto: {texto}"""

    res = requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers={'Authorization': f'Bearer {OPENAI_KEY}'},
        json={
            'model': 'gpt-4o-mini',
            'max_tokens': 300,
            'messages': [
                {'role': 'system', 'content': 'Devuelve SOLO JSON válido, sin markdown ni backticks.'},
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
        filtradas = [f for f in filas if datetime.strptime(f.get('fecha', '2000-01-01'), '%Y-%m-%d') >= hace7]
        etiqueta = 'Últimos 7 días'
    elif comando == '/mensual':
        filtradas = [f for f in filas if f.get('fecha', '')[:7] == ahora.strftime('%Y-%m')]
        etiqueta = 'Este mes'
    elif comando == '/anual':
        filtradas = [f for f in filas if f.get('fecha', '')[:4] == str(ahora.year)]
        etiqueta = f'Año {ahora.year}'
    else:
        return None

    total = sum(float(f.get('monto', 0)) for f in filtradas)
    count = len(filtradas)
    resultado = f'{etiqueta}: ${total:,.0f} ({count} gastos)'
    print(f"[RESUMEN] Resultado: {resultado}")
    return resultado

def consulta_categoria(texto):
    """Detecta preguntas sobre categorías específicas y calcula el total"""
    hoy = datetime.now()
    texto_lower = normalizar(texto)  

    # Detectar periodo
    if 'hoy' in texto_lower:
        periodo = 'hoy'
        etiqueta_periodo = 'hoy'
    elif 'semana' in texto_lower:
        periodo = 'semana'
        etiqueta_periodo = 'esta semana'
    elif 'año' in texto_lower or 'anual' in texto_lower:
        periodo = 'anual'
        etiqueta_periodo = f'este año'
    else:
        periodo = 'mes'
        etiqueta_periodo = 'este mes'

    # Detectar categoría mencionada
    categorias_map = {
        'cafe': ['café', 'cafe', 'coffee', 'flatwhite'],
        'pan': ['pan', 'panadería', 'panaderia', 'dona', 'donas', 'krispy'],
        'comida': ['comida', 'comer', 'restaurante', 'food'],
        'bebida': ['drinks', 'chelas', 'cervezas', 'cocteles', 'coctel', 'cocktail', 'martini', 'negroni', 'mezcal', 'mezcales', 'agua', 'suero', 'electrolit'],
        'transporte': ['transporte', 'uber', 'taxi', 'gasolina'],
        'entretenimiento': ['entretenimiento', 'ocio', 'diversión', 'diversion'],
        'salud': ['salud', 'médico', 'medico', 'farmacia'],
        'hogar': ['hogar', 'casa', 'renta'],
        'ropa': ['ropa', 'ropa', 'vestimenta'],
        'hormiga': ['oxxo', 'seven', 'chatarra'],
        'educacion': ['educacion', 'educación', 'curso', 'clase'],
        'trabajo': ['claude', 'chatgpt', 'chat', 'gpt', 'google'],
        'otro': ['otro']
    }

    categoria_detectada = None
    for cat, palabras in categorias_map.items():
        if any(p in texto_lower for p in palabras):
            categoria_detectada = cat
            break

    if not categoria_detectada:
        return None

    filas = get_all_rows()

    # Filtrar por periodo
    if periodo == 'hoy':
        filas = [f for f in filas if f.get('fecha') == hoy.strftime('%Y-%m-%d')]
    elif periodo == 'semana':
        hace7 = hoy - timedelta(days=7)
        filas = [f for f in filas if datetime.strptime(f.get('fecha', '2000-01-01'), '%Y-%m-%d') >= hace7]
    elif periodo == 'mes':
        filas = [f for f in filas if f.get('fecha', '')[:7] == hoy.strftime('%Y-%m')]
    elif periodo == 'anual':
        filas = [f for f in filas if f.get('fecha', '')[:4] == str(hoy.year)]

    # Filtrar por categoría
    filtradas = [f for f in filas if f.get('categoria', '').lower() == categoria_detectada]
    total = sum(float(f.get('monto', 0)) for f in filtradas)
    count = len(filtradas)

    return f'{categoria_detectada.capitalize()} {etiqueta_periodo}: ${total:,.0f} ({count} gastos)'

# Cuentas conocidas para detectar en consultas
CUENTAS_CONOCIDAS = [
    'revolut', 'nu', 'amex', 'stori', 'bbva', 'efectivo', 'cash'
]

def consulta_banco(texto):
    texto_norm = normalizar(texto)
    
    # Detectar qué cuenta menciona
    cuenta_detectada = None
    for cuenta in CUENTAS_CONOCIDAS:
        if cuenta in texto_norm:
            cuenta_detectada = cuenta
            break
    
    if not cuenta_detectada:
        return None

    # Detectar si es consulta de deuda
    es_deuda = any(p in texto_norm for p in ['debo', 'deuda', 'deber', 'credito', 'crédito', 'adeudo'])

    # Detectar periodo — default mes si no se especifica
    hoy = datetime.now()
    if 'hoy' in texto_norm:
        periodo = 'hoy'
        etiqueta_periodo = 'hoy'
    elif 'semana' in texto_norm:
        periodo = 'semana'
        etiqueta_periodo = 'esta semana'
    elif 'ano' in texto_norm or 'anual' in texto_norm:
        periodo = 'anual'
        etiqueta_periodo = f'este año'
    else:
        # Default: mes actual
        periodo = 'mes'
        etiqueta_periodo = 'este mes'

    filas = get_all_rows()

    # Filtrar por periodo
    if periodo == 'hoy':
        filas_periodo = [f for f in filas if f.get('fecha') == hoy.strftime('%Y-%m-%d')]
    elif periodo == 'semana':
        hace7 = hoy - timedelta(days=7)
        filas_periodo = [f for f in filas if datetime.strptime(f.get('fecha', '2000-01-01'), '%Y-%m-%d') >= hace7]
    elif periodo == 'mes':
        filas_periodo = [f for f in filas if f.get('fecha', '')[:7] == hoy.strftime('%Y-%m')]
    elif periodo == 'anual':
        filas_periodo = [f for f in filas if f.get('fecha', '')[:4] == str(hoy.year)]

    if es_deuda:
        # Deuda = gastos con esa cuenta - pagos a esa cuenta (categoria credito)
        # Busca en TODO el historial, no solo el periodo
        gastos_cuenta = [
            f for f in filas
            if normalizar(f.get('banco', '')) == cuenta_detectada
            and normalizar(f.get('categoria', '')) != 'credito'
        ]
        pagos_cuenta = [
            f for f in filas
            if normalizar(f.get('categoria', '')) == 'credito'
            and cuenta_detectada in normalizar(f.get('concepto', ''))
        ]
        total_gastos = sum(float(f.get('monto', 0)) for f in gastos_cuenta)
        total_pagos = sum(float(f.get('monto', 0)) for f in pagos_cuenta)
        saldo = total_gastos - total_pagos

        detalle = f"Gastos con {cuenta_detectada.capitalize()}: ${total_gastos:,.0f}\n"
        detalle += f"Pagos realizados: ${total_pagos:,.0f}\n"
        detalle += f"Saldo estimado: ${saldo:,.0f}"
        return detalle
    else:
        # Gasto con esa cuenta en el periodo
        filtradas = [
            f for f in filas_periodo
            if normalizar(f.get('banco', '')) == cuenta_detectada
        ]
        total = sum(float(f.get('monto', 0)) for f in filtradas)
        count = len(filtradas)
        return f'{cuenta_detectada.capitalize()} {etiqueta_periodo}: ${total:,.0f} ({count} gastos)'

def consulta_tag(texto):
    texto_norm = normalizar(texto)
    
    # Detectar si pregunta por un tag
    palabras_trigger = ['viaje', 'trip', 'evento', 'gaste en', 'gastado en']
    if not any(p in texto_norm for p in PALABRAS_CONSULTA):
        return None

    filas = get_all_rows()
    
    # Buscar qué tag menciona — tomar las últimas palabras del texto
    # Estrategia: buscar en todos los tags del sheet cuál matchea mejor
    tags_en_sheet = set()
    for f in filas:
        t = normalizar(f.get('tag', ''))
        if t:
            tags_en_sheet.add(t)
    
    tag_detectado = None
    for tag in tags_en_sheet:
        if tag in texto_norm:
            tag_detectado = tag
            break
    
    if not tag_detectado:
        return None
    
    filtradas = [f for f in filas if normalizar(f.get('tag', '')) == tag_detectado]
    total = sum(float(f.get('monto', 0)) for f in filtradas)
    count = len(filtradas)
    
    return f'Tag "{tag_detectado}": ${total:,.0f} ({count} gastos)'

COMANDOS = ['/diario', '/semanal', '/mensual', '/anual']

PALABRAS_CONSULTA = [
    'cuanto', 'cual', 'gastado', 'gaste',
    'total', 'suma', 'resumen', 'llevo', 'he gastado',
    'debo', 'deuda', 'adeudo'
]

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

        # Comandos de resumen
        if texto in COMANDOS:
            resumen = calcular_resumen(texto)
            send_message(chat_id, resumen)
            return 'ok'

        # Consultas en lenguaje natural
        texto_norm = normalizar(texto)
        if any(p in texto_norm for p in PALABRAS_CONSULTA):
            resultado = consulta_tag(texto) or consulta_banco(texto) or consulta_categoria(texto)
            if resultado:
                send_message(chat_id, resultado)
                return 'ok'

        # Captura de gasto
        try:
            gasto = extract_gasto(texto)
            append_row(
                gasto['fecha'],
                gasto['monto'],
                gasto['concepto'],
                gasto['categoria'],
                gasto.get('banco', 'efectivo'),
                gasto.get('tag', '')
            )
            send_message(chat_id,
                f"Guardado ✓\n"
                f"{gasto['concepto']} — ${gasto['monto']}\n"
                f"Categoría: {gasto['categoria']}\n"
                f"Banco: {gasto.get('banco', 'efectivo')}\n"
                f"Fecha: {gasto['fecha']}"
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
