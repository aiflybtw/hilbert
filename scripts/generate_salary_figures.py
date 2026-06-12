"""
generate_salary_figures.py

Salary model visualizations for Model A (hard skills only).
"""

import json, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from collections import defaultdict, Counter
import psycopg2

BASE = os.path.dirname(__file__)
DATA = os.path.join(BASE, "..", "data")
OUT = os.path.join(DATA, "figures")
os.makedirs(OUT, exist_ok=True)

sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

# ── Load Model A ──
with open(os.path.join(DATA, "salary_model", "salary_model_coefficients_k15.json"), encoding="utf-8") as f:
    coeffs = json.load(f)
with open(os.path.join(DATA, "salary_model", "salary_model_predictions_k15.json"), encoding="utf-8") as f:
    predictions = json.load(f)

with open(os.path.join(DATA, "clustering", "clusters_final_model.json"), encoding="utf-8") as f:
    clusters = json.load(f)

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "#f8f9fa",
    "axes.grid": False,
    "grid.alpha": 0.3,
    "font.size": 11,
})

cluster_short = {cid: info["name"] for cid, info in clusters["cluster_info"].items()}

grade_colors = {"Intern": "#86bcfd", "Junior": "#8cdba0", "Middle": "#f9c97c",
                "Senior": "#fd9e9e", "Lead": "#b07fd4"}
grade_order = ["Intern", "Junior", "Middle", "Senior", "Lead"]

# ═══════════════════════════════════════════════════════════════
# FIG 1: Cluster multiplier coefficients
# ═══════════════════════════════════════════════════════════════
print("FIG 1: Cluster multiplier coefficients")

nids_ordered = sorted(
    [k for k in coeffs["coefficients"] if k.startswith("n_cluster_")],
    key=lambda k: -abs(coeffs["coefficients"][k]["coef_raw"])
)

labels = [cluster_short.get(k.replace("n_cluster_", ""), k) for k in nids_ordered]
vals = [coeffs["coefficients"][k]["multiplier_pct"] for k in nids_ordered]
colors = ["#4e79a7" if v >= 0 else "#e15759" for v in vals]

fig, ax = plt.subplots(figsize=(10, 7))

ax.barh(range(len(labels)), vals, color=colors, height=0.7)
ax.axvline(0, color="black", linewidth=0.8)
ax.set_yticks(range(len(labels)))
ax.set_yticklabels(labels)
ax.set_xlabel("Salary multiplier (%)")
ax.set_title("Salary Multiplier by Hard Skill Cluster", fontweight="bold", fontsize=13)
for i, v in enumerate(vals):
    ax.text(v + (0.5 if v >= 0 else -0.5), i, f"{v:+.1f}%", va="center",
            ha="left" if v >= 0 else "right", fontweight="bold", fontsize=9)
ax.margins(x=0.15)

fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_salary_multipliers.png"), dpi=150)
plt.close(fig)

# ═══════════════════════════════════════════════════════════════
# FIG 2: Soft skill & seniority coefficients
# ═══════════════════════════════════════════════════════════════
print("FIG 2: Soft skill & seniority coefficients")
fig, ax = plt.subplots(figsize=(8, 5))

other_keys = [k for k in coeffs["coefficients"]
              if not k.startswith("n_cluster_")]
labels = []
vals = []
for k in other_keys:
    label = k.replace("s_cluster_", "S").replace("seniority_", "")
    labels.append(label)
    vals.append(coeffs["coefficients"][k]["multiplier_pct"])

colors2 = ["#f28e2b" if k.startswith("s_") else "#b07fd4" for k in other_keys]
bars = ax.barh(range(len(labels)), vals, color=colors2, height=0.6)
ax.axvline(0, color="black", linewidth=0.8)
ax.set_yticks(range(len(labels)))
ax.set_yticklabels(labels)
ax.set_xlabel("Salary multiplier (%)")
ax.set_title("Salary Multiplier: Soft Skills & Seniority", fontweight="bold", fontsize=13)
for i, v in enumerate(vals):
    ax.text(v + (1 if v >= 0 else -1), i, f"{v:+.1f}%", va="center",
            ha="left" if v >= 0 else "right", fontweight="bold", fontsize=9)
