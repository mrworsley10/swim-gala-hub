import streamlit as st
import pandas as pd
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
from datetime import datetime
from supabase import create_client, Client

# --- PAGE SETUP ---
st.set_page_config(page_title="Live Swimmer Tracker", page_icon="🏊", layout="centered", initial_sidebar_state="collapsed")

# --- CUSTOM MOBILE-FIRST CSS ---
st.markdown("""
<style>
    #MainMenu {visibility: hidden;} header {visibility: hidden;}
    .stApp { background-color: #0f172a; color: #f8fafc; }
    .pin-container { background: #1e293b; padding: 30px; border-radius: 15px; text-align: center; margin-top: 10vh; border-top: 4px solid #3b82f6; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5); }
    .swimmer-header { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 20px; border-radius: 12px; border: 1px solid #334155; margin-bottom: 20px; text-align: center; }
    .swimmer-name { font-size: 1.8rem; font-weight: 800; color: #facc15; margin-bottom: 5px; line-height: 1.2; }
    .swimmer-stats { font-size: 0.9rem; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
    .race-card { background-color: #1e293b; border-radius: 12px; padding: 16px; margin-bottom: 15px; border-left: 5px solid #334155; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3); }
    .race-card.completed { border-left-color: #4ade80; }
    .race-card.pending { border-left-color: #facc15; }
    .race-top-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid #334155; padding-bottom: 8px; }
    .race-event { font-weight: 700; font-size: 1.05rem; color: #f8fafc; display: flex; align-items: center; justify-content: space-between; width: 100%;}
    .race-heat-lane { font-size: 0.8rem; color: #94a3b8; background: #0f172a; padding: 4px 8px; border-radius: 6px; font-weight: bold; }
    .race-times-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
    .time-box { background: #0f172a; padding: 10px; border-radius: 8px; text-align: center; }
    .time-label { font-size: 0.7rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 3px; font-weight: 700; }
    .time-value { font-size: 1.3rem; font-weight: 900; }
    .val-entry { color: #cbd5e1; }
    .val-achieved { color: #4ade80; }
    .val-pending { color: #facc15; font-size: 1rem !important; line-height: 1.3rem; }
    .race-analysis { background: #0f172a; padding: 10px; border-radius: 8px; font-size: 0.85rem; color: #e2e8f0; text-align: center; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# --- SUPABASE ---
@st.cache_resource
def init_supabase() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
try: supabase = init_supabase()
except Exception as e: st.error(f"Database Failed: {e}")

# --- HELPER FUNCTIONS ---
def safe_int(val, default=-1):
    try: return int(float(val))
    except: return default

def get_event_num(event_str):
    m = re.search(r'Event\s+(\d+)', str(event_str), re.IGNORECASE)
    return int(m.group(1)) if m else 9999

def extract_gender(event_str):
    e_lower = str(event_str).lower()
    return 'F' if 'female' in e_lower or 'girl' in e_lower or 'women' in e_lower else 'M'

def extract_standard_event(event_str):
    m = re.search(r'(\d+m\s+[A-Za-z]+(?:\s+IM)?)', str(event_str), re.IGNORECASE)
    if m: return m.group(1).title().replace('Breaststroke', 'Breast').replace('Breaststrok', 'Breast').replace('Freestyle', 'Free').replace('Backstroke', 'Back').replace('Butterfly', 'Fly').replace('Ind. Medley', 'IM').replace('Ind Medley', 'IM').replace('M ', 'm ').replace(' Im', ' IM').strip()
    return ""

def time_to_seconds(t_str):
    if not t_str or str(t_str).strip().upper() in ["N/A", "S/T", "NT", "", "-", "—", "NONE", "DQ", "DNC", "WD", "WITHDRAWN"]: return None
    t_str = re.sub(r'[^\d:\.]', '', str(t_str).strip())
    if not t_str: return None
    try:
        if t_str.isdigit():
            if len(t_str) >= 5: return int(t_str[:-4]) * 60 + int(t_str[-4:-2]) + (int(t_str[-2:]) / 100.0)
            elif len(t_str) >= 3: return int(t_str[:-2]) + (int(t_str[-2:]) / 100.0)
            else: return float(t_str)
        parts = re.split(r'[:\.]', t_str)
        if len(parts) == 3: return float(parts[0]) * 60 + float(parts[1]) + float(parts[2].ljust(2,'0')[:2]) / 100.0
        elif len(parts) == 2:
            ms_val = parts[1].ljust(2,'0')[:2]
            if ":" in t_str or len(parts[0]) < 3: return float(parts[0]) * 60 + float(parts[1]) if ":" in t_str else float(parts[0]) + float(ms_val) / 100.0
            else: return int(parts[0][:-2]) * 60 + int(parts[0][-2:]) + float(ms_val) / 100.0
        elif len(parts) == 1: return float(parts[0])
    except: return None
    return None

def seconds_to_time(sec):
    return "N/A" if sec is None or sec < 0 else (f"{int(sec // 60)}:{sec % 60:05.2f}" if sec >= 60 else f"{sec % 60:05.2f}")

def calculate_variance(achieved_sec, target_sec):
    if achieved_sec is None or target_sec is None: return "N/A"
    diff = achieved_sec - target_sec
    if diff < 0: return f"✅ -{seconds_to_time(abs(diff))}" 
    elif diff > 0: return f"🔺 +{seconds_to_time(abs(diff))}" 
    else: return f"⏸ 0.00"

def get_target_analysis(row, target_df, has_targets):
    ach_sec, ent_sec = time_to_seconds(row.get('Achieved Time')), time_to_seconds(row.get('Entry Time'))
    c_sec, r_sec = None, None
    if has_targets:
        match = target_df[(target_df['Gender'] == extract_gender(row.get('Event', ''))) & (target_df['Age'] == safe_int(row.get('Age'), -1)) & (target_df['Event'].str.lower() == extract_standard_event(row.get('Event', '')).lower())]
        if not match.empty: c_sec, r_sec = time_to_seconds(match.iloc[0].get('County_Time', "")), time_to_seconds(match.iloc[0].get('Regional_Time', ""))
    if ach_sec is not None:
        res = []
        v = calculate_variance(ach_sec, ent_sec)
        if v and v != "N/A": res.append(f"PB: {v}")
        if has_targets:
            v_c, v_r = calculate_variance(ach_sec, c_sec), calculate_variance(ach_sec, r_sec)
            if v_c and v_c != "N/A": res.append(f"C: {v_c}")
            if v_r and v_r != "N/A": res.append(f"R: {v_r}")
        return " | ".join(res) if res else "Logged"
    else:
        if has_targets:
            res = []
            v_c, v_r = calculate_variance(ent_sec, c_sec), calculate_variance(ent_sec, r_sec)
            if v_c and v_c != "N/A": res.append(f"C: {v_c}")
            if v_r and v_r != "N/A": res.append(f"R: {v_r}")
            return " | ".join(res) if res else "No Targets"
        return "⏳ Awaiting Race"

# --- WEB SCRAPER FOR OFFICIAL MEDALS ---
def fetch_official_medals(gala_url, swimmer_name):
    if not gala_url: return {}
    medals = {}
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        headers = {'User-Agent': 'Mozilla/5.0'}
        soup = BeautifulSoup(requests.get(gala_url, headers=headers, verify=False, timeout=10).text, 'html.parser')
        
        links = [urljoin(gala_url, a['href']) for a in soup.find_all('a', href=True) if 'event' in a['href'].lower() or re.match(r'^\d+\.htm', a['href'])]
        for f in soup.find_all(['frame', 'iframe']):
            if f.get('src'):
                fsoup = BeautifulSoup(requests.get(urljoin(gala_url, f.get('src')), headers=headers, verify=False, timeout=5).text, 'html.parser')
                links.extend([urljoin(gala_url, a['href']) for a in fsoup.find_all('a', href=True)])

        lname = swimmer_name.split()[-1].lower()
        for link in set(links):
            try:
                psoup = BeautifulSoup(requests.get(link, headers=headers, verify=False, timeout=3).text, 'html.parser')
                hdr = psoup.find(['h1', 'h2', 'h3', 'h4'])
                clean_evt = extract_standard_event(hdr.get_text(strip=True)) if hdr else ""
                if not clean_evt: continue
                
                for tr in psoup.find_all('tr'):
                    if lname in tr.get_text(separator=" ", strip=True).lower():
                        cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
                        if cells and cells[0].isdigit():
                            place = int(cells[0])
                            if place == 1: medals[clean_evt] = "🥇 1st"
                            elif place == 2: medals[clean_evt] = "🥈 2nd"
                            elif place == 3: medals[clean_evt] = "🥉 3rd"
            except: continue
    except: pass
    return medals

# --- CLOUD FETCHING ---
def fetch_room_data(pin):
    try:
        response = supabase.table("live_gala_data").select("*").eq("room_pin", str(pin)).execute()
        if response.data: return pd.DataFrame(response.data).rename(columns={"session": "Session", "swimmer": "Swimmer", "age": "Age", "event": "Event", "heat": "Heat", "lane": "Lane", "entry_time": "Entry Time", "achieved_time": "Achieved Time"})
    except: pass
    return pd.DataFrame()

def fetch_room_targets(pin):
    try:
        res = supabase.table("target_times").select("*").eq("room_pin", str(pin)).execute()
        if res.data: return pd.DataFrame(res.data).rename(columns={"gender": "Gender", "age": "Age", "event": "Event", "county_time": "County_Time", "regional_time": "Regional_Time"})
    except: pass
    return pd.DataFrame()

if "parent_room" not in st.session_state: st.session_state["parent_room"] = None
if "gala_df" not in st.session_state: st.session_state["gala_df"] = pd.DataFrame()
if "target_df" not in st.session_state: st.session_state["target_df"] = pd.DataFrame()

if not st.session_state["parent_room"]:
    st.markdown("""<div class="pin-container"><h1 style="color: white; margin-bottom: 5px;">🏊 Swimmer Tracker</h1><p style="color: #94a3b8; margin-bottom: 25px;">Enter the 4-digit PIN provided by your coach.</p></div>""", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        join_pin = st.text_input("Room PIN", max_chars=4, placeholder="e.g. 1234", label_visibility="collapsed")
        if st.button("Access Live Results", use_container_width=True, type="primary") and join_pin:
            with st.spinner("Finding Room..."):
                df = fetch_room_data(join_pin)
                if not df.empty:
                    st.session_state["parent_room"], st.session_state["gala_df"], st.session_state["target_df"] = join_pin, df, fetch_room_targets(join_pin)
                    st.rerun()
                else: st.error("Invalid PIN or empty room.")
    st.stop()

# --- DASHBOARD ---
df, target_df = st.session_state["gala_df"], st.session_state["target_df"]
has_targets = not target_df.empty

cA, cB = st.columns([3, 1])
with cA: st.markdown(f"<span style='color: #4ade80; font-weight: bold;'>🟢 Connected (Room {st.session_state['parent_room']})</span>", unsafe_allow_html=True)
with cB:
    if st.button("🔄 Refresh", use_container_width=True):
        st.session_state["gala_df"], st.session_state["target_df"] = fetch_room_data(st.session_state["parent_room"]), fetch_room_targets(st.session_state["parent_room"])
        st.rerun()

st.divider()
selected_swimmer = st.selectbox("🔍 Search for a Swimmer:", [""] + sorted(df["Swimmer"].unique()))

if selected_swimmer:
    swim_df = df[df["Swimmer"] == selected_swimmer].copy()
    swim_df["_evt_num"] = swim_df["Event"].apply(get_event_num)
    swim_df["_sort_heat"] = pd.to_numeric(swim_df["Heat"], errors='coerce').fillna(9999)
    swim_df["_sort_lane"] = pd.to_numeric(swim_df["Lane"], errors='coerce').fillna(9999)
    swim_df = swim_df.sort_values(by=["Session", "_evt_num", "_sort_heat", "_sort_lane"])
    
    room_url = swim_df.iloc[0].get("gala_url", "")
    with st.spinner("Checking official placements..."):
        swimmer_medals = fetch_official_medals(room_url, selected_swimmer)
    
    st.markdown(f"""<div class="swimmer-header"><div class="swimmer-name">{selected_swimmer}</div><div class="swimmer-stats">Age {swim_df.iloc[0].get('Age', 'N/A')} • {len(swim_df[swim_df['Achieved Time'] != ""])} of {len(swim_df)} Races Completed</div></div>""", unsafe_allow_html=True)

    for _, row in swim_df.iterrows():
        achieved = str(row["Achieved Time"]).strip()
        is_completed = bool(achieved and achieved.lower() not in ["none", "nan"])
        clean_evt = extract_standard_event(row["Event"]) or str(row["Event"]).split(" - ")[0]
        medal_badge = f"<span style='font-size: 1.2rem; color: white;'>{swimmer_medals[clean_evt]}</span>" if clean_evt in swimmer_medals else ""
        
        st.markdown(f"""
        <div class="race-card {'completed' if is_completed else 'pending'}">
            <div class="race-top-row">
                <div class="race-event"><span>{clean_evt}</span> {medal_badge}</div>
                <div class="race-heat-lane">Sess {row["Session"]} | H {row["Heat"]} | L {row["Lane"]}</div>
            </div>
            <div class="race-times-grid">
                <div class="time-box"><div class="time-label">Entry Time</div><div class="time-value val-entry">{row["Entry Time"]}</div></div>
                <div class="time-box"><div class="time-label">Achieved Time</div><div class="time-value {'val-achieved' if is_completed else 'val-pending'}">{achieved if is_completed else 'WAITING'}</div></div>
            </div>
            <div class="race-analysis">{get_target_analysis(row, target_df, has_targets)}</div>
        </div>
        """, unsafe_allow_html=True)
else: st.info("👆 Tap the search bar above to find your swimmer's live report card.")

st.markdown("<br><br>", unsafe_allow_html=True)
if st.button("🚪 Leave Room", type="secondary"):
    st.session_state["parent_room"] = None
    st.session_state["gala_df"] = pd.DataFrame()
    st.rerun()