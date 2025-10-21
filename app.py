# app.py
import re, pathlib
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# ---------- Config ----------
st.set_page_config(page_title="NES · SPACE Dashboard", layout="wide")
DATA_DIR = pathlib.Path("data")
RELATOS_DIR = DATA_DIR / "relatos"

# ---------- Modelo ----------
@dataclass
class Report:
    artifact: str
    sprint: str
    team: Optional[str]
    overall: Optional[float]
    space: Dict[str, float]                # {"SPACE-P (Performance)": 8.2, ...}
    themes: Dict[str, float]
    top5: List[Tuple[str, float]]
    bottom5: List[Tuple[str, float]]
    suggestions: Optional[str]
    source_file: str

# ---------- Regex robustos ----------
PAT = {
    # Ex.: "# Relato – Sprint 1 – Forms Daily 1 (respostas)"
    # captura "Sprint 1" e "Forms Daily 1"
    "title": re.compile(
        r"^#\s*Relato\s*[\-–]\s*Sprint\s*(?P<sprint>\d+)\s*[\-–]\s*(?P<artifact>.+?)(?:\s*\(|$)",
        re.I
    ),
    "overall": re.compile(r"Nota\s*\([^)]+\)\s*:\s*(?P<score>[\d\.,]+)", re.I),   # "Nota (base): 9.17" etc.
    "overall2": re.compile(r"Nota\s*:\s*(?P<score>[\d\.,]+)", re.I),

    "h2_temas": re.compile(r"^##\s*Temas", re.I),
    "h2_space": re.compile(r"^##\s*SPACE", re.I),
    "h2_top":   re.compile(r"^##\s*Top\s*5", re.I),
    "h2_bot":   re.compile(r"^##\s*Bottom\s*5", re.I),
    "h2_sug":   re.compile(r"^##\s*Sugest", re.I),

    # "- Texto da métrica: 9.58"
    "line_qv": re.compile(r"^\-\s+\*?\*?(?P<q>.+?)\*?\*?\s*:\s*(?P<v>[\d\.,]+)\s*$"),
    # "- **SPACE-C (Communication & Collaboration)**: 9.04"
    "space_item": re.compile(r"SPACE[\s\-]?([PCEWSA])", re.I),
}

def _to_float(x: str) -> Optional[float]:
    if x is None: return None
    x = str(x).strip().replace(",", ".")
    try: return float(x)
    except: return None

# Nomes "bonitos"
SPACE_NAME = {
    "P": "SPACE-P (Performance)",
    "C": "SPACE-C (Communication & Collaboration)",
    "E": "SPACE-E (Efficiency & Flow)",
    "W": "SPACE-W (Satisfaction & Well-Being)",
    "S": "SPACE-W (Satisfaction & Well-Being)",  # se vier como S
    "A": "SPACE-A (Activity)",
}
SPACE_PT = {
    "P": "Performance",
    "C": "Comunicação e Colaboração",
    "E": "Eficiência e Flow",
    "W": "Satisfação e Bem-Estar",
    "S": "Satisfação e Bem-Estar",
    "A": None,
}

def _space_to_label(k: str) -> Optional[str]:
    """Converte '...SPACE-X...' -> rótulo PT. Retorna None se não reconhecer."""
    if not k: return None
    m = PAT["space_item"].search(k.upper())
    if not m: return None
    return SPACE_PT.get(m.group(1))

def pretty_space_key(k: str) -> Optional[str]:
    """Converte '...SPACE-X...' -> 'SPACE-X (Nome bonitinho)'."""
    if not k: return None
    m = PAT["space_item"].search(k.upper())
    if not m: return None
    return SPACE_NAME.get(m.group(1), k)

def parse_relato_md(text: str, fname: str) -> Report:
    lines = [l.rstrip() for l in text.splitlines() if l.strip() != ""]

    artifact, sprint = "Desconhecido", "Sprint ?"
    for l in lines[:5]:
        m = PAT["title"].search(l)
        if m:
            artifact = m.group("artifact").strip()
            sprint = f"Sprint {m.group('sprint').strip()}"
            break

    # tenta "Nota (base)" / "Nota (final)" / "Nota:"
    overall = None
    for l in lines[:12]:
        m = PAT["overall"].search(l) or PAT["overall2"].search(l)
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

        if mode == "space":
            # aceita linhas no formato "- **SPACE-C ...**: 9.04"
            m = PAT["line_qv"].match(l)
            if m:
                key = pretty_space_key(m.group("q"))
                if key:
                    space[key] = _to_float(m.group("v"))
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
                bot5.append((m.group("q").strip(), _to_float(m.group("v"))))
        elif mode == "sug":
            if l.startswith("- "): l = l[2:]
            sug.append(l)

    return Report(
        artifact=artifact, sprint=sprint, team=None, overall=overall,
        space=space, themes=themes, top5=top5, bottom5=bot5,
        suggestions="\n".join(sug) if sug else None,
        source_file=fname
    )

