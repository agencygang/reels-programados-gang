"""
Publicador en la nube (corre en GitHub Actions, con tu PC apagada).
Lo sube `python editor.py activar-nube`; no hace falta tocarlo.

Cada archivo cola/NN.json es un reel: cuando llega su hora lo baja del release "videos",
lo publica en Instagram con la API oficial y anota el resultado.
"""
import glob, json, os, random, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone

CFG = json.load(open("config.json", encoding="utf-8"))
TZ = timezone(timedelta(minutes=CFG["utc_offset_min"]))
FMT = "%Y-%m-%d %H:%M"
IG_API = "https://graph.instagram.com/v25.0"
TMP = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "videos")
INTENTOS = 3     # veces que se reintenta un video antes de darlo por perdido
REINTENTO = 15   # minutos hasta el siguiente intento (si todavia estamos en franja)
RESCATE = 45     # minutos: pasado eso, un "subiendo" es una corrida que se corto


def ahora():
    return datetime.now(TZ).replace(tzinfo=None)


def log(msg):
    print(f"{ahora():%Y-%m-%d %H:%M} {msg}", flush=True)


# ------------------------------------------------------------------ GIT (estado)
def guardar(d, msg):
    ruta = f"cola/{d['num']}.json"
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in d.items() if k != "_ruta"}, f, ensure_ascii=False, indent=2)
    subir_cambios([ruta], msg)


