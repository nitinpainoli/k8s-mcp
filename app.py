from fastmcp import FastMCP
from kubernetes import client, config
from kubernetes.client.rest import ApiException

mcp = FastMCP("k8s-mcp")

# Running inside cluster
config.load_incluster_config()

core_v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
custom_api = client.CustomObjectsApi()

# metrics.k8s.io — same data as `kubectl top pods`
METRICS_GROUP = "metrics.k8s.io"
METRICS_VERSION = "v1beta1"
METRICS_PODS_PLURAL = "pods"


def mask_secret_env(env):
    """
    Mask Secret-based env vars
    """
    if env.value_from and env.value_from.secret_key_ref:
        return "***MASKED***"

    return env.value


@mcp.tool()
def get_pods(namespace: str = "test"):
    """
    List all pods in namespace
    """

    pods = core_v1.list_namespaced_pod(namespace)

    return [
        {
            "name": pod.metadata.name,
            "phase": pod.status.phase,
            "pod_ip": getattr(pod.status, "pod_ip", None),
            "node": pod.spec.node_name,
        }
        for pod in pods.items
    ]


@mcp.tool()
def get_pod_details(
    pod_name: str,
    namespace: str = "test"
):
    """
    Get pod details + env variables
    """

    pod = core_v1.read_namespaced_pod(
        pod_name,
        namespace
    )

    result = {
        "pod": pod.metadata.name,
        "namespace": namespace,
        "pod_ip": getattr(pod.status, "pod_ip", None),
        "node": pod.spec.node_name,
        "containers": []
    }

    for container in pod.spec.containers:

        envs = {}

        if container.env:
            for env in container.env:

                envs[env.name] = mask_secret_env(env)

        result["containers"].append({
            "container": container.name,
            "image": container.image,
            "env": envs
        })

    return result


@mcp.tool()
def get_deployments(
    namespace: str = "test"
):
    """
    List deployments
    """

    deployments = apps_v1.list_namespaced_deployment(
        namespace
    )

    return [
        {
            "name": d.metadata.name,
            "replicas": d.spec.replicas,
            "available": d.status.available_replicas,
        }
        for d in deployments.items
    ]


@mcp.tool()
def get_events(
    namespace: str = "test"
):
    """
    Get namespace events
    """

    events = core_v1.list_namespaced_event(
        namespace
    )

    return [
        {
            "type": e.type,
            "reason": e.reason,
            "message": e.message,
            "object": (
                e.involved_object.name
                if e.involved_object
                else ""
            )
        }
        for e in events.items
    ]


@mcp.tool()
def get_logs(
    pod_name: str,
    namespace: str = "test",
    tail_lines: int = 100
):
    """
    Read pod logs
    """

    try:
        logs = core_v1.read_namespaced_pod_log(
            pod_name,
            namespace,
            tail_lines=tail_lines
        )

        return logs

    except ApiException as e:
        return str(e)


@mcp.tool()
def compare_pods(
    pod1: str,
    pod2: str,
    namespace: str = "test"
):
    """
    Compare environment variables between pods
    """

    p1 = core_v1.read_namespaced_pod(
        pod1,
        namespace
    )

    p2 = core_v1.read_namespaced_pod(
        pod2,
        namespace
    )

    env1 = {}
    env2 = {}

    for c in p1.spec.containers:
        if c.env:
            for env in c.env:
                env1[env.name] = mask_secret_env(env)

    for c in p2.spec.containers:
        if c.env:
            for env in c.env:
                env2[env.name] = mask_secret_env(env)

    missing_in_pod2 = list(
        set(env1.keys()) - set(env2.keys())
    )

    missing_in_pod1 = list(
        set(env2.keys()) - set(env1.keys())
    )

    changed = {}

    for key in set(env1.keys()) & set(env2.keys()):
        if env1[key] != env2[key]:
            changed[key] = {
                "pod1": env1[key],
                "pod2": env2[key]
            }

    return {
        "missing_in_pod2": missing_in_pod2,
        "missing_in_pod1": missing_in_pod1,
        "changed": changed
    }


