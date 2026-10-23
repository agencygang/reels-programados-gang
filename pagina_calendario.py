# -*- coding: utf-8 -*-
"""Arma el HTML del calendario de reels. Lo usan la PC (calendario.py) y la nube (publicar_nube.py),
asi las dos generan la misma pagina. No depende de editor.py: recibe la lista de reels ya armada.

Cada reel es un dict: num, linea1, linea2, copy, estado, publicar_en ("%Y-%m-%d %H:%M" o ""),
duracion, thumb (data URI o "").
"""
import hashlib
import html
from datetime import datetime

FMT = "%Y-%m-%d %H:%M"
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
ESTADOS = {  # estado -> (etiqueta, clase de color). "en la nube" es el de la PC; "programado" el de la nube
    "en la nube": ("En cola", "wait"),
    "programado": ("En cola", "wait"),
    "subiendo": ("Subiendo", "wait"),
    "publicado": ("Publicado", "ok"),
    "error subida": ("Error al subir", "bad"),
    "editado": ("Sin programar", "idle"),
}
EN_COLA = ("en la nube", "programado", "subiendo")


def franja(t, horarios):
    for i, (a, b) in enumerate(horarios):
        if a <= t.strftime("%H:%M") <= b:
            return "Mediodía" if a < "14:00" else "Media tarde" if a < "17:00" else "Tarde" if a < "19:30" else "Noche"
    return "Tu video"  # fuera de las franjas de reaccion solo van los videos propios (HORAS_PROPIAS)


def dia_largo(d):
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def hora_am_pm(t):
    return t.strftime("%I:%M %p").lstrip("0").replace("AM", "a.m.").replace("PM", "p.m.")


def tarjeta(r, t, horarios):
    etiqueta, color = ESTADOS.get(r["estado"], (r["estado"] or "—", "idle"))
    copy = html.escape(r["copy"]).replace("\n", "<br>")
    img = (f'<img class="thumb" src="{r["thumb"]}" alt="">' if r.get("thumb")
           else '<div class="thumb thumb-vacio">sin video</div>')
    propio = r.get("propio")
    nombre = "★ Tu video" if propio else franja(t, horarios) if t else ""
    hora = (f'<span class="hora">{hora_am_pm(t)}</span><span class="franja">{nombre}</span>'
            if t else '<span class="hora hora-vacia">—</span>')
    pie = f"tu video · reel de prueba · {r.get('duracion', '')} s" if propio else f"reel de prueba · original {r.get('duracion', '')}"
    return f"""      <article class="reel{' propio' if propio else ''}">
        {img}
        <div class="datos">
          <div class="cabecera">{hora}<span class="pill {color}">{etiqueta}</span></div>
          <h3>{html.escape(r['linea1'].strip())} <em>{html.escape(r['linea2'].strip())}</em></h3>
          <p class="copy">{copy}</p>
          <p class="pie"><span class="num">#{r['num']}</span> {pie}</p>
        </div>
      </article>"""


def armar(reels, cuenta, horarios, actualizado):
    """Devuelve (html, huella). La huella no cambia con la hora de 'actualizado': sirve para saber
    si hay algo nuevo que subir o si es la misma pagina de antes."""
    conf, sin_fecha = [], []
    for r in reels:
        if r.get("publicar_en"):
            conf.append((datetime.strptime(r["publicar_en"], FMT), r))
        else:
            sin_fecha.append(r)
    conf.sort(key=lambda x: x[0])

    publicados = sum(1 for _, r in conf if r["estado"] == "publicado")
    en_cola = sum(1 for _, r in conf if r["estado"] in EN_COLA)
    proxima = next((t for t, r in conf if r["estado"] in EN_COLA[:2]), None)

    dias = []  # (fecha, tarjetas, todo publicado)
    for t, r in conf:
        if not dias or t.date() != dias[-1][0]:
            dias.append((t.date(), [], True))
        dias[-1][1].append(tarjeta(r, t, horarios))
        if r["estado"] != "publicado":
            dias[-1] = (dias[-1][0], dias[-1][1], False)

    # "Hoy" y "Mañana" los pone el celular al abrir la pagina: asi no quedan viejos entre una corrida y otra
    def seccion(fecha, tarjetas):
        return f"""    <section class="dia">
      <h2>{dia_largo(fecha)}<span class="relativo" data-fecha="{fecha.isoformat()}"></span></h2>
{chr(10).join(tarjetas)}
    </section>"""
    # arriba lo que falta salir; los dias ya publicados completos van al final, plegados y del mas nuevo al mas viejo
    bloques = [seccion(f, ts) for f, ts, listo in dias if not listo]
    archivo = [(f, ts) for f, ts, listo in dias if listo][::-1]
    if archivo:
        n = sum(len(ts) for _, ts in archivo)
        bloques.append(f"""    <details class="archivo">
      <summary>Ya publicados<span class="relativo">{n} reels</span></summary>
{chr(10).join(seccion(f, ts) for f, ts in archivo)}
    </details>""")
    if sin_fecha:
        tarjetas = "\n".join(tarjeta(r, None, horarios) for r in sin_fecha)
        bloques.append(f"""    <section class="dia pendiente">
      <h2>Todavía sin fecha<span class="relativo">{len(sin_fecha)} videos</span></h2>
      <p class="nota">Ya están editados y con su copy. Se les asigna día y hora cuando corras el paso de programar.</p>
{tarjetas}
    </section>""")

    proxima_txt = (f"{dia_largo(proxima.date()).capitalize()} a las {hora_am_pm(proxima)}"
                   if proxima else "nada en cola")
    datos = dict(cuenta=html.escape(cuenta or "tu cuenta"), en_cola=en_cola, publicados=publicados,
                 sin_fecha=len(sin_fecha), proxima=html.escape(proxima_txt),
                 franjas=" · ".join(f"{a}–{b}" for a, b in horarios), bloques="\n".join(bloques))
    huella = hashlib.sha1(PAGINA.format(actualizado="", **datos).encode()).hexdigest()
    pagina = PAGINA.format(actualizado=f"{dia_largo(actualizado.date())}, {hora_am_pm(actualizado)}", **datos)
    return f"<!-- huella:{huella} -->\n{pagina}", huella


