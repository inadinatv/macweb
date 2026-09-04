import os
import re
import json
import time
import ssl
import socket
import urllib.request
from datetime import datetime

# Target domain candidate list (User specified fixbettv84.com, along with dynamic domain ranges)
CANDIDATE_DOMAINS = [
    "fixbettv84.com",
    "fixbettv85.com",
    "fixbettv86.com",
    "fixbettv87.com",
    "fixbettv88.com",
    "fixbettv89.com",
    "fixbettv90.com",
    "fixbettv95.com",
    "fixbettv100.com",
    "fixbettv83.com",
    "fixbettv80.com"
]

DEFAULT_DOMAIN = "fixbettv84.com"

# Standard channel list mapping
CHANNELS_DATA = [
    {"id": "zirve", "name": "BEIN SPORTS 1", "icon": "⚽", "category": "futbol", "quality": "4K HD"},
    {"id": "b2", "name": "BEIN SPORTS 2", "icon": "⚽", "category": "futbol", "quality": "1080p HD"},
    {"id": "b3", "name": "BEIN SPORTS 3", "icon": "⚽", "category": "futbol", "quality": "1080p HD"},
    {"id": "b4", "name": "BEIN SPORTS 4", "icon": "⚽", "category": "futbol", "quality": "1080p HD"},
    {"id": "b5", "name": "BEIN SPORTS 5", "icon": "⚽", "category": "futbol", "quality": "1080p HD"},
    {"id": "bm1", "name": "BEIN SPORTS MAX 1", "icon": "⚽", "category": "futbol", "quality": "1080p HD"},
    {"id": "bm2", "name": "BEIN SPORTS MAX 2", "icon": "⚽", "category": "futbol", "quality": "1080p HD"},
    {"id": "ss", "name": "S SPORT 1", "icon": "🏀", "category": "basketbol", "quality": "1080p HD"},
    {"id": "ss2", "name": "S SPORT 2", "icon": "🏀", "category": "basketbol", "quality": "1080p HD"},
    {"id": "smarts", "name": "SMART SPOR 1", "icon": "🧠", "category": "spor", "quality": "1080p HD"},
    {"id": "sms2", "name": "SMART SPOR 2", "icon": "🧠", "category": "spor", "quality": "1080p HD"},
    {"id": "t1", "name": "TİVİBU SPOR 1", "icon": "📡", "category": "futbol", "quality": "1080p HD"},
    {"id": "t2", "name": "TİVİBU SPOR 2", "icon": "📡", "category": "futbol", "quality": "1080p HD"},
    {"id": "t3", "name": "TİVİBU SPOR 3", "icon": "📡", "category": "futbol", "quality": "1080p HD"},
    {"id": "t4", "name": "TİVİBU SPOR 4", "icon": "📡", "category": "futbol", "quality": "1080p HD"},
    {"id": "trtspor", "name": "TRT SPOR", "icon": "🇹🇷", "category": "spor", "quality": "1080p HD"},
    {"id": "trtspor2", "name": "TRT SPOR YILDIZ", "icon": "🇹🇷", "category": "spor", "quality": "1080p HD"},
    {"id": "trt1", "name": "TRT 1", "icon": "🇹🇷", "category": "genel", "quality": "1080p HD"},
    {"id": "as", "name": "A SPOR", "icon": "⚽", "category": "futbol", "quality": "1080p HD"},
    {"id": "atv", "name": "ATV", "icon": "📺", "category": "genel", "quality": "1080p HD"},
    {"id": "tv8", "name": "TV 8", "icon": "📺", "category": "genel", "quality": "1080p HD"},
    {"id": "tv85", "name": "TV 8,5", "icon": "📺", "category": "spor", "quality": "1080p HD"},
    {"id": "eu1", "name": "EUROSPORT 1", "icon": "🚴", "category": "diger", "quality": "1080p HD"},
    {"id": "eu2", "name": "EUROSPORT 2", "icon": "🚴", "category": "diger", "quality": "1080p HD"},
    {"id": "ex1", "name": "TABİİ SPOR 1", "icon": "📡", "category": "futbol", "quality": "1080p HD"},
    {"id": "ex2", "name": "TABİİ SPOR 2", "icon": "📡", "category": "futbol", "quality": "1080p HD"},
    {"id": "ex3", "name": "TABİİ SPOR 3", "icon": "📡", "category": "futbol", "quality": "1080p HD"},
    {"id": "ex4", "name": "TABİİ SPOR 4", "icon": "📡", "category": "futbol", "quality": "1080p HD"},
    {"id": "ex5", "name": "TABİİ SPOR 5", "icon": "📡", "category": "futbol", "quality": "1080p HD"},
    {"id": "ex6", "name": "TABİİ SPOR 6", "icon": "📡", "category": "futbol", "quality": "1080p HD"},
    {"id": "ex7", "name": "TABİİ SPOR 7", "icon": "📡", "category": "futbol", "quality": "1080p HD"}
]