ax.margins(x=0.15)

fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_salary_soft_seniority.png"), dpi=150)
plt.close(fig)

# ═══════════════════════════════════════════════════════════════
# FIG 3: Actual vs Predicted scatter
# ═══════════════════════════════════════════════════════════════
print("FIG 3: Actual vs Predicted")
fig, ax = plt.subplots(figsize=(7, 7))

actuals = np.array([p["actual_salary"] for p in predictions])
preds = np.array([p["predicted_salary"] for p in predictions])
lowers = np.array([p["lower_80"] for p in predictions])
uppers = np.array([p["upper_80"] for p in predictions])
grades = [p["grade"] for p in predictions]
inside = np.array([p["inside_80"] for p in predictions])

grades_a = np.array(grades)
for g in grade_order:
    mask = grades_a == g
    if not mask.any():
        continue
    ax.scatter(preds[mask], actuals[mask], c=grade_colors[g], label=g, alpha=0.6, s=25, edgecolors="none")

max_val = max(actuals.max(), preds.max())
ax.plot([0, max_val], [0, max_val], "k--", linewidth=0.8, alpha=0.5)
ax.set_xlabel("Predicted salary (RUB)")
ax.set_ylabel("Actual salary (RUB)")
ax.set_title("Predicted vs Actual Salary", fontweight="bold", fontsize=13)
ax.legend(fontsize=9)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))
ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))
ax.set_xlim(0, max_val * 1.05)
ax.set_ylim(0, max_val * 1.05)

fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_actual_vs_predicted.png"), dpi=150)
plt.close(fig)

# ═══════════════════════════════════════════════════════════════
# FIG 4: Prediction intervals (band plot for sorted vacancies)
# ═══════════════════════════════════════════════════════════════
print("FIG 4: Prediction intervals")
sorted_idx = np.argsort(actuals)
fig, ax = plt.subplots(figsize=(12, 5))

x = np.arange(len(sorted_idx))
ax.fill_between(x, lowers[sorted_idx], uppers[sorted_idx], alpha=0.3, color="#86bcfd", label="80% interval")
ax.plot(x, actuals[sorted_idx], "o", markersize=2, color="#e15759", label="Actual", alpha=0.7)
ax.plot(x, preds[sorted_idx], "-", linewidth=1.2, color="#4e79a7", label="Predicted", alpha=0.8)

ax.set_xlabel("Vacancies (sorted by actual salary)")
ax.set_ylabel("Salary (RUB)")
ax.set_title("Prediction Intervals for All Vacancies", fontweight="bold", fontsize=13)
ax.legend(fontsize=9)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))

fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_prediction_intervals.png"), dpi=150)
plt.close(fig)

# ═══════════════════════════════════════════════════════════════
# FIG 5: Per-grade sigma (error variance)
# ═══════════════════════════════════════════════════════════════
print("FIG 5: Per-grade sigma")
gs = coeffs["grade_sigma"]
fig, ax = plt.subplots(figsize=(7, 4))

labels_g = [g for g in grade_order if g in gs]
vals_g = [gs[g] for g in labels_g]
colors_g = [grade_colors[g] for g in labels_g]

bars = ax.bar(labels_g, vals_g, color=colors_g, width=0.5)
for bar, v in zip(bars, vals_g):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01, f"{v:.4f}",
            ha="center", fontweight="bold", fontsize=10)
ax.set_ylabel("σ (log-salary residual std)")
ax.set_title("Error Variance by Seniority Grade", fontweight="bold", fontsize=13)

fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_grade_sigma.png"), dpi=150)
plt.close(fig)

# ═══════════════════════════════════════════════════════════════
# FIG 6: Coverage by grade
# ═══════════════════════════════════════════════════════════════
print("FIG 6: Coverage by grade")
fig, ax = plt.subplots(figsize=(7, 4))

coverage_by_grade = {}
for g in grade_order:
    mask = grades_a == g
    if mask.any():
        cov = inside[mask].sum() / mask.sum() * 100
        coverage_by_grade[g] = cov

