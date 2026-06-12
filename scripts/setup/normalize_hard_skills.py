"""normalize_hard_skills.py — Apply alias normalization to hard_skills_json in DB."""
import json, os, sys

import psycopg2

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn

ALIASES = {}

ALIASES["ci/cd pipeline"] = "CI/CD"
ALIASES["ci/cd pipelines"] = "CI/CD"
ALIASES["ci/cd пайплайн"] = "CI/CD"
ALIASES["ci/cd пайплайны"] = "CI/CD"
ALIASES["ci-cd pipeline"] = "CI/CD"
ALIASES["ci-cd pipelines"] = "CI/CD"
ALIASES["elastic stack"] = "ELK Stack"
ALIASES["elk stack"] = "ELK Stack"
ALIASES["elasticsearch logstash kibana"] = "ELK Stack"
ALIASES["k8s"] = "Kubernetes"
ALIASES["k8s."] = "Kubernetes"
ALIASES["kubernetes"] = "Kubernetes"
ALIASES["docker."] = "Docker"
ALIASES["terraform"] = "Terraform"
ALIASES["ansible"] = "Ansible"
ALIASES["python"] = "Python"
ALIASES["golang"] = "Go"
ALIASES["go."] = "Go"
ALIASES["bash"] = "Bash"
ALIASES["prometheus"] = "Prometheus"
ALIASES["grafana"] = "Grafana"
ALIASES["git"] = "Git"
ALIASES["git."] = "Git"
ALIASES["linux"] = "Linux"
ALIASES["aws"] = "AWS"
ALIASES["amazon web services"] = "AWS"
ALIASES["gcp"] = "GCP"
ALIASES["google cloud"] = "GCP"
ALIASES["google cloud platform"] = "GCP"
ALIASES["azure"] = "Azure"
ALIASES["microsoft azure"] = "Azure"
ALIASES["postgresql"] = "PostgreSQL"
ALIASES["postgres"] = "PostgreSQL"
ALIASES["mysql"] = "MySQL"
ALIASES["jenkins"] = "Jenkins"
ALIASES["gitlab"] = "GitLab"
ALIASES["git lab"] = "GitLab"
ALIASES["github"] = "GitHub"
ALIASES["git hub"] = "GitHub"
ALIASES["nginx"] = "Nginx"
ALIASES["redis"] = "Redis"
ALIASES["kafka"] = "Kafka"
ALIASES["rabbitmq"] = "RabbitMQ"
ALIASES["rabbit mq"] = "RabbitMQ"
ALIASES["mongodb"] = "MongoDB"
ALIASES["mongo"] = "MongoDB"
ALIASES["helm"] = "Helm"
ALIASES["argocd"] = "ArgoCD"
ALIASES["argo cd"] = "ArgoCD"
ALIASES["vault"] = "Vault"
ALIASES["hashicorp vault"] = "Vault"
ALIASES["consul"] = "Consul"
ALIASES["hashicorp consul"] = "Consul"
ALIASES["istio"] = "Istio"
ALIASES["envoy"] = "Envoy"
ALIASES["linkerd"] = "Linkerd"
ALIASES["traefik"] = "Traefik"
ALIASES["haproxy"] = "HAProxy"
ALIASES["ha proxy"] = "HAProxy"
ALIASES["keycloak"] = "Keycloak"
ALIASES["sonarqube"] = "SonarQube"
ALIASES["sonar qube"] = "SonarQube"
ALIASES["vmware"] = "VMware"
ALIASES["vm ware"] = "VMware"
ALIASES["proxmox"] = "Proxmox"
ALIASES["ansible tower"] = "Ansible Tower"
ALIASES["ansibletower"] = "Ansible Tower"
ALIASES["terraform cloud"] = "Terraform Cloud"
ALIASES["tfc"] = "Terraform Cloud"
ALIASES["pulumi"] = "Pulumi"
ALIASES["packer"] = "Packer"
ALIASES["vagrant"] = "Vagrant"
ALIASES["saltstack"] = "SaltStack"
ALIASES["salt"] = "SaltStack"
ALIASES["puppet"] = "Puppet"
ALIASES["chef"] = "Chef"
ALIASES["prometheus operator"] = "Prometheus Operator"
ALIASES["prom operator"] = "Prometheus Operator"
ALIASES["victoriametrics"] = "VictoriaMetrics"
ALIASES["victoria metrics"] = "VictoriaMetrics"
ALIASES["thanos"] = "Thanos"
ALIASES["loki"] = "Loki"
ALIASES["jaeger"] = "Jaeger"
ALIASES["tempo"] = "Tempo"
ALIASES["elasticsearch"] = "Elasticsearch"
ALIASES["logstash"] = "Logstash"
ALIASES["kibana"] = "Kibana"
ALIASES["graylog"] = "Graylog"
ALIASES["splunk"] = "Splunk"
ALIASES["datadog"] = "Datadog"
ALIASES["data dog"] = "Datadog"
ALIASES["new relic"] = "New Relic"
ALIASES["newrelic"] = "New Relic"
ALIASES["dynatrace"] = "Dynatrace"
ALIASES["sentry"] = "Sentry"
ALIASES["nagios"] = "Nagios"
ALIASES["zabbix"] = "Zabbix"
ALIASES["icinga"] = "Icinga"
ALIASES["checkmk"] = "CheckMK"
ALIASES["check mk"] = "CheckMK"
ALIASES["ceph"] = "Ceph"
ALIASES["minio"] = "MinIO"
ALIASES["min io"] = "MinIO"
ALIASES["nfs"] = "NFS"
ALIASES["glusterfs"] = "GlusterFS"
ALIASES["gluster fs"] = "GlusterFS"
ALIASES["lvm"] = "LVM"
ALIASES["raid"] = "RAID"
ALIASES["zfs"] = "ZFS"
ALIASES["btrfs"] = "Btrfs"
ALIASES["xfs"] = "XFS"
ALIASES["calico"] = "Calico"
ALIASES["cilium"] = "Cilium"
ALIASES["flannel"] = "Flannel"
ALIASES["weave"] = "Weave"
ALIASES["weave net"] = "Weave"
ALIASES["metallb"] = "MetalLB"
ALIASES["metal lb"] = "MetalLB"
ALIASES["ingress"] = "Ingress"
ALIASES["ingress controller"] = "Ingress"
ALIASES["cert manager"] = "cert-manager"
ALIASES["certmanager"] = "cert-manager"
ALIASES["external dns"] = "ExternalDNS"
ALIASES["externaldns"] = "ExternalDNS"
ALIASES["kube-prometheus"] = "kube-prometheus"
ALIASES["kubeprometheus"] = "kube-prometheus"
ALIASES["grafana operator"] = "Grafana Operator"
ALIASES["opa"] = "OPA"
ALIASES["open policy agent"] = "OPA"
ALIASES["kyverno"] = "Kyverno"
ALIASES["kustomize"] = "Kustomize"
ALIASES["skaffold"] = "Skaffold"
ALIASES["bazel"] = "Bazel"
ALIASES["maven"] = "Maven"
ALIASES["gradle"] = "Gradle"
ALIASES["npm"] = "npm"
ALIASES["yarn"] = "Yarn"
ALIASES["webpack"] = "Webpack"
ALIASES["vite"] = "Vite"
ALIASES["eslint"] = "ESLint"
ALIASES["prettier"] = "Prettier"
ALIASES["typescript"] = "TypeScript"
ALIASES["javascript"] = "JavaScript"
ALIASES["js"] = "JavaScript"
ALIASES["react"] = "React"
ALIASES["vue"] = "Vue"
ALIASES["vue.js"] = "Vue"
ALIASES["angular"] = "Angular"
ALIASES["java"] = "Java"
ALIASES["java."] = "Java"
ALIASES["c#"] = "C#"
ALIASES["csharp"] = "C#"
ALIASES["c++"] = "C++"
ALIASES["cpp"] = "C++"
ALIASES["rust"] = "Rust"
ALIASES["ruby"] = "Ruby"
ALIASES["php"] = "PHP"
ALIASES["perl"] = "Perl"
ALIASES["scala"] = "Scala"
ALIASES["kotlin"] = "Kotlin"
ALIASES["swift"] = "Swift"
ALIASES["objective c"] = "Objective-C"
ALIASES["objectivec"] = "Objective-C"
ALIASES["assembly"] = "Assembly"
ALIASES["asm"] = "Assembly"
ALIASES["powershell"] = "PowerShell"
ALIASES["power shell"] = "PowerShell"
ALIASES["groovy"] = "Groovy"
ALIASES["awk"] = "awk"
ALIASES["sed"] = "sed"
ALIASES["sql"] = "SQL"
ALIASES["promql"] = "PromQL"
ALIASES["logql"] = "LogQL"
ALIASES["graphql"] = "GraphQL"
ALIASES["rest"] = "REST"
ALIASES["rest api"] = "REST API"
ALIASES["grpc"] = "gRPC"
ALIASES["graphite"] = "Graphite"
ALIASES["influxdb"] = "InfluxDB"
ALIASES["influx db"] = "InfluxDB"
ALIASES["clickhouse"] = "ClickHouse"
ALIASES["click house"] = "ClickHouse"
ALIASES["cassandra"] = "Cassandra"
ALIASES["elastic search"] = "Elasticsearch"
ALIASES["opensearch"] = "OpenSearch"
ALIASES["open search"] = "OpenSearch"
ALIASES["hadoop"] = "Hadoop"
ALIASES["spark"] = "Spark"
ALIASES["apache spark"] = "Spark"
ALIASES["airflow"] = "Airflow"
ALIASES["apache airflow"] = "Airflow"
ALIASES["kubeflow"] = "Kubeflow"
ALIASES["kube flow"] = "Kubeflow"
ALIASES["mlflow"] = "MLflow"
ALIASES["ml flow"] = "MLflow"
ALIASES["dvc"] = "DVC"
ALIASES["weights & biases"] = "Weights & Biases"
ALIASES["wandb"] = "Weights & Biases"
ALIASES["langchain"] = "LangChain"
ALIASES["lang chain"] = "LangChain"
ALIASES["llamaindex"] = "LlamaIndex"
ALIASES["llama index"] = "LlamaIndex"
ALIASES["pytorch"] = "PyTorch"
ALIASES["torch"] = "PyTorch"
ALIASES["tensorflow"] = "TensorFlow"
ALIASES["tensor flow"] = "TensorFlow"
ALIASES["jax"] = "JAX"
ALIASES["onnx"] = "ONNX"
ALIASES["triton"] = "Triton"
ALIASES["triton inference server"] = "Triton"
ALIASES["vllm"] = "vLLM"
ALIASES["v llm"] = "vLLM"
ALIASES["ray"] = "Ray"
ALIASES["dask"] = "Dask"
ALIASES["numba"] = "Numba"
ALIASES["cuda"] = "CUDA"
ALIASES["nccl"] = "NCCL"
ALIASES["rdma"] = "RDMA"
ALIASES["infiniband"] = "InfiniBand"
ALIASES["infiniband."] = "InfiniBand"
ALIASES["gpu"] = "GPU"
ALIASES["tpu"] = "TPU"
ALIASES["fpga"] = "FPGA"
ALIASES["asic"] = "ASIC"
ALIASES["docker compose"] = "Docker Compose"
ALIASES["docker-compose"] = "Docker Compose"
ALIASES["docker swarm"] = "Docker Swarm"
ALIASES["podman"] = "Podman"
ALIASES["containerd"] = "containerd"
ALIASES["container d"] = "containerd"
ALIASES["cri-o"] = "CRI-O"
ALIASES["crio"] = "CRI-O"
ALIASES["rkt"] = "rkt"
ALIASES["lxc"] = "LXC"
ALIASES["lxd"] = "LXD"
ALIASES["openshift"] = "OpenShift"
ALIASES["open shift"] = "OpenShift"
ALIASES["rancher"] = "Rancher"
ALIASES["nomad"] = "Nomad"
ALIASES["hashicorp nomad"] = "Nomad"
ALIASES["waypoint"] = "Waypoint"
ALIASES["boundary"] = "Boundary"


