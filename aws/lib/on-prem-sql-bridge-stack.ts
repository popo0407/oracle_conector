import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as kms from "aws-cdk-lib/aws-kms";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as sns from "aws-cdk-lib/aws-sns";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as cloudwatchActions from "aws-cdk-lib/aws-cloudwatch-actions";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as path from "path";

/**
 * OnPremSqlBridgeStack
 *
 * オンプレミス側 Oracle DB に対して SQL を実行するためのブリッジ基盤。
 *
 * 構成要素:
 *   - KMS CMK（S3/SQS 共有、ViaService 制限、自動ローテーション）
 *   - S3 結果バケット（SSE-KMS、Lifecycle 7日削除、SSL 強制）
 *   - SQS リクエストキュー（SSE-KMS、DLQ、IP 制限）
 *   - SQS レスポンスキュー（SSE-KMS、IP 制限）
 *   - DLQ（リトライ上限超過時の隔離）
 *   - SNS アラートトピック
 *   - IAM AssumeRole（オンプレ Python エージェント用）
 *   - Lambda（リクエスト送信サンプル）
 *   - CloudWatch アラーム（DLQ 増加、キュー滞留）
 */
export class OnPremSqlBridgeStack extends cdk.Stack {
  // 外部参照用パブリックプロパティ
  public readonly requestQueue: sqs.Queue;
  public readonly responseQueue: sqs.Queue;
  public readonly resultBucket: s3.Bucket;
  public readonly alertTopic: sns.Topic;
  public readonly onPremRole: iam.Role;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const region = this.region;
    /** オンプレミス固定 IP（SQS IP 制限用）。実際の IP に変更すること */
    const allowedOnPremIp = this.node.tryGetContext("allowedOnPremIp") as string ?? "203.0.113.10/32";
    /** Lambda 実行ロールへ SQS 送信を許可するか（同一アカウント内利用時）*/
    const enableLambdaSender = (this.node.tryGetContext("enableLambdaSender") as string ?? "true") === "true";
    /**
     * モックモード
     * true の場合: Lambda は IS_MOCK_MODE=true で起動。
     * オンプレ側 Python エージェントも MOCK_MODE=true で起動すると
     * Oracle に接続せずダミーデータを S3 に保存する。
     * CDK deploy 時: --context mockMode=true を指定する。
     */
    const mockMode = (this.node.tryGetContext("mockMode") as string ?? "false") === "true";

