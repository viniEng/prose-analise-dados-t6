import os, re, pathlib
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# clique no gráfico (opcional, fallback automático)
try:
    from streamlit_plotly_events import plotly_events
    HAS_PLOTLY_EVENTS = True
except Exception:
    HAS_PLOTLY_EVENTS = False

DATA_DIR = pathlib.Path("data")
RELATOS_DIR = DATA_DIR / "relatos"

st.set_page_config(page_title="NES · SPACE Dashboard", layout="wide")

# ==================== Modelo ====================
@dataclass
class Report:
    artifact: str
    sprint: str
    team: Optional[str]
    overall: Optional[float]
    space: Dict[str, float]                # {"SPACE-P": 8.2, "SPACE-C": 7.9, ...}
    themes: Dict[str, float]               # {"Objetivos & Valor": 7.7, ...}
    top5: List[Tuple[str, float]]
    bottom5: List[Tuple[str, float]]
    suggestions: Optional[str]
    source_file: str

# ==================== Regex =====================
PAT = {
    "title": re.compile(r"^#\s*Relato\s*[\-–]\s*Sprint\s*(?P<sprint>\d+).*?\((?P<artifact>.*?)\)", re.I),
    "overall": re.compile(r"Nota\s+[^\:]+:\s*(?P<score>[\d\.,]+)", re.I),

    "h2_temas": re.compile(r"^##\s*Temas", re.I),
    "h2_space": re.compile(r"^##\s*SPACE", re.I),
    "h2_top":   re.compile(r"^##\s*Top\s*5", re.I),
    "h2_bot":   re.compile(r"^##\s*Bottom\s*5", re.I),
    "h2_sug":   re.compile(r"^##\s*Sugest", re.I),

    # - Texto: 9.58
    "line_qv": re.compile(r"^\-\s+\*?\*?(?P<q>.+?)\*?\*?\:\s*(?P<v>[\d\.,]+)\s*$"),
    # SPACE-C (...): 7.85
    "space_item": re.compile(r"\*?\*?SPACE[\-\s]?([PCEWSA])\b.*?\:\s*([\d\.,]+)", re.I),
}

def _to_float(x: str) -> Optional[float]:
    if x is None: return None
    x = str(x).strip().replace(",", ".")
    try: return float(x)
    except: return None

# Normaliza chave SPACE para nomes “bonitos”
SPACE_NAME = {
    "SPACE-P": "SPACE-P (Performance)",
    "SPACE-C": "SPACE-C (Communication & Collaboration)",
    "SPACE-E": "SPACE-E (Efficiency & Flow)",
    "SPACE-W": "SPACE-W (Satisfaction & Well-Being)",
    "SPACE-S": "SPACE-S (Satisfaction)",   # se algum relato usar “S”
    "SPACE-A": "SPACE-A (Activity)",
}
SPACE_SHORT = {
    "P": "Performance",
    "C": "Comunicação e Colaboração",
    "E": "Eficiência e Flow",
    "W": "Satisfação e Bem-Estar",
    "S": "Satisfação e Bem-Estar",  # sinônimo caso venha como S
    "A": "Activity",
}

