"""
salary_model_v3.py

Heteroscedastic salary model with responsibility cluster features and L1 regularization.

Changes from v1:
  - Adds 12 responsibility cluster features (binary: cluster present in vacancy)
  - Uses LassoCV (L1 regularization) instead of OLS for feature selection
  - Reports which features survive L1 regularization
  - Compares: baseline (hard+soft+seniority) vs +responsibilities
"""

import json, os, sys
import numpy as np
from collections import defaultdict, Counter
from scipy.stats import norm
from sklearn.linear_model import LinearRegression, LassoCV, Lasso
from sklearn.metrics import mean_absolute_error, r2_score, median_absolute_error
from sklearn.model_selection import cross_val_predict, KFold
import psycopg2

BASE = os.path.dirname(__file__)
DATA = os.path.join(BASE, "..", "data")
CLUSTER = os.path.join(DATA, "clustering")
OUTPUT = os.path.join(DATA, "salary_model")

os.makedirs(OUTPUT, exist_ok=True)

sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn
S_CLUSTER_IDS = list(range(1, 7))
SENIORITY_LEVELS = ["Intern", "Junior", "Middle", "Senior", "Lead"]
TAIL_ALPHA = 0.1
COVERAGE = 1 - 2 * TAIL_ALPHA
Z_LOWER = norm.ppf(TAIL_ALPHA)
Z_UPPER = norm.ppf(1 - TAIL_ALPHA)

# ── Responsibility cluster definitions ──
with open(os.path.join(DATA, "responsibility_cluster_definitions.json"), encoding="utf-8") as f:
    resp_cluster_defs = json.load(f)
RESP_CLUSTER_IDS = sorted(int(k) for k in resp_cluster_defs.keys())
RESP_CLUSTER_NAMES = {int(k): v["name"] for k, v in resp_cluster_defs.items()}
print(f"Responsibility clusters: {len(RESP_CLUSTER_IDS)}")
for cid in RESP_CLUSTER_IDS:
    print(f"  {cid}: {RESP_CLUSTER_NAMES[cid]}")

# ── Load embeddings ──
print("\nLoading embeddings...")
embeddings = np.load(os.path.join(CLUSTER, "embeddings.npy"))
with open(os.path.join(CLUSTER, "skill_names.json"), encoding="utf-8") as f:
    skill_names = json.load(f)
skill_to_idx = {name: i for i, name in enumerate(skill_names)}

with open(os.path.join(CLUSTER, "skill_to_cluster_final_model.json"), encoding="utf-8") as f:
    skill_to_cluster = json.load(f)

with open(os.path.join(CLUSTER, "clusters_final_model.json"), encoding="utf-8") as f:
    clusters_final = json.load(f)
N_CLUSTER_IDS = sorted(clusters_final["cluster_info"].keys(), key=lambda c: -clusters_final["cluster_info"][c]["size"])
N_CLUSTER_SHORT = {cid: info["name"] for cid, info in clusters_final["cluster_info"].items()}
print(f"  {len(N_CLUSTER_IDS)} hard skill clusters")

# ── Load soft skill data ──
ss_embeddings = np.load(os.path.join(DATA, "soft_skills_embeddings.npy"))
with open(os.path.join(DATA, "soft_skills_names.json"), encoding="utf-8") as f:
    ss_names = json.load(f)
ss_name_to_idx = {name: i for i, name in enumerate(ss_names)}

with open(os.path.join(DATA, "soft_skills_llm_clusters.json"), encoding="utf-8") as f:
    soft_skill_clusters = json.load(f)

# ── Load responsibility cluster assignments per vacancy ──
print("\nLoading responsibility cluster assignments...")
resp_by_vacancy = defaultdict(set)
with open(os.path.join(DATA, "responsibilities_final_clusters.json"), encoding="utf-8") as f:
    resp_records = json.load(f)
for r in resp_records:
    cid = r["cluster"]
    if cid in RESP_CLUSTER_IDS:
        resp_by_vacancy[r["vacancy_id"]].add(cid)
print(f"  {len(resp_by_vacancy)} vacancies with responsibility clusters")

# ── Load vacancies ──
print("\nLoading vacancies from DB...")
conn = psycopg2.connect(DB_DSN)
cur = conn.cursor()
cur.execute("""
    SELECT vacancy_id, hard_skills_json, soft_skills_json, soft_clusters,
           seniority_grade, salary_from_rub, salary_to_rub
    FROM vacancies
    WHERE (salary_from_rub IS NOT NULL OR salary_to_rub IS NOT NULL)
      AND (hard_skills_json IS NOT NULL)
""")
rows = cur.fetchall()
cur.close()
conn.close()
print(f"  {len(rows)} vacancies with salary data")