# Sample live match list categorized
def get_live_matches(active_domain):
    return [
        {
            "id": "live_1",
            "title": "Galatasaray - Fenerbahçe",
            "sport": "futbol",
            "league": "Trendyol Süper Lig",
            "time": "74'",
            "isLive": True,
            "channelId": "zirve",
            "channelName": "BEIN SPORTS 1",
            "streamUrl": f"https://{active_domain}/channel?id=zirve",
            "score": "2 - 1",
            "icon": "⚽"
        },
        {
            "id": "live_2",
            "title": "Real Madrid - Barcelona",
            "sport": "futbol",
            "league": "La Liga",
            "time": "58'",
            "isLive": True,
            "channelId": "b2",
            "channelName": "BEIN SPORTS 2",
            "streamUrl": f"https://{active_domain}/channel?id=b2",
            "score": "1 - 1",
            "icon": "⚽"
        },
        {
            "id": "live_3",
            "title": "Manchester City - Liverpool",
            "sport": "futbol",
            "league": "Premier League",
            "time": "32'",
            "isLive": True,
            "channelId": "b3",
            "channelName": "BEIN SPORTS 3",
            "streamUrl": f"https://{active_domain}/channel?id=b3",
            "score": "0 - 0",
            "icon": "⚽"
        },
        {
            "id": "live_4",
            "title": "Anadolu Efes - Fenerbahçe Beko",
            "sport": "basketbol",
            "league": "EuroLeague",
            "time": "3. Periyot",
            "isLive": True,
            "channelId": "ss",
            "channelName": "S SPORT 1",
            "streamUrl": f"https://{active_domain}/channel?id=ss",
            "score": "68 - 64",
            "icon": "🏀"
        },
        {
            "id": "live_5",
            "title": "Los Angeles Lakers - Golden State Warriors",
            "sport": "basketbol",
            "league": "NBA",
            "time": "4. Periyot",
            "isLive": True,
            "channelId": "ss2",
            "channelName": "S SPORT 2",
            "streamUrl": f"https://{active_domain}/channel?id=ss2",
            "score": "102 - 98",
            "icon": "🏀"
        },
        {
            "id": "live_6",
            "title": "Carlos Alcaraz - Jannik Sinner",
            "sport": "tenis",
            "league": "US Open Erkekler Finali",
            "time": "2. Set",
            "isLive": True,
            "channelId": "eu1",
            "channelName": "EUROSPORT 1",
            "streamUrl": f"https://{active_domain}/channel?id=eu1",
            "score": "6-4, 3-2",
            "icon": "🎾"
        },
        {
            "id": "live_7",
            "title": "VakıfBank - Eczacıbaşı Dynavit",
            "sport": "voleybol",
            "league": "Sultanlar Ligi",
            "time": "3. Set",
            "isLive": True,
            "channelId": "trtspor",
            "channelName": "TRT SPOR",
            "streamUrl": f"https://{active_domain}/channel?id=trtspor",
            "score": "25-22, 19-25, 14-11",
            "icon": "🏐"
        }
    ]