@mcp.tool()
def find_crashloops(
    namespace: str = "test"
):
    """
    Find CrashLoopBackOff pods
    """

    pods = core_v1.list_namespaced_pod(namespace)

    result = []

    for pod in pods.items:

        if not pod.status.container_statuses:
            continue

        for status in pod.status.container_statuses:

            waiting = status.state.waiting

            if (
                waiting and
                waiting.reason == "CrashLoopBackOff"
            ):
                result.append({
                    "pod": pod.metadata.name,
                    "container": status.name,
                    "reason": waiting.reason
                })

    return result
@mcp.tool()
def deployment_status(
    deployment_name: str,
    namespace: str = "test"
):
    """
    Get deployment health
    """

    deployment = apps_v1.read_namespaced_deployment(
        deployment_name,
        namespace
    )

    return {
        "deployment": deployment_name,
        "desired": deployment.spec.replicas,
        "ready": deployment.status.ready_replicas or 0,
        "available": deployment.status.available_replicas or 0,
        "updated": deployment.status.updated_replicas or 0,
        "healthy": (
            (deployment.status.available_replicas or 0)
            == deployment.spec.replicas
        )
    }
@mcp.tool()
def diagnose_pod(
    pod_name: str,
    namespace: str = "test"
):
    """
    Diagnose pod status and events
    """

    pod = core_v1.read_namespaced_pod(
        pod_name,
        namespace
    )

    events = core_v1.list_namespaced_event(namespace)

    pod_events = []

    for event in events.items:

        if (
            event.involved_object
            and event.involved_object.name == pod_name
        ):
            pod_events.append({
                "type": event.type,
                "reason": event.reason,
                "message": event.message
            })

    return {
        "pod": pod_name,
        "phase": pod.status.phase,
        "node": pod.spec.node_name,
        "events": pod_events
    }
@mcp.tool()
def analyze_crashloop(
    pod_name: str,
    namespace: str = "test"
):
    """
    Analyze CrashLoopBackOff pod
    """

    pod = core_v1.read_namespaced_pod(
        pod_name,
        namespace
    )

    result = []

    for container in pod.status.container_statuses or []:

        item = {
            "container": container.name,
            "restart_count": container.restart_count
        }

        if (
            container.last_state
            and container.last_state.terminated
        ):
            item["exit_code"] = (
                container.last_state.terminated.exit_code
            )

            item["reason"] = (
                container.last_state.terminated.reason
            )

        try:
            item["logs"] = (
                core_v1.read_namespaced_pod_log(
                    pod_name,
                    namespace,
                    tail_lines=50
                )
            )
        except Exception as e:
            item["logs"] = str(e)

        result.append(item)

    return result
@mcp.tool()
def get_env_var(
    pod_name: str,
    env_name: str,
    namespace: str = "test"
):
    """
    Get specific environment variable
    """

    pod = core_v1.read_namespaced_pod(
        pod_name,
        namespace
    )

    for container in pod.spec.containers:

        for env in container.env or []:

            if env.name == env_name:

                if (
                    env.value_from
                    and env.value_from.secret_key_ref
                ):
                    return {
                        "env": env_name,
                        "value": "***MASKED***"
                    }

                return {
                    "env": env_name,
                    "value": env.value
                }

    return {
        "env": env_name,
        "value": None
    }