labels_c = list(coverage_by_grade.keys())
vals_c = list(coverage_by_grade.values())
colors_c = [grade_colors[g] for g in labels_c]

bars = ax.bar(labels_c, vals_c, color=colors_c, width=0.5)
ax.axhline(80, color="green", linewidth=1.5, linestyle="--", alpha=0.7, label="Target 80%")
for bar, v in zip(bars, vals_c):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, f"{v:.0f}%",
            ha="center", fontweight="bold", fontsize=10)
ax.set_ylabel("Coverage (%)")
ax.set_title("80% Prediction Interval Coverage by Grade", fontweight="bold", fontsize=13)
ax.set_ylim(0, 110)
ax.legend()

fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_coverage_by_grade.png"), dpi=150)
plt.close(fig)

# ═══════════════════════════════════════════════════════════════
# FIG 7: Mean prediction and interval bounds by grade (80% + 60%)
# ═══════════════════════════════════════════════════════════════
print("FIG 7: Mean prediction and interval bounds by grade")

fig, ax = plt.subplots(figsize=(8, 5))

pos = np.arange(len(grade_order))
pred_means = []
low80_list = []
high80_list = []
low60_list = []
high60_list = []

for g in grade_order:
    gv = [p for p in predictions if p["grade"] == g]
    if not gv:
        pred_means.append(0); low80_list.append(0); high80_list.append(0)
        low60_list.append(0); high60_list.append(0)
        continue
    pred_means.append(np.median([p["predicted_salary"] for p in gv]))
    low80_list.append(np.median([p["lower_80"] for p in gv]))
    high80_list.append(np.median([p["upper_80"] for p in gv]))
    low60_list.append(np.median([p["lower_60"] for p in gv]))
    high60_list.append(np.median([p["upper_60"] for p in gv]))

low80 = np.array(low80_list)
high80 = np.array(high80_list)
low60 = np.array(low60_list)
high60 = np.array(high60_list)

# 80% interval (lighter, wider)
for i, g in enumerate(grade_order):
    ax.plot([pos[i], pos[i]], [low80[i], high80[i]], color=grade_colors[g], linewidth=6, alpha=0.25, solid_capstyle="butt")

# 60% interval (darker, narrower)
for i, g in enumerate(grade_order):
    ax.plot([pos[i], pos[i]], [low60[i], high60[i]], color=grade_colors[g], linewidth=10, alpha=0.45, solid_capstyle="butt")

# Mean prediction with connecting line (gray)
ax.plot(pos, pred_means, "-", color="#888888", linewidth=1.5, alpha=0.7, zorder=4)
ax.scatter(pos, pred_means, color="black", s=60, zorder=5)

# Legend: per-grade colors + interval types + mean prediction
for g in grade_order:
    ax.plot([], [], color=grade_colors[g], linewidth=5, alpha=0.5, solid_capstyle="butt", label=g)
ax.scatter([], [], color="black", s=60, label="Медианный прогноз")
ax.plot([], [], color="#888888", linewidth=10, alpha=0.3, solid_capstyle="butt", label="80% интервал")
ax.plot([], [], color="#888888", linewidth=14, alpha=0.5, solid_capstyle="butt", label="60% интервал")
ax.legend(fontsize=9, ncol=2, loc="upper left")

ax.set_xticks(pos)
ax.set_xticklabels(grade_order)
ax.set_ylabel("Зарплата (RUB)")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))

fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_interval_width.png"), dpi=150)
plt.close(fig)

# ═══════════════════════════════════════════════════════════════
# FIG 8: Residuals distribution (standardized)
# ═══════════════════════════════════════════════════════════════
print("FIG 8: Residuals distribution")
fig, axes = plt.subplots(2, 3, figsize=(12, 7))
axes = axes.flatten()

