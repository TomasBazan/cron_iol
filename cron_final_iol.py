import requests
import datetime
import os

IOL_USER = os.environ.get("IOL_USER")
IOL_PASS = os.environ.get("IOL_PASS")
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

TNA_OBJETIVO = 30.0  # Avisar si la tasa supera este valor

URL_BASE = "https://api.invertironline.com"

def enviar_telegram(mensaje):
    if TG_TOKEN and TG_CHAT_ID:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        try:
            requests.get(url, params={"chat_id": TG_CHAT_ID, "text": mensaje}, timeout=5)
        except Exception as e:
            print(f"Error enviando Telegram: {e}")

def obtener_token():
    url = f"{URL_BASE}/token"
    try:
        r = requests.post(url, data={"username": IOL_USER, "password": IOL_PASS, "grant_type": "password"})
        r.raise_for_status()
        return r.json()['access_token']
    except Exception as e:
        print(f"Error Login: {e}")
        return None

def chequear_mercado(token):
    # Usamos el endpoint ESTABLE que ya confirmaste que funciona (cron2.py)
    endpoint = "/api/v2/Cotizaciones/cauciones/argentina/todos"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        r = requests.get(f"{URL_BASE}{endpoint}", headers=headers)
        r.raise_for_status()
        
        # Como vimos en tu log, esto devuelve un objeto con 'titulos'
        data = r.json()
        lista = data.get('titulos', [])
        
        print(f"--- Scan {datetime.datetime.now().strftime('%H:%M')} ---")
        
        if not lista:
            print("Mercado cerrado o sin datos.")
            return

        # Analizamos el item "Caución en Pesos Arg."
        item = lista[0] # Tomamos el general
        
        tasa_actual = item.get('ultimoPrecio', 0)  # Última operada
        tasa_maxima = item.get('maximo', 0)        # Pico del día
        
        msg_log = f"TNA Actual: {tasa_actual}% | Máx Día: {tasa_maxima}%"
        print(msg_log)

        # --- LÓGICA DE ALERTA ---
        # 1. Si la tasa actual es buena, avisamos YA.
        if tasa_actual >= TNA_OBJETIVO:
            enviar_telegram(f"🔥 ALERTA IOL: Tasa actual {tasa_actual}% (Superior a {TNA_OBJETIVO}%)")
            
        # 2. Si la tasa actual bajó, pero hubo un pico alto reciente (gap de oportunidad)
        elif tasa_maxima >= (TNA_OBJETIVO + 2.0):
            # Solo avisamos si la diferencia es grande, para estar atentos
            enviar_telegram(f"👀 OJO: Hubo tasas de {tasa_maxima}% hoy (Ahora {tasa_actual}%)")

    except Exception as e:
        print(f"Error chequeo: {e}")

if __name__ == "__main__":
    token = obtener_token()
    if token:
        chequear_mercado(token)
