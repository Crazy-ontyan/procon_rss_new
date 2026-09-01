import datetime as dt
import hashlib
import html
import io
import json
import os
import re
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from discord_webhook import DiscordEmbed, DiscordWebhook
from pypdf import PdfReader
from pypdf.errors import PdfReadError

BASE_URL = "https://www.procon.gr.jp"
NEWS_URL = urljoin(BASE_URL, "/news/")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
NOTICE_STATE = Path("last_notice.json")
DEADLINE_STATE = Path("deadline_state.json")
REMINDER_DAYS = tuple(sorted({int(v) for v in os.environ.get("DEADLINE_REMINDER_DAYS", "14,7,3,1,0").split(",")}, reverse=True))
DEADLINE_CHECK_INTERVAL = dt.timedelta(hours=int(os.environ.get("DEADLINE_CHECK_INTERVAL_HOURS", "24")))
JST = dt.timezone(dt.timedelta(hours=9))
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
DEADLINE_WORDS = re.compile(r"締\s*[切切り]|〆切|期限|提出期間|応募期間|申込期間|申込み期間|申し込み期間")
DATE_RE = re.compile(
    r"(?:(?P<era>令和)\s*(?P<era_year>元|\d{1,2})\s*年|(?P<year>20\d{2})\s*[年/])?\s*"
    r"(?P<month>1[0-2]|0?\d)\s*[月/]\s*(?P<day>3[01]|[12]?\d)(?!\d)\s*日?"
    r"(?:\s*[（(][^）)]{0,3}[）)])?"
    r"(?:\s*(?P<hour>[0-2]?\d)\s*(?:[：:]\s*|時\s*)(?P<minute>[0-5]\d)\s*分?)?"
)


def fetch(url, *, timeout=30):
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "procon-deadline-checker/1.0"})
    response.raise_for_status()
    return response


def load_json(path, default):
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, value):
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")


def send_embed(title, description, color, footer):
    webhook = DiscordWebhook(url=WEBHOOK_URL)
    embed = DiscordEmbed(title=title, description=description, color=color)
    embed.set_footer(text=footer)
    webhook.add_embed(embed)
    response = webhook.execute()
    if response is None or not 200 <= response.status_code < 300:
        raise RuntimeError(f"Discordへの通知に失敗しました: {getattr(response, 'status_code', 'no response')}")


def get_latest_notice():
    soup = BeautifulSoup(fetch(NEWS_URL).text, "html.parser")
    for link_tag in soup.select('a[href*="/news/"]'):
        href = link_tag.get("href", "").strip()
        if not re.search(r"/news/\d{4}/\d{1,2}/\d{1,2}/\d+/?$", href):
            continue
        title = link_tag.get_text(" ", strip=True)
        if title:
            match = re.search(r"\d{4}/\d{1,2}/\d{1,2}", href)
            return {"date": match.group() if match else "日付不明", "title": title, "link": urljoin(BASE_URL, href)}
    return None


def check_latest_notice(now):
    notice = get_latest_notice()
    if not notice:
        print("お知らせが見つかりません")
        return
    last = load_json(NOTICE_STATE, None)
    if last and last.get("link") == notice["link"]:
        print("新着のお知らせはありません")
        return
    if notice["date"] != now.strftime("%Y/%m/%d"):
        print("最新のお知らせは今日公開されたものではありません")
        return
    if WEBHOOK_URL:
        send_embed("高専プロコン 新着お知らせ", f"**{notice['title']}**\n**日付**: {notice['date']}\n[公式サイト]({notice['link']})", 5811194, "高専プロコンチェッカー")
    else:
        print("WEBHOOK_URLが未設定のためDiscordへ通知しません")
    save_json(NOTICE_STATE, notice)


def is_downloadable_link(href, label):
    path = urlparse(href).path.lower()
    return path.endswith((".pdf", ".docx", ".xlsx")) or "/uploads/download/" in path or ("wp-content/uploads/" in path and "ダウンロード" in label)