def normalize_skill(name):
    name = name.strip()
    if not name:
        return None
    key = name.lower().strip().strip('.').strip()
    if key in ALIASES:
        return ALIASES[key]
    if key.isupper() or key.replace('/', '').isupper():
        return key.upper()
    if key.startswith('k8s'):
        return 'Kubernetes'
    return name.strip()


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    print("[normalize_hard_skills] Loading skills from DB...")
    cur.execute("""
        SELECT vacancy_id, hard_skills_json
        FROM vacancies
        WHERE hard_skills_json IS NOT NULL
    """)
    rows = cur.fetchall()
    print(f"[normalize_hard_skills] {len(rows)} vacancies with hard_skills_json")

    updated = 0
    for vid, skills_json in rows:
        if not skills_json:
            continue
        if isinstance(skills_json, str):
            skills = json.loads(skills_json)
        else:
            skills = skills_json
        if not isinstance(skills, list):
            continue

        changed = False
        for s in skills:
            if isinstance(s, dict) and 'name' in s:
                original = s['name']
                normed = normalize_skill(original)
                if normed and normed != original:
                    s['name'] = normed
                    changed = True
            elif isinstance(s, str):
                normed = normalize_skill(s)
                if normed and normed != s:
                    skills[skills.index(s)] = normed
                    changed = True

        if changed:
            cur.execute(
                "UPDATE vacancies SET hard_skills_json = %s WHERE vacancy_id = %s",
                (json.dumps(skills, ensure_ascii=False), vid),
            )
            updated += 1

        if updated > 0 and updated % 200 == 0:
            conn.commit()
            print(f"[normalize_hard_skills] {updated}/{len(rows)} updated")

    conn.commit()
    cur.close()
    conn.close()
    print(f"[normalize_hard_skills] Done. {updated} vacancies updated.")


if __name__ == "__main__":
    main()
