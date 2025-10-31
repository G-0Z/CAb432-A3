import os, time, json, boto3

REGION    = os.getenv("AWS_REGION", "ap-southeast-2")
QUEUE_URL = os.getenv("QUEUE_URL")  # SQS queue URL
NAMESPACE = os.getenv("METRIC_NAMESPACE", "MaxGo/ImageApp")
METRIC    = os.getenv("METRIC_NAME", "ApproximateNumberOfMessagesVisible")

sqs = boto3.client("sqs", region_name=REGION)
cw  = boto3.client("cloudwatch", region_name=REGION)

def get_queue_depth(url: str) -> int:
    attrs = sqs.get_queue_attributes(
        QueueUrl=url, AttributeNames=["ApproximateNumberOfMessagesVisible"]
    )
    return int(attrs["Attributes"].get("ApproximateNumberOfMessagesVisible", "0"))

def put_metric(value: int):
    cw.put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[{
            "MetricName": METRIC,
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "Value": value,
            "Unit": "Count",
        }]
    )

def handler(event, context):
    if not QUEUE_URL:
        raise RuntimeError("QUEUE_URL env var required")
    depth = get_queue_depth(QUEUE_URL)
    put_metric(depth)
    return {"depth": depth}
