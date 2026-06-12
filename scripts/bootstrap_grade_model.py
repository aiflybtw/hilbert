"""
bootstrap_grade_model.py — Bootstrap CI for grade discriminant coefficients.
Matches the methodology used in grade_discriminant_analysis.md:
- known min_years only, Intern=0 forced
- LogisticRegression class_weight='balanced' on raw X
- Stratified bootstrap (1000 iter), 95% percentile CI
"""

import json, os, sys
import numpy as np
from collections import defaultdict
from sklearn.linear_model import LogisticRegression

BASE = os.path.dirname(__file__)
DATA = os.path.join(BASE, "..", "data")
CLUSTER = os.path.join(DATA, "clustering")

sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn
S_CLUSTER_IDS = list(range(1, 7))
SENIORITY_ORDER = ["Intern", "Junior", "Middle", "Senior", "Lead"]
N_BOOTSTRAP = 1000
SEED = 42

np.random.seed(SEED)

# ── Load embeddings + clusters ──
hs_embeddings = np.load(os.path.join(CLUSTER, "embeddings.npy"))
with open(os.path.join(CLUSTER, "skill_names.json")) as f:
    skill_names = json.load(f)
skill_to_idx = {n: i for i, n in enumerate(skill_names)}

with open(os.path.join(CLUSTER, "skill_to_cluster_final_model.json")) as f:
    skill_to_cluster = json.load(f)
with open(os.path.join(CLUSTER, "clusters_final_model.json")) as f:
    clusters_final = json.load(f)
N_CLUSTER_IDS = sorted(clusters_final["cluster_info"].keys(),
                       key=lambda c: -clusters_final["cluster_info"][c]["size"])
N_CLUSTER_SHORT = {cid: info["name"] for cid, info in clusters_final["cluster_info"].items()}

ss_embeddings = np.load(os.path.join(DATA, "soft_skills_embeddings.npy"))
with open(os.path.join(DATA, "soft_skills_names.json")) as f:
    ss_names = json.load(f)
ss_name_to_idx = {n: i for i, n in enumerate(ss_names)}
with open(os.path.join(DATA, "soft_skills_llm_clusters.json")) as f:
    soft_skill_clusters = json.load(f)

ss_cluster_names = {
    "1": "Коллаборация", "2": "Системное мышление", "3": "Обучаемость",
    "4": "Лидерство", "5": "Ответственность", "6": "Наставничество"
}

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

# ── Load vacancies (known min_years only, Intern=0 forced) ──
import psycopg2
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

vacancies = []
for r in rows:
    vid, hsj, ssj, sc, sg, my = r
    grade = sg if sg in SENIORITY_ORDER else None
    if grade is None:
        continue
    try:
        min_y = float(my) if my is not None else None
    except (ValueError, TypeError):
        min_y = None
    # Intern: always include, force min_years=0
    if grade == "Intern":
        min_y = 0.0
    elif min_y is None:
        continue  # non-Intern: only known min_years
    vacancies.append({
        "id": vid, "grade": grade, "min_years": min_y,
        "hard_skills": hsj if isinstance(hsj, list) else [],
        "soft_skills": ssj if isinstance(ssj, list) else [],
        "soft_clusters": sc if isinstance(sc, list) else [],
    })

print(f"Vacancies with known min_years: {len(vacancies)}")
for g in SENIORITY_ORDER:
    print(f"  {g}: {sum(1 for v in vacancies if v['grade'] == g)}")

# ── Build feature matrix ──
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

hs_names = [f"hs_{cid}" for cid in N_CLUSTER_IDS]
ss_names_f = [f"ss_{i}" for i in S_CLUSTER_IDS]
all_feature_names = hs_names + ss_names_f + ["min_years"]
n_features = X.shape[1]

print(f"Feature matrix: {X.shape}")

# ── Standardize features ──
from sklearn.preprocessing import StandardScaler
scaler = StandardScaler()
Xs = scaler.fit_transform(X)

# ── Fit full model on standardized features ──
clf = LogisticRegression(solver='lbfgs', class_weight='balanced',
                         max_iter=1000, random_state=42)
clf.fit(Xs, y)
# Map from sklearn alphabetical class order → SENIORITY_ORDER
class_to_idx = {c: i for i, c in enumerate(clf.classes_)}
idx_map = [class_to_idx[g] for g in SENIORITY_ORDER]
full_coefs = clf.coef_[idx_map]  # (5 grades, 31 features) in SENIORITY_ORDER

