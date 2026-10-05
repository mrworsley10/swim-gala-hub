import streamlit as st
import pdfplumber
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta, time

# Streamlit Page Setup
st.set_page_config(page_title="Swim Gala Hub", layout="wide")

st.title("🏊‍♂️ Swim Gala Hub")

# Initialize Session State Variables
if "gala_df" not in st.session_state:
    st.session_state["gala_df"] = pd.DataFrame()
if "meet_name" not in st.session_state:
    st.session_state["meet_name"] = ""

# Display Extracted Meet / Event Name Prominently at Top
if st.session_state["meet_name"]:
    st.subheader(f"🏆 {st.session_state['meet_name']}")

# Sidebar Navigation
st.sidebar.title("Navigation")
page_selection = st.sidebar.radio(
    "Select View",
    ["📋 Swimmer Wall Planner", "⏱️ Coach Race Info", "🚩 TM Marshalling Info"]
)

st.sidebar.divider()
st.sidebar.header("⚙️ Gala Schedule & Speed Settings")

# Global Session Start Times
session_start_map = {
    1: st.sidebar.time_input("Session 1 Start", value=time(9, 0)),
    2: st.sidebar.time_input("Session 2 Start", value=time(14, 0))
}

pace_factor = st.sidebar.slider(
    "Heat Timing Speed Factor", 
    min_value=0.8, max_value=1.3, value=1.0, step=0.05,
    help="Adjust if the gala is running faster (<1.0) or slower (>1.0) than standard pace."
)
st.sidebar.caption("💡 **Pace Multiplier:** Recalculates estimated call & race times globally across all views.")

st.sidebar.divider()
st.sidebar.header("Data Source Settings")
club_filter = st.sidebar.text_input("Club Keyword / Filter", placeholder="e.g. Warrington")
input_method = st.sidebar.radio("Choose Input Method", ["Web Link (URL)", "Upload PDF File", "Paste Text / HTML"])

def fetch_url_content(url):
    """Fetches web page content with browser headers."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive'
    }
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response

def extract_meet_name_from_soup(soup):
    """Extracts the overall Meet / Event Name (e.g. BCM Autumn Meet 2026)."""
    if soup.title and soup.title.get_text(strip=True):
        title_text = soup.title.get_text(strip=True)
        if title_text and "sportsystems" not in title_text.lower() and len(title_text) > 3:
            return title_text
    for h in soup.find_all(['h1', 'h2', 'h3']):
        text = h.get_text(strip=True)
        if text and not any(k in text.lower() for k in ['sportsystems', 'session', 'event 10', 'event 20', 'event 30', 'heat number']):
            if len(text) > 3:
                return text
    return None

def is_valid_swimmer_name(name):
    """Validates that extracted text is a real person's name."""
    if not name or len(name) < 2:
        return False
    if not re.search(r'[a-zA-Z]', name):
        return False
    blocked_terms = {'name', 'swimmer', 'aad', 'lane', 'comp.no', 'comp no', 'comp', 'club', 'event', 'heat', 'entry', 'time'}
    if name.lower().strip() in blocked_terms:
        return False
    return True

def estimate_heat_duration_seconds(event_str):
    """Estimates heat duration in seconds based on stroke distance."""
    event_lower = str(event_str).lower()
    if '50m' in event_lower:
        return 90     # ~1.5 mins per heat
    elif '100m' in event_lower:
        return 150    # ~2.5 mins per heat
    elif '200m' in event_lower:
        return 270    # ~4.5 mins per heat
    elif '400m' in event_lower:
        return 480    # ~8 mins per heat
    elif '800m' in event_lower:
        return 840    # ~14 mins per heat
    elif '1500m' in event_lower:
        return 1320   # ~22 mins per heat
    return 180        # Fallback default: 3 mins

def get_event_num(event_str):
    """Helper function to extract numeric event number."""
    m = re.search(r'Event\s+(\d+)', str(event_str), re.IGNORECASE)
    return int(m.group(1)) if m else 9999

def infer_session_number(event_str, current_session=1):
    """Infers session number from explicit session context or event numbers."""
    e_num = get_event_num(event_str)
    if e_num != 9999 and e_num >= 100:
        return e_num // 100
    return current_session

