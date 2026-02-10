import requests
import datetime
import os
import json
import gspread
from google.oauth2.service_account import Credentials

IOL_USER = os.environ.get("IOL_USER")
IOL_PASS = os.environ.get("IOL_PASS")
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
GOOGLE_SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")

TNA_OBJETIVO = 30.0  # Avisar si la tasa supera este valor

URL_BASE = "https://api.invertironline.com"

def guardar_en_sheets(tasa_actual, tasa_maxima):
    if not GOOGLE_SHEET_NAME or not GOOGLE_CREDENTIALS_JSON:
        return

    try:
        # Parse credentials from string
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1
        
        # Timestamp, TNA Actual, TNA Max
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, tasa_actual, tasa_maxima])
        print("Datos guardados en Google Sheets.")
        
    except Exception as e:
        print(f"Error guardando en Sheets: {e}")

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

        # Guardar historial
        guardar_en_sheets(tasa_actual, tasa_maxima)

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
