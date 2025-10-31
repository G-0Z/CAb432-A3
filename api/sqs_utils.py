import os, json, boto3
from botocore.config import Config

REGION    = os.getenv("AWS_REGION", "ap-southeast-2")
QUEUE_URL = os.getenv("QUEUE_URL")  # required

if not QUEUE_URL:
    raise RuntimeError("QUEUE_URL env var is required for SQS")

_sqs = boto3.client("sqs", region_name=REGION, config=Config(retries={"max_attempts": 5}))

def send_task(key: str, mode: str, params: dict | None = None) -> dict:
    body = {"key": key, "mode": mode, "params": params or {}}
    return _sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(body))
