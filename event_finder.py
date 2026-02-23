#!/usr/bin/env python3
"""
NYC Event Finder
每周自动搜索纽约市活动并发送邮件通知（默认：未来 7 天）
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


try:
    load_dotenv()
except Exception as e:
    print(f"Warning: .env load skipped: {e}")


LOCATION = "New York"
SEARCH_KEYWORDS = ["tech", "startup", "design", "networking", "ai", "creative", "product", "ux", "founder", "history", "museum", "culture", "humanities", "art", "community", "dog", "dogs", "pet", "walk"]
DAYS_AHEAD = int(os.environ.get("DAYS_AHEAD", "7"))
MAX_EVENTS_IN_EMAIL = int(os.environ.get("MAX_EVENTS_IN_EMAIL", "12"))

CALENDAR_NAMES = ["ccheng2@sva.edu", "ixD Events", "ixD- class of 2027"]
ENABLE_CALENDAR_FILTER = os.environ.get("ENABLE_CALENDAR_FILTER", "true").lower() == "true"

SOURCE_WEIGHT = {
    "Luma": 3,
    "GarysGuide": 3,
    "Meetup": 2,
    "Eventbrite": 2,
}


def get_calendar_events() -> List[Tuple[datetime, datetime, str]]:
    events = []
    calendar_list = '", "'.join(CALENDAR_NAMES)
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
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  Calendar access error: {result.stderr}")
            return events

        now = datetime.now()
        end_date = now + timedelta(days=DAYS_AHEAD)

        for line in result.stdout.strip().split("\n"):
            if not line or "|" not in line:
                continue
            parts = line.split("|")
            if len(parts) < 4:
                continue

            name, start_str, end_str, rrule = parts[0], parts[1], parts[2], parts[3]
            try:
                start_dt = dateparser.parse(start_str)
                end_dt = dateparser.parse(end_str)
                duration = end_dt - start_dt

                if rrule and rrule not in ("none", "missing value"):
                    try:
                        rrule_fixed = re.sub(r"UNTIL=(\d{8}T\d{6})Z", r"UNTIL=\1", rrule)
                        rule = rrulestr(rrule_fixed, dtstart=start_dt)
                        for occ in rule.between(now, end_date, inc=True):
                            events.append((occ, occ + duration, name))
                    except Exception:
                        if now <= start_dt <= end_date:
                            events.append((start_dt, end_dt, name))
                else:
                    if now <= start_dt <= end_date:
                        events.append((start_dt, end_dt, name))
            except Exception:
                continue

    except subprocess.TimeoutExpired:
        print("  Calendar access timed out")
    except Exception as e:
        print(f"  Calendar access failed: {e}")

    seen = set()
    unique = []
    for start, end, name in events:
        key = (start, name)
        if key not in seen:
            seen.add(key)
            unique.append((start, end, name))
    return unique


def check_time_conflict(event_time_str: str, calendar_events: List[Tuple[datetime, datetime, str]]) -> Optional[str]:
    if not event_time_str or not calendar_events:
        return None
    try:
        clean = event_time_str.replace(" · ", " ").replace("·", " ")
        event_dt = dateparser.parse(clean)
        if not event_dt:
            return None
        if event_dt.tzinfo is not None:
            event_dt = event_dt.replace(tzinfo=None)

        event_end = event_dt + timedelta(hours=2)
        for cal_start, cal_end, cal_name in calendar_events:
            if not (event_end <= cal_start or event_dt >= cal_end):
                return cal_name
    except Exception:
        pass
    return None


def parse_event_datetime(event_time_str: str) -> Optional[datetime]:
    if not event_time_str:
        return None
    try:
        clean = event_time_str.replace(" · ", " ").replace("·", " ")
        dt = dateparser.parse(clean)
        if not dt:
            return None
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None


def filter_conflicting_events(events: List[Dict[str, Any]], calendar_events: List[Tuple[datetime, datetime, str]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    available, conflicting = [], []
    for event in events:
        conflict = check_time_conflict(event.get("start", ""), calendar_events)
        if conflict:
            event["conflict_with"] = conflict
            conflicting.append(event)
        else:
            available.append(event)
    return available, conflicting


def score_event(event: Dict[str, Any]) -> int:
    score = SOURCE_WEIGHT.get(event.get("source", ""), 1)
    text = f"{event.get('name','')} {event.get('location','')}".lower()

    for kw in SEARCH_KEYWORDS:
        if kw in text:
            score += 2

    # 轻微惩罚太短标题
    if len(event.get("name", "")) < 10:
        score -= 1

    # 轻微奖励可解析时间
    if parse_event_datetime(event.get("start", "")):
        score += 1

    return score


def select_worthy_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = datetime.now()
    end = now + timedelta(days=DAYS_AHEAD)

    valid = []
    for e in events:
        dt = parse_event_datetime(e.get("start", ""))
        if dt and not (now <= dt <= end):
            continue
        e["_parsed_start"] = dt
        e["_score"] = score_event(e)
        valid.append(e)

    valid.sort(key=lambda x: (-x.get("_score", 0), x.get("_parsed_start") or (now + timedelta(days=999))))
    return valid[:MAX_EVENTS_IN_EMAIL]


def get_luma_events() -> List[Dict[str, Any]]:
    events = []
    urls = [
        "https://luma.com/nyc",
        "https://luma.com/discover?city=New%20York",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
            if response.status_code != 200:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            next_data = soup.find("script", id="__NEXT_DATA__")
            if not (next_data and next_data.string):
                continue

            data = json.loads(next_data.string)
            initial_data = data.get("props", {}).get("pageProps", {}).get("initialData", {}).get("data", {})
            all_events = initial_data.get("events", []) + initial_data.get("featured_events", [])

            for item in all_events:
                event_obj = item.get("event", {})
                event_name = event_obj.get("name", "")
                event_url = event_obj.get("url", "")
                start_at = item.get("start_at") or event_obj.get("start_at", "")
                geo = event_obj.get("geo_address_info", {})
                location = geo.get("full_address") or geo.get("city", "New York")
                if event_name and event_url:
                    events.append({
                        "name": event_name,
                        "start": start_at,
                        "url": f"https://luma.com/{event_url}",
                        "location": location,
                        "source": "Luma",
                    })
        except Exception as e:
            print(f"Error fetching Luma events from {url}: {e}")

    return events


def get_eventbrite_events() -> List[Dict[str, Any]]:
    events, seen = [], set()
    base_url = "https://www.eventbrite.com/d/ny--new-york"
    search_urls = [f"{base_url}/tech/", f"{base_url}/startup/", f"{base_url}/networking/", f"{base_url}/ai/", f"{base_url}/design/", f"{base_url}/history/", f"{base_url}/museum/", f"{base_url}/culture/", f"{base_url}/dogs/", f"{base_url}/pets/"]
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

    for url in search_urls:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string)
                    if not (isinstance(data, dict) and data.get("@type") == "ItemList"):
                        continue
                    for item in data.get("itemListElement", []):
                        ed = item.get("item", {})
                        event_url = ed.get("url", "")
                        if not event_url or event_url in seen:
                            continue
                        seen.add(event_url)

                        event_name = ed.get("name", "")
                        start_date = ed.get("startDate", "")
                        location = ed.get("location", {})
                        if isinstance(location, dict):
                            location = location.get("name", "") or location.get("address", {}).get("addressLocality", "New York")
                        else:
                            location = "New York"

                        if event_name:
                            events.append({
                                "name": event_name,
                                "start": start_date,
                                "url": event_url,
                                "location": location,
                                "source": "Eventbrite",
                            })
                except Exception:
                    continue
        except Exception as e:
            print(f"Error fetching Eventbrite events from {url}: {e}")

    return events


def get_meetup_events() -> List[Dict[str, Any]]:
    events = []
    urls = [
        "https://www.meetup.com/find/?location=us--ny--New%20York&source=EVENTS&keywords=tech",
        "https://www.meetup.com/find/?location=us--ny--New%20York&source=EVENTS&keywords=startup",
        "https://www.meetup.com/find/?location=us--ny--New%20York&source=EVENTS&keywords=history",
        "https://www.meetup.com/find/?location=us--ny--New%20York&source=EVENTS&keywords=culture",
        "https://www.meetup.com/find/?location=us--ny--New%20York&source=EVENTS&keywords=dogs",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    time_pattern = re.compile(r'((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*[,\s·]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+\s*·?\s*\d+:\d+\s*[AP]M(?:\s*[A-Z]{2,4})?)', re.IGNORECASE)

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            event_links = soup.find_all("a", href=re.compile(r"meetup\.com/.*/events/"))

            for link in event_links[:15]:
                href = link.get("href", "")
                full_text = link.get_text(strip=True)
                if not (full_text and href):
                    continue

                time_match = time_pattern.search(full_text)
                start_time = ""
                name = full_text
                if time_match:
                    start_time = time_match.group(1).strip()
                    name_parts = full_text.split(time_match.group(1))
                    if name_parts[0].strip():
                        name = re.sub(r"[\s·,]+$", "", name_parts[0].strip())

                events.append({
                    "name": name,
                    "start": start_time,
                    "url": href,
                    "location": "New York",
                    "source": "Meetup",
                })
        except Exception as e:
            print(f"Error fetching Meetup events: {e}")
    return events


def get_garysguide_events() -> List[Dict[str, Any]]:
    events, seen_urls = [], set()
    url = "https://www.garysguide.com/events?region=nyc"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            return events

        soup = BeautifulSoup(response.text, "html.parser")
        event_links = soup.find_all("a", href=lambda x: x and "/events/" in x and x.count("/") >= 2)

        for link in event_links:
            href = link.get("href", "")
            if not href or "region=" in href or href in seen_urls:
                continue

            event_name = link.get_text(strip=True)
            if not event_name or len(event_name) < 5 or "Newsletter" in event_name:
                continue

            seen_urls.add(href)
            full_url = f"https://www.garysguide.com{href}" if href.startswith("/") else href

            parent_row = link.find_parent("tr")
            date_str = ""
            location = "New York"
            if parent_row:
                text = parent_row.get_text(" ", strip=True)
                date_match = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}", text)
                if date_match:
                    date_str = date_match.group(0)
                time_match = re.search(r"\d{1,2}:\d{2}\s*(am|pm)", text, re.IGNORECASE)
                if time_match:
                    date_str += f" {time_match.group(0)}"

            events.append({
                "name": event_name,
                "start": date_str,
                "url": full_url,
                "location": location,
                "source": "GarysGuide",
            })
    except Exception as e:
        print(f"Error fetching GarysGuide events: {e}")

    return events


def format_event(event: Dict[str, Any]) -> str:
    return f"""
