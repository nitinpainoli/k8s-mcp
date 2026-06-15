# k8s-mcp

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server built with [FastMCP](https://github.com/jlowin/fastmcp) and the official [Kubernetes Python client](https://github.com/kubernetes-client/python). It exposes read-oriented tools so an MCP-capable assistant (for example **Cursor**, Claude Desktop, or other MCP clients) can inspect workloads, events, logs, and basic resource metrics inside a cluster.

The server is intended to run **inside the cluster** (in-cluster service account) and speak MCP over **HTTP** on port `8000` (see `app.py`).

---

## Features (MCP tools)

| Tool | Purpose |
|------|--------|
| `get_pods` | List pods in a namespace |
| `get_pod_details` | Pod details and container env (values from `Secret` refs are masked) |
| `get_deployments` | List deployments |
| `get_events` | Namespace events |
| `get_logs` | Pod logs (tail) |
| `compare_pods` | Diff env keys/values between two pods |
| `find_crashloops` | Pods in `CrashLoopBackOff` |
| `deployment_status` | Desired vs ready/available replicas |
| `diagnose_pod` | Phase, node, and events for one pod |
| `analyze_crashloop` | Container restarts, last termination, short log tail |
| `get_env_var` | Single env var lookup (secret-backed values masked) |
| `diagnose_application` | Deployment + matching pods, issues, events, logs when issues exist |
| `top_pods` | CPU/memory per pod via `metrics.k8s.io` (same API family as `kubectl top pods`) |

**Default namespace:** most tools default to `namespace="test"`. Pass another namespace when calling the tool if your workloads live elsewhere.

**Secrets:** literal env values are returned; only env vars sourced from `secretKeyRef` are replaced with `***MASKED***`. Pod **logs** may still contain sensitive data—treat RBAC and network exposure accordingly.

---

## Requirements

- **Kubernetes** cluster where you can create namespaces, RBAC, Deployments, and Services.
- **Metrics Server** (or any implementation of **Resource Metrics API** `metrics.k8s.io`) if you want `top_pods` to work. If metrics are missing, that tool returns a clear error.
- **Python 3.12+** for local runs (matches `Dockerfile`).
- **FastMCP** and **kubernetes** client libraries (see `requirements.txt`).

---

## Quick start (in-cluster)

### 1. Create the namespace

The manifests assume `mcp-system`:

```bash
kubectl create namespace mcp-system --dry-run=client -o yaml | kubectl apply -f -
```

### 2. Fix the container image

`deployment.yaml` references an example **ECR** image. Replace it with an image you build and push from this repo (see [Build the image](#build-the-image)).

### 3. Apply manifests (order does not strictly matter)

```bash
kubectl apply -f serviceaccount.yaml
kubectl apply -f clusterrole.yaml
kubectl apply -f clusterrolebinding.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
```

### 4. Verify the pod

```bash
kubectl -n mcp-system get pods -l app=k8s-mcp
kubectl -n mcp-system logs -l app=k8s-mcp --tail=50
```

---

## MCP endpoint (FastMCP HTTP)

With `mcp.run(transport="http", host="0.0.0.0", port=8000)` the MCP HTTP endpoint is:

**`http://<host>:<port>/mcp`**

Examples:

- From another pod in the cluster: `http://k8s-mcp.mcp-system.svc.cluster.local/mcp` (Service targets port `8000`; ClusterIP `port: 80` maps to `targetPort: 8000`, so use **port 80** on the Service DNS name: `http://k8s-mcp.mcp-system.svc/mcp`).
- From your laptop via port-forward:

```bash
kubectl -n mcp-system port-forward svc/k8s-mcp 8080:80
```

Then the MCP URL is: **`http://127.0.0.1:8080/mcp`**

If your client is picky about trailing slashes, try `http://127.0.0.1:8080/mcp/` as well.

Official FastMCP HTTP notes: [HTTP deployment](https://gofastmcp.com/deployment/http).

---

## Connect from Cursor (or other MCP clients)

### Cursor

1. Open **Cursor Settings → MCP** (or edit your MCP config file, depending on Cursor version).
2. Add a server entry that points at the **HTTP MCP URL** (after port-forward or via your ingress).

Example shape (adjust to your config format / Cursor version):

```json
{
  "mcpServers": {
    "k8s-mcp": {
      "url": "http://127.0.0.1:8080/mcp"
    }
  }
}
```

Use **HTTPS** and proper auth if you expose this beyond localhost (ingress + mTLS or VPN). The service as shipped has **no application-level auth**; rely on network policy, private networking, or an authenticating reverse proxy.

### Clients that only support stdio

This repo runs **HTTP** transport. Options:

- Use a client/proxy that bridges HTTP MCP to stdio, or  
- Change `app.py` to use `transport="stdio"` for local-only use (and use `load_kube_config()` instead of `load_incluster_config()`—not included in the default `app.py`).

---

## RBAC

- **`serviceaccount.yaml`**: ServiceAccount `k8s-mcp` in `mcp-system`.
- **`clusterrole.yaml`**: Read-only access to core workloads, logs, events, common workload APIs, and `metrics.k8s.io` pods.
- **`clusterrolebinding.yaml`**: Binds the ClusterRole to that ServiceAccount.

To scope access to specific namespaces only, replace the ClusterRole/Binding with a **Role** + **RoleBinding** per namespace (recommended for stricter environments).

---

## Build the image

```bash
cd ai/k8s-mcp
docker build -t your-registry.example.com/k8s-mcp:latest .
docker push your-registry.example.com/k8s-mcp:latest
```

Edit `deployment.yaml` to use your image (and tags), then `kubectl apply -f deployment.yaml`.

---

## Local development (optional)

> **Note:** `app.py` calls `config.load_incluster_config()` only. It expects to run **inside a pod**. Running `python app.py` on your laptop will fail unless you change config loading.

For laptop development you typically:

1. Use `config.load_kube_config()` (and optional context selection), **or**  
2. Run the app in a dev pod / `kubectl run` with the same ServiceAccount/RBAC.

Example virtualenv:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## CI

`.github/workflows/python-syntax-check.yml` runs `python -m py_compile` on all `*.py` files on push/PR.

---

## Project layout

| File | Role |
|------|------|
| `app.py` | FastMCP server, tools, HTTP entrypoint |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container image |
| `deployment.yaml` / `service.yaml` | Kubernetes workload + Service |
| `serviceaccount.yaml` | Pod identity |
| `clusterrole.yaml` / `clusterrolebinding.yaml` | RBAC |

---

## Troubleshooting

| Symptom | What to check |
|--------|----------------|
| MCP client cannot connect | URL must end with `/mcp`; confirm port-forward or ingress path; check pod logs. |
| `Permission denied` / 403 from API | RBAC: ClusterRoleBinding subject namespace/name; redeploy after SA changes. |
| `top_pods` says metrics API missing | Install [Metrics Server](https://github.com/kubernetes-sigs/metrics-server). |
| Empty or wrong namespace | Tools default to `test`; pass `namespace` explicitly. |
| `ImagePullBackOff` | Image name/tag and registry pull secrets on the `mcp-system` namespace. |

---

## References

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [Kubernetes client-python](https://github.com/kubernetes-client/python)
