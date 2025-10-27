from fastapi import FastAPI, UploadFile, File
import boto3
import uuid

app = FastAPI()
s3 = boto3.client('s3')
sqs = boto3.client('sqs')
queue_url = 'https://sqs.ap-southeast-2.amazonaws.com/901444280953/image-processing-queue-n11543027'
bucket = 'maxgo-cab432-2025'

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    key = f'uploads/{uuid.uuid4()}.jpg'
    await s3.upload_fileobj(file.file, bucket, key)
    sqs.send_message(QueueUrl=queue_url, MessageBody=key)
    return {"status": "queued", "key": key}