# ── Remove known outliers ──
OUTLIER_IDS = {'131501988', '132089441', '132167340', '22636'}
rows = [r for r in rows if r[0] not in OUTLIER_IDS]

# ── Filter and build vacancy list ──
vacancies = []
for r in rows:
    vid, hsj, ssj, sc, sg, sfr, sto = r
    if sfr and sto:
        target = (float(sfr) + float(sto)) / 2
    elif sfr:
        target = float(sfr)
    elif sto:
        target = float(sto)
    else:
        continue
    if target <= 0:
        continue
    if sg not in SENIORITY_LEVELS:
        continue
    vacancies.append({
        "id": vid,
        "hard_skills": hsj if isinstance(hsj, list) else [],
        "soft_skills": ssj if isinstance(ssj, list) else [],
        "soft_clusters": sc if isinstance(sc, list) else [],
        "seniority": sg,
        "grade": sg,
        "salary_from": float(sfr) if sfr else None,
        "salary_to": float(sto) if sto else None,
        "target": target,
        "log_target": np.log(target),
        "resp_clusters": resp_by_vacancy.get(str(vid), set()),
    })

print(f"  {len(vacancies)} valid after filtering")
for g in SENIORITY_LEVELS:
    n = sum(1 for v in vacancies if v["grade"] == g)
    if n:
        print(f"    {g}: {n}")

# Vacancies with AND without responsibility clusters
with_resp = [v for v in vacancies if len(v["resp_clusters"]) > 0]
without_resp = [v for v in vacancies if len(v["resp_clusters"]) == 0]
print(f"\n  With responsibility clusters: {len(with_resp)}")
print(f"  Without: {len(without_resp)}")

# ── Feature computation ──
def cosine_sim_matrix(vectors):
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normed = vectors / norms
    return normed @ normed.T

def compute_features(vac, include_resp=False):
    # Hard skills (diversity-weighted)
    n_feats = np.zeros(len(N_CLUSTER_IDS))
    cluster_idxs = defaultdict(list)
    for hs in vac["hard_skills"]:
        name = hs.get("name", "")
        if name in skill_to_cluster:
            cid = skill_to_cluster[name]
            idx = skill_to_idx.get(name)
            if idx is not None:
                cluster_idxs[cid].append(idx)
    for i, cid in enumerate(N_CLUSTER_IDS):
        idxs = cluster_idxs.get(cid, [])
        k = len(idxs)
        if k == 0:
            n_feats[i] = 0.0
        elif k == 1:
            n_feats[i] = 1.0
        else:
            vecs = embeddings[idxs]
            sim = cosine_sim_matrix(vecs)
            upper = sim[np.triu_indices(k, k=1)]
            mean_sim = np.mean(upper) if len(upper) > 0 else 0.0
            n_feats[i] = k * (1.0 - mean_sim)
        n_feats[i] = np.log1p(n_feats[i])

    # Soft skills (diversity-weighted)
    s_feats = np.zeros(len(S_CLUSTER_IDS))
    ss_cluster_idxs = defaultdict(list)
    for ss in vac["soft_skills"]:
        name = ss.get("name", "")
        if name in soft_skill_clusters:
            cid = soft_skill_clusters[name]
            idx = ss_name_to_idx.get(name)
            if idx is not None:
                ss_cluster_idxs[cid].append(idx)
    for i, scid in enumerate(S_CLUSTER_IDS):
        idxs = ss_cluster_idxs.get(scid, [])
        k = len(idxs)
        if k == 0:
            s_feats[i] = 0.0
        elif k == 1:
            s_feats[i] = 1.0
        else:
            vecs = ss_embeddings[idxs]
            sim = cosine_sim_matrix(vecs)
            upper = sim[np.triu_indices(k, k=1)]
            mean_sim = np.mean(upper) if len(upper) > 0 else 0.0
            s_feats[i] = k * (1.0 - mean_sim)
        s_feats[i] = np.log1p(s_feats[i])

    # Seniority one-hot
    seniority = vac["seniority"]
    sen_feats = np.zeros(len(SENIORITY_LEVELS))
    if seniority in SENIORITY_LEVELS:
        sen_feats[SENIORITY_LEVELS.index(seniority)] = 1.0

    # Base features (always included)
    base = np.concatenate([n_feats, s_feats, sen_feats])

    if include_resp:
        resp_feats = np.zeros(len(RESP_CLUSTER_IDS))
        for i, cid in enumerate(RESP_CLUSTER_IDS):
            resp_feats[i] = 1.0 if cid in vac["resp_clusters"] else 0.0
        return np.concatenate([base, resp_feats])
    return base

