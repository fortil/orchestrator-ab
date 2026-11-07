#!/usr/bin/env python3
"""Arnés del A/B de orquestadores para un pipeline agéntico (tasky).

Compara la sesión que recibe /tasky (el orquestador) entre 4 brazos:
sonnet-medium, sonnet-low, haiku-medium, haiku-high. Los subagentes salen por
tasky-route con modelo y effort de la cascada, así que la única variable es el
modelo y el effort de la sesión.

Etapas:
  0  smoke          MODE=xs, headless, 1 rep por brazo. ¿Preflight + línea final?
  1  DECISION       MODE=xs, INTERACTIVO, 1 rep por brazo. Trigger: archivo
                    ajeno staged (the staged-file DECISION). Tú respondes.
  2  run completo   MODE=m,  headless, 3 reps por brazo.
  3  presión        MODE=l,  headless, 3 reps por brazo. Solo si la 2 pasa.

Subcomandos:
  brazos                                  lista los brazos
  preparar  --etapa N --brazo B [--rep R] crea el run (seed fresco + meta + comando)
  correr    --etapa N --brazo B [--rep R] prepara y lanza (headless: claude -p;
                                          etapa 1: imprime la instrucción interactiva)
  extraer   [--run ID | --todos]          transcript -> resultados/<run>.json + fila
  resumen   [--etapa N]                   tabla agregada de resultados/

Transcripts: ~/.claude/projects/<cwd-convertido-a-guiones>/*.jsonl (método del
transcript accounting (context per call = input + cache reads + cache writes)). El debug log de cada run queda en runs/<id>/debug.log
(lleva reglas allow con credenciales: NO pegarlo nunca; extraer solo lee la
línea de modo).
"""
import argparse, functools, json, os, pathlib, re, shutil, subprocess, sys, time

# el lote corre con stdout redirigido a archivo: sin flush el log parece muerto
print = functools.partial(print, flush=True)

ROOT = pathlib.Path(__file__).resolve().parent
SEED = ROOT / "seed"
RUNS = ROOT / "runs"
RESULTADOS = ROOT / "resultados"
BRIEFS = ROOT / "briefs"
PROJECTS = pathlib.Path.home() / ".claude" / "projects"

ARMS = {
    "sonnet-medium": {"model": "claude-sonnet-5-5", "effort": "medium"},
    "sonnet-low":    {"model": "claude-sonnet-5-5", "effort": "low"},
    "haiku-medium":  {"model": "claude-haiku-5-5",  "effort": "medium"},
    "haiku-high":    {"model": "claude-haiku-5-5",  "effort": "high"},
    # segunda ola (2026-11-06): Opus a efforts baratos
    "opus-low":      {"model": "claude-opus-5-5",   "effort": "low"},
    "opus-medium":   {"model": "claude-opus-5-5",   "effort": "medium"},
    # tercera ola (2026-11-07): completar la grilla de efforts
    "sonnet-high":   {"model": "claude-sonnet-5-5", "effort": "high"},
    "haiku-low":     {"model": "claude-haiku-5-5",  "effort": "low"},
}
STAGES = {
    0: {"nombre": "smoke",     "mode": "xs", "brief": "etapa0.md", "reps": 1, "headless": True},
    1: {"nombre": "decision",  "mode": "xs", "brief": "etapa1.md", "reps": 1, "headless": False},
    2: {"nombre": "completo",  "mode": "m",  "brief": "etapa2.md", "reps": 3, "headless": True},
    3: {"nombre": "presion",   "mode": "l",  "brief": "etapa3.md", "reps": 3, "headless": True},
}
# la respuesta humana fija de la etapa 1, la misma decisión que se dio a mano en
# los brazos de las olas 1 y 2 (sacar el archivo ajeno del stage y continuar)
ANSWER1 = ("Saca el archivo ajeno del stage con git restore --staged "
           "ajeno-otro-proyecto.txt y continúa la corrida.")
# el ALLOWED_TOOLS de /tasky preaprueba Bash solo en el turno de invocación; con
# auto mode el resto se clasifica solo. PR=false evita gh y remotes en el repo de prueba.
FLAGS = "PR=false NOTIFY=off"
# objetivos legítimos de Write/Edit del orquestador (documentos del run); lo demás
# que escriba el modelo de la sesión es sospecha de violación de rol
DOC_RE = re.compile(r"^(\.tasky/|PLAN[^/]*\.md$|EXECUTION_REPORT[^/]*\.md$|WORK_REVIEW[^/]*\.md$|CLAUDE\.md$|README\.md$|\.gitignore$)", re.I)