def parse_html_soup(soup, club_keyword):
    """Parses SPORTSYSTEMS HTML start lists extracting Session, Event, Lane, Name, PB."""
    entries = []
    current_event = None
    current_heat = "1"
    current_session = 1
    target_keyword = club_keyword.strip().lower() if club_keyword else ""
    
    for elem in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'div', 'tr']):
        text = elem.get_text(strip=True)
        if not text:
            continue
            
        session_match = re.search(r'Session\s+(\d+)', text, re.IGNORECASE)
        if session_match:
            current_session = int(session_match.group(1))
            
        event_match = re.search(r'(Event\s+\d+.*?)(?=\s+Heat|\n|$)', text, re.IGNORECASE)
        if event_match and elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'div']:
            current_event = event_match.group(1).strip()
            
        heat_match = re.search(r'Heat(?:\s+Number\s*-\s*|\s+)(\d+)', text, re.IGNORECASE)
        if heat_match and elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'div', 'tr']:
            current_heat = heat_match.group(1)
            
        if elem.name == 'tr' and current_event is not None:
            tds = elem.find_all(['td', 'th'])
            cells = [td.get_text(strip=True) for td in tds]
            row_text = " ".join(cells)
            
            if not target_keyword or target_keyword in row_text.lower():
                lane, name, pb_time = None, None, "N/A"
                
                if len(cells) >= 6:
                    lane = cells[0]
                    name = cells[2]
                    pb_time = cells[5]
                elif len(cells) == 5:
                    lane = cells[0]
                    if cells[1].isdigit():
                        name = cells[2]
                        pb_time = cells[4] if target_keyword and target_keyword not in cells[4].lower() else "N/A"
                    else:
                        name = cells[1]
                        pb_time = cells[4]
                elif len(cells) == 4:
                    lane = cells[0]
                    name = cells[1]
                    
                if lane and lane.isdigit() and is_valid_swimmer_name(name):
                    sess_num = infer_session_number(current_event, current_session)
                    entries.append({
                        "Session": sess_num,
                        "Swimmer": name.title(),
                        "Event": current_event,
                        "Heat": int(current_heat) if current_heat.isdigit() else current_heat,
                        "Lane": int(lane),
                        "PB / Entry Time": pb_time,
                        "Achieved Time": "",
                        "Seen Coach": False,
                        "In Marshalling": False
                    })
                    
    return entries

def parse_text_lines(lines, club_keyword):
    """Fallback text parser for PDF uploads or pasted text with Session detection."""
    entries = []
    current_event = None
    current_heat = "1"
    current_session = 1
    target_keyword = club_keyword.strip().lower() if club_keyword else ""
    
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
            
        session_match = re.search(r'Session\s+(\d+)', line_str, re.IGNORECASE)
        if session_match:
            current_session = int(session_match.group(1))
            
        event_match = re.search(r'(Event\s+\d+.*?)(?=\s+Heat|\n|$)', line_str, re.IGNORECASE)
        if event_match:
            current_event = event_match.group(1).strip()
            
        heat_match = re.search(r'Heat(?:\s+Number\s*-\s*|\s+)(\d+)', line_str, re.IGNORECASE)
        if heat_match:
            current_heat = heat_match.group(1)
            
        if current_event is not None and (not target_keyword or target_keyword in line_str.lower()):
            m = re.search(r'^\s*(\d+)\s+(?:(\d+)\s+)?([A-Za-z\s\-\'\.]+?)\s+(\d{1,2})\s+.*?(?:' + (re.escape(club_keyword) if target_keyword else r'[A-Za-z]+') + r')\s*([\d\:\.]+|S/T|NT)?', line_str, re.IGNORECASE)
            if m:
                lane = m.group(1)
                name = m.group(3).strip()
                pb_time = m.group(5) if m.group(5) else "N/A"
                if lane.isdigit() and is_valid_swimmer_name(name):
                    sess_num = infer_session_number(current_event, current_session)
                    entries.append({
                        "Session": sess_num,
                        "Swimmer": name.title(),
                        "Event": current_event,
                        "Heat": int(current_heat) if current_heat.isdigit() else current_heat,
                        "Lane": int(lane),
                        "PB / Entry Time": pb_time,
                        "Achieved Time": "",
                        "Seen Coach": False,
                        "In Marshalling": False
                    })
                
    return entries

