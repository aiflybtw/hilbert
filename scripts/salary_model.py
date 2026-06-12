"""
salary_model.py

Heteroscedastic salary model with embedding-diversity multipliers.

ln(Salary_i) = x_i * beta + sigma_i * epsilon_i,  epsilon_i ~ N(0,1)
sigma_i = exp(z_i * gamma)    # grade-specific error variance

Two-step estimation:
  1. OLS for mean (x_i * beta)
  2. Per-grade residual std (sigma_g = sqrt(MSE_g))

Prediction intervals: bootstrap from per-grade residual pool.
  tail_alpha = 0.1 → 80% interval (10th–90th percentiles)
  tail_alpha = 0.05 → 90% interval (5th–95th percentiles)

Usage:
  python scripts/salary_model.py                    # 80% intervals (default)
  python scripts/salary_model.py --tail-alpha 0.05  # 90% intervals
"""

import argparse, json, os, sys
import numpy as np
from collections import defaultdict
from scipy.stats import norm
from sklearn.linear_model import LinearRegression
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

parser = argparse.ArgumentParser()
parser.add_argument("--tail-alpha", type=float, default=0.1,
                    help="Tail probability for prediction intervals (default: 0.1)")
args = parser.parse_args()

TAIL_ALPHA = args.tail_alpha
COVERAGE = 1 - 2 * TAIL_ALPHA
Z_LOWER = norm.ppf(TAIL_ALPHA)
Z_UPPER = norm.ppf(1 - TAIL_ALPHA)
N_BOOTSTRAP = 10000  # bootstrap draws for prediction intervals

# ── Load embeddings ──
print("Loading embeddings...")
embeddings = np.load(os.path.join(CLUSTER, "embeddings.npy"))
with open(os.path.join(CLUSTER, "skill_names.json"), encoding="utf-8") as f:
    skill_names = json.load(f)
skill_to_idx = {name: i for i, name in enumerate(skill_names)}
print(f"  {embeddings.shape[0]} skills x {embeddings.shape[1]} dims")

# ── Load skill -> cluster mapping ──
with open(os.path.join(CLUSTER, "skill_to_cluster_final_model.json"), encoding="utf-8") as f:
    skill_to_cluster = json.load(f)

# ── Load cluster IDs from final model ──
with open(os.path.join(CLUSTER, "clusters_final_model.json"), encoding="utf-8") as f:
    clusters_final = json.load(f)
N_CLUSTER_IDS = sorted(clusters_final["cluster_info"].keys(), key=lambda c: -clusters_final["cluster_info"][c]["size"])
N_CLUSTER_SHORT = {cid: info["name"] for cid, info in clusters_final["cluster_info"].items()}
print(f"  {len(N_CLUSTER_IDS)} hard skill clusters")

# ── Load soft skill embeddings ──
print("Loading soft skill embeddings...")
ss_embeddings = np.load(os.path.join(DATA, "soft_skills_embeddings.npy"))
with open(os.path.join(DATA, "soft_skills_names.json"), encoding="utf-8") as f:
    ss_names = json.load(f)
ss_name_to_idx = {name: i for i, name in enumerate(ss_names)}
print(f"  {ss_embeddings.shape[0]} skills x {ss_embeddings.shape[1]} dims")

# ── Load soft skill -> cluster mapping ──
with open(os.path.join(DATA, "soft_skills_llm_clusters.json"), encoding="utf-8") as f:
    soft_skill_clusters = json.load(f)
print(f"  {len(soft_skill_clusters)} soft skills with cluster assignments")

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

# ── Remove 3 suspicious outliers ──
OUTLIER_IDS = {'131501988', '132089441', '132167340', '22636'}
rows = [r for r in rows if r[0] not in OUTLIER_IDS]
print(f"  {len(rows)} after removing 3 outliers")

# ── Filter ──
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
    grade = sg
    vacancies.append({
        "id": vid,
        "hard_skills": hsj if isinstance(hsj, list) else [],
        "soft_skills": ssj if isinstance(ssj, list) else [],
        "soft_clusters": sc if isinstance(sc, list) else [],
        "seniority": sg,
        "grade": grade,
        "salary_from": float(sfr) if sfr else None,
        "salary_to": float(sto) if sto else None,
        "target": target,
        "log_target": np.log(target),
    })

