import streamlit as st
import pdfplumber
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta, time
import io
import urllib3
import random
from supabase import create_client, Client

# --- DEFINE PAGE NAMES GLOBALLY ---
VIEW_COACH = "⏱ Coach Race Info"
VIEW_WALL = "📋 Swimmer Wall Planner"
VIEW_TM = "🚩 TM Marshalling Info"

# Streamlit Page Setup
st.set_page_config(page_title="Swim Gala Hub", layout="wide")

# --- SUPABASE CLOUD CONNECTION ---
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_supabase()
except Exception as e:
    st.error(f"Database Connection Failed: {e}")

# --- MODERN CUSTOM CSS ---
st.markdown("""
<style>
    /* --- RADIO BUTTONS TO SLEEK APP BUTTONS --- */
    div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child {
        display: none !important;
    }
    div[role="radiogroup"] label[data-baseweb="radio"] {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 12px 15px;
        margin-bottom: 8px;
        cursor: pointer;
        transition: all 0.2s ease;
        width: 100%;
    }
    div[role="radiogroup"] label[data-baseweb="radio"]:hover {
        background-color: #334155;
        border-color: #facc15;
    }
    div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked) {
        background-color: #facc15 !important;
        border-color: #facc15 !important;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
    }
    div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked) p {
        color: #0b0b0b !important;
        font-weight: 800 !important;
    }

    /* --- MOBILE TABLE OPTIMIZATION --- */
    table {
        white-space: nowrap !important;
        width: 100%;
        font-size: 0.9em;
    }
    th {
        font-size: 0.85em;
        text-transform: uppercase;
        color: #94a3b8;
    }

    /* --- MOBILE-FRIENDLY MODERN HEADER --- */
    .app-header {
        background-color: #0b0b0b;
        border-radius: 12px;
        padding: 20px 25px;
        display: grid;
        grid-template-columns: 1fr 1fr;
        align-items: center;
        margin-top: 10px;
        margin-bottom: 20px;
        border-bottom: 4px solid #facc15;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .header-left {
        text-align: left;
    }
    .header-right {
        text-align: right;
    }
    .view-title {
        color: #facc15 !important;
        font-weight: 800;
        font-size: clamp(1rem, 2.5vw, 1.4rem);
        text-transform: uppercase;
        letter-spacing: 1px;
        margin: 0;
        line-height: 1.2;
    }
    .meet-name {
        color: #ffffff !important;
        font-weight: 700;
        font-size: clamp(0.9rem, 2vw, 1.2rem);
        margin: 0;
        line-height: 1.2;
    }
    .sync-status {
        font-size: clamp(0.7rem, 1.5vw, 0.85rem);
        margin-top: 4px;
        font-weight: 600;
    }
    .sync-live { color: #4ade80 !important; }
    .sync-offline { color: #94a3b8 !important; }

    /* KPI Cards */
    .kpi-container { display: flex; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; }
    .kpi-card {
        flex: 1;
        min-width: 140px;
        background-color: var(--secondary-background-color);
        border-top: 4px solid #facc15;
        border-radius: 8px;
        padding: 15px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .kpi-val {
        font-size: 2.2em;
        font-weight: 800;
        color: var(--text-color) !important;
        line-height: 1;
        margin-bottom: 5px;
    }
    .kpi-val.green { color: #4ade80 !important; }
    .kpi-val.red { color: #ef4444 !important; }
    .kpi-val.orange { color: #f97316 !important; }
    .kpi-label { font-size: 0.75em; color: gray !important; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# Initialize Session State Variables
if "gala_df" not in st.session_state:
    st.session_state["gala_df"] = pd.DataFrame()
if "target_df" not in st.session_state:
    st.session_state["target_df"] = pd.DataFrame()
if "meet_name" not in st.session_state:
    st.session_state["meet_name"] = "Swim Gala Live"
if "redraw_counter" not in st.session_state:
    st.session_state["redraw_counter"] = 0
if "room_pin" not in st.session_state:
    st.session_state["room_pin"] = None
if "last_url" not in st.session_state:
    st.session_state["last_url"] = ""

# Sidebar Navigation
st.sidebar.title("Navigation")
page_selection = st.sidebar.radio("Select View", [VIEW_COACH, VIEW_WALL, VIEW_TM])

# --- DYNAMIC APP HEADER ---
if page_selection == VIEW_COACH: icon_title = "⏱ COACH"
elif page_selection == VIEW_WALL: icon_title = "📋 PLANNER"
else: icon_title = "🚩 TRACKER"

sync_class = "sync-live" if st.session_state["room_pin"] else "sync-offline"
sync_text = f"🟢 Room: {st.session_state['room_pin']}" if st.session_state["room_pin"] else "⚪ Offline"

st.markdown(f"""
<div class="app-header">
    <div class="header-left">
        <div class="view-title">{icon_title}</div>
    </div>
    <div class="header-right">
        <div class="meet-name">{st.session_state['meet_name']}</div>
        <div class="sync-status {sync_class}">{sync_text}</div>
    </div>
</div>
""", unsafe_allow_html=True)


# --- DATA SANITIZATION FUNCTIONS ---
def safe_int(val, default=0):
    try: return int(float(val))
    except: return default

def safe_str(val, default=""):
    if pd.isna(val): return default
    return str(val).strip()

def safe_bool(val):
    if pd.isna(val): return False
    return bool(val)

def extract_gender(event_str):
    e_lower = str(event_str).lower()
    if 'female' in e_lower or 'girl' in e_lower or 'women' in e_lower: return 'F'
    if 'male' in e_lower or 'boy' in e_lower or 'men' in e_lower or 'open' in e_lower: return 'M'
    return 'M'

def extract_standard_event(event_str):
    m = re.search(r'(\d+m\s+[A-Za-z]+(?:\s+IM)?)', str(event_str), re.IGNORECASE)
    if m:
        stroke = m.group(1).title()
        stroke = stroke.replace('Breaststroke', 'Breast').replace('Breaststrok', 'Breast')
        stroke = stroke.replace('Freestyle', 'Free')
        stroke = stroke.replace('Backstroke', 'Back')
        stroke = stroke.replace('Butterfly', 'Fly')
        stroke = stroke.replace('Ind. Medley', 'IM').replace('Ind Medley', 'IM')
        stroke = stroke.replace('M ', 'm ').replace(' Im', ' IM')
        return stroke.strip()
    return ""

# --- CLOUD DATABASE FUNCTIONS ---
def create_room(df):
    pin = str(random.randint(1000, 9999))
    records = []
    
    for _, row in df.iterrows():
        records.append({
            "room_pin": pin,
            "session": safe_int(row.get("Session"), 1),
            "swimmer": safe_str(row.get("Swimmer")),
            "age": safe_str(row.get("Age")),
            "event": safe_str(row.get("Event")),
            "heat": safe_str(row.get("Heat")),
            "lane": safe_int(row.get("Lane"), 0),
            "entry_time": safe_str(row.get("Entry Time")),
            "achieved_time": safe_str(row.get("Achieved Time")),
            "coach_notes": safe_str(row.get("Coach Notes")),
            "checked_in": safe_bool(row.get("Checked In")),
            "checked_out": safe_bool(row.get("Checked Out")),
            "seen_coach": safe_bool(row.get("Seen Coach")),
            "in_marshalling": safe_bool(row.get("In Marshalling"))
        })
        
    try:
        batch_size = 100
        for i in range(0, len(records), batch_size):
            supabase.table("live_gala_data").insert(records[i:i+batch_size]).execute()
        return pin, None
    except Exception as e:
        return None, str(e)

def fetch_room(pin):
    try:
        response = supabase.table("live_gala_data").select("*").eq("room_pin", str(pin)).execute()
        data = response.data
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data)
        df = df.rename(columns={
            "session": "Session", "swimmer": "Swimmer", "age": "Age", "event": "Event",
            "heat": "Heat", "lane": "Lane", "entry_time": "Entry Time", "achieved_time": "Achieved Time",
            "coach_notes": "Coach Notes", "checked_in": "Checked In", "checked_out": "Checked Out",
            "seen_coach": "Seen Coach", "in_marshalling": "In Marshalling"
        })
        return df
    except Exception as e:
        st.error(f"Failed to pull from cloud: {e}")
        return pd.DataFrame()

def fetch_room_targets(pin):
    try:
        res = supabase.table("target_times").select("*").eq("room_pin", str(pin)).execute()
        if res.data:
            tdf = pd.DataFrame(res.data)
            tdf = tdf.rename(columns={"gender": "Gender", "age": "Age", "event": "Event", "county_time": "County_Time", "regional_time": "Regional_Time"})
            return tdf
    except:
        pass
    return pd.DataFrame()

def safe_update_db(row_id, field, value):
    if st.session_state.get("room_pin"):
        try:
            supabase.table("live_gala_data").update({field: value}).eq("id", int(row_id)).execute()
        except Exception:
            pass


# --- CLOUD SYNC SIDEBAR ---
st.sidebar.divider()
st.sidebar.header("☁️ Live Cloud Sync")

if st.session_state.get("room_pin"):
    st.sidebar.success(f"🟢 Connected to Room: **{st.session_state['room_pin']}**")
    if st.sidebar.button("🔄 Refresh Live Data"):
        with st.spinner("Syncing latest data..."):
            st.session_state["gala_df"] = fetch_room(st.session_state["room_pin"])
            st.session_state["target_df"] = fetch_room_targets(st.session_state["room_pin"])
        st.rerun()
    if st.sidebar.button("🚪 Disconnect"):
        st.session_state["room_pin"] = None
        st.session_state["gala_df"] = pd.DataFrame()
        st.session_state["target_df"] = pd.DataFrame()
        st.rerun()
        
    # --- ROOM-BOUND TARGET UPLOADER ---
    st.sidebar.markdown("---")
    with st.sidebar.expander("🎯 Room Target Times", expanded=False):
        if not st.session_state["target_df"].empty:
            st.success(f"{len(st.session_state['target_df'])} Targets active in this room.")
        else:
            st.info("No targets loaded for this room.")
            
        target_file = st.file_uploader("Upload Club/County Targets (CSV)", type=["csv"])
        if target_file is not None:
            if st.button("Link Targets to Room"):
                with st.spinner("Uploading to room..."):
                    try:
                        upload_df = pd.read_csv(target_file)
                        records = []
                        for _, r in upload_df.iterrows():
                            records.append({
                                "room_pin": st.session_state["room_pin"],
                                "gender": safe_str(r.get("Gender")),
                                "age": safe_int(r.get("Age"), -1),
                                "event": safe_str(r.get("Event")),
                                "county_time": safe_str(r.get("County_Time")),
                                "regional_time": safe_str(r.get("Regional_Time"))
                            })
                        
                        # Clear old targets for this specific room, then insert new ones
                        supabase.table("target_times").delete().eq("room_pin", st.session_state["room_pin"]).execute()
                        for i in range(0, len(records), 100):
                            supabase.table("target_times").insert(records[i:i+100]).execute()
                        
                        st.session_state["target_df"] = fetch_room_targets(st.session_state["room_pin"])
                        st.success("Linked! All users in this room now see these targets.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Upload failed: {e}")

else:
    st.sidebar.info("Sync across devices by creating or joining a room.")
    join_pin = st.sidebar.text_input("Enter 4-Digit Room PIN")
    if st.sidebar.button("Join Room"):
        if join_pin:
            with st.spinner("Joining..."):
                new_df = fetch_room(join_pin)
                if not new_df.empty:
                    st.session_state["gala_df"] = new_df
                    st.session_state["room_pin"] = join_pin
                    st.session_state["target_df"] = fetch_room_targets(join_pin)
                    st.rerun()
                else:
                    st.sidebar.error("Invalid PIN or empty room.")
                    
    if not st.session_state["gala_df"].empty and "id" not in st.session_state["gala_df"].columns:
        if st.sidebar.button("☁️ Upload Gala to Cloud"):
            with st.spinner("Scrubbing data & creating secure room..."):
                original_df = st.session_state["gala_df"].copy()
                pin, err = create_room(st.session_state["gala_df"])
                
                if pin:
                    new_df = fetch_room(pin)
                    if not new_df.empty:
                        st.session_state["room_pin"] = pin
                        st.session_state["gala_df"] = new_df
                        st.session_state["target_df"] = pd.DataFrame()
                        st.rerun()
                    else:
                        st.sidebar.error("Upload succeeded, but could not read the data back.")
                        st.session_state["gala_df"] = original_df 
                else:
                    st.sidebar.error(f"Upload Failed: {err}")
                    st.session_state["gala_df"] = original_df

# --- OWNER SECURE WIPER ---
st.sidebar.divider()
with st.sidebar.expander("🔐 Owner Tools"):
    admin_pin = st.text_input("Enter Owner PIN", type="password")
    correct_pin = st.secrets.get("ADMIN_PIN", "9999") 
    
    if admin_pin == correct_pin:
        st.success("Owner Access Granted")
        if st.button("🚨 Wipe All Cloud Rooms"):
            with st.spinner("Clearing entire database..."):
                try:
                    # Wipes all live data and target times
                    supabase.table("live_gala_data").delete().gt("id", 0).execute()
                    supabase.table("target_times").delete().gt("id", 0).execute()
                    st.session_state["room_pin"] = None
                    st.session_state["gala_df"] = pd.DataFrame()
                    st.session_state["target_df"] = pd.DataFrame()
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to clear database: {e}")
    elif admin_pin:
        st.error("Incorrect PIN")

# --- CONFIGURATION & SETTINGS ---
st.sidebar.divider()
st.sidebar.header("⚙ Gala Schedule Settings")
session_start_map = {}
pace_factor = st.sidebar.slider("Heat Timing Speed Factor", 0.8, 1.3, 1.0, 0.05)

st.sidebar.divider()
st.sidebar.header("Load New Data Source")
club_filter = st.sidebar.text_input("Club Keyword / Filter", placeholder="e.g. Warrington")
input_method = st.sidebar.radio("Choose Input Method", ["Web Link (URL)", "Upload PDF File", "Paste Text / HTML"])

def fetch_url_content(url):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9,en-US;q=0.8',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    response = requests.get(url, headers=headers, timeout=20, verify=False)
    response.raise_for_status()
    return response

def extract_meet_name_from_soup(soup):
    if soup.title and soup.title.get_text(strip=True):
        title_text = soup.title.get_text(strip=True)
        if title_text and "sportsystems" not in title_text.lower() and len(title_text) > 3: return title_text
    return None

def is_valid_swimmer_name(name):
    if not name or len(name) < 2: return False
    if not re.search(r'[a-zA-Z]', name): return False
    blocked = {'name', 'swimmer', 'aad', 'lane', 'comp.no', 'comp no', 'comp', 'club', 'event', 'heat', 'entry', 'time'}
    if name.lower().strip() in blocked: return False
    return True

def estimate_heat_duration_seconds(event_str):
    event_lower = str(event_str).lower()
    if '50m' in event_lower: return 90
    elif '100m' in event_lower: return 150
    elif '200m' in event_lower: return 270
    elif '400m' in event_lower: return 480
    elif '800m' in event_lower: return 840
    elif '1500m' in event_lower: return 1320
    return 180

def get_event_num(event_str):
    m = re.search(r'Event\s+(\d+)', str(event_str), re.IGNORECASE)
    return int(m.group(1)) if m else 9999

def infer_session_number(event_str, current_session=1):
    e_num = get_event_num(event_str)
    if e_num != 9999 and e_num >= 100: return e_num // 100
    return current_session

def parse_html_soup(soup, club_keyword):
    entries = []
    current_event, current_heat, current_session = None, "1", 1
    target_keyword = club_keyword.strip().lower() if club_keyword else ""
    for elem in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'div', 'tr']):
        text = elem.get_text(strip=True)
        if not text: continue
        session_match = re.search(r'Session\s+(\d+)', text, re.IGNORECASE)
        if session_match: current_session = int(session_match.group(1))
        event_match = re.search(r'(Event\s+\d+.*?)(?=\s+Heat|\n|$)', text, re.IGNORECASE)
        if event_match and elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'div']: current_event = event_match.group(1).strip()
        heat_match = re.search(r'Heat(?:\s+Number\s*-\s*|\s+)(\d+)', text, re.IGNORECASE)
        if heat_match and elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'div', 'tr']: current_heat = heat_match.group(1)
        
        if elem.name == 'tr' and current_event is not None:
            tds = elem.find_all(['td', 'th'])
            cells = [td.get_text(strip=True) for td in tds]
            row_text = " ".join(cells)
            
            if not target_keyword or target_keyword in row_text.lower():
                if not cells: continue
                lane_str = cells[0].strip()
                if not lane_str.isdigit(): continue
                
                # 1. Dynamically scan right-to-left to find the entry time, skipping blank columns
                entry_time = "N/A"
                for i in range(len(cells)-1, 0, -1):
                    val = cells[i].strip()
                    if not val: continue
                    if re.match(r'^[\d\:\.]+$', val) or val.upper() in ["NT", "S/T", "NONE"]:
                        entry_time = val
                        break
                    # If we hit the club name while scanning left, the time is entirely missing
                    if target_keyword and target_keyword.lower() in val.lower():
                        break

                # 2. Scan left-to-right to find Name and Age
                name = ""
                age = ""
                for i in range(1, len(cells)):
                    val = cells[i].strip()
                    if not val: continue
                    
                    if not name and is_valid_swimmer_name(val):
                        if target_keyword and target_keyword.lower() in val.lower():
                            continue # Ignore the club name
                        name = val.title()
                    elif name and not age and val.isdigit() and 7 <= int(val) <= 99:
                        age = val

                if name and lane_str.isdigit():
                    sess_num = infer_session_number(current_event, current_session)
                    entries.append({
                        "Session": sess_num, "Swimmer": name, "Age": age, "Event": current_event,
                        "Heat": int(current_heat) if current_heat.isdigit() else current_heat, "Lane": int(lane_str),
                        "Entry Time": entry_time, "Achieved Time": "", "Var vs Entry": "", "Coach Notes": "",
                        "Checked In": False, "Checked Out": False, "Seen Coach": False, "In Marshalling": False
                    })
    return entries

def parse_text_lines(lines, club_keyword):
    entries = []
    current_event, current_heat, current_session = None, "1", 1
    target_keyword = club_keyword.strip().lower() if club_keyword else ""
    for line in lines:
        line_str = line.strip()
        if not line_str: continue
        session_match = re.search(r'Session\s+(\d+)', line_str, re.IGNORECASE)
        if session_match: current_session = int(session_match.group(1))
        event_match = re.search(r'(Event\s+\d+.*?)(?=\s+Heat|\n|$)', line_str, re.IGNORECASE)
        if event_match: current_event = event_match.group(1).strip()
        heat_match = re.search(r'Heat(?:\s+Number\s*-\s*|\s+)(\d+)', line_str, re.IGNORECASE)
        if heat_match: current_heat = heat_match.group(1)
        if current_event is not None and (not target_keyword or target_keyword in line_str.lower()):
            m = re.search(r'^\s*(\d+)\s+(?:(\d+)\s+)?([A-Za-z\s\-\'\.]+?)\s+(\d{1,2})\s+.*?(?:' + (re.escape(club_keyword) if target_keyword else r'[A-Za-z]+') + r')\s*([\d\:\.]+|S/T|NT)?', line_str, re.IGNORECASE)
            if m:
                lane, name, age, entry_time = m.group(1), m.group(3).strip(), m.group(4), m.group(5) if m.group(5) else "N/A"
                if lane.isdigit() and is_valid_swimmer_name(name):
                    sess_num = infer_session_number(current_event, current_session)
                    entries.append({
                        "Session": sess_num, "Swimmer": name.title(), "Age": age, "Event": current_event,
                        "Heat": int(current_heat) if current_heat.isdigit() else current_heat, "Lane": int(lane),
                        "Entry Time": entry_time, "Achieved Time": "", "Var vs Entry": "", "Coach Notes": "",
                        "Checked In": False, "Checked Out": False, "Seen Coach": False, "In Marshalling": False
                    })
    return entries

def time_to_seconds(t_str):
    if not t_str or str(t_str).strip().upper() in ["N/A", "S/T", "NT", "", "-", "—", "NONE", "DQ", "DNC", "WD", "WITHDRAWN"]: return None
    t_str = str(t_str).strip()
    t_str = re.sub(r'[^\d:\.]', '', t_str)
    if not t_str: return None
    try:
        if t_str.isdigit():
            if len(t_str) >= 5: 
                m, s, ms = int(t_str[:-4]), int(t_str[-4:-2]), int(t_str[-2:])
                return m * 60 + s + (ms / 100.0)
            elif len(t_str) >= 3: 
                s, ms = int(t_str[:-2]), int(t_str[-2:])
                return s + (ms / 100.0)
            else: return float(t_str)
        parts = re.split(r'[:\.]', t_str)
        if len(parts) == 3: 
            ms_val = parts[2]
            if len(ms_val) == 1: ms_val += '0' 
            return float(parts[0]) * 60 + float(parts[1]) + float(ms_val[:2]) / 100.0
        elif len(parts) == 2:
            ms_val = parts[1]
            if len(ms_val) == 1: ms_val += '0'
            if ":" in t_str or len(parts[0]) < 3: 
                if ":" in t_str: return float(parts[0]) * 60 + float(parts[1])
                else: return float(parts[0]) + float(ms_val[:2]) / 100.0
            else:
                m, s = int(parts[0][:-2]), int(parts[0][-2:])
                return m * 60 + s + float(ms_val[:2]) / 100.0
        elif len(parts) == 1: return float(parts[0])
    except Exception: return None
    return None

def seconds_to_time(sec):
    if sec is None or sec < 0: return "N/A"
    mins = int(sec // 60)
    remainder = sec % 60
    if mins > 0: return f"{mins}:{remainder:05.2f}"
    else: return f"{remainder:05.2f}"

def format_time_input(t_str):
    if not t_str or str(t_str).strip().lower() in ["", "none", "nan"]: return ""
    sec = time_to_seconds(t_str)
    if sec is not None: return seconds_to_time(sec)
    return str(t_str)

def calculate_variance(achieved_sec, target_sec):
    if achieved_sec is None or target_sec is None: return "N/A"
    diff = achieved_sec - target_sec
    if diff < 0: return f"✅ -{seconds_to_time(abs(diff))}" 
    elif diff > 0: return f"🔺 +{seconds_to_time(abs(diff))}" 
    else: return f"⏸️ 0.00"

def populate_variances(df_input):
    if df_input.empty: return df_input
    df = df_input.copy()
    if "Coach Notes" not in df.columns: df["Coach Notes"] = ""
    var_entry = []
    for _, row in df.iterrows():
        ach_sec = time_to_seconds(row.get("Achieved Time", ""))
        entry_sec = time_to_seconds(row.get("Entry Time", ""))
        var_entry.append(calculate_variance(ach_sec, entry_sec))
    df["Var vs Entry"] = var_entry
    return df

def compute_gala_schedule_times(df_input, session_starts, pace):
    if df_input.empty: return df_input
    calc_df = df_input.copy()
    calc_df["Coach Time"], calc_df["Marshalling Time"], calc_df["Est. Race Time"] = "", "", ""
    sessions = sorted(calc_df["Session"].unique())
    for sess in sessions:
        start_t = session_starts.get(sess, time(9, 0) if sess % 2 != 0 else time(14, 0))
        current_event_start_dt = datetime.combine(datetime.today(), start_t)
        sess_mask = calc_df["Session"] == sess
        sess_df = calc_df[sess_mask]
        events = sorted(sess_df["Event"].unique(), key=get_event_num)
        
        for event in events:
            event_mask = sess_mask & (calc_df["Event"] == event)
            event_rows = calc_df[event_mask].sort_values(by=["_sort_heat", "_sort_lane"])
            max_heat = 1
            try: max_heat = int(event_rows["_sort_heat"].max())
            except: pass
            
            heat_duration_sec = estimate_heat_duration_seconds(event) * pace
            event_coach_dt = current_event_start_dt - timedelta(minutes=20)
            event_coach_time_str = event_coach_dt.strftime("%H:%M")
            
            for idx, row in event_rows.iterrows():
                h_num = 1
                try: h_num = int(row["_sort_heat"])
                except: pass
                heat_offset_sec = (h_num - 1) * heat_duration_sec
                heat_race_dt = current_event_start_dt + timedelta(seconds=heat_offset_sec)
                heat_marsh_dt = heat_race_dt - timedelta(minutes=10)
                
                calc_df.loc[idx, "Coach Time"] = event_coach_time_str
                calc_df.loc[idx, "Marshalling Time"] = heat_marsh_dt.strftime("%H:%M")
                calc_df.loc[idx, "Est. Race Time"] = heat_race_dt.strftime("%H:%M")
            current_event_start_dt += timedelta(seconds=heat_duration_sec * max_heat)
    return calc_df

def get_target_analysis(row, target_df, has_targets):
    ach_sec = time_to_seconds(row.get('Achieved Time'))
    ent_sec = time_to_seconds(row.get('Entry Time'))
    c_sec, r_sec = None, None
    
    if has_targets:
        g = extract_gender(row.get('Event', ''))
        a = safe_int(row.get('Age'), -1)
        e = extract_standard_event(row.get('Event', ''))
        match = target_df[(target_df['Gender'] == g) & (target_df['Age'] == a) & (target_df['Event'].str.lower() == e.lower())]
        
        c_time = match.iloc[0].get('County_Time', "") if not match.empty and pd.notna(match.iloc[0].get('County_Time')) else ""
        r_time = match.iloc[0].get('Regional_Time', "") if not match.empty and pd.notna(match.iloc[0].get('Regional_Time')) else ""
        
        c_sec = time_to_seconds(c_time) if c_time else None
        r_sec = time_to_seconds(r_time) if r_time else None

    if ach_sec is not None:
        res = []
        ent_ach_var = calculate_variance(ach_sec, ent_sec) if ent_sec else ""
        if ent_ach_var and ent_ach_var != "N/A": res.append(f"PB: {ent_ach_var}")
        
        if has_targets:
            c_ach_var = calculate_variance(ach_sec, c_sec) if c_sec else ""
            r_ach_var = calculate_variance(ach_sec, r_sec) if r_sec else ""
            if c_ach_var and c_ach_var != "N/A": res.append(f"C: {c_ach_var}")
            if r_ach_var and r_ach_var != "N/A": res.append(f"R: {r_ach_var}")
            
        return " | ".join(res) if res else "Logged"
    else:
        if has_targets:
            res = []
            c_ent_var = calculate_variance(ent_sec, c_sec) if ent_sec and c_sec else ""
            r_ent_var = calculate_variance(ent_sec, r_sec) if ent_sec and r_sec else ""
            if c_ent_var and c_ent_var != "N/A": res.append(f"C: {c_ent_var}")
            if r_ent_var and r_ent_var != "N/A": res.append(f"R: {r_ent_var}")
            return " | ".join(res) if res else "No Targets"
        else:
            return "⏳ Awaiting"


# --- DATA FETCHING ---
parsed_entries = []
if input_method == "Web Link (URL)":
    url_input = st.sidebar.text_input("SPORTSYSTEMS Live URL", value=st.session_state["last_url"])
    if url_input and st.sidebar.button("Fetch & Process Web Link"):
        st.session_state["last_url"] = url_input
        with st.spinner("Fetching and processing data..."):
            try:
                visited_urls = set()
                pages_to_scrape = [url_input]
                resp = fetch_url_content(url_input)
                visited_urls.add(url_input)
                soup = BeautifulSoup(resp.text, 'html.parser')
                meet_name = extract_meet_name_from_soup(soup)
                if meet_name: st.session_state["meet_name"] = meet_name
                for frame in soup.find_all(['frame', 'iframe']):
                    if frame.get('src'): pages_to_scrape.append(urljoin(url_input, frame.get('src')))
                sub_links = []
                for p_url in list(pages_to_scrape):
                    try:
                        p_resp = fetch_url_content(p_url)
                        visited_urls.add(p_url)
                        p_soup = BeautifulSoup(p_resp.text, 'html.parser')
                        parsed_entries.extend(parse_html_soup(p_soup, club_filter))
                        for a in p_soup.find_all('a', href=True):
                            full_url = urljoin(p_url, a['href'])
                            if urlparse(full_url).netloc == urlparse(url_input).netloc and full_url not in visited_urls and a['href'].lower().endswith(('.htm', '.html')):
                                sub_links.append(full_url)
                                visited_urls.add(full_url)
                    except: continue
                for link in sub_links:
                    try: parsed_entries.extend(parse_html_soup(BeautifulSoup(fetch_url_content(link).text, 'html.parser'), club_filter))
                    except: continue
                if parsed_entries:
                    st.session_state["gala_df"] = pd.DataFrame(parsed_entries).drop_duplicates()
                    st.session_state["room_pin"] = None
                    st.rerun()
                else: st.sidebar.warning("No entries matching your Club Keyword were found.")
            except Exception as e: st.error(f"Could not load web page: {e}")

elif input_method == "Upload PDF File":
    uploaded_file = st.sidebar.file_uploader("Upload Heat Sheet PDF", type=["pdf"])
    if uploaded_file and st.sidebar.button("Process PDF"):
        with st.spinner("Extracting data from PDF..."):
            lines = []
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    if page.extract_text(): lines.extend(page.extract_text().split("\n"))
            parsed_entries = parse_text_lines(lines, club_filter)
            if parsed_entries: 
                st.session_state["gala_df"] = pd.DataFrame(parsed_entries).drop_duplicates()
                st.session_state["room_pin"] = None
                st.rerun()

elif input_method == "Paste Text / HTML":
    pasted_text = st.sidebar.text_area("Paste webpage text directly here", height=200)
    if pasted_text and st.sidebar.button("Process Text"):
        with st.spinner("Processing pasted text..."):
            parsed_entries = parse_text_lines(pasted_text.split("\n"), club_filter)
            if parsed_entries: 
                st.session_state["gala_df"] = pd.DataFrame(parsed_entries).drop_duplicates()
                st.session_state["room_pin"] = None
                st.rerun()

# --- DATA COMPILATION ---
df = st.session_state["gala_df"]

if not df.empty:
    df["_sort_heat"] = pd.to_numeric(df["Heat"], errors='coerce').fillna(9999)
    df["_sort_lane"] = pd.to_numeric(df["Lane"], errors='coerce').fillna(9999)
    
    if "Checked In" not in df.columns: df["Checked In"] = False
    if "Checked Out" not in df.columns: df["Checked Out"] = False
    df_with_variances = populate_variances(df)
    df_final = compute_gala_schedule_times(df_with_variances, session_start_map, pace_factor)
else:
    df_final = df


# --- VIEW 1: COACH RACE INFO ---
if page_selection == VIEW_COACH:
    
    if not df_final.empty:
        achieved_upper = df_final["Achieved Time"].astype(str).str.upper()
        notes_upper = df_final["Coach Notes"].astype(str).str.upper()

        is_dq = achieved_upper.str.contains("DQ", na=False) | notes_upper.str.contains("DQ", na=False)
        is_dnc = achieved_upper.str.contains("DNC|WD|WITHDRAWN", na=False) | notes_upper.str.contains("DNC|WD|WITHDRAWN", na=False)
        
        dq_count = int(is_dq.sum())
        dnc_count = int(is_dnc.sum())

        recorded_swims = df_final[(df_final["Achieved Time"] != "") & (~is_dnc) & (~is_dq)]
        swims_done = len(recorded_swims)
        total_swims = len(df_final)
        faster_count = df_final["Var vs Entry"].str.startswith("✅").sum()
        
        swims_remaining = max(0, total_swims - swims_done - dq_count - dnc_count)
        current_time_str = datetime.now().strftime("%H:%M")
        
        st.markdown(f"""
        <div class="status-pill"><span class="status-dot">●</span> Live tracking active · updated {current_time_str}</div>
        <div class="kpi-container">
            <div class="kpi-card"><div class="kpi-val">{swims_done}</div><div class="kpi-label">SWIMS DONE</div></div>
            <div class="kpi-card"><div class="kpi-val green">{faster_count}</div><div class="kpi-label">FASTER THAN ENTRY</div></div>
            <div class="kpi-card"><div class="kpi-val red">{dq_count}</div><div class="kpi-label">DISQUALIFIED</div></div>
            <div class="kpi-card"><div class="kpi-val orange">{dnc_count}</div><div class="kpi-label">WITHDRAWN</div></div>
            <div class="kpi-card"><div class="kpi-val">{swims_remaining}</div><div class="kpi-label">SWIMS REMAINING</div></div>
        </div>
        """, unsafe_allow_html=True)
        
        sessions = sorted(df_final["Session"].unique())
        
        coach_col_config = {
            "Heat": st.column_config.TextColumn("Heat", width="small"),
            "Lane": st.column_config.TextColumn("Lane", width="small"),
            "Age": st.column_config.TextColumn("Age", width="small"),
            "Entry Time": st.column_config.TextColumn("Entry Time", width="medium"),
            "Achieved Time": st.column_config.TextColumn("Achieved Time", width="medium"),
            "Swimmer": st.column_config.TextColumn("Swimmer", width="medium"),
            "Target +/-": st.column_config.TextColumn("Target +/-", width="large"),
            "Coach Notes": st.column_config.TextColumn("Coach Notes", width="large")
        }

        for sess in sessions:
            st.markdown(f"<h3 style='margin-top: 30px; border-bottom: 2px solid #eee; padding-bottom: 10px; color:var(--text-color);'>Session {sess} Input</h3>", unsafe_allow_html=True)
            sess_df = df_final[df_final["Session"] == sess]
            events = sorted(sess_df["Event"].unique(), key=get_event_num)
            
            for event in events:
                event_df = sess_df[sess_df["Event"] == event].sort_values(by=["_sort_heat", "_sort_lane"]).copy()
                
                event_df["Heat"] = event_df["Heat"].astype(str)
                event_df["Lane"] = event_df["Lane"].astype(str)
                event_df["Age"] = event_df["Age"].astype(str)

                with st.expander(f"🏊 {event} ({len(event_df)} Swimmers)", expanded=True):
                    
                    has_targets = not st.session_state["target_df"].empty
                    target_df = st.session_state["target_df"]

                    event_df["Target +/-"] = [get_target_analysis(r, target_df, has_targets) for _, r in event_df.iterrows()]
                    
                    display_cols = ["Heat", "Lane", "Swimmer", "Age", "Entry Time", "Achieved Time", "Target +/-", "Coach Notes"]
                    disabled_cols = ["Heat", "Lane", "Swimmer", "Age", "Entry Time", "Target +/-"]

                    editor_key = f"editor_coach_s{sess}_{event}_{st.session_state['redraw_counter']}"
                    
                    edited_event_df = st.data_editor(
                        event_df[display_cols],
                        key=editor_key,
                        disabled=disabled_cols,
                        column_config=coach_col_config,
                        hide_index=True,
                        use_container_width=True
                    )
                    
                    changes_made = False
                    for _, edited_row in edited_event_df.iterrows():
                        mask = (st.session_state["gala_df"]["Session"] == sess) & (st.session_state["gala_df"]["Event"] == event) & (st.session_state["gala_df"]["Swimmer"] == edited_row["Swimmer"]) & (st.session_state["gala_df"]["Heat"].astype(str) == edited_row["Heat"])
                        
                        curr_achieved = str(st.session_state["gala_df"].loc[mask, "Achieved Time"].values[0])
                        curr_notes = str(st.session_state["gala_df"].loc[mask, "Coach Notes"].values[0])
                        
                        raw_ach = str(edited_row["Achieved Time"]) if pd.notna(edited_row["Achieved Time"]) else ""
                        new_notes = str(edited_row["Coach Notes"]) if pd.notna(edited_row["Coach Notes"]) else ""
                        
                        if raw_ach.lower() in ["none", "nan"]: raw_ach = ""
                        if new_notes.lower() in ["none", "nan"]: new_notes = ""
                        
                        formatted_ach = format_time_input(raw_ach)
                        
                        if raw_ach != curr_achieved:
                            st.session_state["gala_df"].loc[mask, "Achieved Time"] = formatted_ach
                            if st.session_state["room_pin"] and "id" in st.session_state["gala_df"].columns:
                                safe_update_db(st.session_state["gala_df"].loc[mask, "id"].values[0], "achieved_time", formatted_ach)
                            changes_made = True
                            
                        if new_notes != curr_notes:
                            st.session_state["gala_df"].loc[mask, "Coach Notes"] = new_notes
                            if st.session_state["room_pin"] and "id" in st.session_state["gala_df"].columns:
                                safe_update_db(st.session_state["gala_df"].loc[mask, "id"].values[0], "coach_notes", new_notes)
                            changes_made = True
                            
                    if changes_made:
                        st.session_state['redraw_counter'] += 1
                        st.rerun()

    else: st.info("👈 **Please load your gala meet data** from the sidebar first.")

# --- VIEW 2: SWIMMER WALL PLANNER ---
elif page_selection == VIEW_WALL:
    if not df_final.empty:
        sorted_df = df_final.sort_values(by=["Swimmer", "Session", "Event"])
        current_swimmer = None
        club_display = f"{club_filter.upper()} " if club_filter.strip() else ""
        header_meet = f" — {st.session_state['meet_name']}" if st.session_state["meet_name"] else ""
        
        def clean_event_name(e_str):
            m1 = re.search(r'EVENT\s+(\d+)', str(e_str), re.IGNORECASE)
            m2 = re.search(r'(\d+m\s+[A-Za-z]+(?:\s+IM)?)', str(e_str), re.IGNORECASE)
            if m1 and m2:
                stroke = m2.group(1).title()
                stroke = stroke.replace('Breaststroke', 'Breast').replace('Breaststrok', 'Breast')
                stroke = stroke.replace('Freestyle', 'Free')
                stroke = stroke.replace('Backstroke', 'Back')
                stroke = stroke.replace('Butterfly', 'Fly')
                stroke = stroke.replace('M ', 'm ').replace(' Im', ' IM')
                return f"#{m1.group(1)} {stroke}"
            return str(e_str).strip(' -')

        ui_output = f"## {club_display}GALA SCHEDULE{header_meet.upper()} — SWIMMER A–Z\n\n"
        dl_output = f"{club_display}GALA SCHEDULE{header_meet.upper()} — SWIMMER A–Z\n{'='*65}\n"
        
        for idx, row in sorted_df.iterrows():
            if row["Swimmer"] != current_swimmer:
                current_swimmer = row["Swimmer"]
                
                ui_output += f"\n### 👤 {current_swimmer} *(Age: {row.get('Age', 'N/A')})*\n"
                ui_output += "| Sess | Event | H/L | Entry | Call | Race |\n"
                ui_output += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
                
                dl_output += f"\n{current_swimmer.upper()} (Age: {row.get('Age', 'N/A')})\n"
                dl_output += "-" * 65 + "\n"
                
            clean_evt = clean_event_name(row['Event'])
            hl_ui = f"H{row['Heat']}/L{row['Lane']}"
            
            ui_output += f"| {row['Session']} | {clean_evt} | {hl_ui} | {row['Entry Time']} | **{row['Marshalling Time']}** | {row['Est. Race Time']} |\n"
            dl_output += f"Sess {row['Session']} | {clean_evt:<18} | {hl_ui:<7} | Entry: {row['Entry Time']:<8} | Call: {row['Marshalling Time']:<5} | Race: {row['Est. Race Time']}\n"
            
        st.markdown(ui_output)
        st.download_button("📄 Download Printable Schedule (.txt)", dl_output, "gala_wall_schedule.txt", "text/plain")
    else: st.info("👈 **Please load your gala meet data** from the sidebar first.")

# --- VIEW 3: TM MARSHALLING INFO ---
elif page_selection == VIEW_TM:
    st.markdown("Track swimmer movement split by **Session**. All swimmers in an event see **Coach** at event call time (-20 mins); **Marshalling** is calculated per individual **Heat** (-10 mins).")
    
    if not df_final.empty:
        tm_rc_config = {
            "Swimmer": st.column_config.TextColumn("Swimmer", width="medium"),
            "Age": st.column_config.TextColumn("Age", width="small")
        }
        
        tm_event_config = {
            "Heat": st.column_config.TextColumn("Heat", width="small"),
            "Lane": st.column_config.TextColumn("Lane", width="small"),
            "Swimmer": st.column_config.TextColumn("Swimmer", width="medium"),
            "Age": st.column_config.TextColumn("Age", width="small"),
            "Coach Time": st.column_config.TextColumn("Coach Time", width="small"),
            "Marshalling Time": st.column_config.TextColumn("Marshalling Time", width="small"),
            "Est. Race Time": st.column_config.TextColumn("Est. Race Time", width="small"),
            "Seen Coach": st.column_config.CheckboxColumn("Seen Coach?", width="small"),
            "In Marshalling": st.column_config.CheckboxColumn("In Marshalling?", width="small")
        }

        sessions = sorted(df_final["Session"].unique())
        for sess in sessions:
            st.markdown(f"<h3 style='margin-top: 30px; border-bottom: 2px solid #eee; padding-bottom: 10px; color:var(--text-color);'>Session {sess}</h3>", unsafe_allow_html=True)
            sess_df = df_final[df_final["Session"] == sess]
            
            roll_call_df = sess_df.drop_duplicates(subset=["Swimmer"])[["Swimmer", "Age", "Checked In", "Checked Out"]].sort_values("Swimmer")
            roll_call_df["Age"] = roll_call_df["Age"].astype(str)

            with st.expander(f"📝 Session {sess} Swimmer Roll Call ({roll_call_df['Checked In'].sum()} / {len(roll_call_df)} Arrived)", expanded=True):
                rc_editor_key = f"rollcall_s{sess}_{st.session_state['redraw_counter']}"
                edited_rc = st.data_editor(
                    roll_call_df, 
                    key=rc_editor_key, 
                    disabled=["Swimmer", "Age"], 
                    column_config=tm_rc_config,
                    hide_index=True, 
                    use_container_width=True
                )
                rc_changes = False
                for _, row in edited_rc.iterrows():
                    swimmer = row["Swimmer"]
                    mask = (st.session_state["gala_df"]["Session"] == sess) & (st.session_state["gala_df"]["Swimmer"] == swimmer)
                    
                    if row["Checked In"] != st.session_state["gala_df"].loc[mask, "Checked In"].iloc[0]:
                        st.session_state["gala_df"].loc[mask, "Checked In"] = row["Checked In"]
                        if st.session_state["room_pin"]:
                            try: supabase.table("live_gala_data").update({"checked_in": bool(row["Checked In"])}).eq("room_pin", st.session_state["room_pin"]).eq("session", sess).eq("swimmer", swimmer).execute()
                            except: pass
                        rc_changes = True
                    if row["Checked Out"] != st.session_state["gala_df"].loc[mask, "Checked Out"].iloc[0]:
                        st.session_state["gala_df"].loc[mask, "Checked Out"] = row["Checked Out"]
                        if st.session_state["room_pin"]:
                            try: supabase.table("live_gala_data").update({"checked_out": bool(row["Checked Out"])}).eq("room_pin", st.session_state["room_pin"]).eq("session", sess).eq("swimmer", swimmer).execute()
                            except: pass
                        rc_changes = True
                if rc_changes:
                    st.session_state['redraw_counter'] += 1
                    st.rerun()

            events = sorted(sess_df["Event"].unique(), key=get_event_num)
            for event in events:
                event_df = sess_df[sess_df["Event"] == event].sort_values(by=["_sort_heat", "_sort_lane"]).copy()
                
                event_df["Heat"] = event_df["Heat"].astype(str)
                event_df["Lane"] = event_df["Lane"].astype(str)
                event_df["Age"] = event_df["Age"].astype(str)

                display_cols = ["Heat", "Lane", "Swimmer", "Age", "Coach Time", "Seen Coach", "Marshalling Time", "In Marshalling", "Est. Race Time"]
                first_row = event_df.iloc[0] if not event_df.empty else None
                
                with st.expander(f"🏊 {event} — Event Starts ~{first_row['Est. Race Time']} | Coach Call: {first_row['Coach Time']} ({len(event_df)} Swimmers)", expanded=True):
                    editor_key = f"editor_tm_s{sess}_{event}_{st.session_state['redraw_counter']}"
                    edited_tm_df = st.data_editor(
                        event_df[display_cols], 
                        key=editor_key,
                        disabled=["Heat", "Lane", "Swimmer", "Age", "Coach Time", "Marshalling Time", "Est. Race Time"],
                        column_config=tm_event_config,
                        hide_index=True, 
                        use_container_width=True
                    )
                    changes_made_tm = False
                    for _, edited_row in edited_tm_df.iterrows():
                        mask = (st.session_state["gala_df"]["Session"] == sess) & (st.session_state["gala_df"]["Event"] == event) & (st.session_state["gala_df"]["Swimmer"] == edited_row["Swimmer"]) & (st.session_state["gala_df"]["Heat"].astype(str) == edited_row["Heat"])
                        if edited_row["Seen Coach"] != st.session_state["gala_df"].loc[mask, "Seen Coach"].values[0]:
                            st.session_state["gala_df"].loc[mask, "Seen Coach"] = edited_row["Seen Coach"]
                            if st.session_state["room_pin"] and "id" in st.session_state["gala_df"].columns:
                                safe_update_db(st.session_state["gala_df"].loc[mask, "id"].values[0], "seen_coach", bool(edited_row["Seen Coach"]))
                            changes_made_tm = True
                        if edited_row["In Marshalling"] != st.session_state["gala_df"].loc[mask, "In Marshalling"].values[0]:
                            st.session_state["gala_df"].loc[mask, "In Marshalling"] = edited_row["In Marshalling"]
                            if st.session_state["room_pin"] and "id" in st.session_state["gala_df"].columns:
                                safe_update_db(st.session_state["gala_df"].loc[mask, "id"].values[0], "in_marshalling", bool(edited_row["In Marshalling"]))
                            changes_made_tm = True
                    if changes_made_tm:
                        st.session_state['redraw_counter'] += 1
                        st.rerun()
    else: st.info("👈 **Please load your gala meet data** from the sidebar first.")