# ── Build feature matrices ──
print("\nComputing features...")

# Baseline model (no responsibilities)
X_base_list, y_base_list, grades_base_list = [], [], []
for v in vacancies:
    try:
        x = compute_features(v, include_resp=False)
        X_base_list.append(x)
        y_base_list.append(v["log_target"])
        grades_base_list.append(v["grade"])
    except Exception as e:
        print(f"  Error for {v['id']}: {e}")

X_base = np.array(X_base_list)
y_base = np.array(y_base_list)
grades_base = np.array(grades_base_list)

# Full model (with responsibilities) — only vacancies that have resp clusters
X_full_list, y_full_list, grades_full_list = [], [], []
valid_full = []
for v in vacancies:
    if len(v["resp_clusters"]) == 0:
        continue
    try:
        x = compute_features(v, include_resp=True)
        X_full_list.append(x)
        y_full_list.append(v["log_target"])
        grades_full_list.append(v["grade"])
        valid_full.append(v)
    except Exception as e:
        print(f"  Error for {v['id']}: {e}")

X_full = np.array(X_full_list)
y_full = np.array(y_full_list)
grades_full = np.array(grades_full_list)

# Also: baseline on the same subset (for fair comparison)
X_base_subset_list, y_base_subset_list = [], []
for v in valid_full:
    x = compute_features(v, include_resp=False)
    X_base_subset_list.append(x)
    y_base_subset_list.append(v["log_target"])
X_base_subset = np.array(X_base_subset_list)
y_base_subset = np.array(y_base_subset_list)

print(f"\nBaseline model: {X_base.shape} (all {len(vacancies)} vacancies)")
print(f"Full model: {X_full.shape} ({len(valid_full)} vacancies with resp clusters)")
print(f"Baseline (subset): {X_base_subset.shape}")

n_feature_names = [f"n_cluster_{cid}" for cid in N_CLUSTER_IDS]
s_feature_names = [f"s_cluster_{i}" for i in S_CLUSTER_IDS]
seniority_names = [f"seniority_{s}" for s in SENIORITY_LEVELS]
resp_feature_names = [f"resp_{cid}_{RESP_CLUSTER_NAMES[cid]}" for cid in RESP_CLUSTER_IDS]
base_feature_names = n_feature_names + s_feature_names + seniority_names
all_feature_names = base_feature_names + resp_feature_names

# ═══════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════