print(f"  {len(vacancies)} valid after filtering")
for g in SENIORITY_LEVELS:
    n = sum(1 for v in vacancies if v["grade"] == g)
    if n:
        print(f"    {g}: {n}")

# ── Feature computation ──
def cosine_sim_matrix(vectors):
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normed = vectors / norms
    return normed @ normed.T

def compute_features(vac):
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

    seniority = vac["seniority"]
    sen_feats = np.zeros(len(SENIORITY_LEVELS))
    if seniority in SENIORITY_LEVELS:
        sen_feats[SENIORITY_LEVELS.index(seniority)] = 1.0
    elif seniority == "Middle/Senior":
        sen_feats[SENIORITY_LEVELS.index("Middle")] = 1.0
        sen_feats[SENIORITY_LEVELS.index("Senior")] = 1.0

    return np.concatenate([n_feats, s_feats, sen_feats])

# ── Build feature matrix ──
print("\nComputing features...")
X_list = []
y_list = []
grades_list = []
valid_vacancies = []

for v in vacancies:
    try:
        x = compute_features(v)
        X_list.append(x)
        y_list.append(v["log_target"])
        grades_list.append(v["grade"])
        valid_vacancies.append(v)
    except Exception as e:
        print(f"  Error for {v['id']}: {e}")

X = np.array(X_list)
y = np.array(y_list)
grades = np.array(grades_list)
print(f"  Feature matrix: {X.shape}")

n_feature_names = [f"n_cluster_{cid}" for cid in N_CLUSTER_IDS]
s_feature_names = [f"s_cluster_{i}" for i in S_CLUSTER_IDS]
seniority_names = [f"seniority_{s}" for s in SENIORITY_LEVELS]
all_feature_names = n_feature_names + s_feature_names + seniority_names

# ═══════════════════════════════════════════════════════════════
# STEP 1: Mean equation (OLS on log-salary)
# ═══════════════════════════════════════════════════════════════
print("\nStep 1: Mean equation (OLS with statsmodels)...")

import statsmodels.api as sm
X_sm = sm.add_constant(X)
model_sm = sm.OLS(y, X_sm).fit()
model = model_sm

# Extract from statsmodels (params is ndarray when X is ndarray)
intercept = float(model_sm.params[0])
coefs = model_sm.params[1:]
y_pred = model_sm.predict(X_sm)
residuals = y - y_pred
y_pred_salary = np.exp(y_pred)
y_true_salary = np.array([v["target"] for v in valid_vacancies])

r2 = float(model_sm.rsquared)
mae = mean_absolute_error(y_true_salary, y_pred_salary)
medae = median_absolute_error(y_true_salary, y_pred_salary)
mae_log = mean_absolute_error(y, y_pred)

print(f"  R2 = {r2:.4f}, MAE(log) = {mae_log:.4f}, MAE = {mae:,.0f} rub")

coef_std = model_sm.bse[1:]
coef_pval = model_sm.pvalues[1:]
coef_tval = model_sm.tvalues[1:]
coef_ci = model_sm.conf_int()[1:]

# ═══════════════════════════════════════════════════════════════
# STEP 2: Variance equation (per-grade residual std)
# ═══════════════════════════════════════════════════════════════
print("\nStep 2: Variance equation (per-grade sigma)...")

# CV residuals (out-of-sample)
cv_pred = cross_val_predict(LinearRegression(), X, y, cv=KFold(5, shuffle=True, random_state=42))
cv_residuals = y - cv_pred
cv_rmse = float(np.sqrt(np.mean(cv_residuals ** 2)))

grade_sigma = {}
grade_n = {}
for g in SENIORITY_LEVELS:
    mask = grades == g
    n_g = mask.sum()
    if n_g >= 2:
        sig_in = float(np.std(residuals[mask], ddof=0))    # in-sample (MLE)
        sig_cv = float(np.std(cv_residuals[mask], ddof=0)) # CV (out-of-sample)
        grade_sigma[g] = sig_cv
        grade_n[g] = n_g
        print(f"  {g:12s} sigma_in = {sig_in:.4f}  sigma_cv = {sig_cv:.4f}  (n = {n_g})")
    else:
        grade_sigma[g] = float(np.std(cv_residuals))

global_sigma = float(np.std(cv_residuals))
print(f"  Overall CV RMSE = {cv_rmse:.4f}")