def compute_gala_schedule_times(df_input, session_starts, pace):
    """Calculates Coach Time, Marshalling Time, and Est. Race Time across all sessions."""
    if df_input.empty:
        return df_input
        
    calc_df = df_input.copy()
    calc_df["Coach Time"] = ""
    calc_df["Marshalling Time"] = ""
    calc_df["Est. Race Time"] = ""
    
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
            
            try:
                max_heat = int(event_rows["Heat"].max())
            except (ValueError, TypeError):
                max_heat = 1
                
            heat_duration_sec = estimate_heat_duration_seconds(event) * pace
            event_coach_dt = current_event_start_dt - timedelta(minutes=20)
            event_coach_time_str = event_coach_dt.strftime("%H:%M")
            
            for idx, row in event_rows.iterrows():
                try:
                    h_num = int(row["Heat"])
                except (ValueError, TypeError):
                    h_num = 1
                    
                heat_offset_sec = (h_num - 1) * heat_duration_sec
                heat_race_dt = current_event_start_dt + timedelta(seconds=heat_offset_sec)
                heat_marsh_dt = heat_race_dt - timedelta(minutes=10)
                
                calc_df.loc[idx, "Coach Time"] = event_coach_time_str
                calc_df.loc[idx, "Marshalling Time"] = heat_marsh_dt.strftime("%H:%M")
                calc_df.loc[idx, "Est. Race Time"] = heat_race_dt.strftime("%H:%M")
                
            current_event_start_dt += timedelta(seconds=heat_duration_sec * max_heat)
            
    return calc_df

# Fetching Data Logic
parsed_entries = []

if input_method == "Web Link (URL)":
    url_input = st.sidebar.text_input("SPORTSYSTEMS Live URL", placeholder="https://www.example.org.uk/meet_2026/webpages/index.htm")
    if url_input and st.sidebar.button("Fetch & Process Web Link"):
        try:
            visited_urls = set()
            pages_to_scrape = [url_input]
            status_box = st.info("Analyzing SPORTSYSTEMS site structure...")
            
            resp = fetch_url_content(url_input)
            visited_urls.add(url_input)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Extract Meet Title from Main Page
            meet_name = extract_meet_name_from_soup(soup)
            if meet_name:
                st.session_state["meet_name"] = meet_name
            
            frames = soup.find_all(['frame', 'iframe'])
            for frame in frames:
                src = frame.get('src')
                if src:
                    frame_url = urljoin(url_input, src)
                    if frame_url not in visited_urls:
                        pages_to_scrape.append(frame_url)
            
            sub_links = []
            for p_url in list(pages_to_scrape):
                try:
                    p_resp = fetch_url_content(p_url)
                    visited_urls.add(p_url)
                    p_soup = BeautifulSoup(p_resp.text, 'html.parser')
                    
                    if not st.session_state["meet_name"]:
                        m_name = extract_meet_name_from_soup(p_soup)
                        if m_name:
                            st.session_state["meet_name"] = m_name
                            
                    parsed_entries.extend(parse_html_soup(p_soup, club_filter))
                    
                    for a in p_soup.find_all('a', href=True):
                        href = a['href']
                        full_url = urljoin(p_url, href)
                        if urlparse(full_url).netloc == urlparse(url_input).netloc:
                            if full_url not in visited_urls and href.lower().endswith(('.htm', '.html')):
                                if not any(ign in href.lower() for ign in ['menu', 'index', 'header', 'top', 'bottom', 'left']):
                                    sub_links.append(full_url)
                                visited_urls.add(full_url)
                except Exception:
                    continue
            
            if sub_links:
                progress_bar = st.progress(0)
                for i, link in enumerate(sub_links):
                    status_box.info(f"Scanning heat sheet {i+1} of {len(sub_links)}...")
                    try:
                        link_resp = fetch_url_content(link)
                        link_soup = BeautifulSoup(link_resp.text, 'html.parser')
                        parsed_entries.extend(parse_html_soup(link_soup, club_filter))
                    except Exception:
                        continue
                    progress_bar.progress((i + 1) / len(sub_links))
            
            if parsed_entries:
                st.session_state["gala_df"] = pd.DataFrame(parsed_entries).drop_duplicates()
                status_box.success(f"Finished scanning! Loaded {len(st.session_state['gala_df'])} swimmer entries.")
                st.rerun()
            else:
                status_box.warning("Finished scanning, but no entries matching your Club Keyword were found.")
            
        except Exception as e:
            st.error(f"Could not load web page: {e}")

