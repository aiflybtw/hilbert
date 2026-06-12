"""
grade_model.py — Model B
Weighted ordinal grade prediction with kNN experience imputation.
"""

import json, os, sys
import numpy as np
from collections import defaultdict
from sklearn.metrics import accuracy_score
from sklearn.linear_model import LogisticRegression
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
import psycopg2

BASE = os.path.dirname(__file__)
DATA = os.path.join(BASE, "..", "data")
CLUSTER = os.path.join(DATA, "clustering")
OUT = os.path.join(DATA, "figures")
os.makedirs(OUT, exist_ok=True)

sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn
S_CLUSTER_IDS = list(range(1, 7))
SENIORITY_ORDER = ["Intern", "Junior", "Middle", "Senior", "Lead"]
GRADE_PALETTE = {"Intern": "#86bcfd", "Junior": "#8cdba0", "Middle": "#f9c97c",
                 "Senior": "#fd9e9e", "Lead": "#b07fd4"}

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "#f8f9fa",
    "axes.grid": False, "font.size": 11,
})

# ── Load embeddings + clusters ──
print("Loading embeddings...")
hs_embeddings = np.load(os.path.join(CLUSTER, "embeddings.npy"))
with open(os.path.join(CLUSTER, "skill_names.json")) as f:
    skill_names = json.load(f)
skill_to_idx = {n: i for i, n in enumerate(skill_names)}
print(f"  {hs_embeddings.shape[0]} skills x {hs_embeddings.shape[1]}")

with open(os.path.join(CLUSTER, "skill_to_cluster_final_model.json")) as f:
    skill_to_cluster = json.load(f)
with open(os.path.join(CLUSTER, "clusters_final_model.json")) as f:
    clusters_final = json.load(f)
N_CLUSTER_IDS = sorted(clusters_final["cluster_info"].keys(),
                       key=lambda c: -clusters_final["cluster_info"][c]["size"])
N_CLUSTER_SHORT = {cid: info["name"] for cid, info in clusters_final["cluster_info"].items()}
print(f"  {len(N_CLUSTER_IDS)} hard clusters")

ss_embeddings = np.load(os.path.join(DATA, "soft_skills_embeddings.npy"))
with open(os.path.join(DATA, "soft_skills_names.json")) as f:
    ss_names = json.load(f)
ss_name_to_idx = {n: i for i, n in enumerate(ss_names)}
with open(os.path.join(DATA, "soft_skills_llm_clusters.json")) as f:
    soft_skill_clusters = json.load(f)

# ── Load vacancies ──
print("\nLoading vacancies...")
conn = psycopg2.connect(DB_DSN)
cur = conn.cursor()
cur.execute("""
    SELECT vacancy_id, hard_skills_json, soft_skills_json, soft_clusters,
           seniority_grade,
           skills_extracted->'experience'->>'min_years' as min_years
    FROM vacancies
    WHERE seniority_grade IS NOT NULL AND seniority_grade != ''
      AND hard_skills_json IS NOT NULL AND hard_skills_json != '[]'::jsonb
""")
rows = cur.fetchall()
cur.close()
conn.close()
print(f"  {len(rows)} raw")

# ── Parse ──
vacancies_raw = []
for r in rows:
    vid, hsj, ssj, sc, sg, my = r
    grade = sg if sg in ["Intern", "Junior", "Middle", "Middle/Senior", "Senior", "Lead"] else None
    if grade is None:
        continue
    try:
        min_y = float(my) if my is not None else None
    except (ValueError, TypeError):
        min_y = None
    vacancies_raw.append({
        "id": vid, "grade": grade, "min_years": min_y,
        "hard_skills": hsj if isinstance(hsj, list) else [],
        "soft_skills": ssj if isinstance(ssj, list) else [],
        "soft_clusters": sc if isinstance(sc, list) else [],
    })

print(f"  {len(vacancies_raw)} valid")

# ── Feature helpers ──
def cosine_sim_matrix(vectors):
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return (vectors / norms) @ (vectors / norms).T

def diversity_features(embeddings, name_to_idx, cluster_map, cluster_ids, vac_skills):
    feats = np.zeros(len(cluster_ids))
    idxs_by_cid = defaultdict(list)
    for s in vac_skills:
        name = s.get("name", "")
        if name in cluster_map:
            idx = name_to_idx.get(name)
            if idx is not None:
                idxs_by_cid[cluster_map[name]].append(idx)
    for i, cid in enumerate(cluster_ids):
        idxs = idxs_by_cid.get(cid, [])
        k = len(idxs)
        if k == 0:
            feats[i] = 0.0
        elif k == 1:
            feats[i] = 1.0
        else:
            vecs = embeddings[idxs]
            sim = cosine_sim_matrix(vecs)
            upper = sim[np.triu_indices(k, k=1)]
            feats[i] = k * (1.0 - np.mean(upper))
        feats[i] = np.log1p(feats[i])
    return feats

