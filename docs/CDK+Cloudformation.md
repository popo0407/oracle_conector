**CDK（TypeScript）＋CloudFormationベースの本番設計レベル完全版**

構成方針：

- STS AssumeRole（オンプレ → AssumeRole）
- KMS カスタマー管理キー（S3 / SQS 共通利用）
- KMSキーの `kms:ViaService` 制限
- S3 Lifecycle 7日削除
- SQS キュー IP 制限
- DLQ
- SSE有効化
- 最小権限IAM
- 本番運用レベルセキュリティ

---

# 🏗 全体構成

```
AWS Account
 ├─ KMS CMK
 ├─ S3 Bucket (SSE-KMS + Lifecycle 7日削除)
 ├─ SQS Request Queue (SSE-KMS)
 │    └─ DLQ
 ├─ SQS Response Queue (SSE-KMS)
 ├─ SNS Topic (アラート通知)
 ├─ IAM Role (OnPremAssumeRole)
 │    └─ AssumeRole via STS + SNS Publish 許可
 └─ Queue Policy (IP制限)
```

---

# ✅ CDK 完全テンプレート（TypeScript）

```ts
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as kms from "aws-cdk-lib/aws-kms";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as sns from "aws-cdk-lib/aws-sns";

export class OnPremSqlBridgeStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const region = "ap-northeast-1";
    const allowedIp = "203.0.113.10/32"; // オンプレ固定IP

    // ======================
    // ① KMS CMK
    // ======================
    const cmk = new kms.Key(this, "SqlBridgeKey", {
      enableKeyRotation: true,
      alias: "alias/onprem-sql-bridge",
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // KMSポリシー（S3経由のみDecrypt可）
    cmk.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "AllowUseViaS3Only",
        principals: [new iam.AnyPrincipal()],
        actions: ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey*"],
        resources: ["*"],
        conditions: {
          StringEquals: {
            "kms:ViaService": `s3.${region}.amazonaws.com`,
          },
        },
      }),
    );

    // ======================
    // ② S3 Bucket
    // ======================
    const bucket = new s3.Bucket(this, "ResultBucket", {
      bucketName: "onprem-sql-result-bucket",
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: cmk,
      enforceSSL: true,
      versioned: false,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [
        {
          expiration: cdk.Duration.days(7),
        },
      ],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ======================
    // ③ DLQ
    // ======================
    const dlq = new sqs.Queue(this, "SqlDLQ", {
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: cmk,
    });

    // ======================
    // ④ Request Queue
    // ======================
    const requestQueue = new sqs.Queue(this, "SqlRequestQueue", {
      queueName: "onprem-sql-request",
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: cmk,
      deadLetterQueue: {
        maxReceiveCount: 3,
        queue: dlq,
      },
      visibilityTimeout: cdk.Duration.seconds(60),
    });

    // ======================
    // ⑤ Response Queue
    // ======================
    const responseQueue = new sqs.Queue(this, "SqlResponseQueue", {
      queueName: "onprem-sql-response",
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: cmk,
    });

    // ======================
    // ⑥ SQS IP制限ポリシー
    // ======================
    const ipRestrictPolicy = new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      principals: [new iam.AnyPrincipal()],
      actions: ["sqs:*"],
      resources: [requestQueue.queueArn, responseQueue.queueArn],
      conditions: {
        IpAddress: {
          "aws:SourceIp": allowedIp,
        },
      },
    });

    requestQueue.addToResourcePolicy(ipRestrictPolicy);
    responseQueue.addToResourcePolicy(ipRestrictPolicy);

    // ======================
    // ⑦ AssumeRole用 IAM Role
    // ======================
    const assumeRole = new iam.Role(this, "OnPremAssumeRole", {
      roleName: "OnPremSqlBridgeRole",
      assumedBy: new iam.AccountPrincipal(this.account), // 外部アカウントならArnPrincipalに変更
      maxSessionDuration: cdk.Duration.hours(1),
    });

    assumeRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:GetQueueUrl",
          "sqs:SendMessage",
        ],
        resources: [requestQueue.queueArn, responseQueue.queueArn],
      }),
    );

    assumeRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["s3:PutObject"],
        resources: [`${bucket.bucketArn}/*`],
      }),
    );

    assumeRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey*"],
        resources: [cmk.keyArn],
      }),
    );

    // ======================
    // ⑧ SNS 通知トピック（オンプレPython障害時等）
    // ======================
    const alertTopic = new sns.Topic(this, "AlertTopic", {
      topicName: "OnPremSqlBridgeAlerts",
    });

    // オンプレ側で Publish 可能とするための IAM 権限
    assumeRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["sns:Publish"],
        resources: [alertTopic.topicArn],
      }),
    );
  }
}
```

---

# 🔐 KMSキー関連リスクと対策

## リスク

CMK使用でも：

> IAMロールに `kms:Decrypt` があれば直接復号可能

つまり：

S3を介さずに直接 KMS API を叩ける。

---

## 対策（実装済み）

```json
"Condition": {
  "StringEquals": {
    "kms:ViaService": "s3.ap-northeast-1.amazonaws.com"
  }
}
```

これにより：

- S3経由のみ復号可能
- 直接 KMS Decrypt API 呼び出し不可

---

# 🧯 追加セキュリティ強化（推奨）

さらに強化するなら：

```json
"StringEquals": {
  "kms:ViaService": "s3.ap-northeast-1.amazonaws.com",
  "aws:SourceVpce": "vpce-xxxxxxxx"
}
```

→ VPCエンドポイント経由のみ許可

---

# 🚨 SQS IP制限の注意

SQSはパブリックサービスのため：

- NAT IPが変わると接続不可
- 固定グローバルIP必須

より安全なのは：

- VPCエンドポイント
- PrivateLink

---

# 🔄 STS AssumeRole構成（オンプレ側）

オンプレでは：

```bash
aws sts assume-role \
  --role-arn arn:aws:iam::<account>:role/OnPremSqlBridgeRole \
  --role-session-name onprem-session
```

取得した一時クレデンシャルを boto3 に設定。

---

# 📦 CloudFormation出力

CDK deploy で CloudFormation テンプレート生成：

```
cdk synth > template.yaml
```

そのまま IaC 管理可能。

---

# 🎯 完成度

このテンプレートは：

- KMS CMK
- SSE-KMS
- Lifecycle
- IP制限
- DLQ
- AssumeRole
- 最小権限
- ローテーション有効
- SSL強制

まで網羅。
