# 高専プロコン Discordチェッカー

高専プロコン公式サイトを定期確認し、当日公開された最新のお知らせと、今年度の公式ページ・ダウンロード資料（PDF / DOCX / XLSX）に記載された書類締切をDiscordへ通知します。

締切通知は既定で14日前、7日前、3日前、1日前、当日に各1回送信します。通知には自動抽出した該当文と原本URLを載せます。自動抽出には誤りの可能性があるため、必ずリンク先の原本も確認してください。

## 設定

GitHubリポジトリのActions secretに `DISCORD_WEBHOOK` という名前でDiscord Webhook URLを登録してください。通知日を変える場合は、環境変数 `DEADLINE_REMINDER_DAYS` に `21,14,7,3,1,0` のように指定できます。

外部cronから5分ごとに `workflow_dispatch` する運用を想定しています。新着お知らせは毎回確認しますが、ダウンロード資料の締切走査は既定で24時間に1回だけ行います。走査間隔は `DEADLINE_CHECK_INTERVAL_HOURS` で変更できます。GitHub Actions自身のscheduleは設定していないため、外部cronと二重実行されません。

ローカルでは `WEBHOOK_URL` を設定します。未設定の場合、Discordには送らず通知内容を標準出力で確認できます。

```powershell
pip install -r requirements.txt
python procon_checker.py
```

`last_notice.json` と `deadline_state.json` は通知済み状態です。GitHub Actionsが変更をコミットし、重複通知を防ぎます。