# ── Compute skill feature matrix (no min_years yet) ──
print("\nComputing skill features...")
X_skill_list = []
for v in vacancies_raw:
    hs = diversity_features(hs_embeddings, skill_to_idx, skill_to_cluster,
                            N_CLUSTER_IDS, v["hard_skills"])
    ss = diversity_features(ss_embeddings, ss_name_to_idx,
                            soft_skill_clusters, S_CLUSTER_IDS, v["soft_skills"])
    X_skill_list.append(np.concatenate([hs, ss]))
X_skill = np.array(X_skill_list)

# ═══════════════════════════════════════════════
# STEP 1: kNN impute min_years
# ═══════════════════════════════════════════════
print("\n--- Step 1: kNN imputation of min_years ---")
from sklearn.neighbors import KNeighborsRegressor
known_mask = np.array([v["min_years"] is not None for v in vacancies_raw])
unknown_mask = ~known_mask
print(f"  Known min_years: {known_mask.sum()}, Missing: {unknown_mask.sum()}")

if unknown_mask.any():
    knn_imp = KNeighborsRegressor(n_neighbors=10, metric="euclidean")
    knn_imp.fit(X_skill[known_mask], np.array([v["min_years"] for v in vacancies_raw if v["min_years"] is not None]))
    imputed = knn_imp.predict(X_skill[unknown_mask])
    imp_idx = 0
    for i, v in enumerate(vacancies_raw):
        if v["min_years"] is None:
            v["min_years"] = float(max(imputed[imp_idx], 0.5))
            imp_idx += 1

# ═══════════════════════════════════════════════
# STEP 2: Build feature matrix + targets
# ═══════════════════════════════════════════════
vacancies = [v for v in vacancies_raw if v["grade"] in SENIORITY_ORDER]

X_list, y_list = [], []
for v in vacancies:
    hs = diversity_features(hs_embeddings, skill_to_idx, skill_to_cluster,
                            N_CLUSTER_IDS, v["hard_skills"])
    ss = diversity_features(ss_embeddings, ss_name_to_idx,
                            soft_skill_clusters, S_CLUSTER_IDS, v["soft_skills"])
    X_list.append(np.concatenate([hs, ss, [v["min_years"]]]))
    y_list.append(v["grade"])

X = np.array(X_list)
y = np.array(y_list)
grade_to_idx = {g: i for i, g in enumerate(SENIORITY_ORDER)}
y_ord = np.array([grade_to_idx[g] for g in y])

hs_names = [f"hs_{cid}" for cid in N_CLUSTER_IDS]
ss_names_f = [f"ss_{i}" for i in S_CLUSTER_IDS]
all_feature_names = hs_names + ss_names_f + ["min_years"]

print(f"\n  Final: {len(vacancies)} vacancies, {X.shape[1]} features")
for g in SENIORITY_ORDER:
    print(f"    {g}: {(y==g).sum()}")

# ═══════════════════════════════════════════════
# STEP 4: Class-weighted models
# ═══════════════════════════════════════════════
print("\n--- Step 4: Weighted models ---")

# Model 4a: statsmodels OrderedModel (unweighted, ordinal)
from statsmodels.miscmodels.ordinal_model import OrderedModel
mod_ord = OrderedModel(y_ord, X, distr='probit')
res_ord = mod_ord.fit(method='bfgs', disp=False)
probs_ord = res_ord.predict(X)
y_pred_ord = np.array([SENIORITY_ORDER[i] for i in np.argmax(probs_ord, axis=1)])

# Ordinal accuracy
def ordinal_metrics(y_true, y_pred, order):
    yt_num = np.array([order.index(g) for g in y_true])
    yp_num = np.array([order.index(g) for g in y_pred])
    acc = np.mean(yt_num == yp_num)
    adj_acc = np.mean(np.abs(yt_num - yp_num) <= 1)
    mae = np.mean(np.abs(yt_num - yp_num))
    return {"accuracy": float(acc), "adjacent_accuracy": float(adj_acc), "mean_ordinal_error": float(mae)}

