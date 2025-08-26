import os, re, textwrap, pathlib
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import pandas as pd
import streamlit as st
import plotly.express as px

# clique no gráfico (opcional, tem fallback)
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

    "line_qv": re.compile(r"^\-\s+\*?\*?(?P<q>.+?)\*?\*?\:\s*(?P<v>[\d\.,]+)\s*$"),
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
                    # tenta extrair a letra
                    code = " ".join(key.split()).upper()
                    letter = re.search(r"SPACE[\-\s]?([PCEWSA])", code)
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

# tabela SPACE agregada (Dimensão x Sprint x Nota)
rows=[]
for r in reports:
    for dim,score in r.space.items():
        if score is not None:
            rows.append({"Dimensão": dim, "Sprint": r.sprint, "Nota": score, "Artefato": r.artifact})
agg = pd.DataFrame(rows)

# remove Activity se houver
agg = agg[~agg["Dimensão"].str.startswith("SPACE-A")]

# ==================== Filtros ====================
st.sidebar.title("Filtros")
sprints = sorted(agg["Sprint"].unique().tolist())
dims = sorted(agg["Dimensão"].unique().tolist())

sprint_sel = st.sidebar.multiselect("Sprint", sprints, default=sprints)
dim_sel = st.sidebar.multiselect("Dimensões SPACE", dims, default=dims)

df = agg.query("Sprint in @sprint_sel and Dimensão in @dim_sel").copy()
st.title("NES · SPACE Dashboard")

# KPIs
col1, col2, col3 = st.columns(3)
col1.metric("Média geral", f"{df['Nota'].mean():.2f}")
col2.metric("Dimensão destaque", df.groupby("Dimensão")["Nota"].mean().idxmax())
col3.metric("Sprint destaque", df.groupby("Sprint")["Nota"].mean().idxmax())

# ==================== Gráfico principal ====================
st.subheader("SPACE por dimensão (soma de todos os artefatos)")

fig = px.bar(df.groupby(["Dimensão","Sprint"], as_index=False)["Nota"].mean(),
             x="Dimensão", y="Nota", color="Sprint", barmode="group", height=420)
fig.update_yaxes(range=[0, 10])

clicked_dim = None
if HAS_PLOTLY_EVENTS:
    from streamlit_plotly_events import plotly_events
    click = plotly_events(fig, click_event=True, hover_event=False, select_event=False, key="main")
    if click:
        clicked_dim = click[0].get("x")
else:
    st.plotly_chart(fig, use_container_width=True)

if not clicked_dim:
    clicked_dim = st.selectbox("Escolha uma dimensão para detalhar:", dims)

st.markdown(f"### 🔎 Detalhe da dimensão: **{clicked_dim}**")

# ==================== Drill-down: Dimensão → Artefatos ====================
df_dim = df[df["Dimensão"] == clicked_dim]
art_table = (df_dim.groupby(["Artefato","Sprint"], as_index=False)["Nota"]
             .mean().sort_values(["Sprint","Nota"], ascending=[True, False]))
st.dataframe(art_table, use_container_width=True)

art_sel = st.selectbox("Abrir artefato:", ["—"] + art_table["Artefato"].unique().tolist())
if art_sel != "—":
    # procura o(s) report(s) desse artefato nas sprints filtradas
    reps = [r for r in reports if r.artifact == art_sel and r.sprint in sprint_sel]
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
                    st.write("**Top 5 perguntas**")
                    st.table(pd.DataFrame(rep.top5, columns=["Pergunta","Nota"]))
                if rep.bottom5:
                    st.write("**Bottom 5 perguntas**")
                    st.table(pd.DataFrame(rep.bottom5, columns=["Pergunta","Nota"]))
            if rep.suggestions:
                st.write("**Sugestões**")
                st.write(rep.suggestions)
            st.divider()

st.caption("Este dashboard lê diretamente os .md dos seus scripts — novos arquivos aparecem automaticamente.")
