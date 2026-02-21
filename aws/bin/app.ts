#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { OnPremSqlBridgeStack } from "../lib/on-prem-sql-bridge-stack";

const app = new cdk.App();

new OnPremSqlBridgeStack(app, "OnPremSqlBridgeStack", {
  /**
   * 東京リージョンに固定。必要に応じてコンテキスト変数で切替可能。
   */
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? "ap-northeast-1",
  },
  description: "On-premise Oracle SQL bridge stack (SQS/S3/KMS/IAM/SNS)",
  tags: {
    Project: "OnPremSqlBridge",
    ManagedBy: "CDK",
  },
});