print("\n  Model 4a: Ordered Probit (unweighted):")
m = ordinal_metrics(y, y_pred_ord, SENIORITY_ORDER)
for k, v in m.items():
    print(f"    {k}: {v:.4f}")

# Model 4b: sklearn LogisticRegression with class_weight='balanced' (multinomial)
clf = LogisticRegression(solver='lbfgs',
                         class_weight='balanced', max_iter=1000, random_state=42)
clf.fit(X, y)
y_pred_lr = clf.predict(X)
probs_lr = clf.predict_proba(X)

print("\n  Model 4b: LogisticRegression (class_weight='balanced'):")
m2 = ordinal_metrics(y, y_pred_lr, SENIORITY_ORDER)
for k, v in m2.items():
    print(f"    {k}: {v:.4f}")

# Model 4c: Ordered Probit with manual sample weights
# Approximate via weighted loss: duplicate minority class samples
class_counts = {g: (y == g).sum() for g in SENIORITY_ORDER}
max_count = max(class_counts.values())
weights = np.array([max_count / class_counts[g] for g in y])
# Statsmodels OrderedModel doesn't support sample_weight, but we can
# use sklearn's LogisticRegression with ordinal encoding via target order
# Alternative: oversample via numpy
np.random.seed(42)
idx_list = []
for g in SENIORITY_ORDER:
    mask = y == g
    idx_g = np.where(mask)[0]
    # Oversample to match max_count
    if len(idx_g) < max_count:
        idx_g = np.concatenate([idx_g, np.random.choice(idx_g, max_count - len(idx_g), replace=True)])
    idx_list.append(idx_g)
oversample_idx = np.concatenate(idx_list)
X_bal = X[oversample_idx]
y_bal = y[oversample_idx]
y_bal_ord = np.array([grade_to_idx[g] for g in y_bal])

mod_bal = OrderedModel(y_bal_ord, X_bal, distr='probit')
res_bal = mod_bal.fit(method='bfgs', disp=False)
probs_bal = res_bal.predict(X)  # Predict on original
y_pred_bal = np.array([SENIORITY_ORDER[i] for i in np.argmax(probs_bal, axis=1)])

print("\n  Model 4c: Ordered Probit (oversampled):")
m3 = ordinal_metrics(y, y_pred_bal, SENIORITY_ORDER)
for k, v in m3.items():
    print(f"    {k}: {v:.4f}")

# Best model → use for visualizations
best_model = clf
y_pred = y_pred_lr
probs = probs_lr

# ═══════════════════════════════════════════════
# STEP 5: Detailed metrics
# ═══════════════════════════════════════════════
print("\n--- Step 5: Detailed report ---")
from sklearn.metrics import confusion_matrix, classification_report
cm = confusion_matrix(y, y_pred, labels=SENIORITY_ORDER)
print(f"\n  Best model: LogisticRegression (class_weight='balanced')")
print(f"  Accuracy:          {m2['accuracy']:.4f}  ({(y_pred == y).sum()}/{len(y)})")
print(f"  Adjacent accuracy: {m2['adjacent_accuracy']:.4f}")
print(f"  Mean ordinal error:{m2['mean_ordinal_error']:.4f}")
print(f"\n  Classification report:")
print(classification_report(y, y_pred, labels=SENIORITY_ORDER, zero_division=0))

# Per-grade accuracy
print(f"\n  Per-grade metrics:")
for g in SENIORITY_ORDER:
    mask = y == g
    if mask.sum() == 0:
        continue
    acc_g = (y_pred[mask] == g).sum() / mask.sum()
    adj_g = (np.abs([SENIORITY_ORDER.index(y_pred[i]) - SENIORITY_ORDER.index(g) for i in np.where(mask)[0]]) <= 1).mean()
    print(f"    {g:10s}  n={mask.sum():>3d}  acc={acc_g:.3f}  adj_acc={adj_g:.3f}")

# ═══════════════════════════════════════════════
# STEP 6: Standardization + AME + Top skills per grade
# ═══════════════════════════════════════════════
print("\n--- Step 6: AME and top skills per grade ---")
from sklearn.preprocessing import StandardScaler
from scipy.stats import norm as norm_dist

scaler = StandardScaler()
Xs = scaler.fit_transform(X)

# Ordinal probit on standardized features
mod_s = OrderedModel(y_ord, Xs, distr='probit')
res_s = mod_s.fit(method='bfgs', disp=False)

