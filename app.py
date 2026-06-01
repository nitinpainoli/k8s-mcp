from fastmcp import FastMCP
from kubernetes import client, config
from kubernetes.client.rest import ApiException

mcp = FastMCP("k8s-mcp")

# Running inside cluster
config.load_incluster_config()

core_v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()


def mask_secret_env(env):
    """
    Mask Secret-based env vars
    """
    if env.value_from and env.value_from.secret_key_ref:
        return "***MASKED***"

    return env.value


@mcp.tool()
def get_pods(namespace: str = "default"):
    """
    List all pods in namespace
    """

    pods = core_v1.list_namespaced_pod(namespace)

    return [
        {
            "name": pod.metadata.name,
            "phase": pod.status.phase,
            "node": pod.spec.node_name,
        }
        for pod in pods.items
    ]


@mcp.tool()
def get_pod_details(
    pod_name: str,
    namespace: str = "default"
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
    namespace: str = "default"
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
    namespace: str = "default"
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
    namespace: str = "default",
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
    namespace: str = "default"
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
    namespace: str = "default"
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
    namespace: str = "default"
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
    namespace: str = "default"
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
    namespace: str = "default"
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
    namespace: str = "default"
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
    namespace: str = "default"
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
if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8000
    )
