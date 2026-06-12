"""cluster_hard_skills_bertopic.py — BERTopic clustering of hard skills.

Reads descriptions from data/hard_skills_descriptions_clustering.json or falls
back to skill names. Generates embeddings with SentenceTransformer, then runs
BERTopic with UMAP + HDBSCAN in 3 configurations (coarse/medium/fine).
Saves cluster assignments and embeddings.
"""
import json, os, sys
from collections import defaultdict

import numpy as np

BASE = os.path.dirname(__file__)
DATA = os.path.join(BASE, "..", "data")
CLUSTER = os.path.join(DATA, "clustering")
os.makedirs(CLUSTER, exist_ok=True)

DESC_PATH = os.path.join(DATA, "hard_skills_descriptions_clustering.json")
EMBEDDINGS_PATH = os.path.join(CLUSTER, "embeddings.npy")

def load_skills_with_descriptions():
    with open(DESC_PATH, encoding='utf-8') as f:
        descriptions = json.load(f)
    skill_names = list(descriptions.keys())
    texts = []
    for s in skill_names:
        entry = descriptions[s]
        domain = entry.get('domain', '')
        desc = entry.get('description', '')
        text = f"Domain: {domain}. {desc}" if domain else desc
        texts.append(text)
    return skill_names, texts


def load_skills_fallback():
    names_path = os.path.join(CLUSTER, "skill_names.json")
    if os.path.exists(names_path):
        with open(names_path, encoding='utf-8') as f:
            skill_names = json.load(f)
    else:
        print("[cluster] No skill_names.json found — clustering will be empty")
        return [], []
    texts = skill_names[:]
    return skill_names, texts


def run_bertopic(texts, min_cluster_size, label):
    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN

    umap_model = UMAP(n_neighbors=15, min_dist=0.0, n_components=5, random_state=42)
    hdbscan_model = HDBSCAN(min_cluster_size=min_cluster_size, metric='euclidean', prediction_data=True)

    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        verbose=True,
    )
    topics, probs = topic_model.fit_transform(texts)

    cluster_to_skills = defaultdict(list)
    for skill_name, topic_id in zip(skill_names, topics):
        if topic_id != -1:
            cluster_to_skills[int(topic_id)].append(skill_name)

    n_clusters = len(cluster_to_skills)
    n_noise = sum(1 for t in topics if t == -1)
    print(f"[cluster] {label}: {n_clusters} clusters, {n_noise} noise points")

    result = {
        "config": f"min_cluster_size={min_cluster_size}",
        "n_clusters": n_clusters,
        "n_noise": n_noise,
        "clusters": {str(cid): skills for cid, skills in cluster_to_skills.items()},
    }

    out_path = os.path.join(CLUSTER, f"clusters_bertopic_{label}.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[cluster] Saved: {out_path}")
    return topic_model


def main():
    from sentence_transformers import SentenceTransformer

    if os.path.exists(DESC_PATH):
        print("[cluster] Loading skills with descriptions...")
        global skill_names
        skill_names, texts = load_skills_with_descriptions()
    else:
        print("[cluster] Descriptions file not found — using skill names as text")
        skill_names, texts = load_skills_fallback()

    print(f"[cluster] {len(skill_names)} skills to cluster")

    print("[cluster] Loading SentenceTransformer model...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    embeddings = model.encode(texts, show_progress_bar=True)
    print(f"[cluster] Embeddings shape: {embeddings.shape}")

    np.save(EMBEDDINGS_PATH, embeddings)
    print(f"[cluster] Saved embeddings to {EMBEDDINGS_PATH}")

    cfgs = [
        (10, "coarse"),
        (5, "medium"),
        (3, "fine"),
    ]

    skill_names_global = skill_names

    for min_size, label in cfgs:
        print(f"\n[cluster] Running BERTopic ({label}, min_cluster_size={min_size})...")
        from bertopic import BERTopic
        from umap import UMAP
        from hdbscan import HDBSCAN

        umap_model = UMAP(n_neighbors=15, min_dist=0.0, n_components=5, random_state=42)
        hdbscan_model = HDBSCAN(min_cluster_size=min_size, metric='euclidean', prediction_data=True)

        topic_model = BERTopic(
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,
            verbose=True,
        )
        topics, probs = topic_model.fit_transform(texts)

        cluster_to_skills = defaultdict(list)
        for skill_name, topic_id in zip(skill_names_global, topics):
            if topic_id != -1:
                cluster_to_skills[int(topic_id)].append(skill_name)

        n_clusters = len(cluster_to_skills)
        n_noise = sum(1 for t in topics if t == -1)
        print(f"[cluster] {label}: {n_clusters} clusters, {n_noise} noise")

        result = {
            "config": f"min_cluster_size={min_size}",
            "n_clusters": n_clusters,
            "n_noise": n_noise,
            "clusters": {str(cid): skills for cid, skills in cluster_to_skills.items()},
        }

        out_path = os.path.join(CLUSTER, f"clusters_bertopic_{label}.json")
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[cluster] Saved: {out_path}")

    print(f"\n[cluster] Done. 3 configs saved to {CLUSTER}")


if __name__ == "__main__":
    main()
