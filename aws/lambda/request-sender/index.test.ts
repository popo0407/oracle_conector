import { describe, it, expect, beforeEach, jest } from "@jest/globals";
import { handler, SqlRequestEvent } from "./index";

// AWS SDK をモック化
jest.mock("@aws-sdk/client-sqs");
jest.mock("@aws-sdk/client-s3");

describe("Lambda Request Sender - Mock Mode", () => {
  beforeEach(() => {
    process.env.REQUEST_QUEUE_URL = "https://sqs.../req";
    process.env.RESPONSE_QUEUE_URL = "https://sqs.../res";
    process.env.RESULT_BUCKET = "test-bucket";
    process.env.REGION = "ap-northeast-1";
    process.env.IS_MOCK_MODE = "true";
  });

  it("should handle mock request successfully", async () => {
    const event: SqlRequestEvent = {
      sql: "SELECT * FROM orders WHERE mk_date BETWEEN '2025-01-01' AND '2025-01-31'",
      tns: "ORCL_PROD",
      app_id: "app1",
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(200);
    expect(result.body).toBeDefined();

    const body = JSON.parse(result.body);
    expect(body.request_id).toBeDefined();
    expect(body.mock_mode).toBe(true);
    expect(body.s3_key).toBeDefined();
    expect(body.result).toBeDefined();
    expect(Array.isArray(body.result)).toBe(true);
  });

  it("should validate required fields", async () => {
    const event: SqlRequestEvent = {
      sql: "",
      tns: "ORCL",
      app_id: "app1",
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(400);
    const body = JSON.parse(result.body);
    expect(body.error).toBeDefined();
  });

  it("should include mock data in result", async () => {
    const event: SqlRequestEvent = {
      sql: "SELECT * FROM orders",
      tns: "ORCL",
      app_id: "app1",
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(200);

    const body = JSON.parse(result.body);
    expect(body.result).toHaveLength(3); // ダミーデータは 3 行
    expect(body.result[0].ORDER_ID).toBe("ORD-MOCK-001");
    expect(body.result[0]._mock).toBe(true);
  });
});
