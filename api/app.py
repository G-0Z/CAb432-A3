from fastapi import FastAPI, UploadFile, File
import boto3
import uuid

app = FastAPI()
s3 = boto3.client('s3')
sqs = boto3.client('sqs')
queue_url = 'YOUR_SQS_QUEUE_URL'  # Replace after creating SQS
bucket = 'maxgo-cab432-2025'

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    key = f'uploads/{uuid.uuid4()}.jpg'
    await s3.upload_fileobj(file.file, bucket, key)
    sqs.send_message(QueueUrl=queue_url, MessageBody=key)
    return {"status": "queued", "key": key}