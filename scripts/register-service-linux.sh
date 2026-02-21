#!/bin/bash
# ================================================================
# OnPrem SQL Bridge - Linux/Mac サービス登録スクリプト
# ================================================================
# 用途: オンプレミス Python エージェントを systemd サービスとして登録
# 実行: bash register-service-linux.sh
# 例: $ sudo bash register-service-linux.sh --install --agent-path /opt/oracle_conector/onprem

set -e

# 色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# デフォルト値
SERVICE_NAME="onprem-sql-bridge"
AGENT_PATH="${HOME}/oracle_conector/onprem"
SERVICE_USER="${USER}"
ACTION="install"
CONFIG_ONLY=false

# ヘルプ表示
show_help() {
    cat << EOF
使用法: $(basename "$0") [オプション]

オプション:
    --install          サービスをインストール (デフォルト)
    --uninstall        サービスをアンインストール
    --start            サービスを開始
    --stop             サービスを停止
    --restart          サービスを再起動
    --status           サービスステータス確認
    --enable           自動起動を有効化
    --disable          自動起動を無効化
    --agent-path PATH  Python エージェント パス (デフォルト: ~/oracle_conector/onprem)
    --service-name NAME サービス名 (デフォルト: onprem-sql-bridge)
    --service-user USER systemd 実行ユーザー (デフォルト: 現在のユーザー)
    --config-only      サービスファイル生成のみ
    --help             ヘルプ表示

例:
    # インストール
    sudo bash register-service-linux.sh --install --agent-path /opt/oracle_conector/onprem

    # アンインストール
    sudo bash register-service-linux.sh --uninstall

    # 自動起動を有効化
    sudo systemctl enable ${SERVICE_NAME}

EOF
}

# 引数パース
while [[ $# -gt 0 ]]; do
    case $1 in
        --install)
            ACTION="install"
            shift
            ;;
        --uninstall)
            ACTION="uninstall"
            shift
            ;;
        --start)
            ACTION="start"
            shift
            ;;
        --stop)
            ACTION="stop"
            shift
            ;;
        --restart)
            ACTION="restart"
            shift
            ;;
        --status)
            ACTION="status"
            shift
            ;;
        --enable)
            ACTION="enable"
            shift
            ;;
        --disable)
            ACTION="disable"
            shift
            ;;
        --agent-path)
            AGENT_PATH="$2"
            shift 2
            ;;
        --service-name)
            SERVICE_NAME="$2"
            shift 2
            ;;
        --service-user)
            SERVICE_USER="$2"
            shift 2
            ;;
        --config-only)
            CONFIG_ONLY=true
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            echo "不明なオプション: $1"
            show_help
            exit 1
            ;;
    esac
done

# 相対パスを絶対パスに変換
if [[ "$AGENT_PATH" == ~* ]]; then
    AGENT_PATH="${AGENT_PATH/#\~/$HOME}"
fi
AGENT_PATH="$(cd "$AGENT_PATH" 2>/dev/null && pwd)" || {
    echo -e "${RED}エラー: エージェント PATH が見つかりません: $AGENT_PATH${NC}"
    exit 1
}

echo -e "${CYAN}===================================================${NC}"
echo -e "${CYAN}OnPrem SQL Bridge - Linux/Mac サービス管理ツール${NC}"
echo -e "${CYAN}===================================================${NC}"
echo ""
echo -e "${YELLOW}設定:${NC}"
echo "  サービス名: $SERVICE_NAME"
echo "  エージェント PATH: $AGENT_PATH"
echo "  実行ユーザー: $SERVICE_USER"
echo ""

# systemd サービスファイル生成
SERVICE_FILE="/tmp/${SERVICE_NAME}.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=OnPrem SQL Bridge Agent
Documentation=https://github.com/popo0407/oracle_conector
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${AGENT_PATH}
Environment="PATH=${AGENT_PATH}:$PATH"
EnvironmentFile=${AGENT_PATH}/.env
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=onprem-sql-bridge

# セキュリティ強化オプション
PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=${AGENT_PATH}

ExecStart=/usr/bin/python3 ${AGENT_PATH}/main.py

[Install]
WantedBy=multi-user.target
EOF

echo -e "${YELLOW}サービスファイルを生成:${NC}"
echo "  $SERVICE_FILE"
cat "$SERVICE_FILE"
echo ""

