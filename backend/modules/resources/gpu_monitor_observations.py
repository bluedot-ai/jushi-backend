"""Display-only latest physical-card observations; never historical averages.

Reuse the instant-query raw matrix already read by the strict monitor. Its last
point is the latest observation in Prometheus' ordinary five-minute lookback,
not the query evaluation time. No clock adjustment or sample retimestamping.
"""

import math
from datetime import datetime, timedelta, timezone

from . import gpu_allocation_providers as providers

LOOKBACK_SECONDS = 300
_TIMEZONE = timezone(timedelta(hours=8))


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, _TIMEZONE).isoformat(timespec="seconds") if timestamp is not None else None


def _latest(rows, inventory, now, name, vendor):
    streams, aliases, invalid, issues = {}, {}, set(), set()
    uuid_keys, chip_keys, signatures = {}, {}, {}
    for row in rows or []:
        metric = row.get("metric") or {}
        node = next((str(metric.get(label) or "").strip() for label in
                     ("node", "Hostname", "hostname", "kubernetes_node") if metric.get(label)), "")
        if node not in inventory or inventory[node] <= 0:
            continue
        try:
            key, uuid = providers._identity(metric, node, vendor)
        except ValueError:
            # An unidentifiable series cannot be substituted for a physical card.
            issues.add("physical_device_identity_invalid")
            invalid.update(card for card in streams if card[0] == node)
            # Reject this node, including identities encountered later.
            invalid.add((node, None))
            continue
        if key in aliases and aliases[key] != uuid:
            invalid.add(key)
        aliases[key] = uuid
        if uuid:
            if uuid in uuid_keys and uuid_keys[uuid] != key:
                invalid.update((key, uuid_keys[uuid]))
            uuid_keys[uuid] = key
        if vendor == "ascend" and metric.get("id") is not None:
            chip = (node, str(metric["id"]))
            if chip in chip_keys and chip_keys[chip] != key:
                invalid.update((key, chip_keys[chip]))
            chip_keys[chip] = key
        source = tuple(sorted((label, value) for label, value in metric.items()
                              if label not in providers.BUSINESS_OWNER_LABELS and label != "__name__"))
        fragments = streams.setdefault(key, {}).setdefault(source, {})
        signature = tuple(sorted(metric.items()))
        signatures.setdefault((key, source), set()).add(signature)
        for pair in row.get("values") or []:
            try:
                timestamp, value = float(pair[0]), float(pair[1])
                valid = (math.isfinite(timestamp) and math.isfinite(value)
                         and now - LOOKBACK_SECONDS < timestamp <= now
                         and value >= 0 and (name != "utilization" or value <= 100))
            except (TypeError, ValueError, IndexError, OverflowError):
                valid = False
            if not valid:
                invalid.add(key)
                continue
            if timestamp in fragments and fragments[timestamp] != value:
                invalid.add(key)
            fragments[timestamp] = value
    for node, expected in inventory.items():
        keys = [key for key in streams if key[0] == node]
        if len(keys) > expected:
            invalid.update(keys)
            issues.add("physical_inventory_count_mismatch")
    result = {}
    for key, sources in streams.items():
        points = list(sources.values())
        if key in invalid or (key[0], None) in invalid or not points[0]:
            issues.add("invalid_or_conflicting_samples")
            continue
        if any(len(signatures[(key, source)]) > 1 and not (dict(source).get("instance") and dict(source).get("job"))
               for source in sources):
            issues.add("conflicting_monitor_sources")
            continue
        if any(fragment != points[0] for fragment in points[1:]):
            issues.add("conflicting_monitor_sources")
            continue
        timestamp = max(points[0])
        result[key] = {"value": points[0][timestamp], "timestamp": timestamp,
                       "uuid": aliases[key], "sources": frozenset(sources)}
    return result, issues


def _summary(records, inventory, now, scrape, vendor, issues=(), *, memory=False, known=True):
    nodes = []
    for node, expected in sorted(inventory.items()):
        if expected <= 0:
            continue
        present = [record for key, record in records.items() if key[0] == node]
        ages = [now - record["timestamp"] for record in present]
        delayed = sum(age > 2 * scrape for age in ages)
        nodes.append({"node_name": node, "vendor": vendor, "expected_cards": expected,
                      "observed_cards": len(present), "missing_cards": expected - len(present),
                      "delayed_cards": delayed, "maximum_age_seconds": round(max(ages), 2) if ages else None,
                      "latest_sample_at": _iso(max(record["timestamp"] for record in present)) if present else None})
    return _combine([{
        "expected_cards": sum(inventory.values()) if known else None,
        "observed_cards": len(records), "delayed_cards": sum(now - row["timestamp"] > 2 * scrape for row in records.values()),
        "oldest_sample_at": _iso(min(row["timestamp"] for row in records.values())) if records else None,
        "latest_sample_at": _iso(max(row["timestamp"] for row in records.values())) if records else None,
        "maximum_age_seconds": round(max(now - row["timestamp"] for row in records.values()), 2) if records else None,
        "nodes": nodes, "issues": sorted(issues),
        "_numerator": sum(row["used_bytes"] if memory else row["value"] for row in records.values()),
        "_denominator": sum(row["total_bytes"] if memory else 1 for row in records.values()),
    }], memory=memory)


