#!/usr/bin/env python3
"""
Alertas de surf - Pinamar y Mar del Plata
Chequea el pronostico (Open-Meteo, gratis y sin API key) y, si de aca
hasta el final del domingo hay ventanas con buenas condiciones, avisa
por Telegram.

No necesita instalar nada: usa solo la libreria estandar de Python.
"""

import os
import json
import urllib.request
from datetime import datetime, timedelta

# ============================================================
# CONFIG  ->  toca solo esto para ajustar a tu gusto
# ============================================================

SPOTS = [
    {"nombre": "Pinamar",        "lat": -37.106, "lon": -56.861},
    {"nombre": "Mar del Plata",  "lat": -38.005, "lon": -57.545},
]

# Condiciones "optimas" (mismas para los dos spots; cambialas si queres)
OLA_MIN_M      = 0.7    # altura de ola minima (metros)
OLA_MAX_M      = 2.0    # altura de ola maxima (si sube de esto, se pone feo)
PERIODO_MIN_S  = 7.0    # periodo minimo (segundos) -> mas periodo = mejor calidad
VIENTO_MAX_KMH = 18.0   # viento maximo (km/h)

# Solo horas con luz
HORA_DESDE = 6
HORA_HASTA = 20

# Viento offshore (de la tierra hacia el mar) para esta costa: sector Oeste.
# Es un "bonus", no descarta la ventana; solo la marca como mejor.
OFFSHORE_DESDE = 200
OFFSHORE_HASTA = 340

DIAS = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]

# ============================================================

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "surf-alertas"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def datos_spot(lat, lon):
    """Trae olas + viento y los alinea por hora."""
    marine = get_json(
        f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}"
        "&hourly=wave_height,wave_period,wave_direction,swell_wave_period"
        "&timezone=auto&forecast_days=7"
    )["hourly"]

    viento = get_json(
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&hourly=wind_speed_10m,wind_direction_10m"
        "&wind_speed_unit=kmh&timezone=auto&forecast_days=7"
    )["hourly"]

    v_speed = dict(zip(viento["time"], viento["wind_speed_10m"]))
    v_dir   = dict(zip(viento["time"], viento["wind_direction_10m"]))

    filas = []
    for i, t in enumerate(marine["time"]):
        ola     = marine["wave_height"][i]
        periodo = marine["wave_period"][i] or marine["swell_wave_period"][i]
        filas.append({
            "t": t,
            "ola": ola,
            "periodo": periodo,
            "viento": v_speed.get(t),
            "viento_dir": v_dir.get(t),
        })
    return filas

def es_optima(f):
    if None in (f["ola"], f["periodo"], f["viento"]):
        return False
    return (
        OLA_MIN_M <= f["ola"] <= OLA_MAX_M
        and f["periodo"] >= PERIODO_MIN_S
        and f["viento"] <= VIENTO_MAX_KMH
    )

def es_offshore(dir_grados):
    if dir_grados is None:
        return False
    return OFFSHORE_DESDE <= dir_grados <= OFFSHORE_HASTA

def limite_domingo(ahora):
    """Devuelve el final del domingo de esta semana (o de hoy si ya es domingo)."""
    dias_hasta_domingo = (6 - ahora.weekday()) % 7   # lun=0 ... dom=6
    domingo = ahora + timedelta(days=dias_hasta_domingo)
    return domingo.replace(hour=23, minute=59, second=59, microsecond=0)

def ventanas_optimas(filas):
    """Filtra horas buenas (dia + hasta el domingo) y agrupa las consecutivas."""
    ahora = datetime.utcnow() - timedelta(hours=3)   # hora Argentina (UTC-3)
    limite = limite_domingo(ahora)

    buenas = []
    for f in filas:
        dt = datetime.fromisoformat(f["t"])
        if not (ahora <= dt <= limite):
            continue
        if not (HORA_DESDE <= dt.hour <= HORA_HASTA):
            continue
        if es_optima(f):
            f["dt"] = dt
            buenas.append(f)

    # agrupar horas consecutivas en ventanas
    ventanas = []
    grupo = []
    for f in buenas:
        if grupo and (f["dt"] - grupo[-1]["dt"]) == timedelta(hours=1):
            grupo.append(f)
        else:
            if grupo:
                ventanas.append(grupo)
            grupo = [f]
    if grupo:
        ventanas.append(grupo)
    return ventanas

def texto_ventana(grupo):
    ini, fin = grupo[0]["dt"], grupo[-1]["dt"]
    dia = DIAS[ini.weekday()]
    horario = f"{ini.hour:02d}-{fin.hour + 1:02d}h"
    olas = [g["ola"] for g in grupo]
    per_min = min(g["periodo"] for g in grupo)
    vto_max = max(g["viento"] for g in grupo)
    offshore = any(es_offshore(g["viento_dir"]) for g in grupo)
    linea = (
        f"  {dia} {horario} | ola {min(olas):.1f}-{max(olas):.1f}m"
        f" | periodo {per_min:.0f}s | viento {vto_max:.0f} km/h"
    )
    if offshore:
        linea += " offshore"
    return linea

def enviar_telegram(mensaje):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({
        "chat_id": chat_id,
        "text": mensaje,
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=30)

def main():
    bloques = []
    for spot in SPOTS:
        try:
            filas = datos_spot(spot["lat"], spot["lon"])
        except Exception as e:
            print(f"Error con {spot['nombre']}: {e}")
            continue
        ventanas = ventanas_optimas(filas)
        if ventanas:
            lineas = "\n".join(texto_ventana(v) for v in ventanas)
            bloques.append(f"🏄 {spot['nombre']}\n{lineas}")

    if not bloques:
        print("Sin ventanas optimas de aca al domingo. No mando nada.")
        return

    mensaje = "Condiciones para surfear 🌊\n\n" + "\n\n".join(bloques)
    enviar_telegram(mensaje)
    print("Alerta enviada:\n" + mensaje)

if __name__ == "__main__":
    main()