if [ "$CONFIG_ONLY" = true ]; then
    echo -e "${GREEN}✓ サービスファイル生成のみ完了 (--config-only)${NC}"
    exit 0
fi

# sudo チェック
if [ "$ACTION" != "status" ] && [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}エラー: 管理者権限が必要です。${NC}"
    echo "  sudo bash register-service-linux.sh $@"
    exit 1
fi

case "$ACTION" in
    install)
        echo -e "${YELLOW}サービスをインストール中...${NC}"
        
        # Python3 確認
        if ! command -v python3 &> /dev/null; then
            echo -e "${RED}エラー: python3 が見つかりません。インストールしてください。${NC}"
            exit 1
        fi
        
        # systemd ファイルをコピー
        SYSTEM_SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
        cp "$SERVICE_FILE" "$SYSTEM_SERVICE_FILE"
        chmod 644 "$SYSTEM_SERVICE_FILE"
        echo -e "${GREEN}  ✓ $SYSTEM_SERVICE_FILE にコピーしました${NC}"
        
        # systemd リロード
        systemctl daemon-reload
        echo -e "${GREEN}  ✓ systemd daemon-reload 完了${NC}"
        
        # .env ファイルの存在確認
        if [ ! -f "${AGENT_PATH}/.env" ]; then
            echo -e "${YELLOW}警告: .env ファイルが見つかりません${NC}"
            echo "  ${AGENT_PATH}/.env を作成してください"
            echo "  テンプレート: ${AGENT_PATH}/.env.example"
        fi
        
        echo ""
        echo -e "${GREEN}インストール完了。${NC}"
        echo ""
        echo -e "${CYAN}次のステップ:${NC}"
        echo "  1. ${AGENT_PATH}/.env ファイルを確認・更新"
        echo "  2. サービスを開始:"
        echo "     sudo systemctl start $SERVICE_NAME"
        echo "  3. 自動起動を有効化:"
        echo "     sudo systemctl enable $SERVICE_NAME"
        echo "  4. ログを確認:"
        echo "     sudo journalctl -u $SERVICE_NAME -f"
        ;;
        
    uninstall)
        echo -e "${YELLOW}サービスをアンインストール中...${NC}"
        
        SYSTEM_SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
        
        if [ -f "$SYSTEM_SERVICE_FILE" ]; then
            systemctl stop "$SERVICE_NAME" 2>/dev/null || true
            systemctl disable "$SERVICE_NAME" 2>/dev/null || true
            rm -f "$SYSTEM_SERVICE_FILE"
            systemctl daemon-reload
            echo -e "${GREEN}  ✓ サービスを削除しました${NC}"
        else
            echo -e "${YELLOW}  サービス '$SERVICE_NAME' は見つかりません${NC}"
        fi
        ;;
        
    start)
        echo -e "${YELLOW}サービスを開始中...${NC}"
        systemctl start "$SERVICE_NAME"
        echo -e "${GREEN}  ✓ サービスを開始しました${NC}"
        ;;
        
    stop)
        echo -e "${YELLOW}サービスを停止中...${NC}"
        systemctl stop "$SERVICE_NAME"
        echo -e "${GREEN}  ✓ サービスを停止しました${NC}"
        ;;
        
    restart)
        echo -e "${YELLOW}サービスを再起動中...${NC}"
        systemctl restart "$SERVICE_NAME"
        echo -e "${GREEN}  ✓ サービスを再起動しました${NC}"
        ;;
        
    status)
        echo -e "${YELLOW}サービスステータス:${NC}"
        systemctl status "$SERVICE_NAME" --no-pager || true
        echo ""
        echo -e "${YELLOW}最新ログ:${NC}"
        journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true
        ;;
        
    enable)
        echo -e "${YELLOW}自動起動を有効化中...${NC}"
        systemctl enable "$SERVICE_NAME"
        echo -e "${GREEN}  ✓ 自動起動を有効化しました${NC}"
        ;;
        
    disable)
        echo -e "${YELLOW}自動起動を無効化中...${NC}"
        systemctl disable "$SERVICE_NAME"
        echo -e "${GREEN}  ✓ 自動起動を無効化しました${NC}"
        ;;
        
    *)
        echo -e "${RED}不明なアクション: $ACTION${NC}"
        show_help
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}完了。${NC}"
