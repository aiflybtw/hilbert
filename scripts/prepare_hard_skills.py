"""prepare_hard_skills.py — Normalize, deduplicate, split compounds, remove singletons.

Pipeline: read skills_extracted → alias normalization → compound split → 
          case normalization → singleton removal → write hard_skills_json.
"""
import json, os, sys, re
from collections import Counter, defaultdict
import psycopg2

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn

# Compounds that should NOT be split
KNOWN_COMPOUNDS = {
    "ci/cd", "ci cd", "ci-cd",
    "tcp/ip", "tcp ip", "tcp-ip",
    "ssl/tls", "ssl tls",
    "dns/dhcp",
    "it", "it-инфраструктура",
    "sla/slo", "sla-slo",
    "ha/dr", "ha-dr",
    "sl/sli", "sl-sli",
}

# Alias -> canonical name (reverse engineered from skill_names.json)
ALIASES = {
    # CI/CD
    "ci/cd pipeline": "CI/CD", "ci/cd pipelines": "CI/CD",
    "ci/cd пайплайн": "CI/CD", "ci/cd пайплайны": "CI/CD",
    "ci-cd pipeline": "CI/CD", "ci-cd pipelines": "CI/CD",
    # ELK
    "elastic stack": "ELK Stack", "elk stack": "ELK Stack",
    "elasticsearch logstash kibana": "ELK Stack",
    # K8s
    "k8s": "Kubernetes", "k8s.": "Kubernetes", "kubernetes": "Kubernetes",
    # Docker
    "docker.": "Docker",
    # Terraform
    "terraform": "Terraform",
    # Ansible
    "ansible": "Ansible",
    # Python
    "python": "Python",
    # Go
    "golang": "Go", "go.": "Go",
    # Bash
    "bash": "Bash",
    # Prometheus
    "prometheus": "Prometheus",
    # Grafana
    "grafana": "Grafana",
    # Git
    "git": "Git", "git.": "Git",
    # Linux
    "linux": "Linux",
    # AWS
    "aws": "AWS",
    "amazon web services": "AWS",
    # GCP
    "gcp": "GCP",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    # Azure
    "azure": "Azure",
    "microsoft azure": "Azure",
    # PostgreSQL
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    # MySQL
    "mysql": "MySQL",
    # Jenkins
    "jenkins": "Jenkins",
    # GitLab
    "gitlab": "GitLab",
    "git lab": "GitLab",
    # GitHub
    "github": "GitHub",
    "git hub": "GitHub",
    # Nginx
    "nginx": "Nginx",
    # Redis
    "redis": "Redis",
    # Kafka
    "kafka": "Kafka",
    # RabbitMQ
    "rabbitmq": "RabbitMQ",
    "rabbit mq": "RabbitMQ",
    # MongoDB
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    # Helm
    "helm": "Helm",
    # ArgoCD
    "argocd": "ArgoCD",
    "argo cd": "ArgoCD",
    # Vault
    "vault": "Vault",
    "hashicorp vault": "Vault",
    # Consul
    "consul": "Consul",
    "hashicorp consul": "Consul",
    # Istio
    "istio": "Istio",
    # Envoy
    "envoy": "Envoy",
    # Linkerd
    "linkerd": "Linkerd",
    # Traefik
    "traefik": "Traefik",
    # HAProxy
    "haproxy": "HAProxy",
    "ha proxy": "HAProxy",
    # Keycloak
    "keycloak": "Keycloak",
    # SonarQube
    "sonarqube": "SonarQube",
    "sonar qube": "SonarQube",
    # VMWare
    "vmware": "VMware",
    "vm ware": "VMware",
    # Proxmox
    "proxmox": "Proxmox",
    # Ansible Tower
    "ansible tower": "Ansible Tower",
    "ansibletower": "Ansible Tower",
    # Terraform Cloud
    "terraform cloud": "Terraform Cloud",
    "tfc": "Terraform Cloud",
    # Pulumi
    "pulumi": "Pulumi",
    # Packer
    "packer": "Packer",
    # Vagrant
    "vagrant": "Vagrant",
    # SaltStack
    "saltstack": "SaltStack",
    "salt": "SaltStack",
    # Puppet
    "puppet": "Puppet",
    # Chef
    "chef": "Chef",
    # Prometheus Operator
    "prometheus operator": "Prometheus Operator",
    "prom operator": "Prometheus Operator",
    # VictoriaMetrics
    "victoriametrics": "VictoriaMetrics",
    "victoria metrics": "VictoriaMetrics",
    # Thanos
    "thanos": "Thanos",
    # Loki
    "loki": "Loki",
    # Jaeger
    "jaeger": "Jaeger",
    # Tempo
    "tempo": "Tempo",
    # ELK
    "elasticsearch": "Elasticsearch",
    "logstash": "Logstash",
    "kibana": "Kibana",
    # Graylog
    "graylog": "Graylog",
    # Splunk
    "splunk": "Splunk",
    # Datadog
    "datadog": "Datadog",
    "data dog": "Datadog",
    # New Relic
    "new relic": "New Relic",
    "newrelic": "New Relic",
    # Dynatrace
    "dynatrace": "Dynatrace",
    # Sentry
    "sentry": "Sentry",
    # Nagios
    "nagios": "Nagios",
    # Zabbix
    "zabbix": "Zabbix",
    # Icinga
    "icinga": "Icinga",
    # Checkmk
    "checkmk": "CheckMK",
    "check mk": "CheckMK",
    # Ceph
    "ceph": "Ceph",
    # MinIO
    "minio": "MinIO",
    "min io": "MinIO",
    # NFS
    "nfs": "NFS",
    # GlusterFS
    "glusterfs": "GlusterFS",
    "gluster fs": "GlusterFS",
    # LVM
    "lvm": "LVM",
    # RAID
    "raid": "RAID",
    # ZFS
    "zfs": "ZFS",
    # Btrfs
    "btrfs": "Btrfs",
    # XFS
    "xfs": "XFS",
    # Calico
    "calico": "Calico",
    # Cilium
    "cilium": "Cilium",
    # Flannel
    "flannel": "Flannel",
    # Weave
    "weave": "Weave",
    "weave net": "Weave",
    # MetalLB
    "metallb": "MetalLB",
    "metal lb": "MetalLB",
    # Ingress
    "ingress": "Ingress",
    "ingress controller": "Ingress",
    # Cert-Manager
    "cert manager": "cert-manager",
    "certmanager": "cert-manager",
    # ExternalDNS
    "external dns": "ExternalDNS",
    "externaldns": "ExternalDNS",
    # Kube-prometheus
    "kube-prometheus": "kube-prometheus",
    "kubeprometheus": "kube-prometheus",
    # Grafana Operator
    "grafana operator": "Grafana Operator",
    # OPA
    "opa": "OPA",
    "open policy agent": "OPA",
    # Kyverno
    "kyverno": "Kyverno",
    # Kustomize
    "kustomize": "Kustomize",
    # Skaffold
    "skaffold": "Skaffold",
    # Bazel
    "bazel": "Bazel",
    # Maven
    "maven": "Maven",
    # Gradle
    "gradle": "Gradle",
    # NPM
    "npm": "npm",
    # Yarn
    "yarn": "Yarn",
    # Webpack
    "webpack": "Webpack",
    # Vite
    "vite": "Vite",
    # ESLint
    "eslint": "ESLint",
    # Prettier
    "prettier": "Prettier",
    # TypeScript
    "typescript": "TypeScript",
    # JavaScript
    "javascript": "JavaScript",
    "js": "JavaScript",
    # React
    "react": "React",
    # Vue
    "vue": "Vue",
    "vue.js": "Vue",
    # Angular
    "angular": "Angular",
    # Java
    "java": "Java",
    "java.": "Java",
    # C#
    "c#": "C#",
    "csharp": "C#",
    # C++
    "c++": "C++",
    "cpp": "C++",
    # Rust
    "rust": "Rust",
    # Ruby
    "ruby": "Ruby",
    # PHP
    "php": "PHP",
    # Perl
    "perl": "Perl",
    # Scala
    "scala": "Scala",
    # Kotlin
    "kotlin": "Kotlin",
    # Swift
    "swift": "Swift",
    # Objective-C
    "objective c": "Objective-C",
    "objectivec": "Objective-C",
    # Assembly
    "assembly": "Assembly",
    "asm": "Assembly",
    # PowerShell
    "powershell": "PowerShell",
    "power shell": "PowerShell",
    # Groovy
    "groovy": "Groovy",
    # awk
    "awk": "awk",
    # sed
    "sed": "sed",
    # SQL
    "sql": "SQL",
    # PromQL
    "promql": "PromQL",
    # LogQL
    "logql": "LogQL",
    # GraphQL
    "graphql": "GraphQL",
    # REST
    "rest": "REST",
    "rest api": "REST API",
    # gRPC
    "grpc": "gRPC",
    # Graphite
    "graphite": "Graphite",
    # InfluxDB
    "influxdb": "InfluxDB",
    "influx db": "InfluxDB",
    # ClickHouse
    "clickhouse": "ClickHouse",
    "click house": "ClickHouse",
    # Cassandra
    "cassandra": "Cassandra",
    # Elasticsearch
    "elastic search": "Elasticsearch",
    # OpenSearch
    "opensearch": "OpenSearch",
    "open search": "OpenSearch",
    # Hadoop
    "hadoop": "Hadoop",
    # Spark
    "spark": "Spark",
    "apache spark": "Spark",
    # Airflow
    "airflow": "Airflow",
    "apache airflow": "Airflow",
    # Kubeflow
    "kubeflow": "Kubeflow",
    "kube flow": "Kubeflow",
    # MLflow
    "mlflow": "MLflow",
    "ml flow": "MLflow",
    # DVC
    "dvc": "DVC",
    # Weights & Biases
    "weights & biases": "Weights & Biases",
    "wandb": "Weights & Biases",
    # LangChain
    "langchain": "LangChain",
    "lang chain": "LangChain",
    # LlamaIndex
    "llamaindex": "LlamaIndex",
    "llama index": "LlamaIndex",
    # PyTorch
    "pytorch": "PyTorch",
    "torch": "PyTorch",
    # TensorFlow
    "tensorflow": "TensorFlow",
    "tensor flow": "TensorFlow",
    # JAX
    "jax": "JAX",
    # ONNX
    "onnx": "ONNX",
    # Triton
    "triton": "Triton",
    "triton inference server": "Triton",
    # vLLM
    "vllm": "vLLM",
    "v llm": "vLLM",
    # Ray
    "ray": "Ray",
    # Dask
    "dask": "Dask",
    # Numba
    "numba": "Numba",
    # CUDA
    "cuda": "CUDA",
    # NCCL
    "nccl": "NCCL",
    # RDMA
    "rdma": "RDMA",
    # InfiniBand
    "infiniband": "InfiniBand",
    "infiniband.": "InfiniBand",
    # GPU
    "gpu": "GPU",
    # TPU
    "tpu": "TPU",
    # FPGA
    "fpga": "FPGA",
    # ASIC
    "asic": "ASIC",
    # Docker Compose
    "docker compose": "Docker Compose",
    "docker-compose": "Docker Compose",
    # Docker Swarm
    "docker swarm": "Docker Swarm",
    # Podman
    "podman": "Podman",
    # containerd
    "containerd": "containerd",
    "container d": "containerd",
    # CRI-O
    "cri-o": "CRI-O",
    "crio": "CRI-O",
    # RKT
    "rkt": "rkt",
    # LXC
    "lxc": "LXC",
    # LXD
    "lxd": "LXD",
    # OpenShift
    "openshift": "OpenShift",
    "open shift": "OpenShift",
    # Rancher
    "rancher": "Rancher",
    # Nomad
    "nomad": "Nomad",
    "hashicorp nomad": "Nomad",
    # Waypoint
    "waypoint": "Waypoint",
    # Boundary
    "boundary": "Boundary",
    # Vault
    # Sentry
    # etc
}