def parse_relato_md(text: str, fname: str) -> Report:
    lines = [l.rstrip() for l in text.splitlines()]

    artifact, sprint = "Desconhecido", "Sprint ?"
    for l in lines[:5]:
        m = PAT["title"].search(l)
        if m:
            artifact = m.group("artifact").strip()
            sprint = f"Sprint {m.group('sprint').strip()}"
            break

    overall = None
    for l in lines[:12]:
        m = PAT["overall"].search(l)
        if m:
            overall = _to_float(m.group("score"))
            break

    mode=None; space={}; themes={}; top5=[]; bot5=[]; sug=[]
    for raw in lines:
        l = raw.strip()
        if PAT["h2_temas"].match(l): mode="temas";  continue
        if PAT["h2_space"].match(l): mode="space";  continue
        if PAT["h2_top"].match(l):   mode="top";    continue
        if PAT["h2_bot"].match(l):   mode="bottom"; continue
        if PAT["h2_sug"].match(l):   mode="sug";    continue
        if not l: continue

        if mode == "space":
            m = PAT["space_item"].search(l)
            if m:
                code = m.group(1).upper()
                space[f"SPACE-{code}"] = _to_float(m.group(2))
            else:
                m2 = PAT["line_qv"].match(l)
                if m2 and m2.group("q").upper().startswith("SPACE-"):
                    # Ex.: "- SPACE-C (Communication...): 7.85"
                    key = m2.group("q").split(":")[0].strip()
                    letter = re.search(r"SPACE[\-\s]?([PCEWSA])", key.upper())
                    if letter:
                        space[f"SPACE-{letter.group(1)}"] = _to_float(m2.group("v"))
        elif mode == "temas":
            m = PAT["line_qv"].match(l)
            if m:
                themes[m.group("q").strip("* ")] = _to_float(m.group("v"))
        elif mode == "top":
            m = PAT["line_qv"].match(l)
            if m:
                top5.append((m.group("q").strip(), _to_float(m.group("v"))))
        elif mode == "bottom":
            m = PAT["line_qv"].match(l)
            if m:
                # <<< CORREÇÃO: usar 'bot5', não 'bottom5' >>>
                bot5.append((m.group("q").strip(), _to_float(m.group("v"))))
        elif mode == "sug":
            if l.startswith("- "): l = l[2:]
            sug.append(l)

    # dá nomes bonitos às chaves SPACE
    space_named = {}
    for k,v in space.items():
        space_named[SPACE_NAME.get(k, k)] = v

    return Report(
        artifact=artifact, sprint=sprint, team=None, overall=overall,
        space=space_named, themes=themes, top5=top5, bottom5=bot5,
        suggestions="\n".join(sug) if sug else None, source_file=fname
    )

def load_reports(rel_dir: pathlib.Path) -> List[Report]:
    reps=[]
    for p in sorted(rel_dir.glob("*.md")):
        try:
            reps.append(parse_relato_md(p.read_text(encoding="utf-8"), p.name))
        except Exception as e:
            st.warning(f"Falha ao ler {p.name}: {e}")
    return reps

# ==================== Carrega ====================
reports = load_reports(RELATOS_DIR)
if not reports:
    st.error("Nenhum relato encontrado em data/relatos/*.md")
    st.stop()

# Tabela SPACE agregada (Dimensão x Sprint x Nota)
rows=[]
for r in reports:
    for dim,score in r.space.items():
        if score is not None:
            rows.append({"Dimensão": dim, "Sprint": r.sprint, "Nota": score, "Artefato": r.artifact})
agg = pd.DataFrame(rows)
agg = agg[~agg["Dimensão"].str.startswith("SPACE-A")]  # remove Activity

# ==================== Filtros ====================
st.sidebar.title("Filtros")
sprints = sorted(agg["Sprint"].unique().tolist(), key=lambda s: int(re.findall(r"\d+", s)[0]))
dims = sorted(agg["Dimensão"].unique().tolist())

sprint_sel = st.sidebar.multiselect("Sprint", sprints, default=sprints)
dim_sel = st.sidebar.multiselect("Dimensões SPACE", dims, default=dims)

df = agg.query("Sprint in @sprint_sel and Dimensão in @dim_sel").copy()

st.title("NES · SPACE Dashboard")

# ==================== KPIs ====================
col1, col2, col3 = st.columns(3)
col1.metric("Média geral", f"{df['Nota'].mean():.2f}")
col2.metric("Dimensão destaque", df.groupby("Dimensão")["Nota"].mean().idxmax() if not df.empty else "—")
col3.metric("Sprint destaque", df.groupby("Sprint")["Nota"].mean().idxmax() if not df.empty else "—")