@mcp.tool()
def diagnose_application(
    deployment_name: str,
    namespace: str = "test"
):
    """
    Diagnose deployment, pods, events and logs.
    Useful when deployment is unhealthy.
    """

    try:

        deployment = apps_v1.read_namespaced_deployment(
            deployment_name,
            namespace
        )

        result = {
            "deployment": deployment_name,
            "namespace": namespace,
            "deployment_status": {},
            "pods": [],
            "issues": []
        }

        result["deployment_status"] = {
            "desired": deployment.spec.replicas,
            "ready": deployment.status.ready_replicas or 0,
            "available": deployment.status.available_replicas or 0,
            "updated": deployment.status.updated_replicas or 0
        }

        selector = deployment.spec.selector.match_labels

        selector_string = ",".join(
            [f"{k}={v}" for k, v in selector.items()]
        )

        pods = core_v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=selector_string
        )

        events = core_v1.list_namespaced_event(
            namespace
        )

        for pod in pods.items:

            pod_info = {
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "node": pod.spec.node_name,
                "restarts": 0,
                "issues": [],
                "logs": ""
            }

            for container in (
                pod.status.container_statuses or []
            ):

                pod_info["restarts"] += (
                    container.restart_count
                )

                if (
                    container.state
                    and container.state.waiting
                ):

                    reason = (
                        container.state.waiting.reason
                    )

                    pod_info["issues"].append(
                        reason
                    )

                    if reason in [
                        "CrashLoopBackOff",
                        "ImagePullBackOff",
                        "ErrImagePull"
                    ]:
                        result["issues"].append({
                            "pod": pod.metadata.name,
                            "reason": reason
                        })

                if (
                    container.last_state
                    and container.last_state.terminated
                ):
                    pod_info["issues"].append(
                        f"ExitCode={container.last_state.terminated.exit_code}"
                    )

            pod_events = []

            for event in events.items:

                if (
                    event.involved_object
                    and event.involved_object.name
                    == pod.metadata.name
                ):
                    pod_events.append({
                        "type": event.type,
                        "reason": event.reason,
                        "message": event.message
                    })

            pod_info["events"] = pod_events

            try:

                if pod_info["issues"]:

                    pod_info["logs"] = (
                        core_v1.read_namespaced_pod_log(
                            pod.metadata.name,
                            namespace,
                            tail_lines=50
                        )
                    )

            except Exception as e:
                pod_info["logs"] = str(e)

            result["pods"].append(
                pod_info
            )

        return result

    except Exception as e:
        return {
            "error": str(e)
        }


def _parse_cpu_usage_to_cores(usage: str) -> float:
    """
    PodMetrics container usage.cpu is usually nanocores (e.g. '12345678n');
    fall back to resource.Quantity parsing (e.g. '100m' cores).
    """
    if not usage:
        return 0.0
    s = str(usage).strip()
    if s.endswith("n") and len(s) > 1:
        body = s[:-1]
        try:
            return int(body) / 1_000_000_000.0
        except ValueError:
            pass
    try:
        from kubernetes.utils.quantity import parse_quantity

        return float(parse_quantity(s))
    except Exception:
        return 0.0


def _parse_memory_usage_to_bytes(usage: str) -> int:
    if not usage:
        return 0
    try:
        from kubernetes.utils.quantity import parse_quantity

        return int(parse_quantity(str(usage).strip()))
    except Exception:
        return 0


def _format_cpu_like_kubectl(cores: float) -> str:
    """Similar to kubectl top: millicores with 'm' when under 1 core."""
    if cores <= 0:
        return "0"
    millicores = cores * 1000.0
    if millicores < 1000:
        return f"{int(round(millicores))}m"
    s = f"{cores:.3f}".rstrip("0").rstrip(".")
    return s or "0"


def _format_memory_like_kubectl(num_bytes: int) -> str:
    """Binary Mi/Gi style like kubectl top pods."""
    if num_bytes <= 0:
        return "0"
    gib = 1024**3
    mib = 1024**2
    kib = 1024
    if num_bytes >= gib:
        v = num_bytes / gib
        return f"{int(round(v))}Gi" if v >= 10 else f"{v:.1f}Gi".replace(".0Gi", "Gi")
    if num_bytes >= mib:
        v = num_bytes / mib
        return f"{int(round(v))}Mi" if v >= 10 else f"{v:.1f}Mi".replace(".0Mi", "Mi")
    if num_bytes >= kib:
        v = num_bytes / kib
        return f"{int(round(v))}Ki" if v >= 10 else f"{v:.1f}Ki".replace(".0Ki", "Ki")
    return str(int(num_bytes))