def load_reports(rel_dir: pathlib.Path) -> List[Report]:
    reps=[]
    for p in sorted(rel_dir.glob("*.md")):
        try:
            reps.append(parse_relato_md(p.read_text(encoding="utf-8"), p.name))
        except Exception as e:
            st.warning(f"Falha ao ler {p.name}: {e}")
    return reps

# ---------- Helpers de UI/Dados ----------
def sprint_num(s: str) -> int:
    m = re.search(r"(\d+)", s or "")
    return int(m.group(1)) if m else -1

def artifact_label(a: str) -> str:
    """Mapeia o nome livre do arquivo para {Planning, Daily, Retro, Geral}."""
    if not a: 
        return "—"
    t = re.sub(r"[\s_]+", " ", a.lower()).strip()
    if "planning" in t: return "Planning"
    if "daily" in t: return "Daily"
    if "retro" in t or "retrospectiva" in t: return "Retro"
    if "survey" in t or "alunos" in t or "geral" in t: return "Geral"
    return a.strip()

def display_artifact(a: str) -> str:
    """Nome amigável para cabeçalhos (remove 'Forms ' e variações)."""
    if not a: return "—"
    a = re.sub(r"^\s*forms\s+", "", a, flags=re.I)
    a = a.replace("  ", " ").strip()
    return a

# ---------- Carrega os .md ----------
reports = load_reports(RELATOS_DIR)
if not reports:
    st.error("Nenhum relato encontrado em data/relatos/*.md")
    st.stop()

# ---------- Agregado SPACE ----------
rows=[]
for r in reports:
    for dim,score in (r.space or {}).items():
        rows.append({
            "Dimensão": dim,                 # já vem no formato "SPACE-X (Nome)"
            "Sprint": r.sprint,
            "Nota": _to_float(score),
            "Artefato": display_artifact(r.artifact)
        })
agg = pd.DataFrame(rows)
# remove Activity, se existir
agg = agg[~agg["Dimensão"].str.startswith("SPACE-A")]

# ---------- Filtros ----------
st.sidebar.title("Filtros")
sprints = sorted(agg["Sprint"].dropna().unique().tolist(), key=sprint_num)
dims = sorted(agg["Dimensão"].dropna().unique().tolist())

sprint_sel = st.sidebar.multiselect("Sprint", sprints, default=sprints or [])
dim_sel = st.sidebar.multiselect("Dimensões SPACE", dims, default=dims or [])

df = agg.copy()
if sprint_sel: df = df[df["Sprint"].isin(sprint_sel)]
if dim_sel: df = df[df["Dimensão"].isin(dim_sel)]

st.title("NES · SPACE Dashboard")

# ---------- KPIs ----------
col1, col2, col3 = st.columns(3)
if not df.empty:
    col1.metric("Média geral", f"{df['Nota'].mean():.2f}")
    col2.metric("Dimensão destaque", df.groupby("Dimensão")["Nota"].mean().idxmax())
    col3.metric("Sprint destaque", df.groupby("Sprint")["Nota"].mean().idxmax())
else:
    col1.metric("Média geral", "—")
    col2.metric("Dimensão destaque", "—")
    col3.metric("Sprint destaque", "—")

# =========================================================
# 1) “PONTINHOS POR ARTEFATO” – ÚLTIMA SPRINT
# =========================================================
st.subheader("Última Sprint – Notas por Artefato (pontos por dimensão)")

# Descobre a última sprint (respeitando filtro; se vazio, pega a última geral)
all_s = sorted({r.sprint for r in reports}, key=sprint_num)
use_pool = [s for s in all_s if (not sprint_sel or s in sprint_sel)]
last_sprint = (use_pool or all_s)[-1] if (use_pool or all_s) else None
if last_sprint:
    st.caption(f"Última sprint detectada: **{last_sprint}**")

# Monta pontos
points=[]
if last_sprint:
    for r in reports:
        if r.sprint != last_sprint: 
            continue
        for k, v in (r.space or {}).items():
            dim_pt = _space_to_label(k)
            if dim_pt and dim_pt != "Activity" and v is not None:
                points.append({
                    "Artefato": artifact_label(display_artifact(r.artifact)),
                    "Dimensão": dim_pt,
                    "Nota": _to_float(v)
                })

df_pts = pd.DataFrame(points)

if df_pts.empty:
    st.warning("Não encontrei dados de SPACE para a última sprint (verifique a seção **## SPACE** dos .md).")
