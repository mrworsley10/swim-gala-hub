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

    /* --- EXISTING HEADER CSS --- */
    .modern-header {
        background-color: #0b0b0b;
        border-radius: 12px;
        padding: 25px 30px;
        margin-top: 10px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .modern-header h1 {
        color: #ffffff !important;
        margin: 0;
        font-size: 1.8em;
        font-weight: 800;
        letter-spacing: 0.5px;
    }
    .modern-header .club-name {
        color: #facc15;
        font-weight: 700;
        font-size: 1.2em;
        text-transform: uppercase;
        letter-spacing: 2px;
    }
    .dashed-divider {
        border-top: 6px dashed #facc15;
        margin: 15px 0 25px 0;
        opacity: 0.9;
    }
    .status-pill {
        background-color: #fef08a;
        color: #854d0e !important;
        padding: 5px 12px;
        border-radius: 15px;
        font-size: 0.85em;
        font-weight: 700;
        display: inline-block;
        margin-bottom: 20px;
        border: 1px solid #fde047;
    }
    .status-dot { color: #16a34a; margin-right: 5px; }
    .kpi-container { display: flex; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; }
    .kpi-card {
        flex: 1;
        min-width: 200px;
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
    .kpi-label { font-size: 0.75em; color: gray !important; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# Initialize Session State Variables
if "gala_df" not in st.session_state:
    st.session_state["gala_df"] = pd.DataFrame()
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

# --- DYNAMIC HEADER INJECTION ---
if page_selection == VIEW_COACH: banner_title = "🏊‍♂ COACH'S CLIPBOARD"
elif page_selection == VIEW_WALL: banner_title = "📋 SWIMMER WALL PLANNER"
else: banner_title = "🚩 TEAM MANAGER TRACKER"

pin_display = f"<div style='color: #4ade80; font-size: 0.85em; margin-top: 4px;'>🟢 Live Room: {st.session_state['room_pin']}</div>" if st.session_state["room_pin"] else "<div style='color: #ccc; font-size: 0.85em; margin-top: 4px;'>Offline Mode</div>"

st.markdown(f"""
<div class="modern-header">
    <div><div class="club-name">{banner_title}</div></div>
    <div style="text-align: right;">
        <h1>{st.session_state['meet_name']}</h1>
        {pin_display}
    </div>
</div>
<div class="dashed-divider"></div>
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
    if st.sidebar.button("🔄 Refresh Data"):
        with st.spinner("Syncing latest data..."):
            st.session_state["gala_df"] = fetch_room(st.session_state["room_pin"])
        st.rerun()
    if st.sidebar.button("🚪 Disconnect"):
        st.session_state["room_pin"] = None
        st.session_state["gala_df"] = pd.DataFrame()
        st.rerun()
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
                        st.rerun()
                    else:
                        st.sidebar.error("Upload succeeded, but could not read the data back.")
                        st.session_state["gala_df"] = original_df 
                else:
                    st.sidebar.error(f"Upload Failed: {err}")
                    st.session_state["gala_df"] = original_df

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
                lane, name, age, entry_time = None, None, "", "N/A"
                for c in cells:
                    if c.isdigit() and 7 <= int(c) <= 25 and not age: age = c
                if len(cells) >= 6:
                    lane, name = cells[0], cells[2]
                    for c in cells[3:5]:
                        if c.isdigit() and 7 <= int(c) <= 25:
                            age = c; break
                    entry_time = cells[5]
                elif len(cells) == 5:
                    lane = cells[0]
                    if cells[1].isdigit(): name, entry_time = cells[2], cells[4] if target_keyword and target_keyword not in cells[4].lower() else "N/A"
                    else: name, entry_time = cells[1], cells[4]
                elif len(cells) == 4:
                    lane, name = cells[0], cells[1]
                if lane and lane.isdigit() and is_valid_swimmer_name(name):
                    sess_num = infer_session_number(current_event, current_session)
                    entries.append({
                        "Session": sess_num, "Swimmer": name.title(), "Age": age, "Event": current_event,
                        "Heat": int(current_heat) if current_heat.isdigit() else current_heat, "Lane": int(lane),
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
    if not t_str or str(t_str).strip().upper() in ["N/A", "S/T", "NT", "", "-", "—", "NONE"]: return None
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
            ms_val = parts