def huella_de(pagina):
    """La huella que quedo anotada en una pagina ya publicada ('' si no tiene)."""
    if pagina.startswith("<!-- huella:"):
        return pagina[12:pagina.index(" -->")]
    return ""


PAGINA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex">
<title>Cola de Reels</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Instrument+Sans:ital,wght@0,400;0,500;1,600&family=IBM+Plex+Mono:wght@500&display=swap">
<style>
  :root {{
    --ground: #eceef2;   --surface: #ffffff;  --ink: #11151b;
    --muted: #5d6673;    --line: #dbdfe7;     --accent: #d6455e;
    --ok: #1f7a5c;       --ok-bg: #e2f1ea;    --wait: #9c6410;
    --wait-bg: #f7ecd9;  --bad: #b42d2d;      --bad-bg: #f7e0df;
    --idle: #667080;     --idle-bg: #e6e9ef;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --ground: #0f1217;  --surface: #171b22;  --ink: #e7eaf0;
      --muted: #949dab;   --line: #252b34;     --accent: #f3667e;
      --ok: #59c79c;      --ok-bg: #16302a;    --wait: #e4a648;
      --wait-bg: #322718; --bad: #f08080;      --bad-bg: #331d1e;
      --idle: #8b95a3;    --idle-bg: #21262e;
    }}
  }}
  :root[data-theme="dark"] {{
    --ground: #0f1217;  --surface: #171b22;  --ink: #e7eaf0;
    --muted: #949dab;   --line: #252b34;     --accent: #f3667e;
    --ok: #59c79c;      --ok-bg: #16302a;    --wait: #e4a648;
    --wait-bg: #322718; --bad: #f08080;      --bad-bg: #331d1e;
    --idle: #8b95a3;    --idle-bg: #21262e;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--ground); color: var(--ink);
    font-family: "Instrument Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 15px; line-height: 1.5;
  }}
  img {{ max-width: 100%; }}
  .envoltorio {{ max-width: 620px; margin: 0 auto; padding: 0 16px; padding-block: 28px 56px; }}
  header {{ margin-bottom: 26px; }}
  .cuenta {{
    font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 12px;
    letter-spacing: .09em; text-transform: uppercase; color: var(--accent);
  }}
  h1 {{
    font-family: "Bricolage Grotesque", system-ui, sans-serif; font-weight: 800;
    font-size: clamp(30px, 8vw, 40px); line-height: 1.04; margin: 6px 0 14px;
    letter-spacing: -.02em; text-wrap: balance;
  }}
  .resumen {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }}
  .cifra {{
    background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
    padding: 9px 13px; display: flex; align-items: baseline; gap: 7px;
  }}
  .cifra b {{ font-family: "IBM Plex Mono", monospace; font-size: 19px; font-variant-numeric: tabular-nums; }}
  .cifra span {{ font-size: 12.5px; color: var(--muted); }}
  .meta {{ font-size: 13px; color: var(--muted); }}
  .meta strong {{ color: var(--ink); font-weight: 600; }}
  .dia {{ margin-top: 30px; }}
  .dia h2 {{
    font-family: "Bricolage Grotesque", system-ui, sans-serif; font-weight: 600; font-size: 15px;
    letter-spacing: .01em; margin: 0 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--line);
    display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
    position: sticky; top: env(safe-area-inset-top, 0px); background: var(--ground);
    padding-top: 8px; z-index: 2;
  }}
  .relativo {{
    font-family: "IBM Plex Mono", monospace; font-size: 11px; letter-spacing: .08em;
    text-transform: uppercase; color: var(--accent); font-weight: 500;
  }}
  .nota {{ font-size: 13px; color: var(--muted); margin: 0 0 14px; }}
  .reel {{
    display: flex; gap: 13px; background: var(--surface); border: 1px solid var(--line);
    border-radius: 14px; padding: 12px; margin-bottom: 10px;
  }}
  .thumb {{
    width: 62px; aspect-ratio: 9 / 16; object-fit: cover; border-radius: 8px;
    flex: none; background: var(--idle-bg); max-width: 100%;
  }}
  .thumb-vacio {{
    display: grid; place-items: center; font-size: 10px; color: var(--muted); text-align: center;
  }}
  .datos {{ min-width: 0; flex: 1; }}
  .cabecera {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 3px; }}
  .hora {{
    font-family: "IBM Plex Mono", monospace; font-size: 13px; font-variant-numeric: tabular-nums;
    color: var(--ink); font-weight: 500;
  }}
  .hora-vacia {{ color: var(--muted); }}
  .franja {{ font-size: 11.5px; color: var(--muted); }}
  .reel.propio {{ border: 2px solid var(--accent); }}
  .propio .franja {{ color: var(--accent); font-weight: 600; }}
  .pill {{
    margin-left: auto; font-size: 10.5px; font-weight: 600; letter-spacing: .05em;
    text-transform: uppercase; padding: 3px 8px; border-radius: 999px; white-space: nowrap;
  }}
  .ok {{ color: var(--ok); background: var(--ok-bg); }}
  .wait {{ color: var(--wait); background: var(--wait-bg); }}
  .bad {{ color: var(--bad); background: var(--bad-bg); }}
  .idle {{ color: var(--idle); background: var(--idle-bg); }}
  .reel h3 {{
    font-family: "Bricolage Grotesque", system-ui, sans-serif; font-weight: 600;
    font-size: 16px; line-height: 1.2; margin: 0 0 6px; letter-spacing: -.01em;
  }}
  .reel h3 em {{ font-style: italic; color: var(--accent); }}
  .copy {{ margin: 0 0 7px; font-size: 13.5px; color: var(--muted); overflow-wrap: anywhere; }}
  .pie {{ margin: 0; font-size: 11.5px; color: var(--muted); }}
  .num {{ font-family: "IBM Plex Mono", monospace; color: var(--ink); }}
  .archivo {{ margin-top: 34px; }}
  .archivo summary {{
    font-family: "Bricolage Grotesque", system-ui, sans-serif; font-weight: 600; font-size: 15px;
    cursor: pointer; padding: 12px 14px; background: var(--surface); border: 1px solid var(--line);
    border-radius: 12px; display: flex; justify-content: space-between; align-items: baseline;
    list-style: none;
  }}
  .archivo summary::-webkit-details-marker {{ display: none; }}
  .archivo summary::before {{ content: "▸"; margin-right: 8px; color: var(--muted); }}
  .archivo[open] summary::before {{ content: "▾"; }}
  .archivo summary .relativo {{ margin-left: auto; }}
  footer {{ margin-top: 34px; font-size: 12.5px; color: var(--muted); border-top: 1px solid var(--line); padding-top: 14px; }}