# ═══════════════════════════════════════════════════════════════
# Prediction intervals (bootstrap)
# ═══════════════════════════════════════════════════════════════
print(f"\nPrediction intervals ({int(COVERAGE*100)}% coverage, bootstrap N={N_BOOTSTRAP}):")

# Prepare per-grade residual pools (in-sample, for bootstrap sampling)
grade_residual_pool = {g: residuals[grades == g] for g in SENIORITY_LEVELS}

inside_80, inside_60 = 0, 0
total = 0
interval_results = []

rng = np.random.default_rng(42)

for idx, v in enumerate(valid_vacancies):
    mu_log = y_pred[idx]
    sg = v["grade"]
    actual = v["target"]

    pool = grade_residual_pool.get(sg, cv_residuals)
    if len(pool) < 2:
        pool = cv_residuals

    # Bootstrap draws
    boot_eps = rng.choice(pool, size=N_BOOTSTRAP, replace=True)
    boot_salaries = np.exp(mu_log + boot_eps)

    lo_1 = float(np.percentile(boot_salaries, TAIL_ALPHA * 100))
    hi_1 = float(np.percentile(boot_salaries, (1 - TAIL_ALPHA) * 100))
    lo_2 = float(np.percentile(boot_salaries, 2 * TAIL_ALPHA * 100))
    hi_2 = float(np.percentile(boot_salaries, (1 - 2 * TAIL_ALPHA) * 100))

    inside_1 = lo_1 <= actual <= hi_1
    inside_2 = lo_2 <= actual <= hi_2
    if inside_1:
        inside_80 += 1
    if inside_2:
        inside_60 += 1
    total += 1

    sigma_i = grade_sigma.get(sg, global_sigma)

    interval_results.append({
        "vacancy_id": v["id"],
        "seniority": v["seniority"],
        "grade": sg,
        "mu_log": float(mu_log),
        "sigma_log": float(sigma_i),
        "predicted_salary": float(np.exp(mu_log)),
        "lower_80": lo_1,
        "upper_80": hi_1,
        "lower_60": lo_2,
        "upper_60": hi_2,
        "actual_salary": actual,
        "inside_80": inside_1,
        "inside_60": inside_2,
        "half_width_pct_80": float((hi_1 - lo_1) / 2 / np.exp(mu_log) * 100),
        "half_width_pct_60": float((hi_2 - lo_2) / 2 / np.exp(mu_log) * 100),
        "interval_method": "bootstrap",
        "n_bootstrap": N_BOOTSTRAP,
    })

cov_80 = inside_80 / total * 100
cov_60 = inside_60 / total * 100
print(f"  {int(COVERAGE*100)}% coverage: {inside_80}/{total} = {cov_80:.1f}%")
print(f"  {int((1-2*TAIL_ALPHA)*100)}% coverage: {inside_60}/{total} = {cov_60:.1f}%")

# ── Show per-grade coverage ──
print(f"\n  Per-grade coverage:")
for g in SENIORITY_LEVELS:
    g_vals = [r for r in interval_results if r["grade"] == g]
    if not g_vals:
        continue
    g_inside_80 = sum(1 for r in g_vals if r["inside_80"])
    g_inside_60 = sum(1 for r in g_vals if r["inside_60"])
    g_total = len(g_vals)
    print(f"    {g:12s} {int(COVERAGE*100)}%: {g_inside_80:3d}/{g_total:3d} = {g_inside_80/g_total*100:.0f}%  "
          f"{int((1-2*TAIL_ALPHA)*100)}%: {g_inside_60:3d}/{g_total:3d} = {g_inside_60/g_total*100:.0f}%  "
          f"(pool n = {len(grade_residual_pool.get(g, []))})")

# ── Compare with normal approximation ──
print(f"\n  Normal vs bootstrap comparison:")
print(f"  {'Grade':12s} {'Norm 80% width':>14s} {'Boot 80% width':>14s} {'Diff':>8s}")
print(f"  {'-'*12} {'-'*14} {'-'*14} {'-'*8}")
for g in SENIORITY_LEVELS:
    g_vals = [r for r in interval_results if r["grade"] == g]
    if not g_vals:
        continue
    boot_w = np.mean([r["upper_80"] - r["lower_80"] for r in g_vals])
    sigma_g = grade_sigma.get(g, global_sigma)
    norm_w = np.mean([np.exp(r["mu_log"]) * (np.exp(norm.ppf(0.9)*sigma_g) - np.exp(norm.ppf(0.1)*sigma_g)) for r in g_vals])
    diff = (boot_w - norm_w) / norm_w * 100
    print(f"  {g:12s} {norm_w:>14,.0f} {boot_w:>14,.0f} {diff:>+7.1f}%")