for idx, g in enumerate(grade_order):
    ax = axes[idx]
    mask = grades_a == g
    if not mask.any():
        continue
    sigma_g = gs.get(g, 1)
    resid = (np.log(actuals[mask]) - np.log(preds[mask])) / sigma_g
    ax.hist(resid, bins=12, color=grade_colors[g], alpha=0.7, edgecolor="white", density=True)
    x_range = np.linspace(-3, 3, 100)
    ax.plot(x_range, 1/np.sqrt(2*np.pi) * np.exp(-x_range**2/2), "k--", linewidth=1, alpha=0.6)
    ax.set_xlim(-3.5, 3.5)
    ax.set_title(f"{g} (n={mask.sum()})", fontsize=10)
    ax.set_xlabel("Std residual")
    ax.set_ylabel("Density")
    ax.text(0.95, 0.95, f"σ={sigma_g:.3f}", transform=ax.transAxes, va="top", ha="right", fontsize=9)

if len(grade_order) < len(axes):
    axes[len(grade_order)].axis("off")

fig.suptitle("Standardized Residuals by Grade (vs N(0,1))", fontweight="bold", fontsize=13)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_residuals_distribution.png"), dpi=150)
plt.close(fig)

# ═══════════════════════════════════════════════════════════════
# FIG 9: Salary range by grade with model prediction overlay
# ═══════════════════════════════════════════════════════════════
print("FIG 9: Salary by grade with model overlay")
fig, ax = plt.subplots(figsize=(8, 5))

salary_by_grade = {g: [] for g in grade_order}
for p in predictions:
    g = p["grade"]
    if g in salary_by_grade:
        salary_by_grade[g].append(p["actual_salary"])

pos = np.arange(len(grade_order))
bp = ax.boxplot([salary_by_grade[g] for g in grade_order], positions=pos,
                widths=0.5, patch_artist=True)
for patch, color in zip(bp["boxes"], [grade_colors[g] for g in grade_order]):
    patch.set_facecolor(color)

pred_means = []
pred_lowers = []
pred_uppers = []
for g in grade_order:
    mask = grades_a == g
    if mask.any():
        pred_means.append(np.mean(preds[mask]))
        pred_lowers.append(np.mean(lowers[mask]))
        pred_uppers.append(np.mean(uppers[mask]))
    else:
        pred_means.append(0)
        pred_lowers.append(0)
        pred_uppers.append(0)

ax.errorbar(pos, pred_means, yerr=[np.array(pred_means) - np.array(pred_lowers),
                                     np.array(pred_uppers) - np.array(pred_means)],
            fmt="o", color="black", markersize=8, capsize=5, capthick=2, label="Model mean ± 80% CI")

ax.set_xticks(pos)
ax.set_xticklabels(grade_order)
ax.set_ylabel("Salary (RUB)")
ax.set_title("Salary Distribution by Grade with Model Overlay", fontweight="bold", fontsize=13)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))
ax.legend()

fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_salary_by_grade_model.png"), dpi=150)
plt.close(fig)

# ═══════════════════════════════════════════════════════════════
# FIG 10: Salary ranges with 80% prediction intervals
# ═══════════════════════════════════════════════════════════════
print("FIG 10: Salary ranges vs prediction intervals")

conn = psycopg2.connect(config.db_dsn)
cur = conn.cursor()
ids = tuple(p["vacancy_id"] for p in predictions)
cur.execute(f"""
    SELECT vacancy_id, salary_from_rub, salary_to_rub
    FROM vacancies
    WHERE vacancy_id IN ({','.join(['%s'] * len(ids))})
""", ids)
db_map = {row[0]: (float(row[1]) if row[1] else None, float(row[2]) if row[2] else None) for row in cur.fetchall()}
cur.close()
conn.close()

plot_data = []
for p in predictions:
    vid = p["vacancy_id"]
    sfr, sto = db_map.get(vid, (None, None))
    midpoint = p["actual_salary"]
    plot_data.append({
        "midpoint": midpoint,
        "sfr": sfr or midpoint,
        "sto": sto or midpoint,
        "lower_80": p["lower_80"],
        "upper_80": p["upper_80"],
        "grade": p["grade"],
    })

plot_data.sort(key=lambda x: x["midpoint"])

fig, ax = plt.subplots(figsize=(16, 7))
n = len(plot_data)
x = np.arange(n)