📅 {event.get('name','未知活动')}
   🕐 {event.get('start','查看详情')}
   📍 {event.get('location','New York')}
   🔗 {event.get('url','')}
   📌 来源: {event.get('source','')}
   ⭐ 推荐分: {event.get('_score', 0)}
"""


def collect_all_events() -> List[Dict[str, Any]]:
    all_events, seen_urls = [], set()

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

    for event in luma_events + eb_events + meetup_events + garysguide_events:
        url = event.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            all_events.append(event)

    return all_events


def generate_email_body(events: List[Dict[str, Any]], conflicting: List[Dict[str, Any]] = None) -> str:
    conflicting = conflicting or []

    if not events and not conflicting:
        return "本周没有找到符合条件的活动。"

    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for e in events:
        by_source.setdefault(e.get("source", "Other"), []).append(e)

    body = f"""
🗽 NYC Event Finder - 周日精选（未来 {DAYS_AHEAD} 天）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ 推荐可参加: {len(events)} 个活动
❌ 与课程冲突: {len(conflicting)} 个活动

搜索关键词：{', '.join(SEARCH_KEYWORDS)}
"""

    for source, source_events in by_source.items():
        body += f"\n\n━━━ {source} ({len(source_events)} 个活动) ━━━"
        for event in source_events:
            body += format_event(event)

    if conflicting:
        body += "\n\n━━━ ⚠️ 与课程时间冲突的活动（参考） ━━━"
        for event in conflicting[:5]:
            body += f"\n❌ {event.get('name', '')} - 与 [{event.get('conflict_with', '课程')}] 冲突"
            body += f"\n   🔗 {event.get('url', '')}"

    body += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n由 NYC Event Finder 自动生成"
    return body


def send_email(subject: str, body: str):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    recipient = os.environ.get("EMAIL_RECIPIENT", "") or smtp_user

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
        print(body)


def main():
    print("🔍 NYC Event Finder starting...")
    print(f"Searching in {LOCATION} for next {DAYS_AHEAD} days")
    print(f"Keywords: {SEARCH_KEYWORDS}\n")

    events = collect_all_events()
    print(f"\nFound {len(events)} unique events total")

    available_events = events
    conflicting_events: List[Dict[str, Any]] = []

    if ENABLE_CALENDAR_FILTER:
        print("\n📅 Checking calendar conflicts...")
        calendar_events = get_calendar_events()
        print(f"  Found {len(calendar_events)} calendar events in next {DAYS_AHEAD} days")
        if calendar_events:
            available_events, conflicting_events = filter_conflicting_events(events, calendar_events)
            print(f"  ✓ {len(available_events)} events available")
            print(f"  ✗ {len(conflicting_events)} events conflict with your schedule")

    worthy = select_worthy_events(available_events)
    print(f"\n⭐ Selected {len(worthy)} worthy events for weekly digest")

    email_body = generate_email_body(worthy, conflicting_events)
    subject = f"🗽 NYC Weekly Events ({datetime.now().strftime('%Y-%m-%d')})"

    send_email(subject, email_body)
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