@mcp.tool()
def top_pods(namespace: str = "test"):
    """
    Live CPU and memory usage per pod (same API as ``kubectl top pods``: metrics.k8s.io).

    Requires metrics-server (or another implementation of the resource metrics API).
    """
    try:
        metrics = custom_api.list_namespaced_custom_object(
            group=METRICS_GROUP,
            version=METRICS_VERSION,
            namespace=namespace,
            plural=METRICS_PODS_PLURAL,
        )
    except ApiException as e:
        if e.status == 404:
            return {
                "error": "metrics.k8s.io not found — install or enable metrics-server",
                "status": e.status,
            }
        return {"error": str(e), "status": getattr(e, "status", None)}

    items = metrics.get("items") or []
    rows = []
    for item in items:
        meta = item.get("metadata") or {}
        name = meta.get("name", "")
        total_cpu = 0.0
        total_mem = 0
        containers_out = []
        for c in item.get("containers") or []:
            usage = c.get("usage") or {}
            cpu_s = usage.get("cpu") or ""
            mem_s = usage.get("memory") or ""
            c_cores = _parse_cpu_usage_to_cores(cpu_s)
            c_bytes = _parse_memory_usage_to_bytes(mem_s)
            total_cpu += c_cores
            total_mem += c_bytes
            containers_out.append(
                {
                    "container": c.get("name", ""),
                    "cpu": _format_cpu_like_kubectl(c_cores),
                    "memory": _format_memory_like_kubectl(c_bytes),
                }
            )
        rows.append(
            {
                "name": name,
                "cpu": _format_cpu_like_kubectl(total_cpu),
                "memory": _format_memory_like_kubectl(total_mem),
                "containers": containers_out,
            }
        )

    rows.sort(key=lambda r: r["name"])
    return rows
@mcp.tool()
def get_deployment_live_logs(
    deployment_name: str,
    namespace: str = "test",
    since_seconds: int = 300,
    tail_lines: int = 500
):
    """
    Fetch deployment logs from all pods and containers.

    Use this tool whenever a user asks:
    - show deployment logs
    - show application logs
    - show live logs
    - recent logs
    - troubleshoot deployment

    Returns logs from all pods belonging to the deployment.
    """

    try:

        deployment = apps_v1.read_namespaced_deployment(
            deployment_name,
            namespace
        )

        selector = deployment.spec.selector.match_labels

        selector_string = ",".join(
            [
                f"{k}={v}"
                for k, v in selector.items()
            ]
        )

        pods = core_v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=selector_string
        )

        result = {
            "deployment": deployment_name,
            "namespace": namespace,
            "since_seconds": since_seconds,
            "pod_count": len(pods.items),
            "pods": {}
        }

        for pod in pods.items:

            pod_logs = {}

            for container in pod.spec.containers:

                try:

                    logs = (
                        core_v1.read_namespaced_pod_log(
                            name=pod.metadata.name,
                            namespace=namespace,
                            container=container.name,
                            since_seconds=since_seconds,
                            tail_lines=tail_lines,
                            timestamps=True
                        )
                    )

                    pod_logs[container.name] = {
                        "status": "success",
                        "logs": logs
                    }

                except Exception as e:

                    pod_logs[container.name] = {
                        "status": "error",
                        "error": str(e)
                    }

            result["pods"][
                pod.metadata.name
            ] = pod_logs

        return result

    except Exception as e:

        return {
            "status": "error",
            "deployment": deployment_name,
            "namespace": namespace,
            "error": str(e)
        }
