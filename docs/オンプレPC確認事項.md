# 📘 オンプレPC 事前確認 詳細手順書

（AWS ⇔ オンプレ 連携用）

---

# 1. ネットワーク疎通確認

---

## 1-1. AWSエンドポイント疎通確認

対象（例：東京リージョン）

* SQS
  `sqs.ap-northeast-1.amazonaws.com`
* S3
  `s3.ap-northeast-1.amazonaws.com`

---

### 手順① DNS解決確認

```bash
nslookup sqs.ap-northeast-1.amazonaws.com
```

✅ IPアドレスが返ればOK
❌ 返らない → DNS制限あり

---

### 手順② HTTPS疎通確認

```bash
curl -I https://sqs.ap-northeast-1.amazonaws.com
```

期待値：

```id="ok1"
HTTP/1.1 403 Forbidden
```

403は正常（認証なしアクセスのため）

❌ タイムアウト → プロキシまたはFW遮断

---

## 1-2. プロキシ経由通信確認

### プロキシ環境変数確認

```bash
echo %HTTPS_PROXY%
echo %HTTP_PROXY%
```

設定例：

```id="ok2"
http://proxy.company.local:8080
```

---

### curlで明示的にプロキシ指定

```bash
curl -I https://sqs.ap-northeast-1.amazonaws.com -x http://proxy.company.local:8080
```

成功すればプロキシ経由OK。

---

# 2. SSLインスペクション確認（最重要）

---

## 2-1. ブラウザで証明書確認

① Chromeで以下へアクセス

```
https://sqs.ap-northeast-1.amazonaws.com
```

② 鍵マーク → 証明書 → 発行者（Issuer）確認

---

### 判定基準

| 発行者               | 判定              |
| ----------------- | --------------- |
| DigiCert / Amazon | ✅ 問題なし          |
| 会社名CA             | ❌ SSLインスペクションあり |

---

## 2-2. openssl確認（推奨）

```bash
openssl s_client -connect sqs.ap-northeast-1.amazonaws.com:443
```

出力内の：

```
issuer=
```

を確認。

会社独自CAならインスペクション有効。

---

### なぜ問題か？

Amazon Web Services は：

* 証明書厳密検証
* 署名付きリクエスト（SigV4）

を使用。

インスペクションで証明書が置き換わると：

* boto3失敗
* AWS CLI失敗
* セキュリティポリシー違反

---

## 2-3. 対応方法

ネットワーク部門へ依頼：

```
*.amazonaws.com をSSLインスペクション除外
```

---

# 3. TLS1.2確認

---

## 3-1. opensslで明示指定

```bash
openssl s_client -connect sqs.ap-northeast-1.amazonaws.com:443 -tls1_2
```

成功すればOK。

---

## 3-2. Windowsレジストリ確認

```
HKEY_LOCAL_MACHINE
 └ SYSTEM
    └ CurrentControlSet
       └ Control
          └ SecurityProviders
             └ SCHANNEL
                └ Protocols
```

TLS 1.2

```
Client
   Enabled = 1
```

であること。

---

# 4. AWS CLI動作確認

---

## 4-1. インストール確認

```bash
aws --version
```

---

## 4-2. 認証設定

```bash
aws configure
```

* Access Key
* Secret Key
* region
* output

---

## 4-3. 疎通テスト

```bash
aws sqs list-queues --region ap-northeast-1
```

成功 → AWS接続OK
SSLエラー → プロキシ問題

---

# 5. IAM権限確認

オンプレ用IAMユーザーには最低限：

* sqs:ReceiveMessage
* sqs:DeleteMessage
* sqs:SendMessage
* s3:PutObject