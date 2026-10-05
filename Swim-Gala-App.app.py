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

# --- DEFINE PAGE NAMES GLOBALLY TO PREVENT EMOJI MISMATCHES ---
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
    header[data-testid="stHeader"] { display: none; }
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


# --- CLOUD DATABASE FUNCTIONS ---
def create_room(df):
    pin = str(random.randint(1000, 9999))
    records = []
    for _, row in df.iterrows():
        records.append({
            "room_pin": pin,
            "session": int(row.get("Session", 1)),
            "swimmer": str(row.get("Swimmer", "")),
            "age": str(row.get("Age", "")),
            "event": str(row.get("Event", "")),
            "heat": str(row.get("Heat", "")),
            "lane": int(row.get("Lane", 0)) if pd.notna(row.get("Lane")) else 0,
            "entry_time": str(row.get("Entry Time", "")),
            "achieved_time": str(row.get("Achieved Time", "")),
            "coach_notes": str(row.get("Coach Notes", "")),
            "checked_in": bool(row.get("Checked In", False)),
            "checked_out": bool(row.get("Checked Out", False)),
            "seen_coach": bool(row.get("Seen Coach", False)),
            "in_marshalling": bool(row.get("In Marshalling", False))
        })
    try:
        supabase.table("live_gala_data").insert(records).execute()
    except Exception as e:
        st.error(f"Failed to push to cloud: {e}")
    return pin

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
            with st.spinner("Creating secure room..."):
                pin = create_room(st.session_state["gala_df"])
                st.session_state["room_pin"] = pin
                st.session_state["gala_df"] = fetch_room(pin) # Refetch to get database IDs
                st.rerun()

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
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
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
            event_rows = calc_df[event_mask].sort_values(by=["Heat", "Lane"])
            max_heat = 1
            try: max_heat = int(event_rows["Heat"].max())
            except: pass
            
            heat_duration_sec = estimate_heat_duration_seconds(event) * pace
            event_coach_dt = current_event_start_dt - timedelta(minutes=20)
            event_coach_time_str = event_coach_dt.strftime("%H:%M")
            
            for idx, row in event_rows.iterrows():
                h_num = 1
                try: h_num = int(row["Heat"])
                except: pass
                heat_offset_sec = (h_num - 1) * heat_duration_sec
                heat_race_dt = current_event_start_dt + timedelta(seconds=heat_offset_sec)
                heat_marsh_dt = heat_race_dt - timedelta(minutes=10)
                
                calc_df.loc[idx, "Coach Time"] = event_coach_time_str
                calc_df.loc[idx, "Marshalling Time"] = heat_marsh_dt.strftime("%H:%M")
                calc_df.loc[idx, "Est. Race Time"] = heat_race_dt.strftime("%H:%M")
            current_event_start_dt += timedelta(seconds=heat_duration_sec * max_heat)
    return calc_df

# --- DATA FETCHING ---
parsed_entries = []
if input_method == "Web Link (URL)":
    url_input = st.sidebar.text_input("SPORTSYSTEMS Live URL")
    if url_input and st.sidebar.button("Fetch & Process Web Link"):
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
                st.rerun()
            else: st.sidebar.warning("No entries matching your Club Keyword were found.")
        except Exception as e: st.error(f"Could not load web page: {e}")

elif input_method == "Upload PDF File":
    uploaded_file = st.sidebar.file_uploader("Upload Heat Sheet PDF", type=["pdf"])
    if uploaded_file:
        lines = []
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                if page.extract_text(): lines.extend(page.extract_text().split("\n"))
        parsed_entries = parse_text_lines(lines, club_filter)
        if parsed_entries: st.session_state["gala_df"] = pd.DataFrame(parsed_entries).drop_duplicates()

elif input_method == "Paste Text / HTML":
    pasted_text = st.sidebar.text_area("Paste webpage text directly here", height=200)
    if pasted_text:
        parsed_entries = parse_text_lines(pasted_text.split("\n"), club_filter)
        if parsed_entries: st.session_state["gala_df"] = pd.DataFrame(parsed_entries).drop_duplicates()

# --- DATA COMPILATION ---
df = st.session_state["gala_df"]

if not df.empty:
    if "Checked In" not in df.columns: df["Checked In"] = False
    if "Checked Out" not in df.columns: df["Checked Out"] = False
    df_with_variances = populate_variances(df)
    df_final = compute_gala_schedule_times(df_with_variances, session_start_map, pace_factor)
else:
    df_final = df