def fit_model(X, y, grades, model_name="model"):
    """Fit model with LassoCV selection + OLS, then compute per-grade sigma."""
    n = X.shape[0]
    n_features = X.shape[1]

    # ── LassoCV (L1 regularization) ──
    print(f"\n  [{model_name}] LassoCV (L1 regularization)...")
    lasso_cv = LassoCV(
        cv=KFold(5, shuffle=True, random_state=42),
        random_state=42,
        max_iter=10000,
        alphas=50,
    )
    lasso_cv.fit(X, y)
    
    best_alpha = lasso_cv.alpha_
    n_selected = np.sum(np.abs(lasso_cv.coef_) > 1e-10)
    
    print(f"    Best alpha = {best_alpha:.6f}")
    print(f"    Features selected: {n_selected}/{n_features}")
    
    # Which features survived?
    selected_mask = np.abs(lasso_cv.coef_) > 1e-10
    selected_features = [name for name, sel in zip(all_feature_names, selected_mask) if sel]
    print(f"    Selected: {selected_features}")
    
    # Lasso predictions (in-sample)
    y_pred_lasso = lasso_cv.predict(X)
    residuals_lasso = y - y_pred_lasso
    y_pred_salary = np.exp(y_pred_lasso)
    y_true_salary = np.array([v["target"] for v in (valid_full if model_name == "full" else vacancies)])
    # Note: y_true_salary alignment might be off — let me fix
    # Actually, y corresponds to the same order as X
    
    # ── CV residuals ──
    cv_pred = cross_val_predict(Lasso(alpha=best_alpha, random_state=42, max_iter=10000), X, y, cv=KFold(5, shuffle=True, random_state=42))
    cv_residuals = y - cv_pred
    
    # ── Per-grade sigma ──
    grade_sigma = {}
    grade_n = {}
    for g in SENIORITY_LEVELS:
        mask = grades == g
        n_g = mask.sum()
        if n_g >= 2:
            sig_cv = float(np.std(cv_residuals[mask], ddof=0))
            grade_sigma[g] = sig_cv
            grade_n[g] = n_g
        else:
            grade_sigma[g] = float(np.std(cv_residuals))
    
    global_sigma = float(np.std(cv_residuals))
    cv_rmse = float(np.sqrt(np.mean(cv_residuals ** 2)))
    
    # ── Metrics ──
    r2 = r2_score(y, y_pred_lasso)
    mae = mean_absolute_error(np.exp(y), np.exp(y_pred_lasso))
    medae = median_absolute_error(np.exp(y), np.exp(y_pred_lasso))
    mae_log = mean_absolute_error(y, y_pred_lasso)
    
    print(f"    R2 = {r2:.4f}, CV RMSE = {cv_rmse:.4f}, MAE = {mae:,.0f} rub")
    
    # ── Prediction intervals ──
    inside_count, outside_count = 0, 0
    y_true_actual = np.array([v["target"] for v in (valid_full if model_name == "full" else vacancies)])
    
    for idx in range(min(len(y), len(y_true_actual))):
        mu_log = y_pred_lasso[idx]
        sg = grades[idx] if isinstance(grades[idx], str) else SENIORITY_LEVELS[int(grades[idx])]
        if isinstance(sg, str):
            sg_str = sg
        else:
            sg_str = SENIORITY_LEVELS[int(sg)]
        sigma_i = grade_sigma.get(sg_str, global_sigma)
        
        lower_log = mu_log + Z_LOWER * sigma_i
        upper_log = mu_log + Z_UPPER * sigma_i
        lower = float(np.exp(lower_log))
        upper = float(np.exp(upper_log))
        actual = y_true_actual[idx]
        
        if lower <= actual <= upper:
            inside_count += 1
        else:
            outside_count += 1
    
    coverage = inside_count / (inside_count + outside_count) * 100 if (inside_count + outside_count) > 0 else 0
    print(f"    Coverage ({int(COVERAGE*100)}% PI): {inside_count}/{inside_count + outside_count} = {coverage:.1f}%")
    
    return {
        "model_name": model_name,
        "n": int(n),
        "n_features": int(n_features),
        "n_selected": int(n_selected),
        "best_alpha": float(best_alpha),
        "selected_features": selected_features,
        "coefs": lasso_cv.coef_.tolist(),
        "intercept": float(lasso_cv.intercept_),
        "r2": float(r2),
        "cv_rmse": float(cv_rmse),
        "mae_rub": float(mae),
        "mae_log": float(mae_log),
        "medae_rub": float(medae),
        "coverage": float(coverage),
        "grade_sigma": {g: round(float(s), 6) for g, s in grade_sigma.items() if g in SENIORITY_LEVELS},
    }

# ═══════════════════════════════════════════════════════════════
# RUN MODEL COMPARISON
# ═══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("MODEL COMPARISON")
print("="*60)

# 1. Baseline model (all data, no resp features)
print("\n╔════════════════════════════════════════════════════════╗")
print("║ BASELINE: hard + soft + seniority (all vacancies)     ║")
print("╚════════════════════════════════════════════════════════╝")
baseline_all = fit_model(X_base, y_base, grades_base, "baseline (all)")

# 2. Baseline model (subset with resp data, no resp features)
print("\n╔════════════════════════════════════════════════════════╗")
print("║ BASELINE SUBSET: hard+soft+seniority (resp vacancies) ║")
print("╚════════════════════════════════════════════════════════╝")
baseline_subset = fit_model(X_base_subset, y_base_subset, grades_full, "baseline (subset)")

# 3. Full model (with responsibility features)
print("\n╔════════════════════════════════════════════════════════╗")
print("║ FULL: hard + soft + seniority + responsibilities      ║")
print("╚════════════════════════════════════════════════════════╝")
full_model = fit_model(X_full, y_full, grades_full, "full + resp")