def _combine(parts, *, memory=False):
    expected = sum(part["expected_cards"] for part in parts) if all(part["expected_cards"] is not None for part in parts) else None
    count = sum(part["observed_cards"] for part in parts)
    delayed = sum(part["delayed_cards"] for part in parts)
    numerator = sum(part["_numerator"] for part in parts)
    denominator = sum(part["_denominator"] for part in parts)
    issues = set(issue for part in parts for issue in part["issues"])
    if expected is None:
        issues.add("inventory_unavailable")
    elif count < expected:
        issues.add("missing_samples")
    if delayed:
        issues.add("delayed_samples")
    if not count or denominator <= 0:
        status = "unavailable" if expected != 0 else "no_devices"
    elif expected is None or count < expected:
        status = "partial_delayed" if delayed else "partial"
    else:
        status = "delayed" if delayed else "complete"
    oldest = [part["oldest_sample_at"] for part in parts if part["oldest_sample_at"]]
    latest = [part["latest_sample_at"] for part in parts if part["latest_sample_at"]]
    ages = [part["maximum_age_seconds"] for part in parts if part["maximum_age_seconds"] is not None]
    return {"value": round(numerator / denominator * (100 if memory else 1), 4) if count and denominator > 0 else None,
            "expected_cards": expected, "observed_cards": count, "fresh_cards": count - delayed,
            "delayed_cards": delayed, "missing_cards": expected - count if expected is not None else None,
            "status": status, "oldest_sample_at": min(oldest) if oldest else None,
            "latest_sample_at": max(latest) if latest else None, "maximum_age_seconds": max(ages) if ages else None,
            "nodes": [node for part in parts for node in part["nodes"]], "issues": sorted(issues),
            "_numerator": numerator, "_denominator": denominator}


def latest_observations(rows_by_metric, inventory, now, vendor, errors=(), *, known=True):
    """Each display metric has its own physical-card coverage and source age."""
    values, problems = {}, {}
    for name in ("utilization", "memory_used", "memory_total"):
        values[name], problems[name] = _latest(rows_by_metric.get(name), inventory, now, name, vendor)
        if name in errors:
            problems[name].add("query_failed")
            values[name] = {}
    scrape = providers._scrape_interval(vendor)
    memory, memory_issues = {}, problems["memory_used"] | problems["memory_total"]
    multiplier = providers._memory_multiplier(vendor)
    if multiplier is None:
        memory_issues.add("memory_unit_invalid")
    for key in values["memory_used"].keys() & values["memory_total"].keys():
        used, total = values["memory_used"][key], values["memory_total"][key]
        if (used["uuid"] != total["uuid"] or not used["sources"] & total["sources"]
                or abs(used["timestamp"] - total["timestamp"]) > 2 * scrape):
            memory_issues.add("memory_identity_or_timestamp_mismatch")
            continue
        if total["value"] <= 0 or used["value"] > total["value"]:
            memory_issues.add("memory_value_invalid")
            continue
        if multiplier is not None:
            memory[key] = {"timestamp": min(used["timestamp"], total["timestamp"]),
                           "used_bytes": used["value"] * multiplier, "total_bytes": total["value"] * multiplier}
    return {"mode": "latest_observation", "lookback_seconds": LOOKBACK_SECONDS,
            "utilization": _summary(values["utilization"], inventory, now, scrape, vendor, problems["utilization"], known=known),
            "memory": _summary(memory, inventory, now, scrape, vendor, memory_issues, memory=True, known=known)}


def combine_observations(parts):
    return {"mode": "latest_observation", "lookback_seconds": LOOKBACK_SECONDS,
            **{name: _combine([part[name] for part in parts], memory=name == "memory")
               for name in ("utilization", "memory")}}


def public_observations(observations):
    """Internal sums exist only to weight observed subsets across vendors."""
    return {key: {name: value for name, value in field.items() if not name.startswith("_")}
            if isinstance(field, dict) else field for key, field in observations.items()}