# =========================================================
# 1) GRÁFICO DE LINHAS POR SPRINT (com emoji no ponto)
# =========================================================
st.subheader("Evolução por Sprint (uma linha por dimensão)")
df_line = (df.groupby(["Dimensão","Sprint"], as_index=False)["Nota"]
             .mean().sort_values("Sprint", key=lambda s: s.str.extract(r"(\d+)").astype(int)[0]))
def mood_emoji(v):
    if pd.isna(v): return ""
    if v >= 7.5: return "😄"
    if v >= 6.0: return "😐"
    return "🙁"
df_line["Emoji"] = df_line["Nota"].apply(mood_emoji)

fig_line = px.line(df_line, x="Sprint", y="Nota", color="Dimensão",
                   markers=True, height=420)
for dim, sub in df_line.groupby("Dimensão"):
    fig_line.add_trace(go.Scatter(
        x=sub["Sprint"], y=sub["Nota"], mode="text",
        text=sub["Emoji"], textposition="top center", showlegend=False
    ))
fig_line.update_yaxes(range=[0,10])
st.plotly_chart(fig_line, use_container_width=True)

# =========================================================
# 2) “PONTINHOS” POR ARTEFATO – ÚLTIMA SPRINT (patch)
# =========================================================
st.subheader("Última Sprint – Notas por Artefato (pontos por dimensão)")

# 2.1 Detecta a última sprint disponível nos relatos (independe do filtro de cima)
def _sprint_num(s):
    m = re.search(r"(\d+)", s or "")
    return int(m.group(1)) if m else -1

all_sprints = sorted({r.sprint for r in reports}, key=_sprint_num)
if not all_sprints:
    st.info("Sem sprints nos relatos.")
    last_sprint = None
else:
    # se o usuário filtrou sprints, respeita; senão usa a última de todas
    filt = [s for s in all_sprints if not sprint_sel or s in sprint_sel]
    last_sprint = (filt or all_sprints)[-1]
    st.caption(f"Última sprint detectada: **{last_sprint}**")

# 2.2 Normalizações
def _artifact_label(a: str) -> str:
    t = (a or "").lower()
    if "planning" in t: return "Planning"
    if "daily" in t: return "Daily"
    if "retro" in t or "retrospectiva" in t: return "Retro"
    if "survey" in t: return "Geral"
    return a or "—"

SPACE_PT = {"P":"Performance", "C":"Comunicação e Colaboração",
            "E":"Eficiência e Flow", "W":"Satisfação e Bem-Estar",
            "S":"Satisfação e Bem-Estar", "A":None}

def _space_to_label(k: str) -> Optional[str]:
    m = re.search(r"SPACE[\-\s]?([PCEWSA])", (k or "").upper())
    if not m: return None
    return SPACE_PT.get(m.group(1))

# 2.3 Constrói os pontos
rows = []
if last_sprint:
    for r in reports:
        if r.sprint != last_sprint: 
            continue
        for k, v in (r.space or {}).items():
            dim = _space_to_label(k)
            if dim is None or dim == "Activity" or v is None:
                continue
            try:
                rows.append({
                    "Artefato": _artifact_label(r.artifact),
                    "Dimensão": dim,
                    "Nota": float(str(v).replace(",", "."))
                })
            except Exception:
                pass

df_pts = pd.DataFrame(rows)

if df_pts.empty:
    st.warning("Não encontrei pontos para a última sprint. "
               "Verifique se os relatos dessa sprint possuem a seção **SPACE** com notas.")
else:
    # Ordena Y apenas com categorias presentes
    desired_order = ["Planning", "Daily", "Retro", "Geral"]
    order_y = [c for c in desired_order if c in df_pts["Artefato"].unique()]
    df_pts["Artefato"] = pd.Categorical(df_pts["Artefato"], categories=order_y, ordered=True)

    fig_pts = px.strip(
        df_pts, x="Nota", y="Artefato", color="Dimensão",
        orientation="h", stripmode="overlay", height=380,
        category_orders={"Artefato": order_y}
    )
    fig_pts.update_traces(jitter=0.12, marker_size=11, opacity=0.85)
    fig_pts.update_xaxes(range=[0, 10], title="Nota (0–10)")
    fig_pts.update_yaxes(title="")
    st.plotly_chart(fig_pts, use_container_width=True)

    with st.expander("Ver dados usados neste gráfico"):
        st.dataframe(df_pts.sort_values(["Artefato", "Dimensão"]))