# ── Example vacancies with intervals ──
print(f"\n  Example intervals:")
print(f"  {'#':4s} {'Grade':10s} {'Actual':>10s} {'Predicted':>10s} {'Lo80':>10s} {'Hi80':>10s} {'Lo60':>10s} {'Hi60':>10s}")
print(f"  {'-'*4} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
for idx in [0, 50, 150, 250]:
    if idx >= len(interval_results):
        continue
    r = interval_results[idx]
    print(f"  {idx:4d} {r['grade']:10s} {r['actual_salary']:>10,.0f} {r['predicted_salary']:>10,.0f} "
          f"{r['lower_80']:>10,.0f} {r['upper_80']:>10,.0f} {r['lower_60']:>10,.0f} {r['upper_60']:>10,.0f}",
          end="")
    if r["inside_80"]:
        print("  OK")
    else:
        print("  MISS")

# ═══════════════════════════════════════════════════════════════
# Save results
# ═══════════════════════════════════════════════════════════════
print(f"\n  Saving results...")

# Coefficients (coefs, intercept already extracted from statsmodels)

coeffs_out = {
    "model": "Heteroscedastic OLS (log-salary, per-grade sigma, statsmodels)",
    "intercept": float(intercept),
    "r2": float(r2),
    "mae_log": float(mae_log),
    "mae_rub": float(mae),
    "median_ae_rub": float(medae),
    "n_train": len(y),
    "covar_type": "heteroscedastic",
    "tail_alpha": TAIL_ALPHA,
    "coverage_pct": float(cov_80),
    "coverage_60_pct": float(cov_60),
    "grade_sigma": {g: round(float(s), 6) for g, s in grade_sigma.items()},
    "coefficients": {},
}
for i, name in enumerate(all_feature_names):
    ci_low = float(coef_ci[i, 0]) if coef_ci.ndim == 2 and coef_ci.shape[1] >= 2 else 0
    ci_high = float(coef_ci[i, 1]) if coef_ci.ndim == 2 and coef_ci.shape[1] >= 2 else 0
    coeffs_out["coefficients"][name] = {
        "coef_raw": float(coefs[i]),
        "coef_exp": float(np.exp(coefs[i])),
        "multiplier_pct": (float(np.exp(coefs[i])) - 1) * 100,
        "std_err": float(coef_std[i]),
        "t_value": float(coef_tval[i]),
        "p_value": float(coef_pval[i]),
        "ci_lower": ci_low,
        "ci_upper": ci_high,
    }

with open(os.path.join(OUTPUT, "salary_model_coefficients_k15.json"), "w", encoding="utf-8") as f:
    json.dump(coeffs_out, f, ensure_ascii=False, indent=2)
print(f"  Saved: salary_model_coefficients_k15.json")

# Per-vacancy intervals
with open(os.path.join(OUTPUT, "salary_model_predictions_k15.json"), "w", encoding="utf-8") as f:
    json.dump(interval_results, f, ensure_ascii=False, indent=2)
print(f"  Saved: salary_model_predictions_k15.json")

# Full model
full_model = {
    "coefs": coefs.tolist(),
    "intercept": float(intercept),
    "feature_names": all_feature_names,
    "n_cluster_ids": N_CLUSTER_IDS,
    "s_cluster_ids": S_CLUSTER_IDS,
    "seniority_levels": SENIORITY_LEVELS,
    "grade_sigma": grade_sigma,
    "tail_alpha": TAIL_ALPHA,
    "coverage_pct": float(cov_80),
    "coverage_60_pct": float(cov_60),
    "n_train": len(y),
    "r2": float(r2),
    "mae_rub": float(mae),
    "covar_type": "heteroscedastic",
    "std_errs": coef_std.tolist(),
    "p_values": coef_pval.tolist(),
    "t_values": coef_tval.tolist(),
}
with open(os.path.join(OUTPUT, "salary_model_k15_full.json"), "w", encoding="utf-8") as f:
    json.dump(full_model, f, ensure_ascii=False, indent=2)
print(f"  Saved: salary_model_k15_full.json")

print(f"\n{'='*60}")
print("Done.")
