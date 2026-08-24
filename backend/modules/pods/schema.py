def normalize_pod_query(args) -> dict:
    return {
        "namespace": args.get("namespace"),
        "deployment_name": args.get("deployment_name"),
        "phase": args.get("phase"),
        "node_name": args.get("node_name"),
        "pod_name": args.get("pod_name"),
        "tail_lines": int(args.get("tail_lines", 200)),
    }


def normalize_pod_action(payload: dict) -> dict:
    return {
        "namespace": payload.get("namespace"),
        "pod_name": payload.get("pod_name", ""),
    }