# Extract thresholds and coefficients
n_coefs = Xs.shape[1]
beta = np.array(res_s.params[:n_coefs])
thresholds = np.concatenate([[-np.inf], np.array(res_s.params[n_coefs:]), [np.inf]])

# AME: ∂P(Y=j)/∂X_k = [φ(τ_{j-1} - Xβ) - φ(τ_j - Xβ)] * β_k
def compute_ame(beta, thresholds, X):
    n, k = X.shape
    n_grades = len(thresholds) - 1
    xb = X @ beta
    ame = np.zeros((n_grades, k))
    for j in range(n_grades):
        phi_low = norm_dist.pdf(thresholds[j] - xb)
        phi_high = norm_dist.pdf(thresholds[j + 1] - xb)
        me = (phi_low - phi_high)[:, np.newaxis] * beta[np.newaxis, :]
        ame[j] = me.mean(axis=0)
    return ame

ame = compute_ame(beta, thresholds, Xs)

# Print AME table
print(f"\n  AME (Average Marginal Effect) table:\n")
print(f"  {'Feature':35s}", end="")
for g in SENIORITY_ORDER:
    print(f"  {g:>10s}", end="")
print()
print("  " + "-" * 90)
for fi, name in enumerate(all_feature_names):
    short_name = name.replace("hs_", "").replace("ss_", "SoftS")
    print(f"  {short_name:35s}", end="")
    for j in range(len(SENIORITY_ORDER)):
        print(f"  {ame[j, fi]:+10.4f}", end="")
    print()

# Load skill lists per cluster
cluster_skills = defaultdict(list)
with open(os.path.join(CLUSTER, "skill_to_cluster_final_model.json")) as f:
    skill_to_cid = json.load(f)
for skill, cid in skill_to_cid.items():
    cluster_skills[cid].append(skill)

cluster_names = {cid: info["name"] for cid, info in clusters_final["cluster_info"].items()}

# Soft skills per cluster
ss_cluster_skills = defaultdict(list)
with open(os.path.join(DATA, "soft_skills_llm_clusters.json")) as f:
    ss_skill_to_cid = json.load(f)
for skill, cid in ss_skill_to_cid.items():
    ss_cluster_skills[str(cid)].append(skill)

ss_cluster_names = {
    "1": "Коллаборация", "2": "Системное мышление", "3": "Обучаемость",
    "4": "Лидерство", "5": "Ответственность", "6": "Наставничество"
}

# Extract top skills per grade based on distinctive AME profile
print(f"\n  Top skills by grade (from AME profile):\n")
top_skills_report = {}

# For each feature, find which grade it "boosts" most (max AME)
feature_anchor = {}
for fi, name in enumerate(all_feature_names):
    anchor_j = np.argmax(ame[:, fi])
    feature_anchor[name] = anchor_j

# For each grade, collect its anchor features sorted by AME
for j, g in enumerate(SENIORITY_ORDER):
    # Hard skills anchored to this grade
    hs_anchored = []
    for fi in range(len(hs_names)):
        if feature_anchor[all_feature_names[fi]] == j:
            hs_anchored.append((fi, ame[j, fi]))
    hs_anchored.sort(key=lambda x: -x[1])
    top_hs_cids = [all_feature_names[fi].replace("hs_", "") for fi, _ in hs_anchored[:5]]

    # Soft skills anchored to this grade
    ss_anchored = []
    for fi in range(len(hs_names), len(hs_names) + len(ss_names_f)):
        if feature_anchor[all_feature_names[fi]] == j:
            ss_anchored.append((fi, ame[j, fi]))
    ss_anchored.sort(key=lambda x: -x[1])
    top_ss_cids = [str(all_feature_names[fi].replace("ss_", "")) for fi, _ in ss_anchored[:3]]

    report = {"hard": [], "soft": []}
    print(f"  {g}:")
    print(f"    Hard skills:")
    for cid in top_hs_cids:
        skills_list = cluster_skills.get(cid, [])[:5]
        cname = cluster_names.get(cid, cid)
        print(f"      {cname}: {', '.join(skills_list)}")
        report["hard"].append({"cluster": cname, "examples": skills_list[:5]})
    print(f"    Soft skills:")
    for cid in top_ss_cids:
        skills_list = ss_cluster_skills.get(cid, [])[:3]
        cname = ss_cluster_names.get(cid, cid)
        print(f"      {cname}: {', '.join(skills_list)}")
        report["soft"].append({"cluster": cname, "examples": skills_list[:3]})
    print()
    top_skills_report[g] = report