# Slash-separated compounds to split (e.g. "Bash/Python" -> "Bash", "Python")
# but only if both parts are known skills
KNOWN_SKILL_NAMES = set()


def normalize_skill(name):
    """Apply alias mapping and canonical name normalization."""
    name = name.strip()
    if not name:
        return None
    key = name.lower().strip().strip('.').strip()
    # Direct alias lookup
    if key in ALIASES:
        return ALIASES[key]
    # Case normalization: title case for most, uppercase for acronyms
    if key.isupper() or key.replace('/', '').isupper():
        return key.upper()
    if key.startswith('k8s'):
        return 'Kubernetes'
    return name.strip()


def split_compound(name):
    """Split 'Bash/Python' -> ['Bash', 'Python'] if both parts are known."""
    if not name:
        return [name]
    # Check slash-separated
    if '/' in name and name.lower() not in KNOWN_COMPOUNDS:
        parts = [p.strip() for p in name.split('/') if p.strip()]
        if len(parts) > 1:
            known = sum(1 for p in parts if p.lower() in KNOWN_SKILL_NAMES or normalize_skill(p) 
                        and normalize_skill(p).lower() in KNOWN_SKILL_NAMES)
            if known >= 2:
                return parts
    # Check whitespace-separated (e.g., "Python Bash" in some formats)
    if ' ' in name:
        words = name.split()
        if len(words) <= 4:
            parts = [w for w in words if w.lower() not in ('and', '&', ',', '/')]
            if len(parts) > 1:
                known = sum(1 for p in parts if p.lower() in KNOWN_SKILL_NAMES or 
                           normalize_skill(p) and normalize_skill(p).lower() in KNOWN_SKILL_NAMES)
                if known >= 2:
                    return parts
    return [name]


