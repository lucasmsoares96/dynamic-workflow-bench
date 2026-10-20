#!/usr/bin/env python3
"""Benchmark de consumo de tokens: A (agente direto) vs B (dynamic workflow) vs C (Agent sem workflow).

Uso:  python3 bench.py [--tests t1] [--models haiku,deepseek,gemini] [--reps 3]
      python3 bench.py --selftest | --dry-run | --usage-db PATH | --base-url URL

O projeto de teste fica pronto em project/ (uv init, nao e criado aqui); o bench
so roda a matriz e grava results/<timestamp>/. Depende apenas de `claude` no PATH e
do CLIProxyAPI (padrao http://127.0.0.1:8317). Somente stdlib.

CENARIOS (mesma tarefa nos tres; o que muda e quem faz o trabalho)
  A: `claude -p --agent bench-researcher <tarefa>`. O agente e a THREAD PRINCIPAL:
     nao ha orquestrador nem subagente. Mede o trabalho puro em um contexto unico.
  B: `claude -p "/bench-t1 <tarefa>"`. Thread principal PADRAO (sem --agent), que
     chama o Workflow bench-t1; o workflow dispara bench-researcher como SUBAGENTE.
  C: thread principal PADRAO (sem --agent), sem workflow, que delega UMA vez ao
     MESMO subagente pela ferramenta Agent e devolve o resultado dele.

  Texto exato enviado em cada cenario (t1; <tarefa> = TESTS["t1"]["prompt"], identico nos tres):
    A: "<tarefa>"
    B: "/bench-t1 <tarefa>"      (o workflow repassa <tarefa> ao subagente; prompt inalterado)
    C: "<tarefa>" + DELEGATE_C, sendo DELEGATE_C exatamente (dois newlines no inicio):
       '\\n\\nDo not do this work yourself. Use the Agent tool exactly once with subagent_type
       "bench-researcher", passing the task above verbatim, and return the subagent's result unchanged.'
       (o marcador de nova linha acima e escape literal: o texto real tem duas quebras antes de "Do".)
  Ou seja, B e C diferem so no mecanismo (Workflow vs Agent); C acrescenta ao enunciado
  apenas a instrucao de delegar, para que a thread principal nao faca o servico sozinha.

  Por que C: na execucao 20261020_061632, as chamadas do subagente dentro de B custavam o
  mesmo que o A inteiro; 78%-90% do total de B vinha de chamadas grandes da thread principal
  (12-23 mil tokens de input), intercaladas com as do subagente a cada 2-3 s. A vs B mede,
  portanto, o custo de TER um orquestrador, nao o custo do workflow. C isola o workflow:
  B vs C mede o que o dynamic workflow custa a mais que delegar ao mesmo subagente.

FERRAMENTAS (--tools declarado explicitamente nos tres; --allowedTools so da permissao)
  A: --tools=Read,Grep,Glob,StructuredOutput   --allowedTools=Read,Grep,Glob
  B: --tools=Agent,Workflow,StructuredOutput,Read,Grep,Glob   --allowedTools=Workflow,Agent
  C: --tools=Agent,Workflow,StructuredOutput,Read,Grep,Glob   --allowedTools=Agent
  Sondas de haiku que fixaram isso:
    - `--tools` e variadico como `--allowedTools`: `--tools A,B <prompt>` engole o prompt
      ("Input must be provided either through stdin or as a prompt argument"). Usar `--tools=`.
    - `--tools` restringe TAMBEM o subagente: sem Read,Grep,Glob na lista, bench-researcher
      falha com as ferramentas de busca negadas (subagent failed=1). Por isso Read,Grep,Glob
      entram nos dois (B e C), simetricos; quem impede a thread principal de fazer o trabalho
      sozinha e o --allowedTools (sem Read/Grep/Glob), nao a ausencia da definicao.
    - `--allowedTools=Agent` (C) e `--allowedTools=Workflow,Agent` (B): o subagente continua
      com Read,Grep,Glob do proprio frontmatter (permissao herdada do agente, nao da thread
      principal) e devolve o resultado correto. A thread principal, se tentar Read/Grep/Glob,
      recebe negacao.
    - `--tools=Agent` expoe a ferramenta interna "Task" (nome exibido no init do stream-json)
      e e o que faz o spawn do bench-researcher funcionar.

COMO SE VERIFICA A DELEGACAO (sinal de "nao delegou")
  Para B e C a execucao e marcada INVALIDA ("nao delegou") quando nao ha evidencia de que o
  subagente rodou. Dois sinais, basta um:
    1) `subagent_stats.spawned >= 1` no JSON de saida do claude. E exato, mas so enxerga o
       spawn feito pela ferramenta Agent: no B o agente do workflow roda numa session-task
       (campo `origin`), fora dessa contagem (spawned=0 mesmo delegando).
    2) Duas faixas de input nas linhas do usage.db: min(input) * 2 <= max(input). O subagente
       carrega um contexto bem menor (4-6 mil tokens) que a thread principal (9-23 mil, com as
       definicoes de ferramentas e o prompt do workflow), entao a execucao que delegou tem
       necessariamente uma chamada pequena ao lado de uma grande.
  Medido nas sondas (haiku, t1): A 3.806..5.219 (uma faixa); C 4.197..10.378 (duas);
  B 4.423..23.274 (duas); thread principal sem delegar 6.777..8.240 (uma faixa -> invalida).
  LIMITES do criterio: (a) se o contexto do subagente crescer ate mais da metade do da thread
  principal, o sinal 2 pode falhar por baixo (falso "nao delegou"); (b) se a thread principal
  tiver chamadas de tamanhos muito dispares (ex.: compactacao no meio), o sinal 2 pode passar
  por alto (falso "delegou"). O sinal 1 e o forte quando existe; o 2 cobre o B.

CONFIRMADO empiricamente (claude 2.1.304, sondas de haiku, 1 tentativa cada):
  - sem --agent + --json-schema: JSON traz `structured_output` (dict).
  - --agent bench-researcher (tools Read,Grep,Glob) + --json-schema: SEM `structured_output`;
    a resposta vem em texto livre (tabela) em `result`.
  - mesmo agente com `StructuredOutput` acrescentado em `tools:` -> `structured_output` volta.
    Causa: a restricao de tools do agente exclui a ferramenta de saida estruturada.
    O ajuste (StructuredOutput na lista de tools) esta no agente usado por A, B e C (simetrico).
  - `--allowedTools a,b <prompt>` engole o prompt (flag variadica): usa-se --allowedTools=a,b.
  - sem stdin redirecionado o claude espera 3s: usa-se stdin=DEVNULL.
  - mode=ro em banco WAL sem -wal/-shm funcionou num banco temporario (cria -shm/-wal se o
    diretorio for gravavel); no diretorio real do proxy pode falhar -> retries e snapshot.
  - input_tokens inclui cache_read (total = input + output); input nao cacheado = input - cache_read.
HIPOTESE (nao confirmada): nenhuma pendente; o extrator cai para JSON no texto de `result`
  nos tres cenarios se structured_output faltar.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import platform
import shutil
import signal
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE / "project"
RESULTS = HERE / "results"
DEFAULT_DB = Path.home() / "Library/Application Support/com.cpa.gui/usage-records/usage.db"
DEFAULT_URL = "http://127.0.0.1:8317"
MODELS = {"haiku": "claude-haiku-5-5", "deepseek": "deepseek-v4.1-flash", "gemini": "gemini-3.8-flash-high"}
AGENT = "bench-researcher"
SETTINGS_B = '{"enableWorkflows": true, "skipWorkflowUsageWarning": true}'
SCENS = "ABC"
# mesma definicao de ferramentas nas duas threads que podem delegar (B e C); ver cabecalho
TOOLS_MAIN = "Agent,Workflow,StructuredOutput,Read,Grep,Glob"
ALLOWED = {"A": "Read,Grep,Glob", "B": "Workflow,Agent", "C": "Agent"}
TOOLS = {"A": "Read,Grep,Glob,StructuredOutput", "B": TOOLS_MAIN, "C": TOOLS_MAIN}
# texto adicional de C (unico diferencial do enunciado); B acrescenta apenas "/<workflow> "
DELEGATE_C = ('\n\nDo not do this work yourself. Use the Agent tool exactly once with '
              'subagent_type "bench-researcher", passing the task above verbatim, and return the '
              "subagent's result unchanged.")

# ----------------------------------------------------------------- testes (adicionar = acrescentar entrada)
# O projeto de teste (project/) ja existe pronto; aqui so se aponta para arquivos dele.

TESTS = {
    "t1": {
        "name": "t1",
        "descricao": "leitura simples: listar AGENTS.md com primeiro heading",
        "prompt": (
            "List every file named AGENTS.md in this project, ignoring anything under node_modules. "
            "For each give its path relative to the project root (forward slashes) and the text of its "
            "first Markdown heading (without the leading # characters; skip any YAML frontmatter and "
            "any text before the heading). Return count and files."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "files": {"type": "array", "items": {"type": "object",
                          "properties": {"path": {"type": "string"}, "heading": {"type": "string"}},
                          "required": ["path", "heading"]}},
            },
            "required": ["count", "files"],
        },
        "expected": "expected_t1.json",
        "workflow": "bench-t1",
        # A: agente direto; B: workflow pre-montado; C: thread principal delegando pela ferramenta Agent
        "cmd_a": lambda t: ["--agent", AGENT, t["prompt"]],
        "cmd_b": lambda t: [f"/{t['workflow']} {t['prompt']}"],
        "cmd_c": lambda t: [t["prompt"] + DELEGATE_C],
    },
}


def normalize(x):
    try:
        files = sorted((str(f["path"]).lstrip("./") if str(f["path"]).startswith("./") else str(f["path"]),
                        str(f["heading"]).strip()) for f in x["files"])
        return {"count": int(x["count"]), "files": files}
    except Exception:
        return None


def diff_norm(a, b):
    if a is None or b is None:
        return "resultado ausente/ilegivel"
    out = []
    if a["count"] != b["count"]:
        out.append(f"count {a['count']} != {b['count']}")
    sa, sb = set(a["files"]), set(b["files"])
    for f in sorted(sa - sb):
        out.append(f"so em 1o: {f}")
    for f in sorted(sb - sa):
        out.append(f"so em 2o: {f}")
    return "; ".join(out)


# ----------------------------------------------------------------- extracao de resultado

def parse_json_text(text):
    dec = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            obj, _ = dec.raw_decode(text[i:])
            if isinstance(obj, dict) and "files" in obj:
                return obj
            if isinstance(obj, dict):
                for v in obj.values():  # ex.: {"result": {...}} do workflow
                    if isinstance(v, dict) and "files" in v:
                        return v
        except ValueError:
            pass
        i = text.find("{", i + 1)
    return None


def extract(out):
    """Mesmo parser nos dois cenarios: structured_output se vier, senao JSON no texto de result."""
    so = out.get("structured_output")
    if isinstance(so, dict):
        if "files" not in so:
            inner = next((v for v in so.values() if isinstance(v, dict) and "files" in v), None)
            so = inner or so
        return so, "structured_output"
    res = out.get("result")
    if isinstance(res, dict):
        return res, "result(dict)"
    if isinstance(res, str):
        p = parse_json_text(res)
        if p is not None:
            return p, "texto"
    return None, "nenhum"


# ----------------------------------------------------------------- ambiente / comandos

def read_token():
    t = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if t:
        return t
    try:
        return json.loads((Path.home() / ".claude/settings.json").read_text())["env"]["ANTHROPIC_AUTH_TOKEN"]
    except Exception:
        return None


def build_env(base_url, token, model_id, ua):
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    for k in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ATTENDED",
              "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_EXECPATH",
              "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(k, None)  # variaveis da sessao interativa que nos lancou
    env.update({
        "ANTHROPIC_BASE_URL": base_url,
        "CLAUDE_CODE_SUBAGENT_MODEL": "inherit",
        "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1",
        "CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL": model_id,
        "CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS": "1",
        "ANTHROPIC_CUSTOM_HEADERS": f"User-Agent: {ua}",
    })
    if token:
        env["ANTHROPIC_AUTH_TOKEN"] = token
    return env


def build_cmd(test, scen, model_id):
    cmd = ["claude", "-p", "--output-format", "json", "--setting-sources", "project", "--strict-mcp-config",
           "--model", model_id, "--append-system-prompt", " ",
           "--json-schema", json.dumps(test["schema"]), "--permission-prompts", "none",
           f"--tools={TOOLS[scen]}", f"--allowedTools={ALLOWED[scen]}"]
    if scen == "B":
        cmd += ["--settings", SETTINGS_B]
    return cmd + {"A": test["cmd_a"], "B": test["cmd_b"], "C": test["cmd_c"]}[scen](test)


def mask_env(env):
    return {k: ("***" if any(s in k for s in ("TOKEN", "KEY", "SECRET")) else v) for k, v in env.items()
            if k.startswith(("ANTHROPIC", "CLAUDE_CODE"))}


# ----------------------------------------------------------------- leitura do banco

def copy_snapshot(src: Path, tmpdir: Path) -> Path:
    dst = tmpdir / src.name
    shutil.copyfile(src, dst)
    for suf in ("-wal", "-shm"):
        s = src.with_name(src.name + suf)
        d = dst.with_name(dst.name + suf)
        if s.exists():
            shutil.copyfile(s, d)
        else:
            d.touch()  # vazio, SO na copia
    return dst


class UsageDB:
    """Leitor somente-leitura: mode=ro com repeticoes; ultimo recurso, snapshot da copia."""

    def __init__(self, path: Path, retries=5):
        # retries=0 forca o caminho do snapshot (usado no selftest)
        self.path, self.retries, self.snapshots = Path(path), retries, 0

    def query(self, sql, params=()):
        err = None
        for i in range(self.retries):
            try:
                c = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)
                try:
                    return c.execute(sql, params).fetchall()
                finally:
                    c.close()
            except sqlite3.OperationalError as e:
                err = e
                time.sleep(0.3)
        # ponytail: copia o banco inteiro a cada consulta neste caminho; so ocorre se mode=ro falhar sempre
        self.snapshots += 1
        with tempfile.TemporaryDirectory() as td:
            snap = copy_snapshot(self.path, Path(td))
            c = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
            try:
                return c.execute(sql, params).fetchall()
            except sqlite3.Error as e:
                raise RuntimeError(f"banco ilegivel ({err}; snapshot: {e})")
            finally:
                c.close()

    def rows_for(self, ua, since_ms):
        return self.query(
            "SELECT id, timestamp_ms, model, input_tokens, output_tokens, cache_read_tokens, total_tokens, "
            "failed, failure_status, cache_creation_tokens FROM usage_events "
            "WHERE timestamp_ms >= ? AND user_agent LIKE ? ORDER BY id",
            (since_ms, f"%{ua}%"))


def aggregate(rows):
    """rows: (id, ts_ms, model, in, out, cache_read, total, failed, status, cache_creation)."""
    a = {"n": len(rows), "total": 0, "uncached": 0, "completion": 0, "cache_read": 0,
         "cache_creation": 0, "fail_total": 0, "fail_n": 0, "models": {}, "first_ms": None,
         "last_ms": None, "inputs": []}
    for _id, ts, model, i, o, cr, t, failed, st, cc in rows:
        a["total"] += t or 0
        a["uncached"] += (i or 0) - (cr or 0)
        a["completion"] += o or 0
        a["cache_read"] += cr or 0
        a["cache_creation"] += cc or 0
        a["inputs"].append(i or 0)
        a["models"][model] = a["models"].get(model, 0) + 1
        if failed or (st or 0) == 499 or (st or 0) >= 500:
            a["fail_total"] += t or 0
            a["fail_n"] += 1
        a["first_ms"] = ts if a["first_ms"] is None else min(a["first_ms"], ts)
        a["last_ms"] = ts if a["last_ms"] is None else max(a["last_ms"], ts)
    return a


def wait_stable(count_fn, stable_s=10, max_s=90, poll=2.0, sleep=time.sleep, clock=time.monotonic):
    """Espera a contagem ficar estavel por stable_s (maximo max_s). Retorna (contagem, estavel?)."""
    start = clock()
    last, since = count_fn(), clock()
    while clock() - start < max_s:
        sleep(poll)
        n = count_fn()
        if n != last:
            last, since = n, clock()
        elif clock() - since >= stable_s:
            return last, True
    return last, False


# ----------------------------------------------------------------- execucao

CURRENT = {"p": None}  # filho `claude` em andamento (grupo proprio, start_new_session)


def kill_current():
    p, CURRENT["p"] = CURRENT["p"], None
    if p is None or p.poll() is not None:
        return
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 10)):
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError:
            return
        try:
            p.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            pass

def run_one(test, scen, model_key, rep, args, token, db):
    model_id = MODELS[model_key]
    ua = f"bench-{uuid.uuid4()}"
    run = {"uuid": ua, "test": test["name"], "rep": rep, "scen": scen, "model_key": model_key,
           "model": model_id, "invalid": [], "wall": None, "agg": None, "extract": None,
           "correct": None, "result_norm": None, "num_turns": None, "terminal_reason": None,
           "keys": None, "sleep": False, "stable": None, "delegated": None}
    cmd = build_cmd(test, scen, model_id)
    env = build_env(args.base_url, token, model_id, ua)
    since_ms = int(time.time() * 1000) - 2000
    t0 = time.monotonic()
    out = None
    p = CURRENT["p"] = subprocess.Popen(cmd, cwd=args.project, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        so, se = p.communicate(timeout=args.timeout)
        run["exit"] = p.returncode
        if p.returncode != 0:
            run["invalid"].append(f"exit {p.returncode}: {se.strip()[-200:]}")
        try:
            out = json.loads(so)
        except ValueError:
            run["invalid"].append(f"stdout nao-JSON: {so.strip()[:200]!r}")
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        run["invalid"].append(f"timeout {args.timeout}s")
    CURRENT["p"] = None
    run["wall"] = time.monotonic() - t0
    if isinstance(out, dict):
        run["keys"] = sorted(out.keys())
        run["num_turns"], run["terminal_reason"] = out.get("num_turns"), out.get("terminal_reason")
        run["spawned"] = (out.get("subagent_stats") or {}).get("spawned")
        if out.get("is_error"):
            run["invalid"].append(f"is_error: {str(out.get('result'))[:150]}")
        obj, src = extract(out)
        run["extract"] = src
        run["result_norm"] = normalize(obj) if obj is not None else None
        run["result_excerpt"] = str(out.get("result"))[:300]
    # atribuicao no banco
    try:
        count = lambda: len(db.rows_for(ua, since_ms))
        _, run["stable"] = wait_stable(count, args.stable, args.max_wait)
        rows = db.rows_for(ua, since_ms)
        agg = run["agg"] = aggregate(rows)
        if agg["n"] == 0:
            run["invalid"].append("nenhuma linha no banco")
        wrong = {m: n for m, n in agg["models"].items() if m != model_id}
        if wrong:
            run["invalid"].append(f"modelo(s) diferente(s) do pedido {model_id}: {wrong}")
        if not run["stable"]:
            run["invalid"].append("contagem de linhas nao estabilizou")
        if agg["n"] and run["wall"] - (agg["last_ms"] - agg["first_ms"]) / 1000 > args.sleep_slack:
            run["sleep"] = True
        if scen in "BC" and agg["n"]:
            run["delegated"], why = delegated(agg, run.get("spawned"))
            run["delegation_evidence"] = why
            if not run["delegated"]:
                run["invalid"].append(f"nao delegou: {why}")
    except Exception as e:
        run["invalid"].append(f"erro lendo banco: {e}")
    return run


def delegated(agg, spawned):
    """Evidencia de que o subagente rodou (criterio e limites no cabecalho). Retorna (bool, motivo)."""
    if spawned:
        return True, f"subagent_stats.spawned={spawned}"
    ins = [x for x in agg["inputs"] if x > 0]
    if len(ins) >= 2 and min(ins) * 2 <= max(ins):
        return True, f"duas faixas de input {min(ins)}..{max(ins)}"
    return False, (f"sem subagent_stats.spawned e sem duas faixas de input "
                   f"({min(ins) if ins else 0}..{max(ins) if ins else 0})")


def run_status(r):
    return "INVALIDA" if r["invalid"] else "ok"


def precheck(args, token, models):
    if not shutil.which("claude"):
        sys.exit("ERRO: `claude` nao encontrado no PATH.")
    if not token:
        sys.exit("ERRO: ANTHROPIC_AUTH_TOKEN nao esta no ambiente nem em ~/.claude/settings.json (env).")
    try:
        req = urllib.request.Request(args.base_url + "/v1/models", headers={"Authorization": f"Bearer {token}"})
        ids = {m["id"] for m in json.load(urllib.request.urlopen(req, timeout=10))["data"]}
    except Exception as e:
        sys.exit(f"ERRO: proxy nao respondeu GET {args.base_url}/v1/models: {e}")
    missing = [MODELS[m] for m in models if MODELS[m] not in ids]
    if missing:
        sys.exit(f"ERRO: modelos ausentes na lista do proxy: {missing}")
    try:
        UsageDB(args.usage_db).query("SELECT 1 FROM usage_events LIMIT 1")
    except Exception as e:  # nao falha duro: o leitor tem fallback por snapshot
        print(f"AVISO: leitura direta do banco falhou ({e}); sera usado snapshot se necessario.", flush=True)


# ----------------------------------------------------------------- relatorio

def med(v):
    return statistics.median(v) if v else None


def pct(b, a):
    return None if not a else (b - a) / a * 100


def fmt(x, p=False):
    if x is None:
        return "-"
    return f"{x:+.1f}%" if p else (f"{x:,.1f}" if isinstance(x, float) and x % 1 else f"{x:,.0f}").replace(",", ".")


def stat_line(runs, key):
    v = [r["agg"][key] if key != "wall" else r["wall"] for r in runs]
    return med(v), (min(v) if v else None), (max(v) if v else None)


def usable(r, require_correct):
    return not r["invalid"] and r["agg"] and (not require_correct or r["correct"])


def sums(rs, scen):
    """Soma as parcelas das execucoes validas de um cenario (consumo real, falhas incluidas)."""
    out = {k: 0 for k in ("total", "uncached", "cache_read", "cache_creation", "completion")}
    out["calls"] = 0
    for r in rs:
        if r["scen"] != scen or r["invalid"] or not r["agg"]:
            continue
        for k in out:
            out[k] += r["agg"]["n"] if k == "calls" else r["agg"][k]
    return out


METRICS = (("uncached", "input nao cacheado"), ("cache_read", "cache_read"),
           ("cache_creation", "cache_creation"), ("completion", "output"),
           ("total", "total"), ("n", "chamadas"), ("wall", "duracao s"))


def make_report(runs, meta):
    L = []
    w = L.append
    w("=" * 100)
    w("BENCHMARK DE TOKENS: A (agente direto) x B (dynamic workflow) x C (Agent, sem workflow)")
    w("=" * 100)
    if meta.get("partial"):
        w(f"*** RELATORIO PARCIAL: {len(runs)} de {meta['total']} execucoes concluidas"
          + (f"; interrompida (fora das estatisticas): {meta['interrupted']}" if meta.get("interrupted") else "") + " ***")
    w(f"Data: {meta['date']}   claude: {meta['claude']}   proxy: {meta['base_url']}")
    w(f"Modelos: {', '.join(f'{k}={MODELS[k]}' for k in meta['models'])}   reps: {meta['reps']}   testes: {', '.join(meta['tests'])}")
    w("Cenarios (mesma tarefa; muda quem faz o trabalho):")
    w("  A = thread principal E subagente (--agent bench-researcher); nao ha orquestrador.")
    w("  B = thread principal padrao -> Workflow /bench-t1 -> subagente bench-researcher.")
    w("  C = thread principal padrao -> ferramenta Agent -> MESMO subagente; sem workflow.")
    w("Isolamento: --setting-sources project, --strict-mcp-config, --append-system-prompt ' ', --permission-prompts none, "
      "cwd = project/; env SUBAGENT_MODEL=inherit, SUBAGENT_MODEL_FORCE=1, WORKFLOW_SUBAGENT_MODEL=<id>, "
      "WORKFLOW_MAX_CONCURRENT_AGENTS=1; User-Agent unico por execucao; B: --settings enableWorkflows.")
    w(f"Ferramentas: A --tools={TOOLS['A']} --allowedTools={ALLOWED['A']}; "
      f"B --tools={TOOLS['B']} --allowedTools={ALLOWED['B']}; "
      f"C --tools={TOOLS['C']} --allowedTools={ALLOWED['C']}.")
    w(f"Timeout: {meta['timeout']}s   estabilizacao: {meta['stable']}s (max {meta['max_wait']}s)")
    w("Validade B/C: execucao sem evidencia de subagente e INVALIDA ('nao delegou').")
    for t in meta["tests"]:
        for mk in meta["models"]:
            cell = [r for r in runs if r["test"] == t and r["model_key"] == mk]
            w("")
            w("-" * 100)
            w(f"TESTE {t} / modelo {mk} ({MODELS[mk]})")
            w("-" * 100)
            by = {s: [r for r in cell if r["scen"] == s] for s in SCENS}
            for s in SCENS:
                w(f"  {s}: validas={sum(1 for r in by[s] if not r['invalid'])} invalidas={sum(1 for r in by[s] if r['invalid'])} "
                  f"corretas={sum(1 for r in by[s] if not r['invalid'] and r['correct'])}"
                  + (f" delegaram={sum(1 for r in by[s] if r['delegated'])}" if s in "BC" else ""))
            for label, req in (("TODAS as validas", False), ("so validas E corretas", True)):
                w(f"  [{label}]")
                sel = {s: [r for r in by[s] if usable(r, req)] for s in SCENS}
                w(f"    {'metrica':<18}" + "".join(f"{s + ' med':>9}{s + ' min':>9}{s + ' max':>9}" for s in SCENS))
                for key, nm in METRICS:
                    row = ""
                    for s in SCENS:
                        row += (f"{'-':>9}{'-':>9}{'-':>9}" if not sel[s]
                                else "".join(f"{fmt(v):>9}" for v in stat_line(sel[s], key)))
                    w(f"    {nm:<18}" + row)
                w(f"    n(A)={len(sel['A'])} n(B)={len(sel['B'])} n(C)={len(sel['C'])}")
            fa = sum(r["agg"]["fail_total"] for r in cell if r["agg"])
            w(f"  Tokens de chamadas com falha (incluidos nos totais; 499/5xx/failed): {fmt(fa)} em "
              f"{sum(r['agg']['fail_n'] for r in cell if r['agg'])} linhas")
            # equivalencia
            w("  Equivalencia de resultado (por repeticao, execucoes sem erro):")
            for rep in sorted({r["rep"] for r in cell}):
                x = {s: next((r for r in by[s] if r["rep"] == rep), None) for s in SCENS}
                if not all(x.values()):
                    continue
                gab = TESTS[t]["_truth_norm"]
                eqs = [(f"{s}==gab", diff_norm(x[s]["result_norm"], gab)) for s in SCENS]
                eqs.append(("B==C", diff_norm(x["B"]["result_norm"], x["C"]["result_norm"])))
                w(f"    rep {rep}: " + "  ".join(f"{n}={'SIM' if not d else 'NAO'}" for n, d in eqs))
                for n, d in eqs:
                    if d:
                        w(f"       diff {n}: {d[:300]}")
    w("")
    w("=" * 100)
    w("EXECUCOES (uuid, teste, rep, cenario, modelo, status, tokens, duracao)")
    w("=" * 100)
    for r in runs:
        a = r["agg"] or {}
        w(f"{r['uuid']} {r['test']} rep{r['rep']} {r['scen']} {r['model_key']:<8} {run_status(r):<8} "
          f"total={fmt(a.get('total', 0))} linhas={a.get('n', 0)} falhas={fmt(a.get('fail_total', 0))} "
          f"dur={r['wall']:.1f}s resultado={'correto' if r['correct'] else 'INCORRETO'} via={r['extract']} "
          f"turns={r['num_turns']} term={r['terminal_reason']}"
          + (f" delegou={'sim' if r['delegated'] else 'NAO'}" if r["scen"] in "BC" else ""))
        for why in r["invalid"]:
            w(f"      motivo invalida: {why}")
    # totais
    w("")
    w("=" * 100)
    w("TOTAL GERAL (soma das execucoes validas; consumo real, falhas incluidas)")
    w("=" * 100)
    for mk in [None] + list(meta["models"]):
        rs = runs if mk is None else [r for r in runs if r["model_key"] == mk]
        S = {s: sums(rs, s) for s in SCENS}
        w(f"  {('GERAL' if mk is None else mk):<10} {'metrica':<18}" + "".join(f"{s:>14}" for s in SCENS))
        for key, nm in METRICS:
            if key in ("n", "wall"):
                continue
            w(f"  {'':<10} {nm:<18}" + "".join(f"{fmt(S[s][key]):>14}" for s in SCENS))
        w(f"  {'':<10} {'chamadas':<18}" + "".join(f"{S[s]['calls']:>14}" for s in SCENS))
        dur = {s: sum(r["wall"] for r in rs if r["scen"] == s and not r["invalid"]) for s in SCENS}
        w(f"  {'':<10} {'duracao s (soma)':<18}" + "".join(f"{fmt(v):>14}" for v in dur.values()))
    # comparacao entre cenarios
    w("")
    w("=" * 100)
    w("COMPARACAO ENTRE CENARIOS (soma das execucoes validas)")
    w("=" * 100)
    w("  B sobre C = o que o DYNAMIC WORKFLOW custa a mais que delegar ao mesmo subagente sem workflow.")
    w("  C sobre A = o que custa TER um orquestrador delegando, em vez de o agente ser a thread principal.")
    w("  B sobre A = o numero de antes (workflow contra agente direto): inclui orquestrador E workflow.")
    w(f"  {'escopo':<10} {'metrica':<18}{'A':>12}{'B':>12}{'C':>12}{'B/C':>10}{'C/A':>10}{'B/A':>10}")
    for mk in [None] + list(meta["models"]):
        rs = runs if mk is None else [r for r in runs if r["model_key"] == mk]
        S = {s: sums(rs, s) for s in SCENS}
        for key, nm in (("total", "total"), ("uncached", "input nao cacheado")):
            a, b, c = S["A"][key], S["B"][key], S["C"][key]
            w(f"  {('GERAL' if mk is None else mk):<10} {nm:<18}{fmt(a):>12}{fmt(b):>12}{fmt(c):>12}"
              f"{fmt(pct(b, c), True):>10}{fmt(pct(c, a), True):>10}{fmt(pct(b, a), True):>10}")
    # resumo
    w("")
    w("=" * 100)
    w("RESUMO: quanto o dynamic workflow custa a mais que delegar ao mesmo subagente sem workflow")
    w("=" * 100)
    G = {s: sums(runs, s) for s in SCENS}
    w(f"  GERAL       B sobre C: total {fmt(pct(G['B']['total'], G['C']['total']), True)}   "
      f"input nao cacheado {fmt(pct(G['B']['uncached'], G['C']['uncached']), True)}")
    for mk in meta["models"]:
        S = {s: sums([r for r in runs if r["model_key"] == mk], s) for s in SCENS}
        w(f"  {mk:<11} B sobre C: total {fmt(pct(S['B']['total'], S['C']['total']), True)}   "
          f"input nao cacheado {fmt(pct(S['B']['uncached'], S['C']['uncached']), True)}")
    w("  (B sobre C > 0 = o workflow consome mais; a diferenca e o custo extra do orquestrador do workflow"
      " sobre a delegacao direta.)")
    # ressalvas
    w("")
    w("=" * 100)
    w("RESSALVAS")
    w("=" * 100)
    for t in meta["tests"]:
        for mk in meta["models"]:
            for s in SCENS:
                rs = [r for r in runs if r["test"] == t and r["model_key"] == mk and r["scen"] == s]
                n = sum(1 for r in rs if not r["invalid"])
                if n < 3:
                    w(f"  - {t}/{mk}/{s}: n valido = {n} (<3): mediana/min/max pouco informativos.")
    inv = [r for r in runs if r["invalid"]]
    nd = [r for r in runs if r["scen"] in "BC" and r["delegated"] is False]
    w(f"  - Execucoes invalidas: {len(inv)} de {len(runs)}; por 'nao delegou': {len(nd)} "
      f"{[r['scen'] + r['uuid'][-8:] for r in nd]}")
    w("  - 'Nao delegou' = sem subagent_stats.spawned>=1 (exato, mas so ve a ferramenta Agent) e sem duas "
      "faixas de input no banco (min*2<=max); limites no cabecalho do bench.py.")
    wrong = [r for r in runs if not r["invalid"] and not r["correct"]]
    w(f"  - Execucoes validas com resultado incorreto: {len(wrong)} (fora do bloco 'validas E corretas').")
    sl = [r for r in runs if r["sleep"]]
    w(f"  - Possivel sono/suspensao (duracao de parede >> janela do banco): {len(sl)} execucao(oes) {[r['uuid'][-8:] for r in sl]}")
    nf = sum(r["agg"]["fail_n"] for r in runs if r["agg"])
    w(f"  - Linhas com falha do proxy (failed/499/5xx, ex.: 429): {nf}. Tokens delas estao nos totais.")
    srcs = sorted({(r['scen'], r['extract'] or 'nenhum') for r in runs})
    w(f"  - Origem do resultado (cenario, fonte): {srcs}. Se diferir entre cenarios, a comparacao de saida depende do parser de texto.")
    w("  - O Gemini quase nao reporta cache_read (quase sempre 0): NAO comparar a parcela de cache dele com a dos outros modelos.")
    w("  - Amostras pequenas, um unico dia, cache de prompt do provedor varia entre execucoes: nao generalizar.")
    w("  - Cada execucao inclui overhead fixo do harness (system prompt, ferramentas), igual nos tres cenarios por construcao.")
    return "\n".join(L)


# ----------------------------------------------------------------- selftest

def selftest():
    assert med([3, 1, 2]) == 2 and med([1, 2, 3, 4]) == 2.5
    assert round(pct(150, 100), 6) == 50.0 and pct(1, 0) is None
    # agregacao por user_agent em sqlite em memoria
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE usage_events (id INTEGER PRIMARY KEY, timestamp_ms INT, model TEXT, input_tokens INT, "
              "output_tokens INT, cache_read_tokens INT, total_tokens INT, failed INT, failure_status INT, user_agent TEXT, "
              "cache_creation_tokens INT)")
    c.executemany("INSERT INTO usage_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (1, 1000, "m", 100, 10, 50, 110, 0, 0, "bench-x", 30), (2, 2000, "m", 200, 20, 0, 220, 0, 0, "bench-x", 0),
        (3, 3000, "m", 5, 5, 0, 10, 1, 429, "bench-x", 7), (4, 4000, "m", 9, 9, 0, 18, 0, 0, "bench-y", 0)])
    rows = c.execute("SELECT id, timestamp_ms, model, input_tokens, output_tokens, cache_read_tokens, total_tokens, "
                     "failed, failure_status, cache_creation_tokens FROM usage_events WHERE user_agent LIKE ?",
                     ("%bench-x%",)).fetchall()
    a = aggregate(rows)
    assert (a["n"], a["total"], a["uncached"], a["completion"], a["cache_read"], a["cache_creation"],
            a["fail_total"], a["fail_n"]) == (3, 340, 255, 35, 50, 37, 10, 1), a
    assert a["inputs"] == [100, 200, 5]
    # criterio de "nao delegou": spawned ou duas faixas de input (min*2 <= max)
    assert delegated(aggregate(rows), 1)[0] is True
    assert delegated(aggregate(rows), 0)[0] is True  # 5..200: duas faixas
    one = aggregate([(1, 1, "m", 6000, 1, 0, 6001, 0, 0, 0), (2, 2, "m", 8000, 1, 0, 8001, 0, 0, 0)])
    assert delegated(one, 0) == (False, "sem subagent_stats.spawned e sem duas faixas de input (6000..8000)")
    assert delegated(one, 2)[0] is True
    assert delegated(aggregate([]), 0)[0] is False
    # cenario -> ferramentas e texto: B e C simetricos em --tools; so C acrescenta a instrucao de delegar
    cmd_a = build_cmd(TESTS["t1"], "A", "claude-haiku-5-5")
    cmd_b = build_cmd(TESTS["t1"], "B", "claude-haiku-5-5")
    cmd_c = build_cmd(TESTS["t1"], "C", "claude-haiku-5-5")
    assert TOOLS["B"] == TOOLS["C"] and TOOLS["B"] == TOOLS_MAIN
    assert "--allowedTools=Agent" in cmd_c and "--allowedTools=Workflow,Agent" in cmd_b
    assert "--tools=Read,Grep,Glob,StructuredOutput" in cmd_a and "--agent" in cmd_a
    assert "Workflow" in " ".join(cmd_b) and "--settings" in cmd_b
    assert cmd_c[-1] == TESTS["t1"]["prompt"] + DELEGATE_C and "subagent_type" in cmd_c[-1]
    assert cmd_b[-1].startswith("/bench-t1 ") and DELEGATE_C not in cmd_b[-1]
    assert not any(x.startswith("--tools") and not x.startswith("--tools=") for x in cmd_a + cmd_b + cmd_c)
    # rotacao de ordem: nenhum cenario e sempre o primeiro; plano default = 27
    assert [order(1), order(2), order(3)] == [["A", "B", "C"], ["B", "C", "A"], ["C", "A", "B"]]
    assert len({order(r)[0] for r in (1, 2, 3)}) == 3
    assert len(make_plan(["t1"], ["haiku", "deepseek", "gemini"], 3)) == 27
    assert len({(t, mk, rp, s) for t, mk, rp, s in make_plan(["t1"], ["haiku"], 3)}) == 9
    # estabilizacao com relogio falso
    t = [0.0]
    seq = iter([1, 2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3])
    clock = lambda: t[0]
    def sleep(s): t[0] += s
    def cnt():
        return next(seq)
    n, ok = wait_stable(cnt, stable_s=4, max_s=90, poll=2, sleep=sleep, clock=clock)
    assert (n, ok) == (3, True), (n, ok)
    n, ok = wait_stable(lambda: int(t[0]), stable_s=10, max_s=10, poll=2, sleep=sleep, clock=clock)
    assert ok is False
    # banco WAL sem arquivos -wal/-shm -> caminho do snapshot
    with tempfile.TemporaryDirectory() as td:
        dbp = Path(td) / "usage.db"
        w = sqlite3.connect(dbp)
        w.execute("PRAGMA journal_mode=WAL")
        w.execute("CREATE TABLE usage_events (id INTEGER PRIMARY KEY, timestamp_ms INT, model TEXT, input_tokens INT, "
                  "output_tokens INT, cache_read_tokens INT, total_tokens INT, failed INT, failure_status INT, user_agent TEXT, "
                  "cache_creation_tokens INT)")
        w.execute("INSERT INTO usage_events VALUES (1, 5000, 'm', 1, 2, 0, 3, 0, 0, 'bench-z', 4)")
        w.commit()
        w.close()
        assert not (Path(td) / "usage.db-wal").exists() and not (Path(td) / "usage.db-shm").exists()
        db = UsageDB(dbp, retries=0)
        r = db.rows_for("bench-z", 0)
        assert r and r[0][6] == 3, r
        assert db.snapshots == 1
        print(f"  leitura WAL sem -wal/-shm via snapshot: snapshots usados = {db.snapshots}")
        assert not (Path(td) / "usage.db-wal").exists(), "origem foi modificada"
    # relatorio com extract None misturado, gravacao incremental, parcial e Ctrl+C (sem modelo)
    TESTS["t1"]["_truth_norm"] = {"count": 0, "files": []}
    meta = {"date": "d", "claude": "c", "base_url": "u", "models": ["haiku"], "reps": 2, "tests": ["t1"],
            "timeout": 1, "stable": 1, "max_wait": 1, "total": 6}
    plan = make_plan(["t1"], ["haiku"], 2)
    assert len(plan) == 6
    seen = []

    def fake(test, scen, mk, rep, args, token, db):
        n = len(seen)
        if n == 2 and FAKE["mode"] == "boom":
            raise RuntimeError("boom")
        if n == 2 and FAKE["mode"] == "int":
            raise KeyboardInterrupt
        seen.append(1)
        ok = n != 1  # execucao 2: sem JSON
        agg = aggregate([(1, 1, "claude-haiku-5-5", 10, 5, 0, 15, 0, 0, 3)])
        return {"uuid": f"bench-{n:08d}", "test": "t1", "rep": rep, "scen": scen, "model_key": mk, "model": "x",
                "invalid": [] if ok else ["timeout 1s"], "wall": 1.0, "agg": agg, "extract": "texto" if ok else None,
                "correct": None, "result_norm": {"count": 0, "files": []} if ok else None, "num_turns": 1,
                "terminal_reason": None, "keys": None, "sleep": False, "stable": True,
                "delegated": True if scen in "BC" else None}
    FAKE = {"mode": "ok"}
    with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()) as buf:
        o = Path(td) / "r1"
        o.mkdir()
        assert execute(plan, None, None, None, dict(meta), o, fake) == 0
        rt = (o / "report.txt").read_text()
        assert len(json.loads((o / "runs.json").read_text())["runs"]) == 6 and (o / "report.txt").exists()
        assert "'nenhum'" in rt
        for needle in ("B sobre C", "C sobre A", "B sobre A", "input nao cacheado", "cache_creation",
                       "nao delegou", "NAO comparar a parcela de cache", "n(A)=2 n(B)=1 n(C)=2"):
            assert needle in rt, needle
        seen.clear(); FAKE["mode"] = "boom"
        o = Path(td) / "r2"
        o.mkdir()
        try:
            execute(plan, None, None, None, dict(meta), o, fake)
            raise SystemExit("deveria falhar")
        except RuntimeError:
            pass
        assert len(json.loads((o / "runs.json").read_text())["runs"]) == 2
        seen.clear(); FAKE["mode"] = "int"
        o = Path(td) / "r3"
        o.mkdir()
        assert execute(plan, None, None, None, dict(meta), o, fake) == 130
        d = json.loads((o / "runs.json").read_text())
        rt = (o / "report.txt").read_text()
        assert len(d["runs"]) == 2 and d["meta"]["partial"] and "RELATORIO PARCIAL: 2 de 6" in rt, rt[:300]
        assert "Interrompido" in buf.getvalue()
    print("  relatorio c/ extract None, incremental, falha no meio e Ctrl+C parcial (130): OK")
    print("selftest OK")


# ----------------------------------------------------------------- main

def order(rep):
    """Ordem dos cenarios dentro da repeticao, rotacionada: nenhum cenario e sempre o primeiro."""
    return [SCENS[(i + rep - 1) % len(SCENS)] for i in range(len(SCENS))]


def make_plan(tests, models, reps):
    return [(t, mk, rep, s) for t in tests for mk in models for rep in range(1, reps + 1)
            for s in order(rep)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tests", default=",".join(TESTS))
    ap.add_argument("--models", default="haiku,deepseek,gemini")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--base-url", default=DEFAULT_URL)
    ap.add_argument("--usage-db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--stable", type=float, default=10)
    ap.add_argument("--max-wait", type=float, default=90)
    ap.add_argument("--sleep-slack", type=float, default=120, help="s de folga parede-janela antes de sinalizar sono")
    ap.add_argument("--project", type=Path, default=PROJECT, help="projeto de teste pronto (cwd do claude)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-caffeinate", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    args.project = args.project.resolve()
    if not args.project.is_dir():
        sys.exit(f"ERRO: projeto de teste nao encontrado em {args.project}. Ele deve estar pronto (uv init) antes de rodar o bench.")
    tests = args.tests.split(",")
    models = args.models.split(",")
    bad = [x for x in tests if x not in TESTS] + [m for m in models if m not in MODELS]
    if bad:
        sys.exit(f"ERRO: desconhecido(s): {bad}")
    if (platform.system() == "Darwin" and not args.dry_run and not args.no_caffeinate
            and not os.environ.get("BENCH_CAFFEINATED") and shutil.which("caffeinate")):
        os.environ["BENCH_CAFFEINATED"] = "1"
        os.execvp("caffeinate", ["caffeinate", "-i", sys.executable, *sys.argv])
    token = read_token()
    plan = make_plan(tests, models, args.reps)
    total = len(plan)
    if args.dry_run:
        print(f"[dry-run] projeto em {args.project}")
        print(f"Plano: {len(tests)} testes x {len(models)} modelos x {args.reps} reps x {len(SCENS)} cenarios = {total} execucoes")
        print("Ordem por repeticao (rotacao): " + "; ".join(f"rep{r}={''.join(order(r))}" for r in range(1, args.reps + 1)))
        print("Execucoes: " + ", ".join(f"{t}/{mk}/r{rep}/{s}" for t, mk, rep, s in plan))
        for t in tests:
            for mk in models:
                for s in SCENS:
                    ua = "bench-<uuid>"
                    print(f"\n# {t} {s} {mk}\ncwd={args.project}")
                    print("env=" + json.dumps(mask_env(build_env(args.base_url, token, MODELS[mk], ua)), indent=1))
                    print("$ " + " ".join(json.dumps(x) if " " in x or "{" in x else x for x in build_cmd(TESTS[t], s, MODELS[mk])))
        return
    precheck(args, token, models)
    for t in tests:
        TESTS[t]["_truth_norm"] = normalize(json.loads((args.project / TESTS[t]["expected"]).read_text()))
    db = UsageDB(args.usage_db)
    claude_v = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    meta = {"date": datetime.now().isoformat(timespec="seconds"), "claude": claude_v, "base_url": args.base_url,
            "models": models, "reps": args.reps, "tests": tests, "timeout": args.timeout,
            "stable": args.stable, "max_wait": args.max_wait, "total": total}
    out = RESULTS / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True)
    print(f"Iniciando {total} execucoes ({claude_v}). Resultados em {out}", flush=True)
    sys.exit(execute(plan, args, token, db, meta, out))


def save_runs(out, meta, runs):
    tmp = out / "runs.json.tmp"
    tmp.write_text(json.dumps({"meta": meta, "runs": runs}, indent=1, default=str))
    os.replace(tmp, out / "runs.json")


def execute(plan, args, token, db, meta, out, run_fn=None):
    run_fn = run_fn or run_one
    runs, total, rc = [], len(plan), 0
    save_runs(out, meta, runs)
    try:
        for t, mk, rep, s in plan:
            r = run_fn(TESTS[t], s, mk, rep, args, token, db)
            r["correct"] = r["result_norm"] is not None and not diff_norm(r["result_norm"], TESTS[t]["_truth_norm"])
            runs.append(r)
            save_runs(out, meta, runs)
            a = r["agg"] or {}
            print(f"[{len(runs)}/{total}] {t} rep{rep} {s} {mk}: {run_status(r)} total={fmt(a.get('total', 0))} "
                  f"linhas={a.get('n', 0)} dur={r['wall']:.0f}s correto={r['correct']} via={r['extract']}"
                  + (f" motivo={r['invalid']}" if r["invalid"] else ""), flush=True)
    except KeyboardInterrupt:
        kill_current()
        t, mk, rep, s = plan[min(len(runs), total - 1)]
        meta["partial"], meta["interrupted"], rc = True, f"{t} rep{rep} {s} {mk}", 130
        print("\nInterrompido (Ctrl+C): filho encerrado.", flush=True)
    except BaseException:
        kill_current()
        raise
    save_runs(out, meta, runs)
    rep_txt = make_report(runs, meta)
    (out / "report.txt").write_text(rep_txt + "\n")
    print("\n" + rep_txt + f"\n\nSalvo em {out}")
    return rc


if __name__ == "__main__":
    main()
