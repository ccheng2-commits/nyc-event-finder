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
import subprocess
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from dateutil.rrule import rrulestr
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 搜索配置
LOCATION = "New York"
SEARCH_KEYWORDS = ["tech", "startup", "design", "networking", "AI", "creative"]
DAYS_AHEAD = 21

# 日历冲突检测配置
CALENDAR_NAMES = ["ccheng2@sva.edu", "ixD Events", "ixD- class of 2027"]
ENABLE_CALENDAR_FILTER = True


def get_calendar_events() -> List[Tuple[datetime, datetime, str]]:
    """从 macOS Calendar 获取课程事件（包括重复事件）"""
    events = []

    calendar_list = '", "'.join(CALENDAR_NAMES)
    # 简化版本：只获取最近30天内开始的事件
    script = f'''
    tell application "Calendar"
        set output to ""
        set targetCalendars to {{"{calendar_list}"}}
        set cutoffDate to (current date) - 30 * days

        repeat with calName in targetCalendars
            try
                set cal to calendar calName
                set evts to (every event of cal whose start date > cutoffDate)
                repeat with evt in evts
                    set evtName to summary of evt
                    set evtStart to start date of evt
                    set evtEnd to end date of evt
                    set allDay to allday event of evt
                    try
                        set recur to recurrence of evt
                    on error
                        set recur to "none"
                    end try
                    if allDay is false then
                        set output to output & evtName & "|" & (evtStart as string) & "|" & (evtEnd as string) & "|" & recur & linefeed
                    end if
                end repeat
            end try
        end repeat
        return output
    end tell
    '''

    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=60
        )

        if result.returncode != 0:
            print(f"  Calendar access error: {result.stderr}")
            return events

        now = datetime.now()
        end_date = now + timedelta(days=DAYS_AHEAD)

        for line in result.stdout.strip().split('\n'):
            if not line or '|' not in line:
                continue

            parts = line.split('|')
            if len(parts) < 4:
                continue

            name, start_str, end_str, rrule = parts[0], parts[1], parts[2], parts[3]

            try:
                # 解析日期时间
                start_dt = dateparser.parse(start_str)
                end_dt = dateparser.parse(end_str)
                duration = end_dt - start_dt

                if rrule and rrule != "none" and rrule != "missing value":
                    # 处理重复事件
                    try:
                        # 移除 UNTIL 中的 Z 后缀（避免时区不匹配错误）
                        rrule_fixed = re.sub(r'UNTIL=(\d{8}T\d{6})Z', r'UNTIL=\1', rrule)
                        rule = rrulestr(rrule_fixed, dtstart=start_dt)
                        occurrences = list(rule.between(now, end_date, inc=True))
                        for occ in occurrences:
                            events.append((occ, occ + duration, name))
                    except Exception:
                        # 如果 RRULE 解析失败，检查原始事件是否在范围内
                        if now <= start_dt <= end_date:
                            events.append((start_dt, end_dt, name))
                else:
                    # 单次事件
                    if now <= start_dt <= end_date:
                        events.append((start_dt, end_dt, name))

            except Exception as e:
                continue

    except subprocess.TimeoutExpired:
        print("  Calendar access timed out")
    except Exception as e:
        print(f"  Calendar access failed: {e}")

    # 去重（相同时间+名称的事件只保留一个）
    seen = set()
    unique_events = []
    for start, end, name in events:
        key = (start, name)
        if key not in seen:
            seen.add(key)
            unique_events.append((start, end, name))

    return unique_events


def check_time_conflict(event_time_str: str, calendar_events: List[Tuple[datetime, datetime, str]]) -> Optional[str]:
    """检查活动时间是否与日历事件冲突，返回冲突的课程名"""
    if not event_time_str or not calendar_events:
        return None

    try:
        # 清理 Meetup 时间格式中的特殊字符
        clean_time = event_time_str.replace(' · ', ' ').replace('·', ' ')
        # 尝试解析活动时间
        event_dt = dateparser.parse(clean_time)
        if not event_dt:
            return None

        # 移除时区信息以便与本地时间比较
        if event_dt.tzinfo is not None:
            event_dt = event_dt.replace(tzinfo=None)

        # 假设活动持续 2 小时
        event_end = event_dt + timedelta(hours=2)

        for cal_start, cal_end, cal_name in calendar_events:
            # 检查时间重叠
            if not (event_end <= cal_start or event_dt >= cal_end):
                return cal_name

    except Exception:
        pass

    return None


