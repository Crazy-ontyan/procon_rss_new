import requests
import re
import json
import os
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from discord_webhook import DiscordWebhook, DiscordEmbed

URL = "https://www.procon.gr.jp"
NEWS_URL = urljoin(URL, "/news/")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # GitHub Secretsから

def get_latest_notice():
    resp = requests.get(NEWS_URL, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # /news/YYYY/MM/DD/ID/ 形式の記事リンクだけを対象にする
    for link_tag in soup.select('a[href*="/news/"]'):
        href = link_tag.get("href", "").strip()
        if not re.search(r"/news/\d{4}/\d{1,2}/\d{1,2}/\d+/?$", href):
            continue

        title = link_tag.get_text(" ", strip=True)
        if not title:
            continue

        parent_text = link_tag.parent.get_text(" ", strip=True)
        date_match = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日(?:（[^）]+）)?)", parent_text)
        date = date_match.group(1) if date_match else "日付不明"

        return {
            "date": date,
            "title": title,
            "link": urljoin(URL, href),
        }

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
    embed = DiscordEmbed(
        title="高専プロコン 新着お知らせ",
        description=f"**{notice['title']}**\n**日付**: {notice['date']}\n[公式サイト]({notice['link']})",
        color=5811194,
    )
    embed.set_footer(text="高専プロコンチェッカー")
    webhook.add_embed(embed)
    response = webhook.execute()
    if response is None:
        print("通知送信失敗: response が取得できませんでした")
        return
    print(f"通知送信完了: {response.status_code}")

if __name__ == "__main__":
    notice = get_latest_notice()
    if not notice:
        print("お知らせなし")
        exit(0)
    
    last = load_last_notice()
    if last and last.get("link") == notice["link"]:
        print("更新なし")
    else:
        print(f"新着: {notice['title']}")
        if WEBHOOK_URL:
            send_notification(notice)
        else:
            print("WEBHOOK_URL が未設定のためDiscordへ通知できません")
        save_last_notice(notice)