def discover_sources(year):
    soup = BeautifulSoup(fetch(BASE_URL).text, "html.parser")
    sources = [{"url": BASE_URL, "title": f"高専プロコン公式ページ ({year})", "text": soup.get_text("\n", strip=True)}]
    seen = {BASE_URL}
    for link in soup.select("a[href]"):
        href = urljoin(BASE_URL, link.get("href", ""))
        label = link.get_text(" ", strip=True)
        for parent in link.parents:
            if parent.name not in ("li", "dd", "div"):
                continue
            parent_label = parent.get_text(" ", strip=True)
            if len(label) < len(parent_label) <= 250:
                label = parent_label
                break
        if href in seen or not is_downloadable_link(href, label):
            continue
        match = re.search(r"/uploads/(20\d{2})/", href)
        if match and int(match.group(1)) < year - 1:
            continue
        seen.add(href)
        sources.append({"url": href, "title": label or Path(urlparse(href).path).name})
    return sources


def extract_zip_xml_text(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        chunks = []
        for name in archive.namelist():
            if not name.endswith(".xml") or not (name.startswith("word/") or name.startswith("xl/sharedStrings") or name.startswith("xl/worksheets/")):
                continue
            xml = archive.read(name).decode("utf-8", errors="ignore")
            chunks.extend(re.findall(r"<(?:[^>:]+:)?t(?:\s[^>]*)?>(.*?)</(?:[^>:]+:)?t>", xml, flags=re.DOTALL))
        return "\n".join(html.unescape(re.sub(r"<[^>]+>", "", chunk)) for chunk in chunks)


def download_text(source):
    if "text" in source:
        return source["text"]
    response = fetch(source["url"])
    if len(response.content) > MAX_DOCUMENT_BYTES:
        raise ValueError("ファイルが25MBを超えています")
    path = urlparse(source["url"]).path.lower()
    content_type = response.headers.get("content-type", "").lower()
    disposition = response.headers.get("content-disposition", "").lower()
    if path.endswith(".pdf") or ".pdf" in disposition or "application/pdf" in content_type or response.content.startswith(b"%PDF"):
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(response.content)).pages)
    if path.endswith((".docx", ".xlsx")) or any(ext in disposition for ext in (".docx", ".xlsx")) or "officedocument" in content_type or response.content.startswith(b"PK"):
        return extract_zip_xml_text(response.content)
    return ""


def parse_date(match, default_year):
    if match.group("era"):
        era_year = 1 if match.group("era_year") == "元" else int(match.group("era_year"))
        year = 2018 + era_year
    else:
        year = int(match.group("year") or default_year)
    hour = int(match.group("hour") or 23)
    minute = int(match.group("minute") or (59 if match.group("hour") is None else 0))
    try:
        return dt.datetime(year, int(match.group("month")), int(match.group("day")), hour, minute, tzinfo=JST)
    except ValueError:
        return None


def relevant_contexts(text):
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.replace("\r", "\n").split("\n")]
    lines = [line for line in lines if line]
    return [" ".join(lines[max(0, i - 2):i + 3]) for i, line in enumerate(lines) if DEADLINE_WORDS.search(line)]


def dates_for_deadline_word(context, word, date_matches):
    before = [match for match in date_matches if match.end() <= word.start() and word.start() - match.end() <= 35]
    after = [match for match in date_matches if match.start() >= word.end() and match.start() - word.end() <= 100]
    if "期間" in word.group():
        # 応募期間：開始日時～終了日時
        return after[-1:] if after else before[-1:]

    if after:
        between = context[word.end():after[0].start()]
        # 「締切：9月1日」「締切は8月28日」は後続日付にかかる。
        if re.fullmatch(r"[\s:：、，,。はがをの日]*", between):
            return after[:1]
    # 「9月1日締切」「9月1日締切分」は直前の日付にかかる。
    if before:
        return before[-1:]
    return after[:1]


def extract_deadlines(text, source, year):
    deadlines, seen = [], set()
    for context in relevant_contexts(text):
        date_matches = list(DATE_RE.finditer(context))
        if not date_matches:
            continue
        chosen = []
        for word in DEADLINE_WORDS.finditer(context):
            chosen.extend(dates_for_deadline_word(context, word, date_matches))
        for match in chosen:
            due = parse_date(match, year)
            if not due or due.year != year or due.isoformat() in seen:
                continue
            seen.add(due.isoformat())
            excerpt = context[:500]
            fingerprint = hashlib.sha256(f"{due.isoformat()}\n{source['url']}\n{excerpt}".encode()).hexdigest()[:20]
            deadlines.append({"id": fingerprint, "due": due.isoformat(), "title": source["title"][:200], "source": source["url"], "excerpt": excerpt})
    return deadlines


