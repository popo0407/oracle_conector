import {
  SQSClient,
  SendMessageCommand,
  ReceiveMessageCommand,
  DeleteMessageCommand,
} from "@aws-sdk/client-sqs";
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import { randomUUID } from "crypto";

const sqs = new SQSClient({ region: process.env.REGION ?? "ap-northeast-1" });
const s3 = new S3Client({ region: process.env.REGION ?? "ap-northeast-1" });

const REQUEST_QUEUE_URL = process.env.REQUEST_QUEUE_URL!;
const RESPONSE_QUEUE_URL = process.env.RESPONSE_QUEUE_URL!;
const RESULT_BUCKET = process.env.RESULT_BUCKET!;

/** Lambda イベント型定義 */
interface SqlRequestEvent {
  /** 実行する SQL 文 */
  sql: string;
  /** 接続先 Oracle TNS 名 */
  tns: string;
  /** ホワイトリスト登録済みアプリケーション ID */
  app_id: string;
  /** レスポンス受信タイムアウト（秒、デフォルト 25） */
  timeout_seconds?: number;
}

interface SqlResponsePayload {
  id: string;
  s3_key?: string;
  affected_rows?: number;
  error?: string;
}

/**
 * S3 から JSON 結果を取得して返す。
 */
async function fetchS3Result(key: string): Promise<unknown> {
  const cmd = new GetObjectCommand({ Bucket: RESULT_BUCKET, Key: key });
  const res = await s3.send(cmd);
  const body = await res.Body?.transformToString("utf-8");
  return body ? JSON.parse(body) : null;
}

/**
 * レスポンスキューをポーリングして対象 ID のメッセージを取得する。
 * タイムアウト（秒）内に見つからなければ null を返す。
 */
async function pollResponse(
  requestId: string,
  timeoutSeconds: number,
): Promise<SqlResponsePayload | null> {
  const deadline = Date.now() + timeoutSeconds * 1000;

  while (Date.now() < deadline) {
    const res = await sqs.send(
      new ReceiveMessageCommand({
        QueueUrl: RESPONSE_QUEUE_URL,
        MaxNumberOfMessages: 10,
        WaitTimeSeconds: Math.min(10, Math.ceil((deadline - Date.now()) / 1000)),
      }),
    );

    for (const msg of res.Messages ?? []) {
      const payload = JSON.parse(msg.Body!) as SqlResponsePayload;
      if (payload.id === requestId) {
        // 自分宛のメッセージを削除
        await sqs.send(
          new DeleteMessageCommand({
            QueueUrl: RESPONSE_QUEUE_URL,
            ReceiptHandle: msg.ReceiptHandle!,
          }),
        );
        return payload;
      }
    }
  }

  return null;
}

/**
 * Lambda ハンドラー
 *
 * 入力例:
 * ```json
 * {
 *   "sql": "SELECT * FROM orders WHERE mk_date BETWEEN '2025-01-01' AND '2025-01-31'",
 *   "tns": "ORCL_PROD",
 *   "app_id": "app1"
 * }
 * ```
 */
export const handler = async (event: SqlRequestEvent) => {
  const { sql, tns, app_id, timeout_seconds = 25 } = event;

  if (!sql || !tns || !app_id) {
    return {
      statusCode: 400,
      body: JSON.stringify({ error: "sql, tns, app_id は必須項目です" }),
    };
  }

  const requestId = randomUUID();

  // ① SQS にリクエスト送信
  await sqs.send(
    new SendMessageCommand({
      QueueUrl: REQUEST_QUEUE_URL,
      MessageBody: JSON.stringify({ id: requestId, sql, tns, app_id }),
      MessageGroupId: undefined, // 標準キューのため不要
    }),
  );

  console.log(`[${requestId}] Request sent. sql=${sql.slice(0, 80)}...`);

  // ② レスポンスをポーリング
  const response = await pollResponse(requestId, timeout_seconds);

  if (!response) {
    return {
      statusCode: 504,
      body: JSON.stringify({
        error: "タイムアウト: オンプレエージェントからの応答がありませんでした",
        request_id: requestId,
      }),
    };
  }

  if (response.error) {
    console.error(`[${requestId}] SQL error: ${response.error}`);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: response.error, request_id: requestId }),
    };
  }

  // ③ SELECT 結果は S3 から取得
  let result: unknown = null;
  if (response.s3_key) {
    result = await fetchS3Result(response.s3_key);
    console.log(`[${requestId}] Result fetched from S3: ${response.s3_key}`);
  } else {
    result = { affected_rows: response.affected_rows };
    console.log(`[${requestId}] DML affected_rows=${response.affected_rows}`);
  }

  return {
    statusCode: 200,
    body: JSON.stringify({ request_id: requestId, result }),
  };
};