# =========================================================
# 3) BLOCO – ANÁLISE COM IA (O Produtivo)
# =========================================================
st.markdown("""
<div style="background:#4B55B2;color:#fff; padding:22px; border-radius:14px;
            display:flex; align-items:center; gap:18px;">
  <div style="font-size:44px; line-height:1">🧠</div>
  <div>
    <h3 style="margin:0 0 6px 0;">Síntese textual com IA – O Produtivo</h3>
    <div style="opacity:.92;">
      Esta seção gera um resumo automático combinando números e comentários.
      Exemplo: <em>“Well-Being subiu pela força de Comunicação (Daily/Planning),
      mas Retro indica oportunidades em Ação & Aprendizado. Priorize 1) documentar decisões,
      2) transparência pós-sprint e 3) balancear carga.”</em>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

st.divider()

# =========================================================
# 4) DETALHES – DIMENSÃO → ARTEFATOS
# =========================================================
st.subheader("SPACE por dimensão (média das sprints filtradas)")
fig = px.bar(df.groupby(["Dimensão","Sprint"], as_index=False)["Nota"].mean(),
             x="Dimensão", y="Nota", color="Sprint", barmode="group", height=420)
fig.update_yaxes(range=[0, 10])

clicked_dim = None
if HAS_PLOTLY_EVENTS:
    click = plotly_events(fig, click_event=True, hover_event=False, select_event=False, key="main")
    if click:
        clicked_dim = click[0].get("x")
else:
    st.plotly_chart(fig, use_container_width=True)

dims = sorted(df["Dimensão"].unique().tolist())
if not clicked_dim:
    clicked_dim = st.selectbox("Escolha uma dimensão para detalhar:", dims)

st.markdown(f"### 🔎 Detalhe da dimensão: **{clicked_dim}**")

df_dim = df[df["Dimensão"] == clicked_dim]
art_table = (df_dim.groupby(["Artefato","Sprint"], as_index=False)["Nota"]
             .mean().sort_values(["Sprint","Nota"], ascending=[True, False]))
st.dataframe(art_table, use_container_width=True)

art_sel = st.selectbox("Abrir artefato:", ["—"] + art_table["Artefato"].unique().tolist())
if art_sel != "—":
    reps = [r for r in reports if (r.artifact == art_sel) and (r.sprint in sprint_sel)]
    if not reps:
        st.info("Nenhum relato desse artefato para os filtros atuais.")
    else:
        for rep in reps:
            st.markdown(f"#### {rep.artifact} — {rep.sprint}")
            colA, colB = st.columns([2,1])
            with colA:
                if rep.overall is not None:
                    st.write(f"**Nota do artefato:** {rep.overall:.2f}")
                if rep.space:
                    st.write("**SPACE (do relato):**")
                    st.table(pd.Series(rep.space, name="Nota"))
                if rep.themes:
                    st.write("**Temas / Subdimensões do artefato**")
                    st.table(pd.Series(rep.themes, name="Nota"))
            with colB:
                if rep.top5:
                    st.write(f"**Top 5 perguntas — {rep.artifact}**")
                    st.table(pd.DataFrame(rep.top5, columns=["Pergunta","Nota"]))
                if rep.bottom5:
                    st.write(f"**Bottom 5 perguntas — {rep.artifact}**")
                    st.table(pd.DataFrame(rep.bottom5, columns=["Pergunta","Nota"]))
            if rep.suggestions:
                st.write("**Sugestões**")
                st.write(rep.suggestions)
            st.divider()

st.caption("Este dashboard lê diretamente os .md dos seus scripts — novos arquivos aparecem automaticamente.")
