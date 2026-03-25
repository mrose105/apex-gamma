import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import time
import scanner
import config

# ── Page Config ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="APEX Gamma | 0DTE SPY",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Styling ──────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .metric-card {
        background: #1c1f26;
        border-radius: 10px;
        padding: 16px;
        border-left: 4px solid;
    }
    .signal-ENTRY  { color: #00ff88; font-weight: bold; }
    .signal-PEAK   { color: #ffdd00; font-weight: bold; }
    .signal-EXIT   { color: #ff4444; font-weight: bold; }
    .signal-HOLD   { color: #888888; }
    .signal-AVOID  { color: #ff0066; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ── Signal Colors ────────────────────────────────────────────────────
SIGNAL_COLORS = {
    "ENTRY": "#00ff88",
    "PEAK":  "#ffdd00",
    "EXIT":  "#ff4444",
    "HOLD":  "#888888",
    "AVOID": "#ff0066",
}

# ── Sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚡ APEX Gamma")
    st.caption(f"0DTE SPY Options | {config.EXPIRY}")
    st.divider()

    opt_type_filter = st.radio("Option Type", ["All", "Calls", "Puts"], horizontal=True)
    signal_filter = st.multiselect(
        "Signal Filter",
        ["ENTRY", "PEAK", "EXIT", "HOLD", "AVOID"],
        default=["ENTRY", "PEAK", "EXIT"]
    )
    strike_range = st.slider(
        "Strike Range (% from spot)",
        min_value=1, max_value=15, value=5
    )
    auto_refresh = st.toggle("Auto Refresh", value=False)
    refresh_secs = st.select_slider(
        "Refresh Interval",
        options=[15, 30, 60, 120],
        value=30
    )
    st.divider()
    run_button = st.button("🔄 Run Scan", use_container_width=True)

# ── Session State ────────────────────────────────────────────────────
if "df" not in st.session_state:
    st.session_state.df = None
if "spot" not in st.session_state:
    st.session_state.spot = None
if "last_scan" not in st.session_state:
    st.session_state.last_scan = None

# ── Scan Logic ───────────────────────────────────────────────────────
def do_scan():
    with st.spinner("Scanning SPY 0DTE chain..."):
        df, spot = scanner.run_scan()
        st.session_state.df = df
        st.session_state.spot = spot
        st.session_state.last_scan = datetime.now().strftime("%H:%M:%S")

if run_button:
    do_scan()

if auto_refresh and st.session_state.last_scan:
    time.sleep(refresh_secs)
    do_scan()
    st.rerun()

# ── Main Dashboard ───────────────────────────────────────────────────
st.title("⚡ APEX Gamma — 0DTE SPY Options Sniper")

if st.session_state.df is None:
    st.info("👈 Hit **Run Scan** to load the live SPY 0DTE chain.")
    st.stop()

df = st.session_state.df.copy()
spot = st.session_state.spot

# ── Apply Filters ────────────────────────────────────────────────────
if opt_type_filter == "Calls":
    df = df[df["type"] == "call"]
elif opt_type_filter == "Puts":
    df = df[df["type"] == "put"]

if signal_filter:
    df = df[df["signal"].isin(signal_filter)]

# Strike range filter
df = df[abs(df["strike"] - spot) <= spot * (strike_range / 100)]

# ── Top Metrics ──────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("SPY Spot", f"${spot}")
with col2:
    st.metric("Expiry", config.EXPIRY)
with col3:
    st.metric("Contracts", len(st.session_state.df))
with col4:
    entry_count = len(df[df["signal"] == "ENTRY"])
    st.metric("ENTRY Signals", entry_count, delta=None)
with col5:
    st.metric("Last Scan", st.session_state.last_scan or "—")

st.divider()

# ── Gamma Surface Chart ──────────────────────────────────────────────
st.subheader("📈 Gamma Surface by Strike")

calls = st.session_state.df[st.session_state.df["type"] == "call"].copy()
puts  = st.session_state.df[st.session_state.df["type"] == "put"].copy()

# Filter to reasonable strike range for chart
calls = calls[abs(calls["strike"] - spot) <= spot * 0.05]
puts  = puts[abs(puts["strike"] - spot) <= spot * 0.05]

fig_gamma = go.Figure()

fig_gamma.add_trace(go.Scatter(
    x=calls["strike"], y=calls["bs_gamma"],
    mode="lines+markers",
    name="Call Gamma (BS)",
    line=dict(color="#00ff88", width=2),
    marker=dict(size=6)
))

fig_gamma.add_trace(go.Scatter(
    x=puts["strike"], y=puts["bs_gamma"],
    mode="lines+markers",
    name="Put Gamma (BS)",
    line=dict(color="#ff4444", width=2),
    marker=dict(size=6)
))

# Spot line
fig_gamma.add_vline(
    x=spot,
    line_dash="dash",
    line_color="#ffdd00",
    annotation_text=f"Spot ${spot}",
    annotation_position="top right"
)

fig_gamma.update_layout(
    template="plotly_dark",
    height=350,
    xaxis_title="Strike",
    yaxis_title="Gamma",
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    margin=dict(l=40, r=40, t=40, b=40)
)

st.plotly_chart(fig_gamma, use_container_width=True)

# ── Greeks Comparison Panel ──────────────────────────────────────────
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("📊 IV Surface")
    fig_iv = go.Figure()
    fig_iv.add_trace(go.Scatter(
        x=calls["strike"], y=calls["iv"],
        mode="lines+markers", name="Call IV",
        line=dict(color="#00ff88", width=2)
    ))
    fig_iv.add_trace(go.Scatter(
        x=puts["strike"], y=puts["iv"],
        mode="lines+markers", name="Put IV",
        line=dict(color="#ff4444", width=2)
    ))
    fig_iv.add_vline(x=spot, line_dash="dash", line_color="#ffdd00")
    fig_iv.update_layout(
        template="plotly_dark", height=280,
        xaxis_title="Strike", yaxis_title="IV",
        margin=dict(l=40, r=40, t=20, b=40)
    )
    st.plotly_chart(fig_iv, use_container_width=True)

with col_right:
    st.subheader("💰 Pricing Edge (Market vs BS Fair Value)")
    edge_df = st.session_state.df[
        (abs(st.session_state.df["strike"] - spot) <= spot * 0.05) &
        (st.session_state.df["edge_pct"].notna())
    ].copy()

    if not edge_df.empty:
        fig_edge = go.Figure()
        calls_e = edge_df[edge_df["type"] == "call"]
        puts_e  = edge_df[edge_df["type"] == "put"]
        fig_edge.add_trace(go.Bar(
            x=calls_e["strike"], y=calls_e["edge_pct"],
            name="Call Edge %", marker_color="#00ff88"
        ))
        fig_edge.add_trace(go.Bar(
            x=puts_e["strike"], y=puts_e["edge_pct"],
            name="Put Edge %", marker_color="#ff4444"
        ))
        fig_edge.add_hline(y=0, line_color="#ffdd00", line_dash="dash")
        fig_edge.update_layout(
            template="plotly_dark", height=280,
            xaxis_title="Strike", yaxis_title="Edge %",
            barmode="group",
            margin=dict(l=40, r=40, t=20, b=40)
        )
        st.plotly_chart(fig_edge, use_container_width=True)
    else:
        st.info("Edge data available during market hours when broker Greeks populate.")

st.divider()

# ── 3D Surface Tab ───────────────────────────────────────────────────
st.divider()
st.subheader("🧊 3D Surfaces")
tab_3d_1, tab_3d_2, tab_3d_3 = st.tabs(["Gamma Surface", "IV Smile", "Time Evolution"])

surf_df = st.session_state.df.copy()
surf_df = surf_df[abs(surf_df["strike"] - spot) <= spot * 0.05]
surf_calls = surf_df[surf_df["type"] == "call"].sort_values("strike")
surf_puts  = surf_df[surf_df["type"] == "put"].sort_values("strike")

with tab_3d_1:
    fig_3d_gamma = go.Figure()
    fig_3d_gamma.add_trace(go.Scatter3d(
        x=surf_calls["strike"], y=[1] * len(surf_calls), z=surf_calls["bs_gamma"],
        mode="lines+markers", name="Call Gamma",
        line=dict(color="#00ff88", width=4),
        marker=dict(size=4, color=surf_calls["bs_gamma"], colorscale="Viridis"),
    ))
    fig_3d_gamma.add_trace(go.Scatter3d(
        x=surf_puts["strike"], y=[0] * len(surf_puts), z=surf_puts["bs_gamma"],
        mode="lines+markers", name="Put Gamma",
        line=dict(color="#ff4444", width=4),
        marker=dict(size=4, color=surf_puts["bs_gamma"], colorscale="Plasma"),
    ))
    if not surf_calls.empty and not surf_puts.empty:
        strikes = sorted(set(surf_calls["strike"]) & set(surf_puts["strike"]))
        if len(strikes) >= 3:
            z_calls = surf_calls[surf_calls["strike"].isin(strikes)].set_index("strike")["bs_gamma"]
            z_puts  = surf_puts[surf_puts["strike"].isin(strikes)].set_index("strike")["bs_gamma"]
            z_grid  = np.array([z_calls.reindex(strikes).fillna(0).values,
                                z_puts.reindex(strikes).fillna(0).values])
            fig_3d_gamma.add_trace(go.Surface(
                x=strikes, y=[1, 0], z=z_grid,
                colorscale="Viridis", opacity=0.6, showscale=True, name="Gamma Surface",
            ))
    fig_3d_gamma.update_layout(
        template="plotly_dark", height=500,
        scene=dict(xaxis_title="Strike", yaxis_title="Type (1=Call 0=Put)",
                   zaxis_title="Gamma", bgcolor="#0e1117"),
        margin=dict(l=0, r=0, t=30, b=0),
    )
    st.plotly_chart(fig_3d_gamma, use_container_width=True)

with tab_3d_2:
    fig_3d_iv = go.Figure()
    fig_3d_iv.add_trace(go.Scatter3d(
        x=surf_calls["strike"], y=[1] * len(surf_calls), z=surf_calls["iv"],
        mode="lines+markers", name="Call IV",
        line=dict(color="#00ff88", width=4),
        marker=dict(size=4, color=surf_calls["iv"], colorscale="RdYlGn"),
    ))
    fig_3d_iv.add_trace(go.Scatter3d(
        x=surf_puts["strike"], y=[0] * len(surf_puts), z=surf_puts["iv"],
        mode="lines+markers", name="Put IV",
        line=dict(color="#ff4444", width=4),
        marker=dict(size=4, color=surf_puts["iv"], colorscale="RdYlGn"),
    ))
    if not surf_calls.empty and not surf_puts.empty:
        strikes = sorted(set(surf_calls["strike"]) & set(surf_puts["strike"]))
        if len(strikes) >= 3:
            z_iv_calls = surf_calls[surf_calls["strike"].isin(strikes)].set_index("strike")["iv"]
            z_iv_puts  = surf_puts[surf_puts["strike"].isin(strikes)].set_index("strike")["iv"]
            z_iv_grid  = np.array([z_iv_calls.reindex(strikes).fillna(0).values,
                                   z_iv_puts.reindex(strikes).fillna(0).values])
            fig_3d_iv.add_trace(go.Surface(
                x=strikes, y=[1, 0], z=z_iv_grid,
                colorscale="RdYlGn", opacity=0.6, showscale=True, name="IV Surface",
            ))
    fig_3d_iv.update_layout(
        template="plotly_dark", height=500,
        scene=dict(xaxis_title="Strike", yaxis_title="Type (1=Call 0=Put)",
                   zaxis_title="Implied Vol", bgcolor="#0e1117"),
        margin=dict(l=0, r=0, t=30, b=0),
    )
    st.plotly_chart(fig_3d_iv, use_container_width=True)

with tab_3d_3:
    import os, glob
    snapshot_files = sorted(glob.glob("snapshots/snapshot_*.parquet"))
    if len(snapshot_files) < 2:
        st.info("📦 No intraday snapshots yet. Run `collector.py` during market hours to build the time axis. Snapshots save every 30s and will populate this chart automatically.")
    else:
        frames = [pd.read_parquet(f) for f in snapshot_files]
        hist = pd.concat(frames, ignore_index=True)
        for opt_type, color in [("call", "Viridis"), ("put", "Plasma")]:
            subset = hist[hist["type"] == opt_type]
            if subset.empty:
                continue
            pivot = subset.pivot_table(index="timestamp", columns="strike", values="bs_gamma", aggfunc="mean").fillna(0)
            fig_time = go.Figure(data=[go.Surface(
                x=list(pivot.columns),
                y=list(range(len(pivot))),
                z=pivot.values,
                colorscale=color, opacity=0.85, showscale=True,
            )])
            fig_time.update_layout(
                template="plotly_dark", height=520,
                title=f"{opt_type.capitalize()} Gamma Evolution Intraday",
                scene=dict(xaxis_title="Strike", yaxis_title="Time (snapshot #)",
                           zaxis_title="Gamma", bgcolor="#0e1117"),
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_time, use_container_width=True)

# ── Contract Scanner Table ───────────────────────────────────────────
st.divider()
st.subheader("🎯 Contract Scanner")

display_cols = [
    "symbol", "type", "strike", "moneyness",
    "mid_price", "fair_value", "edge_pct",
    "iv", "bs_gamma", "bs_delta", "bs_theta", "bs_vega",
    "br_gamma", "gamma_diff", "hours_left", "signal"
]

display_df = df[[c for c in display_cols if c in df.columns]].copy()

def color_signal(val):
    color = SIGNAL_COLORS.get(val, "#ffffff")
    return f"color: {color}; font-weight: bold"

def color_edge(val):
    if pd.isna(val):
        return ""
    if val > 5:
        return "color: #ff4444"   # overpriced = sell
    if val < -5:
        return "color: #00ff88"   # underpriced = buy
    return ""

styled = display_df.style\
    .applymap(color_signal, subset=["signal"])\
    .applymap(color_edge, subset=["edge_pct"] if "edge_pct" in display_df.columns else [])\
    .format({
        "strike":    "{:.1f}",
        "moneyness": "{:.4f}",
        "mid_price": "${:.4f}",
        "fair_value":"${:.4f}",
        "edge_pct":  "{:.2f}%",
        "iv":        "{:.2%}",
        "bs_gamma":  "{:.4f}",
        "bs_delta":  "{:.4f}",
        "bs_theta":  "{:.4f}",
        "bs_vega":   "{:.4f}",
        "br_gamma":  "{:.4f}",
        "gamma_diff":"{:.4f}",
        "hours_left":"{:.2f}h",
    }, na_rep="—")

st.dataframe(styled, use_container_width=True, height=500)

# ── Entry/Exit Alert Panel ───────────────────────────────────────────
st.divider()
st.subheader("🚨 Active Signals")

alert_col1, alert_col2, alert_col3 = st.columns(3)

with alert_col1:
    st.markdown("### 🟢 ENTRY")
    entries = st.session_state.df[st.session_state.df["signal"] == "ENTRY"].head(5)
    if entries.empty:
        st.caption("No entry signals")
    for _, row in entries.iterrows():
        st.markdown(f"""
        **{row['type'].upper()} ${row['strike']}**
        Gamma: `{row['bs_gamma']:.4f}` | IV: `{row['iv']:.1%}` | Mid: `${row['mid_price']:.3f}`
        """)

with alert_col2:
    st.markdown("### 🟡 PEAK")
    peaks = st.session_state.df[st.session_state.df["signal"] == "PEAK"].head(5)
    if peaks.empty:
        st.caption("No peak signals")
    for _, row in peaks.iterrows():
        st.markdown(f"""
        **{row['type'].upper()} ${row['strike']}**
        Gamma: `{row['bs_gamma']:.4f}` | IV: `{row['iv']:.1%}` | Mid: `${row['mid_price']:.3f}`
        """)

with alert_col3:
    st.markdown("### 🔴 EXIT")
    exits = st.session_state.df[st.session_state.df["signal"] == "EXIT"].head(5)
    if exits.empty:
        st.caption("No exit signals")
    for _, row in exits.iterrows():
        st.markdown(f"""
        **{row['type'].upper()} ${row['strike']}**
        Gamma: `{row['bs_gamma']:.4f}` | IV: `{row['iv']:.1%}` | Mid: `${row['mid_price']:.3f}`
        """)

# ── Footer ───────────────────────────────────────────────────────────
st.divider()
st.caption("APEX Gamma | Built for precision 0DTE SPY execution | Not financial advice")