# Daily matches categorized
def get_daily_matches(active_domain):
    return [
        {
            "id": "daily_1",
            "title": "Beşiktaş - Trabzonspor",
            "sport": "futbol",
            "league": "Trendyol Süper Lig",
            "time": "20:00",
            "status": "Bu Akşam",
            "channelId": "zirve",
            "channelName": "BEIN SPORTS 1",
            "streamUrl": f"https://{active_domain}/channel?id=zirve",
            "icon": "⚽"
        },
        {
            "id": "daily_2",
            "title": "Bayern Münih - Borussia Dortmund",
            "sport": "futbol",
            "league": "Bundesliga",
            "time": "19:30",
            "status": "Bu Akşam",
            "channelId": "b4",
            "channelName": "BEIN SPORTS 4",
            "streamUrl": f"https://{active_domain}/channel?id=b4",
            "icon": "⚽"
        },
        {
            "id": "daily_3",
            "title": "Inter - AC Milan",
            "sport": "futbol",
            "league": "Serie A",
            "time": "21:45",
            "status": "Bu Akşam",
            "channelId": "ss",
            "channelName": "S SPORT 1",
            "streamUrl": f"https://{active_domain}/channel?id=ss",
            "icon": "⚽"
        },
        {
            "id": "daily_4",
            "title": "Paris Saint-Germain - Marseille",
            "sport": "futbol",
            "league": "Ligue 1",
            "time": "22:00",
            "status": "Bu Akşam",
            "channelId": "b5",
            "channelName": "BEIN SPORTS 5",
            "streamUrl": f"https://{active_domain}/channel?id=b5",
            "icon": "⚽"
        },
        {
            "id": "daily_5",
            "title": "Panathinaikos - Olympiacos",
            "sport": "basketbol",
            "league": "EuroLeague",
            "time": "21:15",
            "status": "Bu Akşam",
            "channelId": "ss2",
            "channelName": "S SPORT 2",
            "streamUrl": f"https://{active_domain}/channel?id=ss2",
            "icon": "🏀"
        },
        {
            "id": "daily_6",
            "title": "İtalya GP - Sıralama Turları",
            "sport": "motor",
            "league": "Formula 1",
            "time": "17:00",
            "status": "Tamamlandı",
            "channelId": "ss",
            "channelName": "S SPORT 1",
            "streamUrl": f"https://{active_domain}/channel?id=ss",
            "icon": "🏎️"
        }
    ]

def detect_active_domain():
    print("Checking domain candidates...")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for domain in CANDIDATE_DOMAINS:
        # First check DNS
        try:
            ip = socket.gethostbyname(domain)
            print(f"DNS resolved: {domain} -> {ip}")
        except Exception:
            continue

        # Try HTTP request
        url = f"https://{domain}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=3, context=ctx) as resp:
                if resp.status in [200, 301, 302]:
                    print(f"Successfully connected to active domain: {domain}")
                    return domain
        except Exception as e:
            print(f"Connection attempt to {domain} failed ({e}). Proceeding to next candidate.")
            pass

    print(f"Using default fallback domain: {DEFAULT_DOMAIN}")
    return DEFAULT_DOMAIN

def update_files():
    active_domain = detect_active_domain()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Generate channel stream links
    stream_links = [f"https://{active_domain}/channel?id={c['id']}" for c in CHANNELS_DATA]
    channel_names = [c["name"] for c in CHANNELS_DATA]
    quality_labels = [c["quality"] for c in CHANNELS_DATA]
    
    live_matches = get_live_matches(active_domain)
    daily_matches = get_daily_matches(active_domain)

    # Save to JSON data file
    data_payload = {
        "activeDomain": active_domain,
        "lastUpdated": now_str,
        "channels": CHANNELS_DATA,
        "streamLinks": stream_links,
        "channelNames": channel_names,
        "qualityLabels": quality_labels,
        "liveMatches": live_matches,
        "dailyMatches": daily_matches
    }

    os.makedirs("data", exist_ok=True)
    with open("data/streams.json", "w", encoding="utf-8") as f:
        json.dump(data_payload, f, ensure_ascii=False, indent=2)
    print("Updated data/streams.json")

    # Update index.html between markers if present or update variables
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()

        bot_code = f"""/*BOT_START*/
        const activeDomain = "{active_domain}";
        const lastUpdatedStr = "{now_str}";
        const streamLinks = {json.dumps(stream_links, ensure_ascii=False, indent=12)};
        const channelNames = {json.dumps(channel_names, ensure_ascii=False, indent=12)};
        const qualityLabels = {json.dumps(quality_labels, ensure_ascii=False, indent=12)};
        const liveMatchesData = {json.dumps(live_matches, ensure_ascii=False, indent=12)};
        const dailyMatchesData = {json.dumps(daily_matches, ensure_ascii=False, indent=12)};
        /*BOT_END*/"""

        pattern = r"/\*BOT_START\*/[\s\S]*?/\*BOT_END\*/"
        if re.search(pattern, html):
            new_html = re.sub(pattern, bot_code, html)
            with open("index.html", "w", encoding="utf-8") as f:
                f.write(new_html)
            print("Successfully updated index.html with new BOT data block!")
        else:
            print("Warning: BOT_START/BOT_END tag not found in index.html")

if __name__ == "__main__":
    update_files()