# ── Bootstrap ──
grade_indices = {g: np.where(y == g)[0] for g in SENIORITY_ORDER}
grade_counts = {g: len(grade_indices[g]) for g in SENIORITY_ORDER}

boot_coefs = np.zeros((N_BOOTSTRAP, len(SENIORITY_ORDER), n_features))
failed = 0

# OOB predictions accumulator: for each obs, list of (predicted, actual)
oob_predictions = [[] for _ in range(len(y))]

for b in range(N_BOOTSTRAP):
    idx = []
    oob_mask = np.ones(len(y), dtype=bool)
    for g in SENIORITY_ORDER:
        idx_g = np.random.choice(grade_indices[g], size=grade_counts[g], replace=True)
        idx.append(idx_g)
        # Mark selected indices as NOT OOB (but only unique — observation may be selected multiple times)
        unique_selected = np.unique(idx_g)
        oob_mask[unique_selected] = False
    idx = np.concatenate(idx)
    oob_idx = np.where(oob_mask)[0]

    try:
        clf_b = LogisticRegression(solver='lbfgs', class_weight='balanced',
                                   max_iter=1000, random_state=b)
        clf_b.fit(Xs[idx], y[idx])
        class_to_idx_b = {c: i for i, c in enumerate(clf_b.classes_)}
        idx_map_b = [class_to_idx_b[g] for g in SENIORITY_ORDER]
        boot_coefs[b] = clf_b.coef_[idx_map_b]

        # OOB predictions
        if len(oob_idx) > 0:
            y_oob_pred = clf_b.predict(Xs[oob_idx])
            for oi, yi in zip(oob_idx, y_oob_pred):
                oob_predictions[oi].append(yi)
    except Exception:
        boot_coefs[b] = np.nan
        failed += 1

if failed:
    print(f"Warning: {failed}/{N_BOOTSTRAP} bootstrap iterations failed")

# ── OOB metrics ──
# Majority vote per observation
y_oob_majority = []
y_oob_actual = []
for i, preds in enumerate(oob_predictions):
    if len(preds) == 0:
        continue
    from collections import Counter
    majority = Counter(preds).most_common(1)[0][0]
    y_oob_majority.append(majority)
    y_oob_actual.append(y[i])

y_oob_majority = np.array(y_oob_majority)
y_oob_actual = np.array(y_oob_actual)

# Overall OOB metrics
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, confusion_matrix
oob_acc = accuracy_score(y_oob_actual, y_oob_majority)

# Adjacent accuracy
oob_adj = np.mean(np.abs([SENIORITY_ORDER.index(a) - SENIORITY_ORDER.index(p)
                          for a, p in zip(y_oob_actual, y_oob_majority)]) <= 1)

# Mean ordinal error
oob_meo = np.mean([abs(SENIORITY_ORDER.index(a) - SENIORITY_ORDER.index(p))
                   for a, p in zip(y_oob_actual, y_oob_majority)])

# Per-grade metrics from OOB
oob_per_grade = {}
for g in SENIORITY_ORDER:
    mask = y_oob_actual == g
    n = mask.sum()
    if n == 0:
        oob_per_grade[g] = {"n": 0, "precision": 0, "recall": 0, "f1": 0, "adj_accuracy": 0}
        continue
    correct = (y_oob_majority[mask] == g).sum()
    adj_correct = sum(1 for a, p in zip(y_oob_actual[mask], y_oob_majority[mask])
                      if abs(SENIORITY_ORDER.index(a) - SENIORITY_ORDER.index(p)) <= 1)
    p, r, f, _ = precision_recall_fscore_support(y_oob_actual, y_oob_majority,
                                                  labels=SENIORITY_ORDER, zero_division=0)
    gi = SENIORITY_ORDER.index(g)
    oob_per_grade[g] = {
        "n": int(n),
        "precision": round(float(p[gi]), 3),
        "recall": round(float(r[gi]), 3),
        "f1": round(float(f[gi]), 3),
        "adj_accuracy": round(adj_correct / n, 3),
    }

# OOB confusion matrix
oob_cm = confusion_matrix(y_oob_actual, y_oob_majority, labels=SENIORITY_ORDER)

