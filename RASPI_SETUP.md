# Raspberry Pi Zero 2W セットアップガイド
## 目標：Tailscale Subnet Router として iPhoneテザリング網を eva に公開する

```
[Tapoカメラ] ──WiFi──▶ [iPhone hotspot] ◀──WiFi── [Pi Zero 2W]
                                                          │
                                                    Tailscale VPN
                                                          │
                                                    [eva (自宅PC)]
```

---

## ステップ 1：Raspberry Pi Imager でSDカードを作る（Windows）

1. **Raspberry Pi Imager をダウンロード・インストール**
   https://www.raspberrypi.com/software/

2. **Imager を起動して設定**
   - Raspberry Pi Device: `Raspberry Pi Zero 2 W`
   - Operating System: `Raspberry Pi OS (other)` → `Raspberry Pi OS Lite (64-bit)`
   - Storage: SDカードを選択

3. **⚙ 設定ボタン（次へ）をクリック → OS カスタマイズ**

   | 項目 | 設定値 |
   |------|--------|
   | ホスト名 | `raspi-zero` |
   | SSH | 有効にする（パスワード認証） |
   | ユーザー名 | `pi` |
   | パスワード | 任意（覚えておく） |
   | Wi-Fi SSID | 自宅Wi-Fiのネットワーク名 |
   | Wi-Fi パスワード | 自宅Wi-Fiのパスワード |
   | Wi-Fi国 | JP |
   | ロケール | Asia/Tokyo |

4. **書き込み** → 完了したらSDカードをPiに挿す

---

## ステップ 2：起動して SSH 接続

1. **電源を入れる**（USB-C ポートに電源ケーブル接続）
   - 初回起動は2〜3分かかる

2. **Windows から SSH 接続**
   ```
   ssh pi@raspi-zero.local
   ```
   ※ `.local` で接続できない場合は、ルーターのDHCP一覧でIPを確認

3. パスワードを入力してログイン成功すれば OK

---

## ステップ 3：基本セットアップ

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y vim curl
```

---

## ステップ 4：iPhoneホットスポットの Wi-Fi を追加

```bash
sudo nano /etc/wpa_supplicant/wpa_supplicant.conf
```

以下を追記（自宅Wi-Fiの設定の下に追加）：

```
network={
    ssid="iPhoneの名前"
    psk="iPhoneのホットスポットパスワード"
    priority=5
}
```

> ⚠ iPhone の名前に日本語が含まれる場合、設定アプリ→一般→情報→名前 で英語名に変更するか、
> ssid に正確にコピー（UTF-8）する。

保存後：
```bash
sudo reboot
```

---

## ステップ 5：Tailscale インストール

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

---

## ステップ 6：Subnet Router として設定

### IP フォワーディングを有効化
```bash
echo 'net.ipv4.ip_forward=1' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### Tailscale を起動（サブネット広告）
```bash
sudo tailscale up --advertise-routes=172.20.10.0/28 --accept-routes
```

表示された URL をブラウザで開いてアカウントにログイン（eva と同じアカウントで OK）

---

## ステップ 7：Tailscale 管理画面でサブネット承認

1. https://login.tailscale.com/admin/machines を開く
2. `raspi-zero` を見つける
3. `...` メニュー → `Edit route settings`
4. `172.20.10.0/28` にチェック → Save

---

## ステップ 8：動作確認

eva（自宅PC）から：
```bash
# Piにpingが通るか
ping raspi-zero

# iPhoneテザリング中のカメラにアクセスできるか（カメラのIPは要確認）
ping 172.20.10.x
```

---

## 散歩時のチェックリスト

- [ ] iPhone のホットスポットをONにする
- [ ] Pi に電源を入れる（30秒待つ）
- [ ] Tapo カメラの電源を入れる
- [ ] eva から `ping raspi-zero` が通ることを確認
- [ ] Wi-Fi カメラ MCP が繋がることを確認

---

## トラブルシューティング

| 症状 | 確認すること |
|------|-------------|
| `raspi-zero.local` に繋がらない | ルーターのDHCP確認、または `arp -a` でIP探す |
| Tailscale に表示されない | `sudo systemctl status tailscaled` でログ確認 |
| サブネットにpingが通らない | 管理画面でルート承認されているか確認、ip_forward 確認 |
| カメラが見つからない | iPhoneホットスポットにカメラが接続されているか確認 |