# --- VIEW 1: COACH RACE INFO ---
if page_selection == VIEW_COACH:
    
    if not df_final.empty:
        recorded_swims = df_final[df_final["Achieved Time"] != ""]
        swims_done = len(recorded_swims)
        total_swims = len(df_final)
        faster_count = df_final["Var vs Entry"].str.startswith("✅").sum()
        current_time_str = datetime.now().strftime("%H:%M")
        
        st.markdown(f"""
        <div class="status-pill"><span class="status-dot">●</span> Live tracking active · updated {current_time_str}</div>
        <div class="kpi-container">
            <div class="kpi-card"><div class="kpi-val">{swims_done}</div><div class="kpi-label">OF {total_swims} SWIMS DONE</div></div>
            <div class="kpi-card"><div class="kpi-val green">{faster_count}</div><div class="kpi-label">FASTER THAN ENTRY</div></div>
            <div class="kpi-card"><div class="kpi-val">{total_swims - swims_done}</div><div class="kpi-label">SWIMS REMAINING</div></div>
        </div>
        """, unsafe_allow_html=True)
        
        sessions = sorted(df_final["Session"].unique())
        for sess in sessions:
            st.markdown(f"<h3 style='margin-top: 30px; border-bottom: 2px solid #eee; padding-bottom: 10px; color:var(--text-color);'>Session {sess} Input</h3>", unsafe_allow_html=True)
            sess_df = df_final[df_final["Session"] == sess]
            events = sorted(sess_df["Event"].unique(), key=get_event_num)
            
            for event in events:
                event_df = sess_df[sess_df["Event"] == event].sort_values(by=["Heat", "Lane"])
                with st.expander(f"🏊 {event} ({len(event_df)} Swimmers)", expanded=True):
                    display_cols = ["Heat", "Lane", "Swimmer", "Age", "Entry Time", "Achieved Time", "Var vs Entry", "Coach Notes"]
                    editor_key = f"editor_coach_s{sess}_{event}_{st.session_state['redraw_counter']}"
                    
                    edited_event_df = st.data_editor(
                        event_df[display_cols],
                        key=editor_key,
                        disabled=["Heat", "Lane", "Swimmer", "Age", "Entry Time", "Var vs Entry"],
                        hide_index=True,
                        use_container_width=True
                    )
                    
                    changes_made = False
                    for _, edited_row in edited_event_df.iterrows():
                        mask = (st.session_state["gala_df"]["Session"] == sess) & (st.session_state["gala_df"]["Event"] == event) & (st.session_state["gala_df"]["Swimmer"] == edited_row["Swimmer"]) & (st.session_state["gala_df"]["Heat"] == edited_row["Heat"])
                        
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
        formatted_output = f"## {club_display}GALA SCHEDULE{header_meet.upper()} — SWIMMER A–Z\n\n"
        for idx, row in sorted_df.iterrows():
            if row["Swimmer"] != current_swimmer:
                current_swimmer = row["Swimmer"]
                formatted_output += f"\n### 👤 {current_swimmer} *(Age: {row.get('Age', 'N/A')})*\n"
            formatted_output += f"* **Session {row['Session']} | {row['Event']}** — Heat {row['Heat']}, Lane {row['Lane']} *(Entry: {row['Entry Time']})* | 🚩 **Marshalling:** {row['Marshalling Time']} | ⏱️ **Est. Race:** {row['Est. Race Time']}\n"
        st.markdown(formatted_output)
        st.download_button("📄 Download Printable Schedule (.txt)", formatted_output, "gala_wall_schedule.txt", "text/plain")
    else: st.info("👈 **Please load your gala meet data** from the sidebar first.")

# --- VIEW 3: TM MARSHALLING INFO ---
elif page_selection == VIEW_TM:
    st.markdown("Track swimmer movement split by **Session**. All swimmers in an event see **Coach** at event call time (-20 mins); **Marshalling** is calculated per individual **Heat** (-10 mins).")
    
    if not df_final.empty:
        sessions = sorted(df_final["Session"].unique())
        for sess in sessions:
            st.markdown(f"<h3 style='margin-top: 30px; border-bottom: 2px solid #eee; padding-bottom: 10px; color:var(--text-color);'>Session {sess}</h3>", unsafe_allow_html=True)
            sess_df = df_final[df_final["Session"] == sess]
            
            roll_call_df = sess_df.drop_duplicates(subset=["Swimmer"])[["Swimmer", "Age", "Checked In", "Checked Out"]].sort_values("Swimmer")
            with st.expander(f"📝 Session {sess} Swimmer Roll Call ({roll_call_df['Checked In'].sum()} / {len(roll_call_df)} Arrived)", expanded=True):
                rc_editor_key = f"rollcall_s{sess}_{st.session_state['redraw_counter']}"
                edited_rc = st.data_editor(roll_call_df, key=rc_editor_key, disabled=["Swimmer", "Age"], hide_index=True, use_container_width=True)
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
                event_df = sess_df[sess_df["Event"] == event].sort_values(by=["Heat", "Lane"])
                display_cols = ["Heat", "Lane", "Swimmer", "Age", "Coach Time", "Seen Coach", "Marshalling Time", "In Marshalling", "Est. Race Time"]
                first_row = event_df.iloc[0] if not event_df.empty else None
                
                with st.expander(f"🏊 {event} — Event Starts ~{first_row['Est. Race Time']} | Coach Call: {first_row['Coach Time']} ({len(event_df)} Swimmers)", expanded=True):
                    editor_key = f"editor_tm_s{sess}_{event}_{st.session_state['redraw_counter']}"
                    edited_tm_df = st.data_editor(
                        event_df[display_cols], key=editor_key,
                        disabled=["Heat", "Lane", "Swimmer", "Age", "Coach Time", "Marshalling Time", "Est. Race Time"],
                        column_config={"Seen Coach": st.column_config.CheckboxColumn("Seen Coach?"), "In Marshalling": st.column_config.CheckboxColumn("In Marshalling?")},
                        hide_index=True, use_container_width=True
                    )
                    changes_made_tm = False
                    for _, edited_row in edited_tm_df.iterrows():
                        mask = (st.session_state["gala_df"]["Session"] == sess) & (st.session_state["gala_df"]["Event"] == event) & (st.session_state["gala_df"]["Swimmer"] == edited_row["Swimmer"]) & (st.session_state["gala_df"]["Heat"] == edited_row["Heat"])
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