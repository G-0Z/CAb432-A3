from fastapi import FastAPI, UploadFile, File
import boto3
import uuid
from asyncio import run_in_executor

app = FastAPI()
s3 = boto3.client('s3', region_name='ap-southeast-2')  # Match SQS region
sqs = boto3.client('sqs', region_name='ap-southeast-2')  # Match SQS region
queue_url = 'https://sqs.ap-southeast-2.amazonaws.com/901444280953/image-processing-queue-n11543027'
bucket = 'maxgo-cab432-2025'  

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    key = f'uploads/{uuid.uuid4()}.jpg'
    await run_in_executor(None, lambda: s3.upload_fileobj(file.file, bucket, key))
    await run_in_executor(None, lambda: sqs.send_message(QueueUrl=queue_url, MessageBody=key))
    return {"status": "queued", "key": key}