    // ================================================================
    // ① KMS CMK
    // ================================================================
    const cmk = new kms.Key(this, "SqlBridgeKey", {
      description: "CMK for OnPremSqlBridge (S3 / SQS shared)",
      enableKeyRotation: true,
      alias: "alias/onprem-sql-bridge",
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    /**
     * kms:ViaService 制限
     * S3 または SQS 経由のみ Encrypt/Decrypt を許可する。
     * 直接 KMS API を叩いての復号を防止する。
     */
    cmk.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "AllowUseViaS3AndSqs",
        effect: iam.Effect.ALLOW,
        principals: [new iam.AnyPrincipal()],
        actions: [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey*",
          "kms:ReEncrypt*",
        ],
        resources: ["*"],
        conditions: {
          StringEquals: {
            "kms:ViaService": [
              `s3.${region}.amazonaws.com`,
              `sqs.${region}.amazonaws.com`,
            ],
          },
        },
      }),
    );

    // ================================================================
    // ② S3 結果バケット
    // ================================================================
    this.resultBucket = new s3.Bucket(this, "ResultBucket", {
      bucketName: `onprem-sql-result-${this.account}-${region}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: cmk,
      enforceSSL: true,
      versioned: false,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      lifecycleRules: [
        {
          id: "DeleteAfter7Days",
          enabled: true,
          expiration: cdk.Duration.days(7),
          // 不完全なマルチパートアップロードも削除
          abortIncompleteMultipartUploadAfter: cdk.Duration.days(1),
        },
      ],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ================================================================
    // ③ DLQ（リクエストキュー用）
    // ================================================================
    const dlq = new sqs.Queue(this, "SqlDLQ", {
      queueName: "onprem-sql-request-dlq",
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: cmk,
      // DLQ 自体のメッセージ保持期間は 14 日（最大）
      retentionPeriod: cdk.Duration.days(14),
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ================================================================
    // ④ SQS リクエストキュー
    // ================================================================
    this.requestQueue = new sqs.Queue(this, "SqlRequestQueue", {
      queueName: "onprem-sql-request",
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: cmk,
      deadLetterQueue: {
        // 3 回受信後に処理失敗とみなし DLQ へ転送
        maxReceiveCount: 3,
        queue: dlq,
      },
      // オンプレ側の処理時間を考慮して 60 秒
      visibilityTimeout: cdk.Duration.seconds(60),
      // Long Polling 対応: 受信待機最大 20 秒
      receiveMessageWaitTime: cdk.Duration.seconds(20),
      retentionPeriod: cdk.Duration.days(4),
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ================================================================
    // ⑤ SQS レスポンスキュー
    // ================================================================
    this.responseQueue = new sqs.Queue(this, "SqlResponseQueue", {
      queueName: "onprem-sql-response",
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: cmk,
      receiveMessageWaitTime: cdk.Duration.seconds(20),
      retentionPeriod: cdk.Duration.days(1),
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ================================================================
    // ⑥ SQS IP 制限ポリシー（オンプレ固定 IP のみ許可）
    // ================================================================
    const ipRestrictAllowStatement = new iam.PolicyStatement({
      sid: "AllowOnPremIpOnly",
      effect: iam.Effect.ALLOW,
      principals: [new iam.AnyPrincipal()],
      actions: ["sqs:*"],
      resources: ["*"],
      conditions: {
        IpAddress: {
          "aws:SourceIp": allowedOnPremIp,
        },
      },
    });

    // Deny: IP 制限外からのアクセスを拒否（HTTPS 強制も兼ねる）
    const denyNonSslStatement = new iam.PolicyStatement({
      sid: "DenyNonSsl",
      effect: iam.Effect.DENY,
      principals: [new iam.AnyPrincipal()],
      actions: ["sqs:*"],
      resources: ["*"],
      conditions: {
        Bool: {
          "aws:SecureTransport": "false",
        },
      },
    });

    this.requestQueue.addToResourcePolicy(ipRestrictAllowStatement);
    this.requestQueue.addToResourcePolicy(denyNonSslStatement);
    this.responseQueue.addToResourcePolicy(ipRestrictAllowStatement);
    this.responseQueue.addToResourcePolicy(denyNonSslStatement);

    // ================================================================
    // ⑦ SNS アラートトピック
    // ================================================================
    this.alertTopic = new sns.Topic(this, "AlertTopic", {
      topicName: "OnPremSqlBridgeAlerts",
      displayName: "OnPrem SQL Bridge Alerts",
    });

    // ================================================================
    // ⑧ IAM AssumeRole（オンプレ Python エージェント用）
    // ================================================================
    this.onPremRole = new iam.Role(this, "OnPremAssumeRole", {
      roleName: "OnPremSqlBridgeRole",
      description: "Role assumed by on-premise Python agent via STS",
      assumedBy: new iam.AccountPrincipal(this.account),
      maxSessionDuration: cdk.Duration.hours(1),
    });

    // SQS 操作権限（最小権限）
    this.onPremRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "SQSAccess",
        actions: [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:GetQueueUrl",
          "sqs:SendMessage",
        ],
        resources: [
          this.requestQueue.queueArn,
          this.responseQueue.queueArn,
        ],
      }),
    );

    // S3 結果アップロード権限
    this.onPremRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "S3PutObject",
        actions: ["s3:PutObject"],
        resources: [`${this.resultBucket.bucketArn}/*`],
      }),
    );

    // KMS 操作権限（S3/SQS の暗号化・復号に必要）
    this.onPremRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "KMSAccess",
        actions: [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey*",
          "kms:ReEncrypt*",
        ],
        resources: [cmk.keyArn],
      }),
    );

    // SNS Publish 権限（オンプレ側から障害通知を送信するため）
    this.onPremRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "SNSPublish",
        actions: ["sns:Publish"],
        resources: [this.alertTopic.topicArn],
      }),
    );

    // ================================================================
    // ⑨ Lambda（SQS リクエスト送信サンプル）
    //    同一アカウント内の Caller が SQS へ SQL リクエストを送る例
    // ================================================================
    if (enableLambdaSender) {
      const lambdaLogGroup = new logs.LogGroup(this, "RequestSenderLogGroup", {
        logGroupName: "/aws/lambda/onprem-sql-request-sender",
        retention: logs.RetentionDays.ONE_MONTH,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      });

      const requestSenderFn = new lambda.Function(this, "RequestSenderLambda", {
        functionName: "onprem-sql-request-sender",
        description: "Send SQL execution request to on-premise agent via SQS",
        runtime: lambda.Runtime.NODEJS_22_X,
        handler: "index.handler",
        code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/request-sender")),
        environment: {
          REQUEST_QUEUE_URL: this.requestQueue.queueUrl,
          RESPONSE_QUEUE_URL: this.responseQueue.queueUrl,
          RESULT_BUCKET: this.resultBucket.bucketName,
          REGION: region,
          /** モックモード: Lambda からのリクエストはオンプレを通さず即レスポンスを確認できる */
          IS_MOCK_MODE: mockMode ? "true" : "false",
        },
        timeout: cdk.Duration.seconds(30),
        memorySize: 128,
        logGroup: lambdaLogGroup,
      });

      // Lambda に SQS 送信権限を付与
      this.requestQueue.grantSendMessages(requestSenderFn);
      this.responseQueue.grantConsumeMessages(requestSenderFn);
      this.resultBucket.grantRead(requestSenderFn);
      cmk.grantEncryptDecrypt(requestSenderFn);
    }

    // ================================================================
    // ⑩ CloudWatch アラーム
    // ================================================================
    // DLQ メッセージ数増加アラーム
    const dlqAlarm = new cloudwatch.Alarm(this, "DLQMessageAlarm", {
      alarmName: "OnPremSqlBridge-DLQ-MessageCount",
      alarmDescription: "DLQ にメッセージが積まれています。オンプレ側エラーを確認してください。",
      metric: dlq.metricApproximateNumberOfMessagesVisible({
        period: cdk.Duration.minutes(5),
        statistic: "Maximum",
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    dlqAlarm.addAlarmAction(new cloudwatchActions.SnsAction(this.alertTopic));

    // リクエストキュー滞留アラーム（最古メッセージが 5 分以上）
    const queueAgeAlarm = new cloudwatch.Alarm(this, "RequestQueueAgeAlarm", {
      alarmName: "OnPremSqlBridge-RequestQueue-OldestMessageAge",
      alarmDescription: "リクエストキューのメッセージが長時間処理されていません。オンプレエージェントの死活確認が必要です。",
      metric: this.requestQueue.metricApproximateAgeOfOldestMessage({
        period: cdk.Duration.minutes(5),
        statistic: "Maximum",
      }),
      threshold: 300, // 5 分（秒）
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    queueAgeAlarm.addAlarmAction(new cloudwatchActions.SnsAction(this.alertTopic));

    // ================================================================
    // ⑪ CloudFormation Outputs
    // ================================================================
    new cdk.CfnOutput(this, "RequestQueueUrl", {
      value: this.requestQueue.queueUrl,
      description: "SQS Request Queue URL（オンプレ側環境変数 REQUEST_QUEUE_URL に設定）",
      exportName: "OnPremSqlBridge-RequestQueueUrl",
    });

    new cdk.CfnOutput(this, "ResponseQueueUrl", {
      value: this.responseQueue.queueUrl,
      description: "SQS Response Queue URL（オンプレ側環境変数 RESPONSE_QUEUE_URL に設定）",
      exportName: "OnPremSqlBridge-ResponseQueueUrl",
    });

    new cdk.CfnOutput(this, "ResultBucketName", {
      value: this.resultBucket.bucketName,
      description: "S3 Result Bucket Name（オンプレ側環境変数 RESULT_BUCKET に設定）",
      exportName: "OnPremSqlBridge-ResultBucketName",
    });

    new cdk.CfnOutput(this, "OnPremRoleArn", {
      value: this.onPremRole.roleArn,
      description: "AssumeRole ARN（オンプレ側環境変数 ROLE_ARN に設定）",
      exportName: "OnPremSqlBridge-OnPremRoleArn",
    });

    new cdk.CfnOutput(this, "AlertTopicArn", {
      value: this.alertTopic.topicArn,
      description: "SNS Alert Topic ARN",
      exportName: "OnPremSqlBridge-AlertTopicArn",
    });

    new cdk.CfnOutput(this, "KmsCmkArn", {
      value: cmk.keyArn,
      description: "KMS CMK ARN",
      exportName: "OnPremSqlBridge-KmsCmkArn",
    });
  }
}