# Also try L1-regularized model (sklearn with L1)
print("\n  L1-regularized LogisticRegression (+ standardization, C=1.0):")
clf_l1 = LogisticRegression(l1_ratio=1, solver='saga', C=1.0, max_iter=2000, random_state=42)
clf_l1.fit(Xs, y)
y_pred_l1 = clf_l1.predict(Xs)
n_nonzero = np.sum(np.any(np.abs(clf_l1.coef_) > 1e-5, axis=0))
m_l1 = ordinal_metrics(y, y_pred_l1, SENIORITY_ORDER)
print(f"    Accuracy: {m_l1['accuracy']:.4f}, Adj acc: {m_l1['adjacent_accuracy']:.4f}, MEO: {m_l1['mean_ordinal_error']:.4f}")
print(f"    Non-zero features: {n_nonzero}/{Xs.shape[1]}")
# Tune C via simple grid
print(f"\n  L1 regularization path:")
for C in [0.01, 0.1, 1.0, 10.0, 100.0]:
    clf_tmp = LogisticRegression(l1_ratio=1, solver='saga', C=C, max_iter=2000, random_state=42)
    clf_tmp.fit(Xs, y)
    nnz = np.sum(np.any(np.abs(clf_tmp.coef_) > 1e-5, axis=0))
    yp = clf_tmp.predict(Xs)
    m_tmp = ordinal_metrics(y, yp, SENIORITY_ORDER)
    print(f"    C={C:>6.2f}  acc={m_tmp['accuracy']:.4f}  adj={m_tmp['adjacent_accuracy']:.4f}  nnz={nnz}/{Xs.shape[1]}")

# ═══════════════════════════════════════════════
# STEP 7: Visualizations
# ═══════════════════════════════════════════════
print("\nSaving visualizations...")

# FIG 1: Confusion matrix
print("  FIG 1: Confusion matrix")
fig, ax = plt.subplots(figsize=(7, 6))
sns.heatmap(cm, annot=True, fmt="d", cmap="Blues",
            xticklabels=SENIORITY_ORDER, yticklabels=SENIORITY_ORDER, ax=ax)
ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
ax.set_title("Model B: Confusion Matrix (weighted LR)", fontweight="bold", fontsize=13)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_model_b_confusion.png"), dpi=150); plt.close(fig)

# FIG 2: Feature importance
print("  FIG 2: Feature importance")
coef_values = np.concatenate([clf.coef_[0], [0]]) if clf.coef_.shape[0] > 1 else clf.coef_[0]
# Use first class vs rest or average absolute across classes
coef_avg = np.mean(np.abs(clf.coef_), axis=0)
coef_series = {all_feature_names[i]: coef_avg[i] for i in range(len(all_feature_names))}
coef_sorted = sorted(coef_series.items(), key=lambda x: -abs(x[1]))
fig, ax = plt.subplots(figsize=(8, 6))
def short(n):
    if n.startswith("hs_"):
        return N_CLUSTER_SHORT.get(n[3:], n[3:])
    if n.startswith("ss_"):
        return f"Soft S{n[3:]}"
    return n
labels_c = [short(k) for k, v in coef_sorted]
vals_c = [v for k, v in coef_sorted]
colors_c = ["#4e79a7" if v >= 0 else "#e15759" for v in vals_c]
ax.barh(range(len(labels_c)), vals_c, color=colors_c, height=0.7)
ax.axvline(0, color="black", linewidth=0.8)
ax.set_yticks(range(len(labels_c)))
ax.set_yticklabels(labels_c)
ax.set_xlabel("Mean |Coefficient| (logistic)")
ax.set_title("Model B: Feature Importance", fontweight="bold", fontsize=13)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_model_b_feature_importance.png"), dpi=150); plt.close(fig)

# FIG 3: Probability distribution
print("  FIG 3: Probability distribution")
fig, axes = plt.subplots(1, len(SENIORITY_ORDER), figsize=(14, 4))
for idx, g in enumerate(SENIORITY_ORDER):
    ax = axes[idx]
    mask = y == g
    if mask.sum() == 0:
        ax.set_title(f"{g} (0)"); continue
    mean_p = probs[mask].mean(axis=0)
    colors_p = [GRADE_PALETTE[g2] for g2 in SENIORITY_ORDER]
    ax.bar(range(len(SENIORITY_ORDER)), mean_p, color=colors_p, width=0.6, edgecolor="white")
    ax.set_xticks(range(len(SENIORITY_ORDER)))
    ax.set_xticklabels(SENIORITY_ORDER, fontsize=7, rotation=45)
    ax.set_ylim(0, 1); ax.set_ylabel("Mean prob")
    ax.set_title(f"Actual: {g} (n={mask.sum()})", fontsize=10)
