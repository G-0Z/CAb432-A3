import os, time, json, boto3

LOG_GROUP  = os.getenv("CW_LOG_GROUP", "/app/api")
LOG_STREAM = os.getenv("CW_LOG_STREAM", "requests")
_cw = boto3.client("logs")
_seq = None

def log_event(event: dict):
    global _seq
    event["ts"] = int(time.time()*1000)
    msg = json.dumps(event, separators=(",", ":"))
    try:
        args = {
            "logGroupName": LOG_GROUP,
            "logStreamName": LOG_STREAM,
            "logEvents": [{"timestamp": event["ts"], "message": msg}],
        }
        if _seq: args["sequenceToken"] = _seq
        resp = _cw.put_log_events(**args)
        _seq = resp.get("nextSequenceToken", _seq)
    except Exception:
        pass  # best-effort
