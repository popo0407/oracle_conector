import json
import boto3
import uuid

client = boto3.client('sqs', region_name='ap-northeast-1')
request_id = 'test-' + str(uuid.uuid4())[:8]
message = {
    'id': request_id,
    'sql': "SELECT * FROM orders WHERE MK_DATE BETWEEN TO_DATE('2024-01-01','YYYY-MM-DD') AND TO_DATE('2024-12-31','YYYY-MM-DD')",
    'tns': 'ORCL_PROD',
    'app_id': 'app1'
}
json_str = json.dumps(message)
print(f'Message ID: {request_id}')
print(f'Message Body: {json_str}')
response = client.send_message(
    QueueUrl='https://sqs.ap-northeast-1.amazonaws.com/590184009554/onprem-sql-request',
    MessageBody=json_str
)
print(f"SQS MessageId: {response['MessageId']}")
print(f"MD5OfMessageBody: {response['MD5OfMessageBody']}")