</style>
</head>
<body>
<div class="envoltorio">
  <header>
    <div class="cuenta">@{cuenta}</div>
    <h1>Lo que va a salir</h1>
    <div class="resumen">
      <div class="cifra"><b>{en_cola}</b><span>en cola</span></div>
      <div class="cifra"><b>{publicados}</b><span>publicados</span></div>
      <div class="cifra"><b>{sin_fecha}</b><span>sin fecha</span></div>
    </div>
    <p class="meta">Próxima publicación: <strong>{proxima}</strong><br>
    Se publican solos desde la nube, con la computadora apagada.</p>
  </header>
{bloques}
  <footer>
    Franjas de publicación: {franjas} · 3 reels por día.<br>
    Actualizado el {actualizado}. Se actualiza sola cada vez que la nube publica o reprograma un reel.
  </footer>
</div>
<script>
  (function () {{
    var d = new Date(), p = function (n) {{ return String(n).padStart(2, "0"); }};
    var hoy = d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
    d.setDate(d.getDate() + 1);
    var manana = d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
    document.querySelectorAll("[data-fecha]").forEach(function (el) {{
      el.textContent = el.dataset.fecha === hoy ? "Hoy" : el.dataset.fecha === manana ? "Mañana" : "";
    }});
  }})();
  // Se refresca sola: compara su huella con la publicada y, si hay una mas nueva, se recarga
  // saltando la cache del celular (al abrirla, al volver a la pestana y cada 2 minutos).
  (function () {{
    var c = document.firstChild, m = c && c.nodeType === 8 && /huella:(\\w+)/.exec(c.data);
    var mia = m ? m[1] : "";
    function revisar() {{
      fetch(location.pathname + "?t=" + Date.now(), {{ cache: "no-store" }})
        .then(function (r) {{ return r.ok ? r.text() : ""; }})
        .then(function (t) {{
          var n = /huella:(\\w+)/.exec(t);
          if (!n || n[1] === mia) return;
          try {{ if (sessionStorage.getItem("recargada") === n[1]) return; sessionStorage.setItem("recargada", n[1]); }} catch (e) {{}}
          location.replace(location.pathname + "?v=" + n[1]);
        }})
        .catch(function () {{}});
    }}
    revisar();
    setInterval(function () {{ if (!document.hidden) revisar(); }}, 120000);
    document.addEventListener("visibilitychange", function () {{ if (!document.hidden) revisar(); }});
  }})();
</script>
</body>
</html>
"""
