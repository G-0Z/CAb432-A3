from fastapi import FastAPI, UploadFile, File
import boto3
import uuid

app = FastAPI()
s3 = boto3.client('s3', region_name='ap-southeast-2')  # Match SQS region
sqs = boto3.client('sqs', region_name='ap-southeast-2')  # Match SQS region
queue_url = 'https://sqs.ap-southeast-2.amazonaws.com/901444280953/image-processing-queue-n11543027'
bucket = 'maxgo-cab432-2025'  # Your S3 bucket name

@app.post("/upload")
def upload(file: UploadFile = File(...)):
    key = f'uploads/{uuid.uuid4()}.jpg'
    s3.upload_fileobj(file.file, bucket, key)  # Synchronous
    sqs.send_message(QueueUrl=queue_url, MessageBody=key)  # Synchronous
    return {"status": "queued", "key": key}