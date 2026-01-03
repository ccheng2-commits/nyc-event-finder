#!/usr/bin/env python3
"""
NYC Event Finder
每周自动搜索纽约市的活动并发送邮件通知

数据来源:
- Luma (lu.ma) - Tech/Startup 活动
- Eventbrite embed widget - 公开活动
"""

import os
import re
import json
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any
from bs4 import BeautifulSoup

# 搜索配置
LOCATION = "New York"
SEARCH_KEYWORDS = ["tech", "startup", "design", "networking", "AI", "creative"]
DAYS_AHEAD = 14


def get_luma_events() -> List[Dict[str, Any]]:
    """从 Luma 获取纽约的活动"""
    events = []

    # Luma NYC discover page
    urls = [
        "https://lu.ma/nyc",
        "https://lu.ma/discover?city=New%20York",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                continue

            # 尝试从页面提取 JSON 数据
            soup = BeautifulSoup(response.text, 'html.parser')

            # 查找 script 标签中的事件数据
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and 'events' in script.string.lower():
                    # 尝试提取 JSON
                    try:
                        # 查找 JSON 对象
                        matches = re.findall(r'\{[^{}]*"name"[^{}]*"start_at"[^{}]*\}', script.string)
                        for match in matches:
                            try:
                                event_data = json.loads(match)
                                events.append({
                                    "name": event_data.get("name", ""),
                                    "start": event_data.get("start_at", ""),
                                    "url": event_data.get("url", ""),
                                    "location": event_data.get("geo_address_info", {}).get("full_address", "New York"),
                                    "source": "Luma"
                                })
                            except json.JSONDecodeError:
                                continue
                    except Exception:
                        continue

            # 备用方案: 从 HTML 提取活动链接
            event_links = soup.find_all('a', href=re.compile(r'lu\.ma/[a-zA-Z0-9]+'))
            for link in event_links[:20]:  # 限制数量
                href = link.get('href', '')
                if href and 'lu.ma' in href:
                    events.append({
                        "name": link.get_text(strip=True) or "Luma Event",
                        "start": "",
                        "url": href if href.startswith('http') else f"https://lu.ma{href}",
                        "location": "New York",
                        "source": "Luma"
                    })

        except Exception as e:
            print(f"Error fetching Luma events from {url}: {e}")

    return events


def get_eventbrite_events() -> List[Dict[str, Any]]:
    """从 Eventbrite 公开页面获取活动"""
    events = []

    # Eventbrite NYC 公开搜索页面
    base_url = "https://www.eventbrite.com/d/ny--new-york"

    search_urls = [
        f"{base_url}/tech/",
        f"{base_url}/startup/",
        f"{base_url}/networking/",
        f"{base_url}/business/",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    for url in search_urls:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, 'html.parser')

            # 查找活动卡片
            event_cards = soup.find_all('div', {'data-testid': re.compile(r'event-card')})
            if not event_cards:
                event_cards = soup.find_all('article')
            if not event_cards:
                event_cards = soup.find_all('div', class_=re.compile(r'event'))

            for card in event_cards[:15]:
                try:
                    # 提取活动名称
                    title_elem = card.find(['h2', 'h3', 'a'])
                    name = title_elem.get_text(strip=True) if title_elem else ""

                    # 提取链接
                    link = card.find('a', href=True)
                    event_url = link['href'] if link else ""
                    if event_url and not event_url.startswith('http'):
                        event_url = f"https://www.eventbrite.com{event_url}"

                    # 提取日期
                    date_elem = card.find(['time', 'span'], class_=re.compile(r'date|time'))
                    date_str = date_elem.get_text(strip=True) if date_elem else ""

                    # 提取地点
                    location_elem = card.find(['span', 'p'], class_=re.compile(r'location|venue'))
                    location = location_elem.get_text(strip=True) if location_elem else "New York"

                    if name and event_url:
                        events.append({
                            "name": name,
                            "start": date_str,
                            "url": event_url,
                            "location": location,
                            "source": "Eventbrite"
                        })
                except Exception:
                    continue

        except Exception as e:
            print(f"Error fetching Eventbrite events from {url}: {e}")

    return events


def get_meetup_events() -> List[Dict[str, Any]]:
    """从 Meetup 获取活动"""
    events = []

    # Meetup NYC tech groups
    urls = [
        "https://www.meetup.com/find/?location=us--ny--New%20York&source=EVENTS&keywords=tech",
        "https://www.meetup.com/find/?location=us--ny--New%20York&source=EVENTS&keywords=startup",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, 'html.parser')

            # 查找活动链接
            event_links = soup.find_all('a', href=re.compile(r'meetup\.com/.*/events/'))

            for link in event_links[:15]:
                href = link.get('href', '')
                name = link.get_text(strip=True)

                if name and href:
                    events.append({
                        "name": name,
                        "start": "",
                        "url": href,
                        "location": "New York",
                        "source": "Meetup"
                    })

        except Exception as e:
            print(f"Error fetching Meetup events: {e}")

    return events


def format_event(event: Dict[str, Any]) -> str:
    """格式化单个活动信息"""
    name = event.get("name", "未知活动")
    start = event.get("start", "")
    url = event.get("url", "")
    location = event.get("location", "New York")
    source = event.get("source", "")

    return f"""
📅 {name}
   🕐 {start if start else "查看详情"}
   📍 {location}
   🔗 {url}
   📌 来源: {source}
"""


def collect_all_events() -> List[Dict[str, Any]]:
    """收集所有来源的活动"""
    all_events = []
    seen_urls = set()

    print("Fetching from Luma...")
    luma_events = get_luma_events()
    print(f"  Found {len(luma_events)} Luma events")

    print("Fetching from Eventbrite...")
    eb_events = get_eventbrite_events()
    print(f"  Found {len(eb_events)} Eventbrite events")

    print("Fetching from Meetup...")
    meetup_events = get_meetup_events()
    print(f"  Found {len(meetup_events)} Meetup events")

    # 合并去重
    for event in luma_events + eb_events + meetup_events:
        url = event.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            all_events.append(event)

    return all_events


def generate_email_body(events: List[Dict[str, Any]]) -> str:
    """生成邮件内容"""
    if not events:
        return "本周没有找到符合条件的活动。"

    # 按来源分组
    by_source = {}
    for event in events:
        source = event.get("source", "Other")
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(event)

    body = f"""
🗽 NYC Event Finder - 本周活动推荐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

找到 {len(events)} 个活动（未来 {DAYS_AHEAD} 天）

搜索关键词：{', '.join(SEARCH_KEYWORDS)}
"""

    for source, source_events in by_source.items():
        body += f"\n\n━━━ {source} ({len(source_events)} 个活动) ━━━"
        for event in source_events:
            body += format_event(event)

    body += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
由 NYC Event Finder 自动生成
"""
    return body


def send_email(subject: str, body: str):
    """发送邮件"""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    recipient = os.environ.get("EMAIL_RECIPIENT", smtp_user)

    if not all([smtp_user, smtp_password]):
        print("Email credentials not configured. Printing to console instead:")
        print("=" * 50)
        print(f"Subject: {subject}")
        print("=" * 50)
        print(body)
        return

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        print(f"Email sent successfully to {recipient}")
    except Exception as e:
        print(f"Failed to send email: {e}")
        print("Email content:")
        print(body)


def main():
    print("🔍 NYC Event Finder starting...")
    print(f"Searching for events in {LOCATION}")
    print(f"Keywords: {SEARCH_KEYWORDS}")
    print()

    events = collect_all_events()
    print(f"\nFound {len(events)} unique events total")

    email_body = generate_email_body(events)
    subject = f"🗽 NYC Events - {datetime.now().strftime('%Y-%m-%d')}"

    send_email(subject, email_body)
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