def run_id(etapa, brazo, rep):
    return f"e{etapa}-{brazo}-r{rep}"


def run_dir(rid):
    return RUNS / rid


def prompt_for(etapa, brazo, rep):
    st = STAGES[etapa]
    brief = (BRIEFS / st["brief"]).read_text().strip()
    return f"/tasky {brief} MODE={st['mode']} {FLAGS}"


def cmd_claude(meta, headless=True):
    args = ["claude"]
    if headless:
        args += ["-p", meta["prompt"]]
    args += ["--model", meta["model"], "--effort", meta["effort"],
             "--permission-mode", "auto", "--debug-file", str(run_dir(meta["run_id"]) / "debug.log")]
    return args


# ---------- preparar ----------

def preparar(etapa, brazo, rep):
    if brazo not in ARMS:
        sys.exit(f"brazo desconocido: {brazo} (usa: brazos)")
    st = STAGES[etapa]
    rid = run_id(etapa, brazo, rep)
    rd = run_dir(rid)
    if rd.exists():
        sys.exit(f"{rid} ya existe; borra runs/{rid} si quieres repetirlo")
    rd.mkdir(parents=True)
    # seed fresco
    dst = rd / "repo"
    shutil.copytree(SEED, dst)
    subprocess.run(["git", "init", "-q"], cwd=dst, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dst, check=True)
    subprocess.run(["git", "-c", "user.name=arnes", "-c", "user.email=arnes@test",
                    "commit", "-qm", "seed"], cwd=dst, check=True)
    # etapa 1: archivo ajeno staged, el trigger DECISION
    if etapa == 1:
        ajeno = dst / "ajeno-otro-proyecto.txt"
        ajeno.write_text("Este archivo viene de otro proyecto y no debe commitearse.\n")
        subprocess.run(["git", "add", "ajeno-otro-proyecto.txt"], cwd=dst, check=True)
    arm = ARMS[brazo]
    meta = {"run_id": rid, "etapa": etapa, "stage": st["nombre"], "brazo": brazo,
            "model": arm["model"], "effort": arm["effort"], "mode": st["mode"],
            "rep": rep, "headless": st["headless"], "prompt": prompt_for(etapa, brazo, rep),
            "creado": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (rd / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    args = cmd_claude(meta, headless=st["headless"])
    if st["headless"]:
        (rd / "comando.txt").write_text(" ".join(args) + "\n")
    print(f"OK preparado {rid} (MODE={st['mode']}, {arm['model']} @ {arm['effort']})")
    if st["headless"]:
        print(f"  lanzar con: arnes.py correr --etapa {etapa} --brazo {brazo} --rep {rep}")
    else:
        print(f"""  ETAPA 1 (interactiva): en una terminal, dentro de {dst}:
    1. lanza: {" ".join(args[:1])}   (sesión normal, sin -p)
    2. escribe: {meta["prompt"]}
    3. cuando emita la DECISION de los staged ajenos, respóndele una opción y deja terminar
    4. extrae con: arnes.py extraer --run {rid}""")
    return rd


# ---------- correr ----------

def hecho(rid):
    """Un run está hecho si ya tiene métricas extraídas (reanudable)."""
    return (RESULTADOS / f"{rid}.json").exists()


def correr(etapa, brazo=None, rep=1, todos=False, armas=None):
    st = STAGES[etapa]
    if todos:
        brazos = [b for b in ARMS if not armas or b in armas]
        pend = [(b, r) for b in brazos for r in range(1, st["reps"] + 1) if not hecho(run_id(etapa, b, r))]
        total = len(brazos) * st["reps"]
        print(f"ETAPA {etapa} ({st['nombre']}): {total} runs, {total - len(pend)} ya hechos, {len(pend)} por lanzar")
        for i, (b, r) in enumerate(pend, 1):
            rid = run_id(etapa, b, r)
            print(f"\n[{i}/{len(pend)}] {rid}  {time.strftime('%H:%M:%S')}")
            try:
                correr_uno(etapa, b, r)
            except KeyboardInterrupt:
                print(f"\ninterrumpido en {rid}; relanza el mismo comando para reanudar (los hechos se saltan)")
                raise
        print("\n== lote terminado ==")
        extraer_todos(etapa)
        resumen(etapa)
        notificar(f"Arnés: etapa {etapa} terminada", f"{total} runs, resultados en resultados/")
    else:
        correr_uno(etapa, brazo, rep)


def notificar(titulo, mensaje):
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{mensaje}" with title "{titulo}" sound name "Glass"'],
                       check=False, capture_output=True)
    except Exception:
        pass


def correr_uno(etapa, brazo, rep):
    st = STAGES[etapa]
    rid = run_id(etapa, brazo, rep)
    rd = run_dir(rid)
    if rd.exists() and not (rd / "meta.json").exists():
        # carpeta huérfana de un run interrumpido antes de prepararse: se borra y se repite
        print(f"{rid}: carpeta sin meta.json (run interrumpido); borrando y repitiendo")
        shutil.rmtree(rd)
    if not rd.exists():
        preparar(etapa, brazo, rep)
    meta = json.loads((rd / "meta.json").read_text())
    dst = rd / "repo"
    if etapa == 1:
        return correr_etapa1_auto(rid, rd, meta, dst)
    args = cmd_claude(meta, headless=True)
    t0 = time.time()
    print(f"lanzando {rid}: {' '.join(args[:4])} ...")
    p = subprocess.run(args, cwd=dst, capture_output=True, text=True)
    (rd / "salida.txt").write_text(p.stdout + ("\n[stderr]\n" + p.stderr if p.stderr else ""))
    dur = time.time() - t0
    print(f"terminado {rid} en {dur:.0f}s -> runs/{rid}/salida.txt")
    if re.search(r"hit your weekly limit|usage limit (reached|exceeded)", (p.stdout or "") + (p.stderr or ""), re.I):
        extraer_run(rid)
        print(f"{rid}: CUOTA AGOTADA (weekly limit). Detengo el lote; reanuda tras el reset con el mismo comando (los hechos se saltan).")
        sys.exit(3)
    extraer_run(rid)


def correr_etapa1_auto(rid, rd, meta, dst):
    """Etapa 1 sin humano: sesión multi-turno por stream-json; cuando el
    orquestador emite la DECISION del archivo ajeno, el arnés responde con la
    misma decisión fija que se dio a mano en las olas 1 y 2."""
    args = ["claude", "-p", "--verbose",
            "--input-format", "stream-json", "--output-format", "stream-json",
            "--model", meta["model"], "--effort", meta["effort"],
            "--permission-mode", "auto",
            "--debug-file", str(rd / "debug.log")]
    t0 = time.time()
    print(f"lanzando {rid} (etapa 1 AUTO, responde la DECISION sola) ...")
    proc = subprocess.Popen(args, cwd=dst, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _send(texto):
        proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user",
            "content": [{"type": "text", "text": texto}]}}) + "\n")
        proc.stdin.flush()

    _send(meta["prompt"])
    respuestas, lineas = 0, []
    for line in proc.stdout:
        lineas.append(line)
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for b in (ev.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "text" \
                        and (b.get("text") or "").strip().startswith("DECISION"):
                    print(f"  DECISION detectada en {rid}; respondiendo la decisión fija")
                    _send(ANSWER1)
                    respuestas += 1
        elif ev.get("type") == "result":
            break
    try:
        proc.stdin.close()
    except Exception:
        pass
    proc.wait()
    (rd / "salida.txt").write_text("".join(lineas)
                                   + ("\n[stderr]\n" + proc.stderr.read() if proc.stderr else ""))
    (rd / "respuestas.txt").write_text(f"{respuestas}\n")
    dur = time.time() - t0
    print(f"terminado {rid} en {dur:.0f}s ({respuestas} DECISION respondida(s)) -> runs/{rid}/salida.txt")
    extraer_run(rid)


# ---------- extraer ----------

def transcript_dir(rd):
    # ~/.claude/projects codifica el cwd con "/" -> "-" y conserva el guion inicial
    absrepo = str((rd / "repo").resolve())
    return PROJECTS / absrepo.replace("/", "-")


def find_transcript(rd):
    """El transcript del orquestador: el que abre con /tasky. El mismo dir
    recibe también los transcripts de los subagentes (claude-run), que abren
    con 'TASK: ...' y no llevan el marcador del comando."""
    d = transcript_dir(rd)
    if not d.exists():
        return None
    for f in sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(f) as fh:
                head = fh.read(200_000)
            if "/tasky" in head:
                return f
        except OSError:
            continue
    return None


def extraer_run(rid):
    rd = run_dir(rid)
    if not (rd / "meta.json").exists():
        sys.exit(f"no existe runs/{rid}/meta.json")
    meta = json.loads((rd / "meta.json").read_text())
    tx = find_transcript(rd)
    if not tx:
        sys.exit(f"sin transcript de orquestador para {rid} en {transcript_dir(rd)}")
    eventos = []
    for line in tx.read_text().splitlines():
        try:
            eventos.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    model_prefix = meta["model"]
    m = {"run_id": rid, "brazo": meta["brazo"], "etapa": meta["etapa"], "rep": meta["rep"],
         "transcript": str(tx), "eventos": len(eventos)}
    finish, decisions, errors, narrative = None, 0, [], 0
    ses_tools, ses_writes, ses_tokens = {}, [], {"in": 0, "cache_r": 0, "cache_w": 0, "out": 0}
    peak = 0
    route_lines, denegados = [], 0
    t_first = t_last = None
    prev_had_tool = False
    for ev in eventos:
        ts = ev.get("timestamp")
        if ts:
            t_first = t_first or ts
            t_last = ts
        msg = ev.get("message") or {}
        es_sesion = str(msg.get("model", "")).startswith(model_prefix)
        content = msg.get("content") or []
        if not isinstance(content, list):
            continue
        tools_en_ev = 0
        for blk in content:
            if not isinstance(blk, dict):
                continue
            bt = blk.get("type")
            if bt == "tool_use":
                tools_en_ev += 1
                if es_sesion:
                    name = blk.get("name", "?")
                    ses_tools[name] = ses_tools.get(name, 0) + 1
                    inp = blk.get("input") or {}
                    if name in ("Write", "Edit"):
                        target = str(inp.get("file_path") or inp.get("notebook_path") or "")
                        ses_writes.append(target)
            elif bt == "text":
                txt = (blk.get("text") or "").strip()
                if not txt:
                    continue
                if es_sesion:
                    if txt.startswith("DECISION:"):
                        decisions += 1
                    elif txt.startswith("ERROR:"):
                        errors.append({"respaldado": prev_had_tool or tools_en_ev > 0, "texto": txt[:120]})
                    elif re.match(r"^(COMPLETED|FAILED|PLANNED)\b", txt):
                        finish = txt[:160]
                    elif len(txt) > 80:
                        narrative += 1
            elif bt == "tool_result":
                blob = json.dumps(blk.get("content"), ensure_ascii=False)
                for mo in re.finditer(r"ROUTE: [^\n\\\"]{0,90}", blob):
                    route_lines.append(mo.group(0))
                if re.search(r"denied|permission required|approval", blob, re.I):
                    denegados += 1
        if es_sesion:
            u = msg.get("usage") or {}
            ci = u.get("cache_creation") or {}
            tot = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                   + ci.get("ephemeral_5m_input_tokens", 0) + ci.get("ephemeral_1h_input_tokens", 0))
            peak = max(peak, tot)
            ses_tokens["in"] += u.get("input_tokens", 0)
            ses_tokens["cache_r"] += u.get("cache_read_input_tokens", 0)
            ses_tokens["cache_w"] += ci.get("ephemeral_5m_input_tokens", 0) + ci.get("ephemeral_1h_input_tokens", 0)
            ses_tokens["out"] += u.get("output_tokens", 0)
        prev_had_tool = tools_en_ev > 0
    writes_sospechosas = [w for w in ses_writes if not DOC_RE.match(str(pathlib.PurePosixPath(w.replace("\\", "/")).name)) and ".tasky/" not in w]
    m.update({
        "fin": (finish.split("—")[0].strip() if finish else ("DECISION" if decisions and not finish else "sin-linea")),
        # bypass: terminó sin pasar por el pipeline (sin rutas y sin subagentes);
        # el revisor lo confirma con linea_final ("hice el trabajo directamente...")
        "bypass": (finish is not None and not route_lines
                   and not any(k.lower() == "agent" for k in ses_tools)),
        "linea_final": finish, "decisiones": decisions,
        "errores": len(errors), "errores_sin_respaldo": sum(1 for e in errors if not e["respaldado"]),
        "errores_txt": [e["texto"] for e in errors][:5],
        "narracion": narrative,
        "sesion_tool_use": ses_tools, "sesion_writes": ses_writes[:12],
        "writes_sospechosas": writes_sospechosas[:8],
        "route_lines": len(route_lines), "route_muestra": route_lines[:6],
        "denegados": denegados,
        "tokens": ses_tokens, "pico_contexto": peak,
    })
    # duración desde los timestamps ISO
    if t_first and t_last:
        from datetime import datetime
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                m["duracion_s"] = round((datetime.strptime(t_last, fmt) - datetime.strptime(t_first, fmt)).total_seconds(), 1)
                break
            except ValueError:
                continue
    RESULTADOS.mkdir(exist_ok=True)
    out = RESULTADOS / f"{rid}.json"
    out.write_text(json.dumps(m, ensure_ascii=False, indent=1))
    print(fila(m))
    return m