print(f"\nOOB metrics (n={len(y_oob_actual)}):")
print(f"  Accuracy: {oob_acc:.4f}")
print(f"  Adjacent accuracy: {oob_adj:.4f}")
print(f"  Mean ordinal error: {oob_meo:.4f}")
for g in SENIORITY_ORDER:
    m = oob_per_grade[g]
    print(f"  {g:10s} n={m['n']:>3d}  p={m['precision']:.3f}  r={m['recall']:.3f}  f1={m['f1']:.3f}  adj_acc={m['adj_accuracy']:.3f}")

# ── Compute CIs ──
ci_lo = np.nanpercentile(boot_coefs, 2.5, axis=0)  # (5, 31)
ci_hi = np.nanpercentile(boot_coefs, 97.5, axis=0)  # (5, 31)

# ── Save ──
# Build feature display names matching the document
hs_display = []
for cid in N_CLUSTER_IDS:
    name = N_CLUSTER_SHORT.get(cid, cid)
    # Truncate to match doc style (the doc uses some truncated names)
    if len(name) > 40:
        name = name[:39]
    hs_display.append(name)
ss_display = [ss_cluster_names[str(i)] for i in S_CLUSTER_IDS]
feature_display = hs_display + ss_display + ["min_years"]

output = {
    "n_vacancies": len(vacancies),
    "grade_distribution": {g: grade_counts[g] for g in SENIORITY_ORDER},
    "n_bootstrap": N_BOOTSTRAP,
    "n_failed": failed,
    "feature_order": feature_display,
    "grade_order": SENIORITY_ORDER,
    "coefficients": {},
    "ci_lo": {},
    "ci_hi": {},
    "oob_metrics": {
        "n_oob": int(len(y_oob_actual)),
        "accuracy": round(float(oob_acc), 4),
        "adjacent_accuracy": round(float(oob_adj), 4),
        "mean_ordinal_error": round(float(oob_meo), 4),
        "per_grade": oob_per_grade,
        "confusion_matrix": oob_cm.tolist(),
    },
}

for fi, fname in enumerate(feature_display):
    output["coefficients"][fname] = {}
    output["ci_lo"][fname] = {}
    output["ci_hi"][fname] = {}
    for gi, g in enumerate(SENIORITY_ORDER):
        output["coefficients"][fname][g] = round(float(full_coefs[gi, fi]), 3)
        output["ci_lo"][fname][g] = round(float(ci_lo[gi, fi]), 3)
        output["ci_hi"][fname][g] = round(float(ci_hi[gi, fi]), 3)

# Also compute CIs for Δβ
# Δβ has 4 transitions (I→J, J→M, M→S, S→L)
transitions = [(0, 1), (1, 2), (2, 3), (3, 4)]  # (lower_idx, higher_idx)
trans_names = ["Δβ I→J", "Δβ J→M", "Δβ M→S", "Δβ S→L"]

boot_delta = np.zeros((N_BOOTSTRAP, len(transitions), n_features))
for ti, (lo, hi) in enumerate(transitions):
    boot_delta[:, ti, :] = boot_coefs[:, hi, :] - boot_coefs[:, lo, :]

delta_ci_lo = np.nanpercentile(boot_delta, 2.5, axis=0)
delta_ci_hi = np.nanpercentile(boot_delta, 97.5, axis=0)

output["delta_ci_lo"] = {}
output["delta_ci_hi"] = {}
for ti, tname in enumerate(trans_names):
    output["delta_ci_lo"][tname] = {}
    output["delta_ci_hi"][tname] = {}
    for fi, fname in enumerate(feature_display):
        output["delta_ci_lo"][tname][fname] = round(float(delta_ci_lo[ti, fi]), 3)
        output["delta_ci_hi"][tname][fname] = round(float(delta_ci_hi[ti, fi]), 3)

with open(os.path.join(DATA, "salary_model", "bootstrap_ci.json"), "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\nSaved bootstrap CI to data/salary_model/bootstrap_ci.json")

# Quick summary of CI widths
print("\nAverage CI width by feature:")
for fi, fname in enumerate(feature_display):
    widths = []
    for gi, g in enumerate(SENIORITY_ORDER):
        w = ci_hi[gi, fi] - ci_lo[gi, fi]
        widths.append(w)
    avg_w = np.mean(widths)
    print(f"  {fname[:45]:45s} avg CI width={avg_w:.3f}")