elif input_method == "Upload PDF File":
    uploaded_file = st.sidebar.file_uploader("Upload Heat Sheet PDF", type=["pdf"])
    if uploaded_file:
        lines = []
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    lines.extend(page_text.split("\n"))
        if lines and not st.session_state["meet_name"]:
            for line in lines[:5]:
                clean_line = line.strip()
                if clean_line and not any(k in clean_line.lower() for k in ['session', 'event', 'page', 'sportsystems']):
                    st.session_state["meet_name"] = clean_line
                    break
        parsed_entries = parse_text_lines(lines, club_filter)
        if parsed_entries:
            st.session_state["gala_df"] = pd.DataFrame(parsed_entries).drop_duplicates()

elif input_method == "Paste Text / HTML":
    pasted_text = st.sidebar.text_area("Paste webpage text directly here", height=200)
    if pasted_text:
        lines = pasted_text.split("\n")
        if lines and not st.session_state["meet_name"]:
            for line in lines[:5]:
                clean_line = line.strip()
                if clean_line and not any(k in clean_line.lower() for k in ['session', 'event', 'page', 'sportsystems']):
                    st.session_state["meet_name"] = clean_line
                    break
        parsed_entries = parse_text_lines(lines, club_filter)
        if parsed_entries:
            st.session_state["gala_df"] = pd.DataFrame(parsed_entries).drop_duplicates()

df = st.session_state["gala_df"]

# Compute times across the dataset
if not df.empty:
    df_with_times = compute_gala_schedule_times(df, session_start_map, pace_factor)
else:
    df_with_times = df

# --- VIEW 1: SWIMMER WALL PLANNER ---
if page_selection == "📋 Swimmer Wall Planner":
    st.header("📋 Swimmer A–Z Wall Planner")
    
    if not df_with_times.empty:
        sorted_df = df_with_times.sort_values(by=["Swimmer", "Session", "Event"])
        
        current_swimmer = None
        club_display = f"{club_filter.upper()} " if club_filter.strip() else ""
        header_meet = f" — {st.session_state['meet_name']}" if st.session_state["meet_name"] else ""
        formatted_output = f"## {club_display}GALA SCHEDULE{header_meet.upper()} — SWIMMER A–Z\n\n"
        
        for idx, row in sorted_df.iterrows():
            if row["Swimmer"] != current_swimmer:
                current_swimmer = row["Swimmer"]
                formatted_output += f"\n### 👤 {current_swimmer}\n"
            
            formatted_output += (
                f"* **Session {row['Session']} | {row['Event']}** — "
                f"Heat {row['Heat']}, Lane {row['Lane']} *(PB: {row['PB / Entry Time']})* | "
                f"🚩 **Marshalling:** {row['Marshalling Time']} | "
                f"⏱️ **Est. Race:** {row['Est. Race Time']}\n"
            )
        
        st.markdown(formatted_output)
        
        st.download_button(
            label="📄 Download Printable Schedule (.txt)",
            data=formatted_output,
            file_name="gala_wall_schedule.txt",
            mime="text/plain"
        )
    else:
        st.info("👈 Load gala data from the sidebar to display the Swimmer Wall Planner.")

# --- VIEW 2: COACH RACE INFO ---
elif page_selection == "⏱️ Coach Race Info":
    st.header("⏱️ Coach Race Info (Event Chronological Order)")
    st.markdown("Events listed sequentially by Session for coaches to track PBs and record race times.")
    
    if not df_with_times.empty:
        sessions = sorted(df_with_times["Session"].unique())
        
        for sess in sessions:
            st.subheader(f"📅 Session {sess}")
            sess_df = df_with_times[df_with_times["Session"] == sess]
            events = sorted(sess_df["Event"].unique(), key=get_event_num)
            
            for event in events:
                event_df = sess_df[sess_df["Event"] == event].sort_values(by=["Heat", "Lane"])
                club_label = f"{club_filter} " if club_filter.strip() else ""
                
                with st.expander(f"🏊 {event} ({len(event_df)} {club_label}Swimmers)", expanded=True):
                    display_cols = ["Heat", "Lane", "Swimmer", "PB / Entry Time", "Achieved Time"]
                    
                    edited_event_df = st.data_editor(
                        event_df[display_cols],
                        key=f"editor_coach_s{sess}_{event}",
                        disabled=["Heat", "Lane", "Swimmer", "PB / Entry Time"],
                        hide_index=True,
                        use_container_width=True
                    )
                    
                    for _, edited_row in edited_event_df.iterrows():
                        mask = (
                            (st.session_state["gala_df"]["Session"] == sess) &
                            (st.session_state["gala_df"]["Event"] == event) & 
                            (st.session_state["gala_df"]["Swimmer"] == edited_row["Swimmer"]) &
                            (st.session_state["gala_df"]["Heat"] == edited_row["Heat"])
                        )
                        st.session_state["gala_df"].loc[mask, "Achieved Time"] = edited_row["Achieved Time"]
        
        st.divider()
        st.subheader("📥 Export Recorded Gala Results")
        csv_data = st.session_state["gala_df"].to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📊 Download Coach Results (.csv)",
            data=csv_data,
            file_name="gala_coach_results.csv",
            mime="text/csv"
        )
    else:
        st.info("👈 Load gala data from the sidebar to populate event heat sheets.")