else:
    order_y = ["Planning","Daily","Retro","Geral"]
    present = [c for c in order_y if c in df_pts["Artefato"].unique()]
    df_pts = df_pts[df_pts["Artefato"].isin(present)].copy()
    df_pts["Artefato"] = pd.Categorical(df_pts["Artefato"], categories=present, ordered=True)

    fig_pts = px.strip(
        df_pts, x="Nota", y="Artefato", color="Dimensão",
        orientation="h", stripmode="overlay", height=380,
        category_orders={"Artefato": present}
    )
    fig_pts.update_traces(jitter=0.12, marker_size=11, opacity=0.9)
    fig_pts.update_xaxes(range=[0, 10], title="Nota (0–10)")
    fig_pts.update_yaxes(title="")
    st.plotly_chart(fig_pts, use_container_width=True)

    with st.expander("Ver dados usados neste gráfico"):
        st.dataframe(df_pts.sort_values(["Artefato","Dimensão"]))

st.divider()

# =========================================================
# 2) SPACE por dimensão (média das sprints filtradas)
# =========================================================
st.subheader("SPACE por dimensão (média das sprints filtradas)")
if df.empty:
    st.info("Sem dados para os filtros atuais.")
else:
    df_bar = df.groupby(["Dimensão","Sprint"], as_index=False)["Nota"].mean()
    df_bar["Nota"] = df_bar["Nota"].astype(float)
    fig = px.bar(df_bar, x="Dimensão", y="Nota", color="Sprint", barmode="group", height=420)
    fig.update_yaxes(range=[0,10], title="Nota")
    fig.update_xaxes(title="Dimensão")
    st.plotly_chart(fig, use_container_width=True)

# =========================================================
# 3) DETALHE – DIMENSÃO → ARTEFATOS
# =========================================================
dims_for_select = sorted(df["Dimensão"].unique().tolist()) if not df.empty else []
if dims_for_select:
    dim_choice = st.selectbox("Escolha uma dimensão para detalhar:", dims_for_select)
    df_dim = df[df["Dimensão"] == dim_choice]
    art_table = (df_dim.groupby(["Artefato","Sprint"], as_index=False)["Nota"]
                        .mean().sort_values(["Sprint","Nota"], ascending=[True, False]))
    st.dataframe(art_table, use_container_width=True)

    art_sel = st.selectbox("Abrir artefato:", ["—"] + art_table["Artefato"].unique().tolist())
    if art_sel != "—":
        reps = [r for r in reports if display_artifact(r.artifact) == art_sel and (not sprint_sel or r.sprint in sprint_sel)]
        if not reps:
            st.info("Nenhum relato desse artefato para os filtros atuais.")
        else:
            for rep in reps:
                title_art = display_artifact(rep.artifact)
                st.markdown(f"#### {title_art} — {rep.sprint}")
                colA, colB = st.columns([2,1])
                with colA:
                    if rep.overall is not None:
                        st.write(f"**Nota do artefato:** {rep.overall:.2f}")
                    if rep.space:
                        st.write("**SPACE (do relato):**")
                        # Garante ordem P,C,E,W se existirem
                        order_space = ["SPACE-P (Performance)",
                                       "SPACE-C (Communication & Collaboration)",
                                       "SPACE-E (Efficiency & Flow)",
                                       "SPACE-W (Satisfaction & Well-Being)"]
                        s_space = pd.Series(rep.space, name="Nota")
                        s_space = s_space.reindex([k for k in order_space if k in s_space.index] +
                                                  [k for k in s_space.index if k not in order_space])
                        st.table(s_space)
                    if rep.themes:
                        st.write("**Temas / Subdimensões do artefato**")
                        st.table(pd.Series(rep.themes, name="Nota"))
                with colB:
                    if rep.top5:
                        st.write(f"**Top 5 perguntas — {title_art}**")
                        st.table(pd.DataFrame(rep.top5, columns=["Pergunta","Nota"]))
                    if rep.bottom5:
                        st.write(f"**Bottom 5 perguntas — {title_art}**")
                        st.table(pd.DataFrame(rep.bottom5, columns=["Pergunta","Nota"]))
                if rep.suggestions:
                    st.write("**Sugestões**")
                    st.write(rep.suggestions)
                st.divider()
else:
    st.info("Carregue ao menos uma dimensão nas sprints filtradas para ver o detalhe.")

# ---------- Rodapé ----------
st.caption("Este dashboard lê diretamente os .md dos seus scripts — novos arquivos aparecem automaticamente. "
           "Se algum item não aparecer, confira a seção **## SPACE** dos relatos e a nomenclatura dos títulos.")
