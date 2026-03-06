# Raspberry Pi Zero 2W × Tailscale サブネットルーター設定ガイド

散歩時にiPhoneテザリング内のダルちゃん（Tapo C220）を自宅eva（Tailscale接続済み）からアクセスするためのセットアップガイドです。

---

## 概要：何をするのか？

現在の問題：
- iPhoneのPersonal Hotspot（172.20.10.0/28）内のダルちゃんに、自宅evaからアクセスできない
- iOSのTailscaleはSubnet Router非対応のため

解決策：
- Raspberry Pi Zero 2WをSubnet Routerに設定
- Pi → iPhone Hotspotに接続
- evaからTailscale経由でPiのサブネット（172.20.10.0/28）にアクセス
- ダルちゃんが見える！

```
[ダルちゃん(172.20.10.5)] ──WiFi──▶ [iPhone Hotspot]
                                        │
                                        │ Tailscale
                                        │
                         [Pi Zero 2W (Subnet Router)]
                                        │
                                   Tailscale VPN
                                        │
                            [自宅 eva (Claude Code)]
```

---

## 1. 必要なもの確認

- Raspberry Pi Zero 2W
- 32GB microSD カード（またはそれ以上）
- microSD カードリーダー（Windows PCに接続）
- USB-C 電源アダプタ（5V/2A 以上推奨）
- micro HDMI → HDMI ケーブル（オプション、SSHで完結するため不要）
- 無線LAN環境（自宅WiFi + iPhoneホットスポット）

**ソフトウェア：**
- Raspberry Pi Imager（Windowsに無料インストール）
- SSH クライアント（Windows 10/11 標準装備）

---

## 2. Raspberry Pi OS をSDカードに書き込む（Windows）

### ステップ 2.1: Raspberry Pi Imager をダウンロード・インストール