# --- VIEW 3: TM MARSHALLING INFO ---
elif page_selection == "🚩 TM Marshalling Info":
    st.header("🚩 Team Manager Marshalling & Call Tracker")
    st.markdown("Track swimmer movement split by **Session**. All swimmers in an event see **Coach** at event call time (-20 mins); **Marshalling** is calculated per individual **Heat** (-10 mins).")
    
    if not df_with_times.empty:
        sessions = sorted(df_with_times["Session"].unique())
        
        with st.expander("ℹ️ How does Heat Timing Speed Factor work?", expanded=False):
            st.markdown("""
            **Heat Timing Speed Factor** (in the sidebar) lets Team Managers adjust estimated call times live during a session:
            * **`1.0` (Standard Pace):** Assumes the gala runs on normal schedule based on standard event distances.
            * **Below `1.0` (e.g. `0.85` or `0.90` — Running Ahead):** Use when heats turn over quickly. Shortens estimated heat times and brings Coach/Marshalling calls earlier so swimmers don't miss races.
            * **Above `1.0` (e.g. `1.10` or `1.20` — Running Behind):** Use when there are delays or long breaks. Lengthens heat estimates and pushes call times back so swimmers aren't sent to marshalling too early.
            """)

        for sess in sessions:
            st.subheader(f"🚩 Session {sess} (Starts ~{session_start_map.get(sess, time(9,0)).strftime('%H:%M')})")
            
            sess_df = df_with_times[df_with_times["Session"] == sess]
            events = sorted(sess_df["Event"].unique(), key=get_event_num)
            
            for event in events:
                event_df = sess_df[sess_df["Event"] == event].sort_values(by=["Heat", "Lane"])
                
                display_cols = ["Heat", "Lane", "Swimmer", "Coach Time", "Seen Coach", "Marshalling Time", "In Marshalling", "Est. Race Time"]
                
                first_row = event_df.iloc[0] if not event_df.empty else None
                coach_call_str = first_row["Coach Time"] if first_row is not None else "N/A"
                event_start_str = first_row["Est. Race Time"] if first_row is not None else "N/A"
                
                with st.expander(f"🏊 {event} — Event Starts ~{event_start_str} | Coach Call: {coach_call_str} ({len(event_df)} Swimmers)", expanded=True):
                    
                    edited_tm_df = st.data_editor(
                        event_df[display_cols],
                        key=f"editor_tm_s{sess}_{event}",
                        disabled=["Heat", "Lane", "Swimmer", "Coach Time", "Marshalling Time", "Est. Race Time"],
                        column_config={
                            "Seen Coach": st.column_config.CheckboxColumn("Seen Coach?"),
                            "In Marshalling": st.column_config.CheckboxColumn("In Marshalling?")
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                    
                    for _, edited_row in edited_tm_df.iterrows():
                        mask = (
                            (st.session_state["gala_df"]["Session"] == sess) &
                            (st.session_state["gala_df"]["Event"] == event) & 
                            (st.session_state["gala_df"]["Swimmer"] == edited_row["Swimmer"]) &
                            (st.session_state["gala_df"]["Heat"] == edited_row["Heat"])
                        )
                        st.session_state["gala_df"].loc[mask, "Seen Coach"] = edited_row["Seen Coach"]
                        st.session_state["gala_df"].loc[mask, "In Marshalling"] = edited_row["In Marshalling"]

    else:
        st.info("👈 Load gala data from the sidebar to populate the Team Manager tracker.")