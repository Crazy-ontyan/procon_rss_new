import requests
import re
import json
import os
from discord_webhook import DiscordWebhook
from datetime import datetime

URL = "https://www.procon.gr.jp"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # GitHub Secretsから

def get_latest_notice():
    resp = requests.get(URL)
    text = resp.text
    
    # 最新お知らせパターン（2026/4/24確認）
    pattern = r'(\d{4}年\d{1,2}月\d{1,2}日[^\。]*プロコン[^\。]*しました\.)'
    matches = list(re.finditer(pattern, text))
    
    if matches:
        latest = matches[0].group(1)
        date = latest.split('プロコン')[0].strip()
        title = latest.split('しました。')[0].replace(date, '').replace('プロコン ', '').strip()
        return {"date": date, "title": title, "link": URL}
    return None

def load_last_notice():
    if os.path.exists("last_notice.json"):
        with open("last_notice.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def save_last_notice(notice):
    with open("last_notice.json", "w", encoding="utf-8") as f:
        json.dump(notice, f, ensure_ascii=False, indent=2)

def send_notification(notice):
    webhook = DiscordWebhook(url=WEBHOOK_URL)
    embed = {
        "title": "🆕 高専プロコン 新着お知らせ",
        "description": f"**{notice['title']}**\n**日付**: {notice['date']}\n[公式サイト]({notice['link']})",
        "color": 5811194,
        "footer": {"text": "高専プロコンチェッカー"}
    }
    webhook.add_embed(embed)
    response = webhook.execute()
    print(f"通知送信完了: {response.status_code}")

if __name__ == "__main__":
    notice = get_latest_notice()
    if not notice:
        print("お知らせなし")
        exit(0)
    
    last = load_last_notice()
    if last and last["title"] == notice["title"]:
        print("更新なし")
    else:
        print(f"新着: {notice['title']}")
        if WEBHOOK_URL:
            send_notification(notice)
        save_last_notice(notice)