def filter_conflicting_events(events: List[Dict[str, Any]], calendar_events: List[Tuple[datetime, datetime, str]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """过滤与日历冲突的活动，返回 (可参加的活动, 冲突的活动)"""
    available = []
    conflicting = []

    for event in events:
        start_time = event.get("start", "")
        conflict = check_time_conflict(start_time, calendar_events)

        if conflict:
            event["conflict_with"] = conflict
            conflicting.append(event)
        else:
            available.append(event)

    return available, conflicting


def get_luma_events() -> List[Dict[str, Any]]:
    """从 Luma 获取纽约的活动（使用 __NEXT_DATA__ JSON）"""
    events = []

    # Luma 域名已从 lu.ma 改为 luma.com
    urls = [
        "https://luma.com/nyc",
        "https://luma.com/discover?city=New%20York",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, 'html.parser')

            # 从 Next.js __NEXT_DATA__ 提取事件数据
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data and next_data.string:
                try:
                    data = json.loads(next_data.string)
                    initial_data = data.get('props', {}).get('pageProps', {}).get('initialData', {}).get('data', {})

                    # 合并 events 和 featured_events
                    all_events = initial_data.get('events', []) + initial_data.get('featured_events', [])

                    for item in all_events:
                        event_obj = item.get('event', {})
                        event_name = event_obj.get('name', '')
                        event_url = event_obj.get('url', '')
                        start_at = item.get('start_at') or event_obj.get('start_at', '')
                        geo_info = event_obj.get('geo_address_info', {})
                        location = geo_info.get('full_address') or geo_info.get('city', 'New York')

                        if event_name and event_url:
                            events.append({
                                "name": event_name,
                                "start": start_at,
                                "url": f"https://luma.com/{event_url}",
                                "location": location,
                                "source": "Luma"
                            })
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    print(f"  Error parsing Luma JSON: {e}")

        except Exception as e:
            print(f"Error fetching Luma events from {url}: {e}")

    return events


def get_eventbrite_events() -> List[Dict[str, Any]]:
    """从 Eventbrite 获取活动（使用 JSON-LD 结构化数据）"""
    events = []
    seen_urls = set()

    # Eventbrite NYC 搜索页面
    base_url = "https://www.eventbrite.com/d/ny--new-york"

    search_urls = [
        f"{base_url}/tech/",
        f"{base_url}/startup/",
        f"{base_url}/networking/",
        f"{base_url}/ai/",
        f"{base_url}/design/",
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

            # 从 JSON-LD (ItemList) 提取事件数据
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and data.get('@type') == 'ItemList':
                        items = data.get('itemListElement', [])
                        for item in items:
                            event_data = item.get('item', {})
                            event_url = event_data.get('url', '')

                            # 去重
                            if event_url in seen_urls:
                                continue
                            seen_urls.add(event_url)

                            event_name = event_data.get('name', '')
                            start_date = event_data.get('startDate', '')
                            location = event_data.get('location', {})
                            if isinstance(location, dict):
                                location = location.get('name', '') or location.get('address', {}).get('addressLocality', 'New York')
                            else:
                                location = 'New York'

                            if event_name and event_url:
                                events.append({
                                    "name": event_name,
                                    "start": start_date,
                                    "url": event_url,
                                    "location": location,
                                    "source": "Eventbrite"
                                })
                except (json.JSONDecodeError, KeyError, TypeError):
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

    # 时间格式匹配: "Mon, Jan 26 · 5:30 PM EST" 或 "Every two weeks on Tue·Jan 27 · 6:30 PM"
    time_pattern = re.compile(
        r'((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*[,\s·]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+\s*·?\s*\d+:\d+\s*[AP]M(?:\s*[A-Z]{2,4})?)',
        re.IGNORECASE
    )

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
                full_text = link.get_text(strip=True)

                if full_text and href:
                    # 尝试从文本中提取时间
                    time_match = time_pattern.search(full_text)
                    start_time = ""
                    name = full_text

                    if time_match:
                        start_time = time_match.group(1).strip()
                        # 从名称中移除时间部分，保留前面的标题
                        name_parts = full_text.split(time_match.group(1))
                        if name_parts[0].strip():
                            name = name_parts[0].strip()
                            # 清理末尾的特殊字符
                            name = re.sub(r'[\s·,]+$', '', name)

                    events.append({
                        "name": name,
                        "start": start_time,
                        "url": href,
                        "location": "New York",
                        "source": "Meetup"
                    })

        except Exception as e:
            print(f"Error fetching Meetup events: {e}")

    return events


def get_garysguide_events() -> List[Dict[str, Any]]:
    """从 GarysGuide 获取 NYC Tech 活动"""
    events = []
    seen_urls = set()

    url = "https://www.garysguide.com/events?region=nyc"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            return events

        soup = BeautifulSoup(response.text, 'html.parser')

        # 查找所有事件链接
        event_links = soup.find_all('a', href=lambda x: x and '/events/' in x and x.count('/') >= 2)

        for link in event_links:
            href = link.get('href', '')

            # 过滤非事件链接
            if not href or 'region=' in href or href in seen_urls:
                continue

            event_name = link.get_text(strip=True)
            if not event_name or len(event_name) < 5 or 'Newsletter' in event_name:
                continue

            seen_urls.add(href)

            # 构建完整 URL
            full_url = f"https://www.garysguide.com{href}" if href.startswith('/') else href

            # 尝试从父元素提取日期和地点
            parent_row = link.find_parent('tr')
            date_str = ""
            location = "New York"

            if parent_row:
                text = parent_row.get_text(' ', strip=True)
                # 提取日期模式 "Jan 23" 等
                date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}', text)
                if date_match:
                    date_str = date_match.group(0)
                # 提取时间
                time_match = re.search(r'\d{1,2}:\d{2}\s*(am|pm)', text, re.IGNORECASE)
                if time_match:
                    date_str += f" {time_match.group(0)}"

            events.append({
                "name": event_name,
                "start": date_str,
                "url": full_url,
                "location": location,
                "source": "GarysGuide"
            })

    except Exception as e:
        print(f"Error fetching GarysGuide events: {e}")

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

    print("Fetching from GarysGuide...")
    garysguide_events = get_garysguide_events()
    print(f"  Found {len(garysguide_events)} GarysGuide events")

    # 合并去重
    for event in luma_events + eb_events + meetup_events + garysguide_events:
        url = event.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            all_events.append(event)

    return all_events


def generate_email_body(events: List[Dict[str, Any]], conflicting: List[Dict[str, Any]] = None) -> str:
    """生成邮件内容"""
    conflicting = conflicting or []

    if not events and not conflicting:
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

✅ 可参加: {len(events)} 个活动
❌ 与课程冲突: {len(conflicting)} 个活动
（未来 {DAYS_AHEAD} 天）

搜索关键词：{', '.join(SEARCH_KEYWORDS)}
"""

    for source, source_events in by_source.items():
        body += f"\n\n━━━ {source} ({len(source_events)} 个活动) ━━━"
        for event in source_events:
            body += format_event(event)

    # 显示冲突的活动（可选参考）
    if conflicting:
        body += "\n\n━━━ ⚠️ 与课程时间冲突的活动 ━━━"
        for event in conflicting[:5]:  # 最多显示 5 个
            conflict_name = event.get("conflict_with", "课程")
            body += f"\n❌ {event.get('name', '')} - 与 [{conflict_name}] 冲突"
            body += f"\n   🔗 {event.get('url', '')}"

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
    recipient = os.environ.get("EMAIL_RECIPIENT", "") or smtp_user  # 如果 EMAIL_RECIPIENT 为空，使用 SMTP_USER

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

    # 日历冲突检测
    available_events = events
    conflicting_events = []

    if ENABLE_CALENDAR_FILTER:
        print("\n📅 Checking calendar conflicts...")
        calendar_events = get_calendar_events()
        print(f"  Found {len(calendar_events)} calendar events in next {DAYS_AHEAD} days")

        if calendar_events:
            available_events, conflicting_events = filter_conflicting_events(events, calendar_events)
            print(f"  ✓ {len(available_events)} events available")
            print(f"  ✗ {len(conflicting_events)} events conflict with your schedule")

    email_body = generate_email_body(available_events, conflicting_events)
    subject = f"🗽 NYC Events - {datetime.now().strftime('%Y-%m-%d')}"

    send_email(subject, email_body)
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