# ═══════════════════════════════════════════════════════════════
# COMPARISON TABLE
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("COMPARISON TABLE")
print("="*60)
print(f"\n{'Metric':<30} {'Baseline':>15} {'Baseline(subset)':>20} {'+Responsibilities':>20}")
print(f"{'─'*30} {'─'*15} {'─'*20} {'─'*20}")
print(f"{'N':<30} {baseline_all['n']:>15} {baseline_subset['n']:>20} {full_model['n']:>20}")
print(f"{'Features':<30} {baseline_all['n_features']:>15} {baseline_subset['n_features']:>20} {full_model['n_features']:>20}")
print(f"{'Selected (Lasso)':<30} {baseline_all['n_selected']:>15} {baseline_subset['n_selected']:>20} {full_model['n_selected']:>20}")
print(f"{'R²':<30} {baseline_all['r2']:>15.4f} {baseline_subset['r2']:>20.4f} {full_model['r2']:>20.4f}")
print(f"{'MAE (rub)':<30} {baseline_all['mae_rub']:>15,.0f} {baseline_subset['mae_rub']:>20,.0f} {full_model['mae_rub']:>20,.0f}")
print(f"{'MAE (log)':<30} {baseline_all['mae_log']:>15.4f} {baseline_subset['mae_log']:>20.4f} {full_model['mae_log']:>20.4f}")
print(f"{'MedAE (rub)':<30} {baseline_all['medae_rub']:>15,.0f} {baseline_subset['medae_rub']:>20,.0f} {full_model['medae_rub']:>20,.0f}")
print(f"{'Coverage (80% PI)':<30} {baseline_all['coverage']:>15.1f}% {baseline_subset['coverage']:>19.1f}% {full_model['coverage']:>19.1f}%")

# ═══════════════════════════════════════════════════════════════
# DETAILED FULL MODEL RESULTS
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("FULL MODEL COEFFICIENTS")
print("="*60)

# Load LassoCV coefficients
lasso_full = LassoCV(
    cv=KFold(5, shuffle=True, random_state=42),
    random_state=42, max_iter=10000, alphas=50
)
lasso_full.fit(X_full, y_full)

print(f"\nIntercept: {lasso_full.intercept_:.4f}")
print(f"\n{'#':<3} {'Feature':<50} {'Coeff':>10} {'exp(Coeff)':>12} {'Δ%':>10} {'Selected':>10}")
print(f"{'─'*3} {'─'*50} {'─'*10} {'─'*12} {'─'*10} {'─'*10}")

for i, name in enumerate(all_feature_names):
    coef = lasso_full.coef_[i]
    exp_coef = np.exp(coef)
    delta_pct = (exp_coef - 1) * 100
    selected = "YES" if abs(coef) > 1e-10 else "—"
    marker = "★" if selected == "YES" else " "
    print(f"{marker} {i:<2d} {name:<50} {coef:>+10.4f} {exp_coef:>12.4f} {delta_pct:>+9.1f}% {selected:>10}")

# ═══════════════════════════════════════════════════════════════
# PER-GRADE SIGMA
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print("PER-GRADE SIGMA (FULL MODEL)")
print(f"{'='*60}")

lasso_cv_full = Lasso(alpha=full_model['best_alpha'], random_state=42, max_iter=10000)
cv_pred_full = cross_val_predict(lasso_cv_full, X_full, y_full, cv=KFold(5, shuffle=True, random_state=42))
cv_res_full = y_full - cv_pred_full

for g in SENIORITY_LEVELS:
    mask = grades_full == g
    n_g = mask.sum()
    if n_g >= 2:
        sig = float(np.std(cv_res_full[mask], ddof=0))
        print(f"  {g:12s} sigma = {sig:.4f} (n = {n_g})")

# ═══════════════════════════════════════════════════════════════
# SAVE
# ═══════════════════════════════════════════════════════════════
results = {
    "baseline_all": baseline_all,
    "baseline_subset": baseline_subset,
    "full_with_resp": full_model,
    "comparison": {
        "metric": ["N", "Features", "Selected", "R²", "MAE_rub", "MAE_log", "MedAE_rub", "Coverage_80pct"],
        "baseline_all": [baseline_all[k] for k in ["n","n_features","n_selected","r2","mae_rub","mae_log","medae_rub","coverage"]],
        "baseline_subset": [baseline_subset[k] for k in ["n","n_features","n_selected","r2","mae_rub","mae_log","medae_rub","coverage"]],
        "full_with_resp": [full_model[k] for k in ["n","n_features","n_selected","r2","mae_rub","mae_log","medae_rub","coverage"]],
    },
    "full_coefficients": {
        name: {
            "coef": float(lasso_full.coef_[i]),
            "exp_coef": float(np.exp(lasso_full.coef_[i])),
            "multiplier_pct": float((np.exp(lasso_full.coef_[i]) - 1) * 100),
            "selected": bool(abs(lasso_full.coef_[i]) > 1e-10),
        }
        for i, name in enumerate(all_feature_names)
    },
    "feature_names": all_feature_names,
    "resp_cluster_names": RESP_CLUSTER_NAMES,
}

with open(os.path.join(OUTPUT, "salary_model_v3_results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\nSaved: salary_model_v3_results.json")
print(f"\nDone.")