@mcp.tool()
def get_deployment_full_details(
    deployment_name: str,
    namespace: str = "test",
    tail_lines: int = 100
):
    """
    Complete deployment diagnostics.

    Returns:
    - Deployment health
    - Resource Requests
    - Resource Limits
    - Live CPU Usage
    - Live Memory Usage
    - Pod status
    - Restart count
    - Events
    - Logs
    """

    try:

        deployment = apps_v1.read_namespaced_deployment(
            deployment_name,
            namespace
        )

        result = {
            "deployment": deployment_name,
            "namespace": namespace,
            "deployment_status": {
                "desired": deployment.spec.replicas,
                "ready": deployment.status.ready_replicas or 0,
                "available": deployment.status.available_replicas or 0,
                "updated": deployment.status.updated_replicas or 0,
                "healthy": (
                    (deployment.status.available_replicas or 0)
                    == deployment.spec.replicas
                )
            },
            "containers": [],
            "pods": []
        }

        #
        # Deployment Resources
        #
        for container in deployment.spec.template.spec.containers:

            result["containers"].append({
                "container": container.name,
                "image": container.image,
                "requests": (
                    container.resources.requests or {}
                ),
                "limits": (
                    container.resources.limits or {}
                )
            })

        #
        # Find Deployment Pods
        #
        selector = (
            deployment.spec.selector.match_labels
        )

        selector_string = ",".join(
            [
                f"{k}={v}"
                for k, v in selector.items()
            ]
        )

        pods = core_v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=selector_string
        )

        #
        # Get Metrics
        #
        metrics_map = {}

        try:

            metrics = (
                custom_api.list_namespaced_custom_object(
                    group=METRICS_GROUP,
                    version=METRICS_VERSION,
                    namespace=namespace,
                    plural=METRICS_PODS_PLURAL,
                )
            )

            for item in metrics.get(
                "items",
                []
            ):

                pod_cpu = 0.0
                pod_mem = 0

                for c in item.get(
                    "containers",
                    []
                ):

                    usage = c.get(
                        "usage",
                        {}
                    )

                    pod_cpu += (
                        _parse_cpu_usage_to_cores(
                            usage.get(
                                "cpu",
                                ""
                            )
                        )
                    )

                    pod_mem += (
                        _parse_memory_usage_to_bytes(
                            usage.get(
                                "memory",
                                ""
                            )
                        )
                    )

                metrics_map[
                    item["metadata"]["name"]
                ] = {
                    "cpu": (
                        _format_cpu_like_kubectl(
                            pod_cpu
                        )
                    ),
                    "memory": (
                        _format_memory_like_kubectl(
                            pod_mem
                        )
                    )
                }

        except Exception as e:

            metrics_map = {
                "__error__": str(e)
            }

        #
        # Get Events Once
        #
        all_events = (
            core_v1.list_namespaced_event(
                namespace
            )
        )

        #
        # Pod Details
        #
        for pod in pods.items:

            pod_name = pod.metadata.name

            pod_info = {
                "pod": pod_name,
                "phase": pod.status.phase,
                "pod_ip": getattr(
                    pod.status,
                    "pod_ip",
                    None
                ),
                "node": pod.spec.node_name,
                "cpu": None,
                "memory": None,
                "containers": [],
                "events": [],
                "logs": ""
            }

            #
            # Metrics
            #
            if pod_name in metrics_map:

                pod_info["cpu"] = (
                    metrics_map[pod_name]["cpu"]
                )

                pod_info["memory"] = (
                    metrics_map[pod_name]["memory"]
                )

            #
            # Container Status
            #
            for status in (
                pod.status.container_statuses
                or []
            ):

                container_data = {
                    "container": status.name,
                    "ready": status.ready,
                    "restart_count": (
                        status.restart_count
                    ),
                    "state": ""
                }

                if (
                    status.state
                    and status.state.running
                ):
                    container_data[
                        "state"
                    ] = "Running"

                elif (
                    status.state
                    and status.state.waiting
                ):
                    container_data[
                        "state"
                    ] = (
                        status.state.waiting.reason
                    )

                elif (
                    status.state
                    and status.state.terminated
                ):
                    container_data[
                        "state"
                    ] = (
                        status.state.terminated.reason
                    )

                pod_info[
                    "containers"
                ].append(
                    container_data
                )

            #
            # Pod Events
            #
            for event in all_events.items:

                if (
                    event.involved_object
                    and event.involved_object.name
                    == pod_name
                ):

                    pod_info[
                        "events"
                    ].append({
                        "type": event.type,
                        "reason": event.reason,
                        "message": event.message
                    })

            #
            # Logs
            #
            try:

                pod_info["logs"] = (
                    core_v1.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=namespace,
                        tail_lines=tail_lines
                    )
                )

            except Exception as e:

                pod_info["logs"] = str(e)

            result["pods"].append(
                pod_info
            )

        return result

    except Exception as e:

        return {
            "error": str(e)
        }
if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8000
    )
