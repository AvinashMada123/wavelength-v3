"""GCP VM CPU Auto-Scaler Cloud Function.

Monitors VM CPU utilization via Cloud Monitoring and resizes the VM
between MIN_CPUS and MAX_CPUS. Triggered by Cloud Scheduler every 5 minutes.

How it works:
1. Reads average CPU utilization over the last 10 minutes
2. If CPU > SCALE_UP_THRESHOLD (70%) → increase CPUs (stop VM → resize → start)
3. If CPU < SCALE_DOWN_THRESHOLD (20%) → decrease CPUs
4. If within thresholds → no action

IMPORTANT: Resizing requires a VM stop/start (~30-60 seconds downtime).
"""

import logging
import os
import time

import functions_framework
from google.cloud import compute_v1
from google.cloud import monitoring_v3 as monitoring
from google.protobuf import timestamp_pb2

logger = logging.getLogger(__name__)

# Configuration — set via environment variables or defaults
PROJECT_ID = os.environ.get("GCP_PROJECT", "ai-calling-9238e")
ZONE = os.environ.get("GCP_ZONE", "asia-south1-c")
INSTANCE_NAME = os.environ.get("GCP_INSTANCE", "wavelength-v3")

MIN_CPUS = int(os.environ.get("MIN_CPUS", "1"))
MAX_CPUS = int(os.environ.get("MAX_CPUS", "4"))
SCALE_UP_THRESHOLD = float(os.environ.get("SCALE_UP_THRESHOLD", "70"))
SCALE_DOWN_THRESHOLD = float(os.environ.get("SCALE_DOWN_THRESHOLD", "20"))

# CPU to machine type mapping (e2-custom: CPUs, memory in MB)
# Memory scales with CPUs: 4GB per CPU
MACHINE_TYPE_MAP = {
    1: f"zones/{ZONE}/machineTypes/e2-custom-1-4096",
    2: f"zones/{ZONE}/machineTypes/e2-custom-2-8192",
    4: f"zones/{ZONE}/machineTypes/e2-custom-4-16384",
}


def get_cpu_utilization() -> float | None:
    """Get average CPU utilization over the last 10 minutes."""
    client = monitoring.MetricServiceClient()

    now = time.time()
    start = now - 600  # 10 minutes ago

    start_time = timestamp_pb2.Timestamp()
    start_time.FromSeconds(int(start))
    end_time = timestamp_pb2.Timestamp()
    end_time.FromSeconds(int(now))

    interval = monitoring.TimeInterval(
        start_time=start_time,
        end_time=end_time,
    )

    results = client.list_time_series(
        request={
            "name": f"projects/{PROJECT_ID}",
            "filter": (
                'metric.type = "compute.googleapis.com/instance/cpu/utilization" '
                f'AND resource.labels.instance_id = "{_get_instance_id()}"'
            ),
            "interval": interval,
            "view": monitoring.ListTimeSeriesRequest.TimeSeriesView.FULL,
        }
    )

    values = []
    for ts in results:
        for point in ts.points:
            values.append(point.value.double_value * 100)  # Convert to percentage

    if not values:
        logger.warning("no_cpu_data", instance=INSTANCE_NAME)
        return None

    avg = sum(values) / len(values)
    logger.info("cpu_utilization", instance=INSTANCE_NAME, avg_cpu_pct=round(avg, 2))
    return avg


def _get_instance_id() -> str:
    """Get the numeric instance ID from instance name."""
    client = compute_v1.InstancesClient()
    instance = client.get(project=PROJECT_ID, zone=ZONE, instance=INSTANCE_NAME)
    return str(instance.id)


def get_current_cpus() -> int:
    """Get current CPU count of the VM."""
    client = compute_v1.InstancesClient()
    instance = client.get(project=PROJECT_ID, zone=ZONE, instance=INSTANCE_NAME)
    machine_type = instance.machine_type.split("/")[-1]

    # Parse CPU count from machine type name (e.g., "e2-custom-2-8192" → 2)
    parts = machine_type.split("-")
    for i, part in enumerate(parts):
        if part == "custom" and i + 1 < len(parts):
            return int(parts[i + 1])

    # Fallback: use GCP API
    mt_client = compute_v1.MachineTypesClient()
    mt = mt_client.get(project=PROJECT_ID, zone=ZONE, machine_type=machine_type)
    return mt.guest_cpus


def resize_vm(target_cpus: int) -> str:
    """Stop VM, change machine type, restart VM.

    Returns status message.
    """
    if target_cpus not in MACHINE_TYPE_MAP:
        return f"invalid_cpu_count: {target_cpus}, valid: {list(MACHINE_TYPE_MAP.keys())}"

    client = compute_v1.InstancesClient()
    new_machine_type = MACHINE_TYPE_MAP[target_cpus]

    # Step 1: Stop the VM
    logger.info("stopping_vm", instance=INSTANCE_NAME)
    stop_op = client.stop(project=PROJECT_ID, zone=ZONE, instance=INSTANCE_NAME)
    stop_op.result()  # Wait for stop to complete

    # Step 2: Change machine type
    logger.info("resizing_vm", instance=INSTANCE_NAME, target_cpus=target_cpus)
    client.set_machine_type(
        project=PROJECT_ID,
        zone=ZONE,
        instance=INSTANCE_NAME,
        instances_set_machine_type_request_resource=compute_v1.InstancesSetMachineTypeRequest(
            machine_type=new_machine_type,
        ),
    )

    # Step 3: Start the VM
    logger.info("starting_vm", instance=INSTANCE_NAME)
    start_op = client.start(project=PROJECT_ID, zone=ZONE, instance=INSTANCE_NAME)
    start_op.result()  # Wait for start to complete

    logger.info("resize_complete", instance=INSTANCE_NAME, cpus=target_cpus)
    return f"resized to {target_cpus} CPUs"


def determine_target_cpus(current_cpus: int, cpu_pct: float) -> int:
    """Decide target CPU count based on utilization."""
    if cpu_pct > SCALE_UP_THRESHOLD:
        # Scale up: double CPUs (capped at MAX_CPUS)
        target = min(current_cpus * 2, MAX_CPUS)
    elif cpu_pct < SCALE_DOWN_THRESHOLD:
        # Scale down: halve CPUs (min MIN_CPUS)
        target = max(current_cpus // 2, MIN_CPUS)
    else:
        target = current_cpus

    # Snap to valid CPU counts
    valid_cpus = sorted(MACHINE_TYPE_MAP.keys())
    for v in valid_cpus:
        if v >= target:
            return v
    return valid_cpus[-1]


@functions_framework.http
def autoscale_vm(request) -> str:
    """Main Cloud Function entry point.

    Triggered by Cloud Scheduler every 5 minutes via HTTP.
    """
    cpu_pct = get_cpu_utilization()
    if cpu_pct is None:
        return "no CPU data available, skipping"

    current_cpus = get_current_cpus()
    target_cpus = determine_target_cpus(current_cpus, cpu_pct)

    logger.info(
        "autoscale_decision",
        current_cpus=current_cpus,
        target_cpus=target_cpus,
        cpu_pct=round(cpu_pct, 2),
        scale_up_threshold=SCALE_UP_THRESHOLD,
        scale_down_threshold=SCALE_DOWN_THRESHOLD,
    )

    if target_cpus == current_cpus:
        return f"no change needed: {current_cpus} CPUs at {cpu_pct:.1f}%"

    result = resize_vm(target_cpus)
    return f"scaled {current_cpus} → {target_cpus} CPUs (CPU was {cpu_pct:.1f}%): {result}"