def fila(m):
    tok = m["tokens"]
    return (f"{m['run_id']:<22} fin={m['fin']:<9} err={m['errores']}({m['errores_sin_respaldo']} sin respaldo) "
            f"dec={m['decisiones']} narr={m['narracion']} tools={sum(m['sesion_tool_use'].values()):<4} "
            f"sospecha={len(m['writes_sospechosas'])} pico={m['pico_contexto']//1000}K "
            f"tok_in={tok['in']//1000}K cache_r={tok['cache_r']//1000}K out={tok['out']//1000}")


def extraer_todos(etapa=None):
    for p in sorted(RUNS.glob("*/meta.json")):
        meta = json.loads(p.read_text())
        if etapa is None or meta["etapa"] == etapa:
            try:
                extraer_run(meta["run_id"])
            except SystemExit as e:
                print(f"  (sin extraer {meta['run_id']}: {e})")


# ---------- resumen ----------

def resumen(etapa=None):
    files = sorted(RESULTADOS.glob("*.json"))
    rows = [json.loads(p.read_text()) for p in files]
    if etapa is not None:
        rows = [r for r in rows if r["etapa"] == etapa]
    if not rows:
        print("sin resultados")
        return
    print(f"{'run':<22} {'brazo':<15} fin        err(sinR) dec narr tools sospecha pico  cache_r")
    for r in rows:
        t = r["tokens"]
        print(f"{r['run_id']:<22} {r['brazo']:<15} {r['fin']:<10} {r['errores']}({r['errores_sin_respaldo']})     {r['decisiones']:<3} {r['narracion']:<4} {sum(r['sesion_tool_use'].values()):<5} {len(r['writes_sospechosas']):<8} {r['pico_contexto']//1000}K   {t['cache_r']//1000}K")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("brazos")
    p = sub.add_parser("preparar"); p.add_argument("--etapa", type=int, required=True, choices=STAGES); p.add_argument("--brazo", required=True); p.add_argument("--rep", type=int, default=1)
    p = sub.add_parser("correr");   p.add_argument("--etapa", type=int, required=True, choices=STAGES)
    p.add_argument("--brazo"); p.add_argument("--rep", type=int, default=1)
    p.add_argument("--todos", action="store_true", help="lanza en secuencia todos los runs de la etapa que falten")
    p.add_argument("--armas", help="con --todos: subconjunto separado por comas (p. ej. haiku-medium,haiku-high)")
    p = sub.add_parser("extraer");  p.add_argument("--run"); p.add_argument("--todos", action="store_true"); p.add_argument("--etapa", type=int)
    p = sub.add_parser("resumen");  p.add_argument("--etapa", type=int)
    a = ap.parse_args()
    if a.cmd == "brazos":
        for k, v in ARMS.items():
            print(f"{k:<16} {v['model']}  effort={v['effort']}")
    elif a.cmd == "preparar":
        preparar(a.etapa, a.brazo, a.rep)
    elif a.cmd == "correr":
        armas = set(a.armas.split(",")) if a.armas else None
        if not a.todos and not a.brazo:
            sys.exit("usa --brazo B o --todos")
        correr(a.etapa, a.brazo, a.rep, todos=a.todos, armas=armas)
    elif a.cmd == "extraer":
        if a.todos:
            extraer_todos(a.etapa)
        elif a.run:
            extraer_run(a.run)
        else:
            sys.exit("usa --run ID o --todos")
    elif a.cmd == "resumen":
        resumen(a.etapa)


if __name__ == "__main__":
    main()
