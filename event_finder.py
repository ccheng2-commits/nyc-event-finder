#!/usr/bin/env python3
"""
NYC Event Finder
每周自动搜索纽约市的活动并发送邮件通知
"""

import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Eventbrite API 配置
EVENTBRITE_TOKEN = os.environ.get("EVENTBRITE_TOKEN", "")
EVENTBRITE_API_URL = "https://www.eventbriteapi.com/v3"

# 搜索配置
LOCATION = "New York"  # 搜索地点
SEARCH_KEYWORDS = ["tech", "startup", "design", "networking", "creative"]  # 关键词
DAYS_AHEAD = 14  # 搜索未来多少天的活动


def get_events(keyword: str) -> List[Dict[str, Any]]:
    """通过 Eventbrite API 搜索活动"""
    headers = {
        "Authorization": f"Bearer {EVENTBRITE_TOKEN}",
    }

    # 计算日期范围
    start_date = datetime.now()
    end_date = start_date + timedelta(days=DAYS_AHEAD)

    params = {
        "q": keyword,
        "location.address": LOCATION,
        "start_date.range_start": start_date.strftime("%Y-%m-%dT%H:%M:%S"),
        "start_date.range_end": end_date.strftime("%Y-%m-%dT%H:%M:%S"),
        "expand": "venue",
    }

    try:
        response = requests.get(
            f"{EVENTBRITE_API_URL}/events/search/",
            headers=headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        return data.get("events", [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching events for '{keyword}': {e}")
        return []


def format_event(event: Dict[str, Any]) -> str:
    """格式化单个活动信息"""
    name = event.get("name", {}).get("text", "未知活动")
    start = event.get("start", {}).get("local", "")
    url = event.get("url", "")

    # 解析日期
    if start:
        try:
            dt = datetime.fromisoformat(start)
            date_str = dt.strftime("%m/%d (%a) %H:%M")
        except ValueError:
            date_str = start
    else:
        date_str = "日期未知"

    # 获取地点
    venue = event.get("venue", {})
    if venue:
        venue_name = venue.get("name", "")
        address = venue.get("address", {}).get("localized_address_display", "")
        location = f"{venue_name} - {address}" if venue_name else address
    else:
        location = "地点待定"

    return f"""
📅 {name}
   🕐 {date_str}
   📍 {location}
   🔗 {url}
"""


def collect_all_events() -> List[Dict[str, Any]]:
    """收集所有关键词的活动"""
    all_events = []
    seen_ids = set()

    for keyword in SEARCH_KEYWORDS:
        print(f"Searching for: {keyword}")
        events = get_events(keyword)

        for event in events:
            event_id = event.get("id")
            if event_id and event_id not in seen_ids:
                seen_ids.add(event_id)
                all_events.append(event)

    # 按日期排序
    all_events.sort(key=lambda x: x.get("start", {}).get("local", ""))
    return all_events


def generate_email_body(events: List[Dict[str, Any]]) -> str:
    """生成邮件内容"""
    if not events:
        return "本周没有找到符合条件的活动。"

    body = f"""
🗽 NYC Event Finder - 本周活动推荐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

找到 {len(events)} 个活动（未来 {DAYS_AHEAD} 天）

搜索关键词：{', '.join(SEARCH_KEYWORDS)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

    for event in events:
        body += format_event(event)

    body += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
由 NYC Event Finder 自动生成
"""
    return body


def send_email(subject: str, body: str):
    """发送邮件（使用 GitHub Actions 的 SMTP 或其他服务）"""
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
    print(f"\nFound {len(events)} unique events")

    email_body = generate_email_body(events)
    subject = f"🗽 NYC Events - {datetime.now().strftime('%Y-%m-%d')}"

    send_email(subject, email_body)
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