1. [Raspberry Pi Imager 公式サイト](https://www.raspberrypi.com/software/) にアクセス
2. 「Windows」版をダウンロード
3. インストール（デフォルト設定でOK）

### ステップ 2.2: OS を選択

1. Raspberry Pi Imager を起動
2. **「Choose Device」** → **「Raspberry Pi Zero 2」** を選択
3. **「Choose OS」** → **「Raspberry Pi OS Lite (64-bit)」** を選択
   - Lite版でOK（GUI不要、サーバー用）

### ステップ 2.3: Advanced settings で事前設定（重要）

1. **「Choose Storage」** → microSD カードリーダーを選択
2. **歯車アイコン** をクリック（Advanced settings）
3. 以下を設定：

| 項目 | 値 | 説明 |
|------|-----|------|
| **Set hostname** | `tailscale-router` | Pi のホスト名（後でSSHで使う） |
| **Enable SSH** | ✓ チェック | SSHサーバーを有効化 |
| SSH password authentication | ✓ チェック | パスワード認証許可 |
| **Set username and password** | `pi` / `tailscale2025` | ユーザー名とパスワード（後で変更推奨） |
| **Set locale settings** | タイムゾーン: `Asia/Tokyo` | 日本のタイムゾーン |
| **Set wireless LAN (WiFi)** | ✓ チェック | 以下で Wi-Fi を設定 |

### ステップ 2.4: WiFi 事前設定（2つのネットワーク）

Advanced settings で **「Set wireless LAN (WiFi)」** チェック後、以下を入力：

**設定1：自宅WiFi（初回セットアップ用）**
```
SSID: [自宅WiFiの名前]
Password: [自宅WiFiのパスワード]
```

**設定2：iPhoneホットスポット（散歩時用）**
- Advanced settings で WiFi を複数追加できるか確認
- または後でSSH接続してから設定（推奨）

ポイント：iPhoneのSSIDに日本語や特殊文字が含まれている場合は、
- Imager では自宅WiFi のみ設定
- 散歩直前にPiから `nmcli` コマンドでiPhoneホットスポットを追加（手順6で説明）

### ステップ 2.5: 書き込み実行

1. Advanced settings を保存（「Save」ボタン）
2. **「Write」** をクリック
3. 確認ダイアログが出たら「Yes」で確定
4. 進捗バーが出て、完了するまで待つ（5～10分）
5. 「Finish」をクリック
6. microSD カードを取り外す

---

## 3. Raspberry Pi Zero 2W の初回起動

### ステップ 3.1: 物理的な接続

1. microSD をPiの底面スロットに差し込む（カチッと音がするまで）
2. USB-C 電源ケーブルを接続
3. 緑色のLEDが点灯 → 起動開始
4. 約30秒～1分で起動完了

**確認：**
- 赤色LED：電源供給OK
- 緑色LED：SDカード読み込み中 → 点灯終了で起動完了

### ステップ 3.2: Piの IP アドレスを調べる

Piの IP を調べるには、複数の方法があります：

**方法1：ルーター管理画面（推奨）**
- ルーターの管理画面にアクセス
- 接続済みデバイス一覧から `tailscale-router` の IP を確認

**方法2：nmap コマンド（Windowsで自分で探す）**
```bash
# WindowsのPowerShellやGit Bashで実行
nmap -sn 192.168.1.0/24
# または
arp -a
```
IPは通常 `192.168.1.xxx` の形式

### ステップ 3.3: SSH で接続（Windows）

1. Windows のコマンドプロンプト or PowerShell を開く
2. 以下を実行：

```bash
ssh pi@[Pi のIP アドレス]
# 例：ssh pi@192.168.1.100
```

3. パスワード入力（Imager で設定したもの）：
```
password: tailscale2025
```

4. プロンプトが `pi@tailscale-router:~ $` に変わったら接続成功

**補足：** 初回接続時に「RSA key fingerprint...」という警告が出たら「yes」と入力。

---

## 4. 基本設定：apt update & upgrade

SSHで接続したら、OSを最新にします：

```bash
# パッケージ情報を更新
sudo apt update

# インストール済みパッケージをアップグレード
sudo apt upgrade -y

# 確認：Raspbian OSのバージョン確認
cat /etc/os-release | grep VERSION
```

完了後も接続は切れません。

---

## 5. IPv4 Forwarding を有効化（必須）

Subnet Router として機能させるには、IPフォワーディングを有効にする必要があります：

```bash
# IPv4 フォワーディングを有効化（永続設定）
sudo bash -c 'echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf'

# 設定を即座に反映
sudo sysctl -p

# 確認（"1" が表示されればOK）
sudo sysctl net.ipv4.ip_forward
```

出力：
```
net.ipv4.ip_forward = 1
```

---

## 6. Tailscale をインストール・設定

### ステップ 6.1: Tailscale インストール

```bash
# Tailscale公式リポジトリを追加してインストール
curl -fsSL https://tailscale.com/install.sh | sh
```

出力例：
```
...
Installed Tailscale!
```

### ステップ 6.2: Tailscale にログイン

```bash
sudo tailscale up
```

実行すると以下のようなログイン用URLが表示されます：

```
To authenticate, visit:

    https://login.tailscale.com/a/xxxxxxxx

Waiting for login...
```

このURLをWindowsのブラウザで開き、TP-Linkアカウント（自宅evaと同じ）でログイン。

ログインが成功するとSSH側に以下が表示されます：

```
Logged in.
```

### ステップ 6.3: ローカルIPアドレス確認

Piがどんなローカルネットワークに接続しているかを確認：

```bash
# Piが接続しているWiFiインターフェース確認
ip addr show

# 例：
# wlan0: inet 192.168.1.100/24 （自宅WiFi）
```

後で使うので、メモしておく（例：`192.168.1.100`）。

---

## 7. Subnet Router として登録

### ステップ 7.1: サブネット設定コマンド

Piをsubnet routerに設定。**以下のコマンドはPiのSSH接続上で実行：**

```bash
# Piが接続しているサブネットを調べる（自宅WiFi）
ip route | grep "^0.0.0.0"
# 出力例：default via 192.168.1.1 dev wlan0

# 自宅WiFiのサブネット（例：192.168.1.0/24）を取得
ip addr show wlan0 | grep "inet "
```

出力例：
```
inet 192.168.1.100/24 brd 192.168.1.255 scope global dynamic wlan0
```

この場合、サブネットは `192.168.1.0/24` です。

### ステップ 7.2: 散歩用：iPhoneホットスポットを接続・登録

散歩の直前に、以下を実行：

```bash
# NetworkManager で iPhoneホットスポットを追加（接続）
# iPhoneのPersonal Hotspot SSID: "[iPhone の名前]"
# 新しいWiFiネットワークを手動追加する場合：
nmcli dev wifi connect "[iPhone の名前]" password "[iPhone ホットスポットのパスワード]"

# Pi がアクセスポイント経由で接続したら、新しい IP を確認
ip addr show wlan0
# 出力：inet 172.20.10.3/28 （iPhoneテザリングの範囲）
```

**重要：** iPhoneホットスポットのサブネットは通常 `172.20.10.0/28` です（変わる可能性あり）。

### ステップ 7.3: Tailscale Subnet Router として宣伝

以下のコマンドで、Piが「このサブネットをルーティングできる」と Tailscale に通知：

```bash
# 自宅WiFi接続時（初回セットアップ用）
sudo tailscale up --advertise-routes=192.168.1.0/24

# または、複数サブネット（自宅WiFi + iPhone）を同時登録：
sudo tailscale up --advertise-routes=192.168.1.0/24,172.20.10.0/28
```

実行後、以下のようなメッセージが表示されます：

```
Advertising routes:
  - 192.168.1.0/24
  - 172.20.10.0/28

To enable the routes, login to Tailscale admin:
  https://login.tailscale.com/admin/machines
```

---

## 8. Tailscale ダッシュボードでサブネットを承認（重要）

### ステップ 8.1: 管理画面にアクセス

1. [Tailscale Admin Console](https://login.tailscale.com/admin) を開く
2. 左メニュー **「Machines」** をクリック
3. リスト内から **「tailscale-router」** を見つける

### ステップ 8.2: ルートを有効化

1. `tailscale-router` の右側にある **「⋮」（メニューボタン）** をクリック
2. **「Subnets」** セクションを探す
3. 表示中のサブネット（`192.168.1.0/24` と `172.20.10.0/28`）の左側にチェックボックスがあります
4. 両方にチェック ✓ を入れる

画面例：
```
tailscale-router
├── IP: 100.x.x.x （Tailscale用内部IP）
├── Platform: Linux
└── Advertised Subnet Routes: (有効化待機)
    ☐ 192.168.1.0/24
    ☐ 172.20.10.0/28
```

チェック後：
```
✓ 192.168.1.0/24 (Active)
✓ 172.20.10.0/28 (Active)
```

### ステップ 8.3: IP フォワーディング機能を有効化（オプション）

Admin Console の **「Account」** → **「Subnet routes」** にて：
- 「Allow subnet routes」を有効化（デフォルトで有効の可能性あり）

---

## 9. 動作確認

### ステップ 9.1: evaから Piに ping

自宅PC（eva）のPowerShellで：

```bash
# Piの Tailscale IP にpingを送る
# （Tailscale Admin Consoleで確認、例：100.x.x.x）
ping 100.x.x.x

# 返答があれば接続OK
```

### ステップ 9.2: evaから ダルちゃん に ping（散歩シミュレーション）

ダルちゃんのIPアドレスが `172.20.10.5` の場合：

```bash
# evaから iPhoneホットスポット内のダルちゃんに ping
ping 172.20.10.5

# または、Tapo カメラの RTSP ストリームを確認
ffmpeg -i "rtsp://[ユーザー名]:[パスワード]@172.20.10.5:554/stream1" -f null -
```

接続成功！

### ステップ 9.3: Claude Code から wifi-cam-mcp を使う

evaのClaude Codeで、wifi-cam-mcp の設定を以下に変更：

```bash
# ~/.claude/.mcp.json の wifi-cam-mcp セクションで：
"CAMERA_IP": "172.20.10.5"  # iPhone Hotspot 内のダルちゃん
```

これで散歩時に Claude が見た・聞いたことが動作します。

---

## トラブルシューティング

| 問題 | 原因 | 解決方法 |
|------|------|--------|
| SSH接続できない | Piのネットワーク接続がない | ルーター管理画面でPiが接続しているか確認。再起動を試す |
| Tailscale ログインできない | インターネット接続がない | ルーターのインターネット接続を確認 |
| サブネット承認待ちが続く | Tailscale Admin Console で有効化していない | 手順8を確認。チェックボックスを有効化 |
| iPhoneホットスポットに接続できない | SSID/パスワード間違い | iPhoneのSSIDに日本語が含まれていないか確認。含まれていれば`nmcli`コマンドで試す |
| ダルちゃんに ping が通らない | Tailscaleルーティングが未設定 | `sudo tailscale up --advertise-routes=...` を再実行 |
| `ip_forward` が0に戻った | reboot後に設定が失われた | `sudo sysctl -p` を再度実行（再起動後毎回） |

---

## 散歩時のチェックリスト

出発前に確認：

- [ ] Piに電源を接続（モバイルバッテリー確認）
- [ ] iPhoneのPersonal Hotspot を有効化
- [ ] Piが iPhoneホットスポットに接続しているか確認：
  ```bash
  ssh pi@[Pi の IP]  # または tailscale-router の Tailscale IP
  ip addr show wlan0 | grep "inet"  # 172.20.10.x であることを確認
  ```
- [ ] evaからPiに ping が通るか確認
- [ ] Claude Code で wifi-cam-mcp が動作するか確認（`see` を実行）
- [ ] ダルちゃんが見えているか確認

---

## セキュリティのヒント

- **初回はパスワード変更を推奨：**
  ```bash
  passwd pi
  ```

- **SSH接続をセキュアに（オプション）：**
  ```bash
  # 公開鍵認証の設定（後述）
  mkdir -p ~/.ssh
  # evaから公開鍵をPiにコピー
  ```

- **Tailscale ACL で evaのみアクセス許可（オプション）：**
  - Admin Console → **ACL Editor** で `172.20.10.0/28` へのアクセスを制限

---

## 参考リンク

- [Raspberry Pi 公式ドキュメント](https://www.raspberrypi.com/documentation/)
- [Tailscale Subnet Routers](https://tailscale.com/kb/1019/subnets/)
- [NetworkManager nmcli コマンド](https://linux.die.net/man/1/nmcli)

---

**楽しい散歩になるといいですね！**
