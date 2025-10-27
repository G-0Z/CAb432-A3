import boto3
import time
from PIL import Image
import io

s3 = boto3.client('s3', region_name='ap-southeast-2')
sqs = boto3.client('sqs', region_name='ap-southeast-2')
queue_url = 'https://sqs.ap-southeast-2.amazonaws.com/901444280953/image-processing-queue-n11543027'
bucket = 'maxgo-cab432-2025'  # Match API bucket

while True:
    messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1)
    if 'Messages' in messages:
        msg = messages['Messages'][0]
        key = msg['Body']
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            img = Image.open(io.BytesIO(obj['Body'].read()))
            img = img.resize((800, 600))  # CPU-intensive
            img = img.convert('L')  # Grayscale
            output_key = f'processed/{key.split("/")[-1]}'
            with io.BytesIO() as output:
                img.save(output, format='JPEG')
                output.seek(0)
                s3.upload_fileobj(output, bucket, output_key)
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg['ReceiptHandle'])
        except Exception as e:
            print(f"Error processing {key}: {e}")
    time.sleep(1)