sfr_vals = np.array([d["sfr"] for d in plot_data])
sto_vals = np.array([d["sto"] for d in plot_data])
ax.fill_between(x, sfr_vals, sto_vals, alpha=0.2, color="#86bcfd", label="Actual salary range (from–to)")

lower_vals = np.array([d["lower_80"] for d in plot_data])
upper_vals = np.array([d["upper_80"] for d in plot_data])
ax.fill_between(x, lower_vals, upper_vals, alpha=0.4, color="#fd9e9e", label="80% prediction interval")

mid_vals = np.array([d["midpoint"] for d in plot_data])
ax.plot(x, mid_vals, "-", linewidth=0.8, color="#4e79a7", alpha=0.7, label="Salary midpoint")

ax.set_xlabel("Vacancies (sorted by salary)", fontsize=12)
ax.set_ylabel("Salary (RUB)", fontsize=12)
# (no title)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))
ax.legend(fontsize=11, loc="upper left")
ax.margins(x=0.01)

grade_ranges = Counter(d["grade"] for d in plot_data)
y_pos = max(mid_vals) * 0.98
cum = 0
for g in ["Intern", "Junior", "Middle", "Senior", "Lead"]:
    cnt = grade_ranges.get(g, 0)
    if cnt == 0:
        continue
    ax.annotate(g, xy=(cum + cnt/2, y_pos), ha="center", va="top", fontsize=9,
                fontweight="bold", color="#555",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="gray", alpha=0.7))
    cum += cnt

fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_salary_ranges.png"), dpi=150)
plt.close(fig)

# ═══════════════════════════════════════════════════════════════
# FIG 11: Salary ranges with 60% prediction intervals
# ═══════════════════════════════════════════════════════════════
print("FIG 11: Salary ranges (60% intervals)")

plot_data_60 = []
for p in predictions:
    vid = p["vacancy_id"]
    sfr, sto = db_map.get(vid, (None, None))
    midpoint = p["actual_salary"]
    plot_data_60.append({
        "midpoint": midpoint,
        "sfr": sfr or midpoint,
        "sto": sto or midpoint,
        "lower_60": p["lower_60"],
        "upper_60": p["upper_60"],
        "grade": p["grade"],
    })

plot_data_60.sort(key=lambda x: x["midpoint"])

fig, ax = plt.subplots(figsize=(16, 7))
n = len(plot_data_60)
x = np.arange(n)

sfr_vals = np.array([d["sfr"] for d in plot_data_60])
sto_vals = np.array([d["sto"] for d in plot_data_60])
ax.fill_between(x, sfr_vals, sto_vals, alpha=0.2, color="#86bcfd", label="Фактическая вилка (from–to)")

lower_vals = np.array([d["lower_60"] for d in plot_data_60])
upper_vals = np.array([d["upper_60"] for d in plot_data_60])
ax.fill_between(x, lower_vals, upper_vals, alpha=0.4, color="#59a14f", label="60% prediction interval")

mid_vals = np.array([d["midpoint"] for d in plot_data_60])
ax.plot(x, mid_vals, "-", linewidth=0.8, color="#4e79a7", alpha=0.7, label="Зарплата")

ax.set_xlabel("Vacancies (sorted by salary)", fontsize=12)
ax.set_ylabel("Salary (RUB)", fontsize=12)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))
ax.legend(fontsize=11, loc="upper left")
ax.margins(x=0.01)

grade_ranges = Counter(d["grade"] for d in plot_data_60)
y_pos = max(mid_vals) * 0.98
cum = 0
for g in ["Intern", "Junior", "Middle", "Senior", "Lead"]:
    cnt = grade_ranges.get(g, 0)
    if cnt == 0:
        continue
    ax.annotate(g, xy=(cum + cnt/2, y_pos), ha="center", va="top", fontsize=9,
                fontweight="bold", color="#555",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="gray", alpha=0.7))
    cum += cnt

fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig_salary_ranges_60pct.png"), dpi=150)
plt.close(fig)

print(f"\nAll figures saved to {OUT}")