def collect_deadlines(now):
    deadlines = []
    for source in discover_sources(now.year):
        try:
            found = extract_deadlines(download_text(source), source, now.year)
            deadlines.extend(found)
            print(f"締切候補 {len(found)}件: {source['title']}")
        except (requests.RequestException, PdfReadError, ValueError, zipfile.BadZipFile, OSError) as error:
            print(f"資料を読み取れませんでした: {source['url']} ({error})")
    grouped = {}
    for deadline in deadlines:
        due = deadline["due"]
        if due not in grouped:
            grouped[due] = deadline
            grouped[due]["id"] = hashlib.sha256(due.encode()).hexdigest()[:20]
            grouped[due]["sources"] = [deadline["source"]]
            grouped[due]["titles"] = [deadline["title"]]
            continue
        current = grouped[due]
        if deadline["source"] not in current["sources"]:
            current["sources"].append(deadline["source"])
        if deadline["title"] not in current["titles"]:
            current["titles"].append(deadline["title"])
        if len(deadline["excerpt"]) > len(current["excerpt"]):
            current["excerpt"] = deadline["excerpt"]
            current["source"] = deadline["source"]
        current["title"] = " / ".join(current["titles"][:3])
        current["id"] = hashlib.sha256(due.encode()).hexdigest()[:20]
    return sorted(grouped.values(), key=lambda d: d["due"])


def reminder_threshold(days_left):
    eligible = [days for days in REMINDER_DAYS if days_left <= days]
    return min(eligible) if eligible and days_left >= 0 else None


def deadline_check_due(now, state):
    last_checked = state.get("last_checked_at")
    if not last_checked:
        return True
    try:
        checked_at = dt.datetime.fromisoformat(last_checked)
    except (TypeError, ValueError):
        return True
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=JST)
    return now >= checked_at + DEADLINE_CHECK_INTERVAL


def check_deadlines(now):
    state = load_json(DEADLINE_STATE, {"deadlines": {}})
    if not deadline_check_due(now, state):
        next_check = dt.datetime.fromisoformat(state["last_checked_at"]) + DEADLINE_CHECK_INTERVAL
        print(f"締切資料の確認は省略します（次回: {next_check.astimezone(JST).strftime('%Y-%m-%d %H:%M JST')}）")
        return
    deadlines = collect_deadlines(now)
    records = state.setdefault("deadlines", {})
    discovered_ids = set()
    for deadline in deadlines:
        discovered_ids.add(deadline["id"])
        due = dt.datetime.fromisoformat(deadline["due"])
        days_left = (due.date() - now.date()).days
        threshold = None if due < now else reminder_threshold(days_left)
        record = records.setdefault(deadline["id"], {"notified": []})
        record.update({key: deadline[key] for key in ("due", "title", "source", "excerpt")})
        if threshold is None or threshold in record["notified"]:
            continue
        when = "本日" if days_left == 0 else f"あと{days_left}日"
        description = f"**{when}（{due.strftime('%Y年%m月%d日 %H:%M')}締切）**\n**資料**: {deadline['title']}\n> {deadline['excerpt'][:350]}\n[締切が記載された資料]({deadline['source']})"
        print(f"締切通知: {deadline['title']} / {when}")
        if WEBHOOK_URL:
            send_embed("⏰ 高専プロコン 書類締切のお知らせ", description, 15105570, "必ず原本も確認してください")
            record["notified"].append(threshold)
        else:
            print(description)
    # A successful scan is authoritative: remove corrected, deleted and false-positive entries.
    state["deadlines"] = {key: records[key] for key in discovered_ids}
    state["last_checked_at"] = now.isoformat()
    save_json(DEADLINE_STATE, state)


def main():
    now = dt.datetime.now(JST)
    failures = []
    for name, checker in (("news", check_latest_notice), ("deadlines", check_deadlines)):
        try:
            checker(now)
        except Exception as error:
            failures.append(f"{name}: {error}")
            print(f"{name}の確認に失敗しました: {error}")
    if failures:
        raise SystemExit(" / ".join(failures))


if __name__ == "__main__":
    main()