def subir_cambios(rutas, msg):
    subprocess.run(["git", "add", *rutas], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(["git", "commit", "-q", "-m", msg], check=True)
    for _ in range(6):
        if subprocess.run(["git", "pull", "-q", "--rebase"]).returncode != 0:
            subprocess.run(["git", "rebase", "--abort"])
        elif subprocess.run(["git", "push", "-q"]).returncode == 0:
            return
        time.sleep(10)
    raise RuntimeError("No se pudo guardar el estado en GitHub")


# ------------------------------------------------------------------ INSTAGRAM
def abrir(req, timeout=120):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode(errors="replace")
        try:
            msg = json.loads(cuerpo)["error"]["message"]
        except Exception:
            msg = cuerpo[:300]
        raise RuntimeError(f"Instagram {e.code}: {msg}") from None


def ig(ruta, token, datos=None, metodo="POST"):
    url = ruta if ruta.startswith("http") else f"{IG_API}/{ruta}"
    q = urllib.parse.urlencode(dict(datos or {}, access_token=token))
    if metodo == "GET":
        return abrir(urllib.request.Request(f"{url}?{q}"))
    return abrir(urllib.request.Request(url, data=q.encode(), method="POST"))


def token_vigente():
    """El token de Instagram dura 60 dias: se renueva cada semana y se guarda en el secreto IG_TOKEN."""
    token = os.environ["IG_TOKEN"]
    renovado = date.fromisoformat(open("renovado.txt").read().strip())
    if (date.today() - renovado).days < 7:
        return token
    try:
        nuevo = ig("https://graph.instagram.com/refresh_access_token", token, {"grant_type": "ig_refresh_token"}, "GET")["access_token"]
        print(f"::add-mask::{nuevo}")
        subprocess.run(["gh", "secret", "set", "IG_TOKEN", "--body", nuevo, "-R", os.environ["REPO"]], check=True,
                       env=dict(os.environ, GH_TOKEN=os.environ["GH_PAT"]), capture_output=True)
        with open("renovado.txt", "w") as f:
            f.write(date.today().isoformat())
        subir_cambios(["renovado.txt"], "token renovado")
        log("Token de Instagram renovado")
        return nuevo
    except Exception as e:
        log(f"AVISO: no se pudo renovar el token ({e})")
        return token


def buzon(*args, falla_ok=False):
    """Comandos sobre el repo publico temporal, con el token que puede escribir en el."""
    return subprocess.run(["gh", *args, "-R", CFG["buzon"]], check=not falla_ok,
                          env=dict(os.environ, GH_TOKEN=os.environ["GH_PAT"]), capture_output=True)


def preparar_reel(d, token):
    """Deja el video procesado y listo en Instagram, sin publicarlo todavia. Devuelve el contenedor.

    Instagram no acepta que le mandemos el archivo (eso es solo con Facebook Login): tiene que descargarlo
    el mismo de una URL publica, asi que el video pasa unos minutos por el buzon y despues se borra."""
    os.makedirs(TMP, exist_ok=True)
    video = os.path.join(TMP, d["asset"])
    subprocess.run(["gh", "release", "download", "videos", "-p", d["asset"], "-D", TMP, "--clobber"], check=True)
    buzon("release", "upload", "videos", video, "--clobber")
    url = f"https://github.com/{CFG['buzon']}/releases/download/videos/{d['asset']}"
    datos = {"media_type": "REELS", "video_url": url, "caption": d["caption"]}
    if CFG["reel_de_prueba"]:
        datos["trial_params"] = json.dumps({"graduation_strategy": CFG["paso_a_seguidores"]})
    contenedor = ig(f"{os.environ['IG_ID']}/media", token, datos)["id"]
    for _ in range(90):  # hasta 15 min descargando y procesando
        r = ig(contenedor, token, {"fields": "status_code,status"}, "GET")
        if r.get("status_code") == "FINISHED":
            return contenedor
        if r.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram no pudo procesar el video: {r.get('status') or r['status_code']}")
        time.sleep(10)
    raise RuntimeError("Instagram tardo demasiado procesando el video")


def esperar_la_hora(objetivo):
    """La orden final se da al segundo: GitHub arranca tarde, pero la publicacion sale puntual."""
    falta = (objetivo - ahora()).total_seconds()
    if falta <= 0:
        return
    log(f"Video listo. Esperando {falta / 60:.1f} min para publicar a las {objetivo:%H:%M}")
    time.sleep(falta)


# ------------------------------------------------------------------ CALENDARIO
def ya_publicado(d, token):
    """Antes de reintentar algo que quedo a medias: mirar si en realidad ya habia salido.

    Puede pasar que Instagram publique y la corrida se corte antes de anotarlo. Se compara la
    primera linea del copy contra las ultimas publicaciones de la cuenta."""
    primera = (d["caption"].splitlines() or [""])[0][:60].strip()
    if not primera:
        return None
    try:
        medios = ig(f"{os.environ['IG_ID']}/media", token, {"fields": "id,caption", "limit": "12"}, "GET")
    except Exception as e:
        log(f"AVISO: no se pudo revisar lo ya publicado ({e})")
        return None
    for m in medios.get("data", []):
        if primera in (m.get("caption") or ""):
            return m["id"]
    return None


def rescatar(cola, token):
    """Los que quedaron trabados en 'subiendo' (corrida cortada) vuelven a la cola."""
    for d in cola:
        if d["estado"] != "subiendo":
            continue
        desde = datetime.strptime(d.get("intento_en", d["publicar_en"]), FMT)
        if ahora() - desde < timedelta(minutes=RESCATE):
            continue
        media = ya_publicado(d, token)
        if media:
            d.update(estado="publicado", ig_media=media, publicado_en=ahora().strftime(FMT), nota="")
            log(f"{d['num']} ya estaba publicado: se anota y listo")
        else:
            d.update(estado="programado", publicar_en=next(huecos_libres(cola, ahora())).strftime(FMT))
            log(f"{d['num']} quedo a medias. Vuelve a la cola: {d['publicar_en']}")
        guardar(d, f"rescatar {d['num']}")


def franja(t):
    for i, (a, b) in enumerate(CFG["horarios"]):
        if a <= t.strftime("%H:%M") <= b:
            return i


def huecos_libres(cola, desde):
    ocupados = {(datetime.strptime(d["publicar_en"], FMT).date(), franja(datetime.strptime(d["publicar_en"], FMT)))
                for d in cola if d["estado"] == "programado"}
    dia = desde.date()
    while True:
        for i, (a, b) in enumerate(CFG["horarios"]):
            ini = max(datetime.combine(dia, datetime.strptime(a, "%H:%M").time()), desde + timedelta(minutes=10))
            fin = datetime.combine(dia, datetime.strptime(b, "%H:%M").time())
            if (dia, i) in ocupados or ini >= fin:
                continue
            ocupados.add((dia, i))
            yield ini + timedelta(minutes=random.randint(0, int((fin - ini).total_seconds() // 60)))
        dia += timedelta(days=1)


def main():
    cola = [json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob("cola/*.json"))]
    token = token_vigente()
    rescatar(cola, token)
    t = ahora()
    margen = timedelta(minutes=CFG.get("espera_maxima", 20))  # se agarra lo que esta por salir, no solo lo vencido
    turno = []
    for d in cola:
        if d["estado"] != "programado" or datetime.strptime(d["publicar_en"], FMT) > t + margen:
            continue
        if t - datetime.strptime(d["publicar_en"], FMT) > timedelta(minutes=CFG["atraso_maximo"]):
            d["publicar_en"] = next(huecos_libres(cola, t)).strftime(FMT)
            log(f"{d['num']} se paso de hora. Nueva hora: {d['publicar_en']}")
            guardar(d, f"reprogramar {d['num']}")
        else:
            turno.append(d)
    if not turno:
        log("Nada que publicar ahora")
        return
    d = min(turno, key=lambda d: d["publicar_en"])  # uno por vez
    objetivo = datetime.strptime(d["publicar_en"], FMT)
    d["estado"], d["intento_en"] = "subiendo", ahora().strftime(FMT)  # se guarda ANTES: asi nunca se publica dos veces
    d["intentos"] = d.get("intentos", 0) + 1
    guardar(d, f"subiendo {d['num']}")
    log(f"{d['num']} preparando para las {d['publicar_en']} (intento {d['intentos']})")
    try:
        contenedor = preparar_reel(d, token)
        esperar_la_hora(objetivo)
        d["ig_media"] = ig(f"{os.environ['IG_ID']}/media_publish", token, {"creation_id": contenedor})["id"]
        d["estado"], d["publicado_en"], d["nota"] = "publicado", ahora().strftime(FMT), ""
        log(f"{d['num']} publicado {'como reel de prueba' if CFG['reel_de_prueba'] else ''}")
        subprocess.run(["gh", "release", "delete-asset", "videos", d["asset"], "-y"])  # libera espacio
    except Exception as e:
        media = ya_publicado(d, token)  # pudo fallar despues de publicar
        if media:
            d.update(estado="publicado", ig_media=media, publicado_en=ahora().strftime(FMT), nota="")
            log(f"{d['num']} publicado igual (el error fue despues): {e}")
        elif d["intentos"] < INTENTOS:
            pronto = ahora() + timedelta(minutes=REINTENTO)
            d["estado"] = "programado"
            d["publicar_en"] = (pronto if franja(pronto) is not None
                                else next(huecos_libres(cola, ahora()))).strftime(FMT)
            d["nota"] = f"intento {d['intentos']} fallido: {str(e)[:300]}"
            log(f"{d['num']} falló: {e}\n  Reintento a las {d['publicar_en']}")
        else:
            d["estado"], d["nota"] = "error subida", str(e)[:500]
            log(f"{d['num']} ERROR definitivo tras {d['intentos']} intentos: {e}")
    buzon("release", "delete-asset", "videos", d["asset"], "-y", falla_ok=True)  # el buzon queda vacio siempre
    guardar(d, f"{d['estado']} {d['num']}")
    if d["estado"] == "error subida":
        sys.exit(1)  # que la corrida figure como fallida: GitHub avisa por correo


# ------------------------------------------------------------------ PAGINA DEL CALENDARIO
def gh_api(ruta, datos=None, metodo=None):
    req = urllib.request.Request(f"https://api.github.com/{ruta}", method=metodo,
                                 data=json.dumps(datos).encode() if datos is not None else None,
                                 headers={"Authorization": f"Bearer {os.environ['GH_PAT']}",
                                          "Accept": "application/vnd.github+json", "User-Agent": "publicador"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"GitHub {e.code}: {e.read().decode(errors='replace')[:200]}") from None


def actualizar_pagina():
    """Rehace el calendario del celular (repo publico con GitHub Pages) si algo cambio.

    La PC deja en calendario/ lo que no esta en la cola: el titulo en dos lineas, la duracion y la miniatura."""
    import base64
    import pagina_calendario as pc
    if not os.path.exists("calendario/info.json"):
        return
    info = json.load(open("calendario/info.json", encoding="utf-8"))
    reels = []
    for p in sorted(glob.glob("cola/*.json")):
        d = json.load(open(p, encoding="utf-8"))
        extra = {}
        if os.path.exists(f"calendario/{d['num']}.json"):
            extra = json.load(open(f"calendario/{d['num']}.json", encoding="utf-8"))
            if extra.get("asset") != d["asset"]:  # es de un reel viejo con el mismo numero
                extra = {}
        thumb = ""
        if extra and os.path.exists(f"calendario/{d['num']}.jpg"):
            thumb = "data:image/jpeg;base64," + base64.b64encode(open(f"calendario/{d['num']}.jpg", "rb").read()).decode()
        reels.append({"num": d["num"], "linea1": extra.get("linea1", d["titulo"]), "linea2": extra.get("linea2", ""),
                      "copy": d["caption"], "estado": d["estado"], "publicar_en": d["publicar_en"],
                      "duracion": extra.get("duracion", ""), "thumb": thumb, "propio": extra.get("propio", False)})
    pagina, huella = pc.armar(reels, info["cuenta"], CFG["horarios"], ahora())
    actual = gh_api(f"repos/{info['pagina']}/contents/index.html")
    if actual and pc.huella_de(base64.b64decode(actual["content"]).decode()) == huella:
        return
    datos = {"message": "calendario actualizado", "content": base64.b64encode(pagina.encode()).decode()}
    if actual:
        datos["sha"] = actual["sha"]
    gh_api(f"repos/{info['pagina']}/contents/index.html", datos, "PUT")
    log("Calendario del celular actualizado")


if __name__ == "__main__":
    try:
        main()
    finally:  # tambien cuando algo fallo: la pagina tiene que mostrar el error
        try:
            subprocess.run(["git", "pull", "-q", "--rebase"])  # por si otra corrida cambio la cola mientras tanto
            actualizar_pagina()
        except Exception as e:
            log(f"AVISO: no se pudo actualizar el calendario del celular ({e})")
