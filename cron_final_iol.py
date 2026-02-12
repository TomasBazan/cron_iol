import requestimport requests
import datetime
import os
import json
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURACIÓN ---
IOL_USER = os.environ.get("IOL_USER")
IOL_PASS = os.environ.get("IOL_PASS")
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
GOOGLE_SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")

URL_BASE = "https://api.invertironline.com"

# --- VARIABLES DE ESTRATEGIA (Opción 3) ---
UMBRAL_ACTIVACION = 30.0  # Empezamos a mirar si supera esto
RETROCESO_CONFIRMACION = 2.0  # Si baja X puntos desde el pico -> COMPRAR

def get_google_client():
    if not GOOGLE_CREDENTIALS_JSON:
        return None
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        print(f"Error Auth Google: {e}")
        return None

def gestionar_estado(client, tasa_actual=None, actualizar=False):
    """
    Lee o guarda el estado del bot (Memoria) en una hoja llamada 'ESTADO_BOT'.
    Estructura en Sheets: A1: 'TRACKING' (TRUE/FALSE), B1: 'MAX_PEAK' (Float)
    """
    if not client or not GOOGLE_SHEET_NAME:
        return {"tracking": False, "max_peak": 0.0}

    try:
        sh = client.open(GOOGLE_SHEET_NAME)
        # Intentamos abrir la hoja de estado, si no existe la creamos
        try:
            worksheet = sh.worksheet("ESTADO_BOT")
        except:
            worksheet = sh.add_worksheet(title="ESTADO_BOT", rows=1, cols=2)
            worksheet.update('A1:B1', [['FALSE', 0.0]])

        # SI ES LECTURA
        if not actualizar:
            vals = worksheet.get('A1:B1')
            if not vals:
                return {"tracking": False, "max_peak": 0.0}
            
            # Parseamos los valores
            tracking_str = vals[0][0] if len(vals[0]) > 0 else "FALSE"
            max_peak_str = vals[0][1] if len(vals[0]) > 1 else "0"
            
            return {
                "tracking": tracking_str == "TRUE",
                "max_peak": float(max_peak_str)
            }
        
        # SI ES ESCRITURA (Actualizar)
        else:
            tracking_val = "TRUE" if tasa_actual['tracking'] else "FALSE"
            worksheet.update('A1:B1', [[tracking_val, tasa_actual['max_peak']]])
            print(f"Estado actualizado: Tracking={tracking_val}, Peak={tasa_actual['max_peak']}")

    except Exception as e:
        print(f"Error gestionando estado en Sheets: {e}")
        return {"tracking": False, "max_peak": 0.0} # Fallback seguro

def guardar_historial(client, tasa_actual):
    """Guarda el log histórico en la hoja principal"""
    if not client: return
    try:
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, tasa_actual])
    except Exception as e:
        print(f"Error historial: {e}")

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
    client = get_google_client()

    try:
        r = requests.get(f"{URL_BASE}{endpoint}", headers=headers)
        r.raise_for_status()
        
        data = r.json()
        lista = data.get('titulos', [])
        
        print(f"--- Scan {datetime.datetime.now().strftime('%H:%M')} ---")
        
        if not lista:
            print("Mercado cerrado o sin datos.")
            return

        item = lista[0] 
        tasa_actual = float(item.get('ultimoPrecio', 0))
        
        msg_log = f"TNA Actual: {tasa_actual}%"
        print(msg_log)

        # 1. Guardar Historial (Log)
        guardar_historial(client, tasa_actual)

        # --- LÓGICA INTELIGENTE (TRAILING PEAK) ---
        
        # 2. Recuperar memoria de la hora anterior
        estado = gestionarl_estado(client, actualizar=False)
        tracking = estado['tracking']
        max_peak = estado['max_peak']

        nuevo_estado = estado.copy()
        
        if tasa_actual < UMBRAL_ACTIVACION:
            # CASO 1: La tasa es baja (<30%). 
            # Si estábamos rastreando, se cancela todo (falsa alarma o fin de ciclo)
            if tracking:
                print("Tasa cayó por debajo del umbral base. Reseteando rastreo.")
            nuevo_estado = {"tracking": False, "max_peak": 0.0}

        else:
            # CASO 2: La tasa es alta (>30%). Entramos en zona de interés.
            if not tracking:
                # 2A: Recién cruzamos el 30%. Empezamos a rastrear.
                print(f"Umbral {UMBRAL_ACTIVACION}% superado. Iniciando búsqueda de pico...")
                # Opcional: Avisar que empezó la subida, pero NO decir "comprar"
                # enviar_telegram(f"👀 OJO: Cauciones subiendo ({tasa_actual}%). Rastreando pico...")
                nuevo_estado = {"tracking": True, "max_peak": tasa_actual}
            
            else:
                # 2B: Ya estábamos rastreando.
                if tasa_actual > max_peak:
                    # Sigue subiendo (ej: era 35, ahora 38). Actualizamos el pico.
                    print(f"Nuevo máximo detectado: {tasa_actual}% (Anterior: {max_peak}%)")
                    nuevo_estado["max_peak"] = tasa_actual
                
                elif tasa_actual <= (max_peak - RETROCESO_CONFIRMACION):
                    # CONFIRMACIÓN DE VENTA: Bajó X puntos desde el máximo
                    # Ej: Pico 40%, Actual 37% (Bajó 3, margen es 2).
                    mensaje = (
                        f"🚨 **OPORTUNIDAD DE COMPRA** 🚨\n"
                        f"El pico fue: {max_peak}%\n"
                        f"Tasa actual: {tasa_actual}%\n"
                        f"Confirmamos reversión. ¡Entrá ahora!"
                    )
                    enviar_telegram(mensaje)
                    
                    # Reseteamos para no spammear, esperamos el próximo ciclo de subida
                    nuevo_estado = {"tracking": False, "max_peak": 0.0}
                
                else:
                    print(f"Tasa estable o bajada leve ({tasa_actual}%). Pico sigue en {max_peak}%. Esperando...")

        # 3. Guardar el nuevo estado para la próxima hora
        gestionar_estado(client, tasa_actual=nuevo_estado, actualizar=True)

    except Exception as e:
        print(f"Error chequeo: {e}")
        # Enviar error a Telegram para debug
        # enviar_telegram(f"Error en Bot: {e}")

if __name__ == "__main__":
    token = obtener_token()
    if token:
        chequear_mercado(token)chequear_mercado(token)