def load_skill_names():
    global KNOWN_SKILL_NAMES
    with open(os.path.join(BASE, "..", "data", "clustering", "skill_names.json")) as f:
        names = json.load(f)
    KNOWN_SKILL_NAMES = {n.lower() for n in names}
    return names


def main():
    load_skill_names()
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    
    print("[prepare_hard_skills] Loading existing skill frequencies...")
    cur.execute("SELECT hard_skills_json FROM vacancies WHERE hard_skills_json IS NOT NULL")
    existing_counts = Counter()
    for (row,) in cur.fetchall():
        if isinstance(row, list):
            skills = row
        else:
            try:
                skills = json.loads(row)
            except (json.JSONDecodeError, TypeError):
                continue
        if isinstance(skills, list):
            names = [s.get("name", "") if isinstance(s, dict) else s for s in skills]
            existing_counts.update(n for n in names if n)

    cur.execute("""
        SELECT vacancy_id, skills_extracted
        FROM vacancies
        WHERE skills_extracted IS NOT NULL
          AND hard_skills_json IS NULL
    """)
    new_rows = cur.fetchall()
    if not new_rows:
        print("[prepare_hard_skills] No new vacancies to process")
        conn.close()
        return
    print(f"[prepare_hard_skills] {len(new_rows)} new vacancies (existing data has {len(existing_counts)} unique skills)")
    
    # Step 1: Normalize and split new rows
    all_new_skills = []
    vacancy_skills = {}
    for vid, extracted in new_rows:
        if not extracted:
            continue
        hs = extracted.get('hard_skills', []) if isinstance(extracted, dict) else []
        names = []
        for h in hs:
            raw = h.get('name', '')
            priority = h.get('priority', 'required')
            context = h.get('context_snippet', '')
            normed = normalize_skill(raw)
            if not normed:
                continue
            for part in split_compound(normed):
                pn = normalize_skill(part)
                if pn and len(pn) > 1:
                    names.append({"name": pn, "priority": priority, "context_snippet": context})
        
        seen = set()
        unique = []
        for n in names:
            key = n["name"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(n)
        vacancy_skills[vid] = unique
        all_new_skills.extend(n["name"] for n in unique)
    
    # Step 2: Combined frequencies (existing + new) for singleton detection
    total_counts = existing_counts.copy()
    total_counts.update(all_new_skills)
    print(f"[prepare_hard_skills] {len(total_counts)} unique skills total")
    
    # Step 3: Remove singletons (skills appearing in only 1 vacancy)
    singleton_names = {s for s, c in total_counts.items() if c <= 1}
    print(f"[prepare_hard_skills] Removing {len(singleton_names)} singletons")
    
    # Step 4: Write back (only new rows)
    updated = 0
    for vid, skills in vacancy_skills.items():
        filtered = [s for s in skills if s["name"] not in singleton_names]
        cur.execute(
            "UPDATE vacancies SET hard_skills_json = %s WHERE vacancy_id = %s",
            (json.dumps(filtered, ensure_ascii=False), vid),
        )
        updated += 1
        if updated % 200 == 0:
            conn.commit()
            print(f"[prepare_hard_skills] {updated}/{len(new_rows)}")
    
    conn.commit()
    cur.close()
    conn.close()
    print(f"[prepare_hard_skills] Done. {updated} vacancies updated.")


if __name__ == "__main__":
    main()