fig.suptitle("Model B: Predicted Probabilities by Grade", fontweight="bold", fontsize=13)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_model_b_probabilities.png"), dpi=150); plt.close(fig)

# FIG 4: min_years distribution
print("  FIG 4: min_years by grade")
fig, ax = plt.subplots(figsize=(7, 4))
data_by_grade = {g: [] for g in SENIORITY_ORDER}
for v in vacancies:
    data_by_grade[v["grade"]].append(v["min_years"])
pos = np.arange(len(SENIORITY_ORDER))
bp = ax.boxplot([data_by_grade[g] for g in SENIORITY_ORDER], positions=pos, widths=0.5, patch_artist=True)
for patch, g in zip(bp["boxes"], SENIORITY_ORDER):
    patch.set_facecolor(GRADE_PALETTE[g])
for med in bp["medians"]:
    med.set_color("black"); med.set_linewidth(2)
ax.set_xticks(pos); ax.set_xticklabels(SENIORITY_ORDER)
ax.set_ylabel("min_years (kNN imputed)")
ax.set_title("Model B: Experience by Grade", fontweight="bold", fontsize=13)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_model_b_experience.png"), dpi=150); plt.close(fig)

# FIG 5: Correct vs wrong
print("  FIG 5: Correct vs wrong")
fig, ax = plt.subplots(figsize=(7, 4))
correct_counts = defaultdict(int)
wrong_counts = defaultdict(int)
for a, p in zip(y, y_pred):
    (correct_counts if a == p else wrong_counts)[a] += 1
pos = np.arange(len(SENIORITY_ORDER))
corr = [correct_counts.get(g, 0) for g in SENIORITY_ORDER]
wrong = [wrong_counts.get(g, 0) for g in SENIORITY_ORDER]
ax.bar(pos - 0.2, corr, 0.35, color="#4e79a7", label="Correct")
ax.bar(pos + 0.2, wrong, 0.35, color="#e15759", label="Wrong")
for i, (c, w) in enumerate(zip(corr, wrong)):
    if c + w > 0:
        ax.text(i - 0.2, c + 1, str(c), ha="center", fontsize=8, fontweight="bold")
        ax.text(i + 0.2, w + 1, str(w), ha="center", fontsize=8, fontweight="bold")
ax.set_xticks(pos); ax.set_xticklabels(SENIORITY_ORDER)
ax.set_ylabel("Count"); ax.legend()
ax.set_title("Model B: Correct vs Wrong by Grade", fontweight="bold", fontsize=13)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_model_b_accuracy_by_grade.png"), dpi=150); plt.close(fig)

# FIG 6: Mistake heatmap
print("  FIG 6: Mistake heatmap")
mistake_cm = np.zeros((len(SENIORITY_ORDER), len(SENIORITY_ORDER)), dtype=int)
for a, p in zip(y, y_pred):
    i, j = SENIORITY_ORDER.index(a), SENIORITY_ORDER.index(p)
    if i != j:
        mistake_cm[i, j] += 1
fig, ax = plt.subplots(figsize=(6, 5))
sns.heatmap(mistake_cm, annot=True, fmt="d", cmap="Reds",
            xticklabels=SENIORITY_ORDER, yticklabels=SENIORITY_ORDER, ax=ax)
ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
ax.set_title("Model B: Misclassification", fontweight="bold", fontsize=13)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_model_b_mistakes.png"), dpi=150); plt.close(fig)

# ═══════════════════════════════════════════════
# Save results
# ═══════════════════════════════════════════════
print("\nSaving results...")
results = {
    "model": "LogisticRegression (class_weight=balanced)",
    "imputation": "kNN (k=5, skill features)",
    "middle_senior_merge": True,
    "n_train": len(y),
    "grade_order": SENIORITY_ORDER,
    "grade_distribution": {g: int((y == g).sum()) for g in SENIORITY_ORDER},
    "metrics": {**m2,
        "accuracy_ord_probit": m["accuracy"],
        "adjacent_accuracy_ord_probit": m["adjacent_accuracy"],
        "accuracy_ord_oversampled": m3["accuracy"],
        "adjacent_accuracy_ord_oversampled": m3["adjacent_accuracy"],
    },
}
with open(os.path.join(DATA, "salary_model", "grade_model_b_results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print("Done.")
