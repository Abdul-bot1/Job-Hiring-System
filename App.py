# ============================================================
# SkillLink – On-Demand Technical & General Services Marketplace
# MVP for Streamlit Cloud + Cloudflare
# Target: Pakistan | Commission 25% | Gemini 2.5 Flash
# ============================================================

import streamlit as st
import sqlite3
import os
import random
import uuid
import json
import base64
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
from PIL import Image
import io

# ------------------------------------------------------------
# Gemini (google-genai) – use the latest available model
# ------------------------------------------------------------
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# ------------------------------------------------------------
# Constants & Config
# ------------------------------------------------------------
DB_PATH = "skilllink.db"
COMMISSION_RATE = 0.25
OTP_EXPIRY_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

SERVICE_CATEGORIES = [
    "Electrician", "Plumber", "Carpenter", "Cook",
    "Gardener", "Sweeper", "General Labor"
]

STATUS_FLOW = {
    "REQUESTED": ["ACCEPTED", "REJECTED", "CANCELLED"],
    "ACCEPTED": ["EN_ROUTE", "CANCELLED"],
    "EN_ROUTE": ["IN_PROGRESS", "CANCELLED"],
    "IN_PROGRESS": ["COMPLETED", "CANCELLED"],
    "COMPLETED": [],
    "REJECTED": [],
    "CANCELLED": []
}

# ------------------------------------------------------------
# Database Layer (kept inside app.py as requested)
# ------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE NOT NULL,
        role TEXT,
        name TEXT,
        status TEXT DEFAULT 'ACTIVE',
        created_at TEXT,
        last_login TEXT
    );

    CREATE TABLE IF NOT EXISTS provider_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        full_name TEXT,
        bio TEXT,
        hourly_rate REAL DEFAULT 1000,
        rating REAL DEFAULT 4.5,
        completed_jobs INTEGER DEFAULT 0,
        online INTEGER DEFAULT 0,
        account_status TEXT DEFAULT 'ACTIVE',
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS provider_skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id INTEGER,
        skill TEXT,
        FOREIGN KEY(provider_id) REFERENCES provider_profiles(id)
    );

    CREATE TABLE IF NOT EXISTS provider_locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id INTEGER UNIQUE,
        latitude REAL,
        longitude REAL,
        updated_at TEXT,
        FOREIGN KEY(provider_id) REFERENCES provider_profiles(id)
    );

    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id TEXT UNIQUE,
        customer_id INTEGER,
        provider_id INTEGER,
        service_category TEXT,
        description TEXT,
        scheduled_date TEXT,
        scheduled_time TEXT,
        quoted_amount REAL,
        final_amount REAL,
        status TEXT DEFAULT 'REQUESTED',
        created_at TEXT,
        accepted_at TEXT,
        started_at TEXT,
        completed_at TEXT,
        cancelled_at TEXT,
        FOREIGN KEY(customer_id) REFERENCES users(id),
        FOREIGN KEY(provider_id) REFERENCES provider_profiles(id)
    );

    CREATE TABLE IF NOT EXISTS booking_status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER,
        old_status TEXT,
        new_status TEXT,
        changed_by INTEGER,
        timestamp TEXT
    );

    CREATE TABLE IF NOT EXISTS commission_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER UNIQUE,
        provider_id INTEGER,
        job_amount REAL,
        commission_rate REAL,
        commission_amount REAL,
        status TEXT DEFAULT 'UNPAID',
        created_at TEXT,
        due_at TEXT,
        paid_at TEXT
    );

    CREATE TABLE IF NOT EXISTS payment_receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        commission_id INTEGER,
        provider_id INTEGER,
        payment_method TEXT,
        reference_id TEXT,
        image_path TEXT,
        uploaded_at TEXT,
        UNIQUE(reference_id)
    );

    CREATE TABLE IF NOT EXISTS ai_verification_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        commission_id INTEGER,
        provider_id INTEGER,
        model TEXT,
        timestamp TEXT,
        raw_response TEXT,
        extracted_amount REAL,
        transaction_id TEXT,
        confidence REAL,
        verification_status TEXT,
        error_message TEXT
    );

    CREATE TABLE IF NOT EXISTS ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER UNIQUE,
        customer_id INTEGER,
        provider_id INTEGER,
        rating INTEGER,
        comment TEXT,
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS admin_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        action_type TEXT,
        target_type TEXT,
        target_id INTEGER,
        details TEXT,
        timestamp TEXT
    );
    """)
    conn.commit()

    # Seed demo data only once
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        seed_demo_data(conn)
    conn.close()

def seed_demo_data(conn):
    c = conn.cursor()
    now = datetime.utcnow().isoformat()

    # Demo accounts
    demos = [
        ("03000000001", "customer", "Muhammad Ali"),
        ("03000000002", "provider", "Ali Khan"),
        ("03000000003", "admin", "Admin User"),
        ("03000000004", "provider", "Hamza Ahmed"),
        ("03000000005", "provider", "Usman Raza"),
        ("03000000006", "provider", "Bilal Khan"),
        ("03000000007", "provider", "Ahmed Sheikh"),
    ]
    for phone, role, name in demos:
        c.execute(
            "INSERT INTO users (phone, role, name, status, created_at, last_login) VALUES (?,?,?,?,?,?)",
            (phone, role, name, "ACTIVE", now, now)
        )

    # Provider profiles + locations (Islamabad / Rawalpindi area)
    providers = [
        (2, "Ali Khan", "Professional electrician with 6 years experience.", 1500, 4.9, 127, 1, 33.6844, 73.0479, ["Electrician"]),
        (4, "Hamza Ahmed", "Expert plumber – bathrooms & kitchens.", 1200, 4.8, 93, 1, 33.6900, 73.0550, ["Plumber"]),
        (5, "Usman Raza", "Carpenter & furniture maker.", 1400, 4.5, 41, 1, 33.6780, 73.0400, ["Carpenter"]),
        (6, "Bilal Khan", "Home cook – Pakistani & Chinese.", 800, 4.7, 65, 0, 33.6950, 73.0600, ["Cook"]),
        (7, "Ahmed Sheikh", "Gardener & landscaping.", 900, 4.6, 38, 1, 33.6700, 73.0300, ["Gardener", "Sweeper"]),
    ]
    for uid, name, bio, rate, rating, jobs, online, lat, lon, skills in providers:
        c.execute(
            """INSERT INTO provider_profiles 
               (user_id, full_name, bio, hourly_rate, rating, completed_jobs, online, account_status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (uid, name, bio, rate, rating, jobs, online, "ACTIVE", now)
        )
        pid = c.lastrowid
        c.execute(
            "INSERT INTO provider_locations (provider_id, latitude, longitude, updated_at) VALUES (?,?,?,?)",
            (pid, lat, lon, now)
        )
        for s in skills:
            c.execute("INSERT INTO provider_skills (provider_id, skill) VALUES (?,?)", (pid, s))
    conn.commit()

# ------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------
def generate_transaction_id() -> str:
    return f"SL-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

def format_currency(amount: float) -> str:
    return f"PKR {amount:,.0f}"

def calculate_distance(lat1, lon1, lat2, lon2) -> float:
    return geodesic((lat1, lon1), (lat2, lon2)).km

def validate_image(file) -> Tuple[bool, str]:
    if file is None:
        return False, "No file uploaded"
    if file.size > 5 * 1024 * 1024:
        return False, "File too large (max 5 MB)"
    try:
        img = Image.open(file)
        if img.format not in ("PNG", "JPEG", "WEBP"):
            return False, "Unsupported format"
        return True, ""
    except Exception:
        return False, "Invalid image"

def get_gemini_client():
    if not GEMINI_AVAILABLE:
        return None
    try:
        api_key = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY"))
        if not api_key:
            return None
        return genai.Client(api_key=api_key)
    except Exception:
        return None

def analyze_receipt_with_gemini(image_bytes: bytes, expected_amount: float, commission_id: int) -> Dict:
    """Call Gemini 2.5 Flash (or latest available) and return structured result."""
    client = get_gemini_client()
    if client is None:
        return {
            "valid": False,
            "amount": None,
            "currency": "PKR",
            "transaction_id": None,
            "payment_date": None,
            "payment_time": None,
            "payment_status": None,
            "confidence": 0.0,
            "reason": "Gemini API key not configured or google-genai not installed",
            "raw": ""
        }

    prompt = f"""
You are verifying a payment receipt for a Pakistani service marketplace.
Extract ONLY information that is clearly visible in the image.
Do NOT invent missing information.
Return ONLY valid JSON with these exact keys:
{{
  "valid": true/false,
  "amount": number or null,
  "currency": "PKR" or null,
  "transaction_id": string or null,
  "payment_date": "YYYY-MM-DD" or null,
  "payment_time": "HH:MM" or null,
  "payment_status": "successful" / "failed" / "pending" or null,
  "confidence": 0.0-1.0,
  "reason": "short explanation"
}}
Expected commission amount is approximately {expected_amount} PKR.
If the amount is close (within 5%) mark valid=true.
"""

    try:
        # Use the model name requested in PRD (falls back gracefully)
        model_name = "gemini-2.5-flash"
        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                        types.Part.from_text(text=prompt)
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        raw = response.text
        data = json.loads(raw)
        data["raw"] = raw
        return data
    except Exception as e:
        return {
            "valid": False,
            "amount": None,
            "currency": "PKR",
            "transaction_id": None,
            "payment_date": None,
            "payment_time": None,
            "payment_status": None,
            "confidence": 0.0,
            "reason": f"Gemini error: {str(e)[:120]}",
            "raw": str(e)
        }

def check_and_apply_penalties(provider_id: int):
    """Deterministic penalty engine based on unpaid commissions."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT id, created_at, status FROM commission_records
        WHERE provider_id = ? AND status = 'UNPAID'
        ORDER BY created_at ASC
    """, (provider_id,))
    unpaid = c.fetchall()
    now = datetime.utcnow()
    worst = "ACTIVE"
    for row in unpaid:
        created = datetime.fromisoformat(row["created_at"])
        hours = (now - created).total_seconds() / 3600
        if hours >= 24:
            worst = "BLOCKED"
            break
        elif hours >= 12:
            worst = "WARNING"
    c.execute("UPDATE provider_profiles SET account_status = ? WHERE id = ?", (worst, provider_id))
    conn.commit()
    conn.close()
    return worst

# ------------------------------------------------------------
# Session & Auth helpers
# ------------------------------------------------------------
def init_session():
    defaults = {
        "authenticated": False,
        "user_id": None,
        "phone": None,
        "role": None,
        "page": "dashboard",
        "otp": None,
        "otp_phone": None,
        "otp_created_at": None,
        "otp_attempts": 0,
        "customer_lat": 33.6844,
        "customer_lon": 73.0479,
        "selected_provider": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def login_user(phone: str, role: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE phone = ?", (phone,))
    user = c.fetchone()
    now = datetime.utcnow().isoformat()
    if user is None:
        c.execute(
            "INSERT INTO users (phone, role, name, status, created_at, last_login) VALUES (?,?,?,?,?,?)",
            (phone, role, f"User {phone[-4:]}", "ACTIVE", now, now)
        )
        user_id = c.lastrowid
        if role == "provider":
            c.execute(
                """INSERT INTO provider_profiles 
                   (user_id, full_name, bio, hourly_rate, rating, completed_jobs, online, account_status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (user_id, f"Provider {phone[-4:]}", "New provider", 1000, 4.5, 0, 0, "ACTIVE", now)
            )
    else:
        user_id = user["id"]
        c.execute("UPDATE users SET last_login = ?, role = ? WHERE id = ?", (now, role, user_id))
    conn.commit()
    conn.close()

    st.session_state.authenticated = True
    st.session_state.user_id = user_id
    st.session_state.phone = phone
    st.session_state.role = role
    st.session_state.page = "dashboard"
    st.rerun()

# ------------------------------------------------------------
# CSS – modern SaaS look
# ------------------------------------------------------------
def load_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        padding: 1.2rem 1.5rem;
        border-radius: 16px;
        color: white;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 20px rgba(0,0,0,0.15);
    }
    
    .metric-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 1.1rem 1.3rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        text-align: center;
    }
    .metric-card h3 {
        margin: 0;
        font-size: 1.6rem;
        font-weight: 700;
        color: #0f172a;
    }
    .metric-card p {
        margin: 0.3rem 0 0 0;
        color: #64748b;
        font-size: 0.85rem;
    }
    
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.7rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .badge-active { background: #dcfce7; color: #166534; }
    .badge-warning { background: #fef9c3; color: #854d0e; }
    .badge-blocked { background: #fee2e2; color: #991b1b; }
    .badge-online { background: #dcfce7; color: #166534; }
    .badge-offline { background: #f1f5f9; color: #475569; }
    
    .provider-card {
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.8rem;
        background: white;
        transition: box-shadow 0.2s;
    }
    .provider-card:hover {
        box-shadow: 0 6px 18px rgba(0,0,0,0.08);
    }
    
    .stButton > button {
        border-radius: 10px;
        font-weight: 600;
    }
    
    div[data-testid="stSidebar"] {
        background: #0f172a;
    }
    div[data-testid="stSidebar"] * {
        color: #e2e8f0 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# ------------------------------------------------------------
# UI Components
# ------------------------------------------------------------
def metric_card(title: str, value: str):
    st.markdown(f"""
    <div class="metric-card">
        <h3>{value}</h3>
        <p>{title}</p>
    </div>
    """, unsafe_allow_html=True)

def status_badge(status: str) -> str:
    mapping = {
        "ACTIVE": "badge-active",
        "WARNING": "badge-warning",
        "BLOCKED": "badge-blocked",
        "ONLINE": "badge-online",
        "OFFLINE": "badge-offline",
    }
    cls = mapping.get(status.upper(), "badge-offline")
    return f'<span class="status-badge {cls}">{status}</span>'

# ------------------------------------------------------------
# Authentication Screens
# ------------------------------------------------------------
def render_login():
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0;font-size:1.8rem;">🛠 SkillLink</h1>
        <p style="margin:0.3rem 0 0 0;opacity:0.85;">On-Demand Technical & General Services • Pakistan</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("Login with Phone")
        phone = st.text_input("Phone Number", placeholder="+92 3xx xxx xxxx", value="03000000001")
        phone = phone.strip().replace(" ", "").replace("-", "")
        if phone.startswith("+92"):
            phone = "0" + phone[3:]
        if not phone.startswith("0"):
            phone = "0" + phone

        if st.button("Send OTP", use_container_width=True, type="primary"):
            if len(phone) < 10:
                st.error("Enter a valid Pakistani phone number")
            else:
                otp = random.randint(1000, 9999)
                st.session_state.otp = otp
                st.session_state.otp_phone = phone
                st.session_state.otp_created_at = datetime.utcnow()
                st.session_state.otp_attempts = 0
                st.success(f"OTP sent! (Demo OTP: **{otp}**)")
                st.info("In production the OTP is never shown.")

        if st.session_state.otp is not None:
            st.divider()
            entered = st.text_input("Enter 4-digit OTP", max_chars=4)
            if st.button("Verify OTP", use_container_width=True):
                created = st.session_state.otp_created_at
                if created and (datetime.utcnow() - created).total_seconds() > OTP_EXPIRY_MINUTES * 60:
                    st.error("OTP expired. Request a new one.")
                    st.session_state.otp = None
                elif st.session_state.otp_attempts >= OTP_MAX_ATTEMPTS:
                    st.error("Too many attempts. Request a new OTP.")
                    st.session_state.otp = None
                elif entered == str(st.session_state.otp):
                    st.session_state.otp = None
                    st.session_state.page = "role_select"
                    st.rerun()
                else:
                    st.session_state.otp_attempts += 1
                    st.error(f"Incorrect OTP. Attempts left: {OTP_MAX_ATTEMPTS - st.session_state.otp_attempts}")

def render_role_select():
    st.markdown("""
    <div class="main-header">
        <h2 style="margin:0;">Welcome to SkillLink</h2>
        <p style="margin:0.3rem 0 0 0;opacity:0.85;">Choose your account type</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("👤 Customer\nFind local workers", use_container_width=True, type="primary"):
            login_user(st.session_state.otp_phone, "customer")
    with col2:
        if st.button("🛠 Service Provider\nOffer your services", use_container_width=True, type="primary"):
            login_user(st.session_state.otp_phone, "provider")
    with col3:
        if st.button("🛡 Administrator\nManage platform", use_container_width=True):
            login_user(st.session_state.otp_phone, "admin")

# ------------------------------------------------------------
# CUSTOMER DASHBOARD
# ------------------------------------------------------------
def render_customer():
    with st.sidebar:
        st.markdown("### 🛠 SkillLink")
        st.caption(f"Customer • {st.session_state.phone}")
        page = st.radio(
            "Navigation",
            ["Dashboard", "Find Services", "Map", "My Requests", "Active Jobs",
             "Receipts", "Booking History", "Profile", "Logout"],
            label_visibility="collapsed"
        )
        if page == "Logout":
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    if page == "Dashboard":
        customer_dashboard()
    elif page == "Find Services":
        customer_find_services()
    elif page == "Map":
        customer_map()
    elif page == "My Requests":
        customer_requests()
    elif page == "Active Jobs":
        customer_active_jobs()
    elif page == "Receipts":
        customer_receipts()
    elif page == "Booking History":
        customer_history()
    elif page == "Profile":
        customer_profile()

def customer_dashboard():
    st.markdown('<div class="main-header"><h2 style="margin:0;">Customer Dashboard</h2></div>', unsafe_allow_html=True)
    conn = get_conn()
    c = conn.cursor()
    uid = st.session_state.user_id
    c.execute("SELECT COUNT(*) FROM bookings WHERE customer_id=? AND status NOT IN ('COMPLETED','CANCELLED','REJECTED')", (uid,))
    active = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM bookings WHERE customer_id=? AND status='COMPLETED'", (uid,))
    completed = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(final_amount),0) FROM bookings WHERE customer_id=? AND status='COMPLETED'", (uid,))
    spent = c.fetchone()[0] or 0
    conn.close()

    c1, c2, c3 = st.columns(3)
    with c1: metric_card("Active Jobs", str(active))
    with c2: metric_card("Completed", str(completed))
    with c3: metric_card("Total Spent", format_currency(spent))

    st.info("Use **Find Services** to request a nearby electrician, plumber, cook, etc.")

def customer_find_services():
    st.subheader("Find a Service")
    service = st.selectbox("Service", SERVICE_CATEGORIES)
    radius = st.selectbox("Search Radius (km)", [1, 2, 5, 10, 20], index=2)
    col1, col2 = st.columns(2)
    with col1:
        lat = st.number_input("Latitude", value=st.session_state.customer_lat, format="%.4f")
    with col2:
        lon = st.number_input("Longitude", value=st.session_state.customer_lon, format="%.4f")
    st.session_state.customer_lat = lat
    st.session_state.customer_lon = lon

    if st.button("Use Demo Location (Islamabad)", use_container_width=True):
        st.session_state.customer_lat = 33.6844
        st.session_state.customer_lon = 73.0479
        st.rerun()

    if st.button("Find Workers", type="primary", use_container_width=True):
        providers = get_nearby_providers(lat, lon, radius, service)
        if not providers:
            st.warning("No online providers found in this radius.")
        else:
            for p in providers:
                with st.container():
                    st.markdown(f"""
                    <div class="provider-card">
                        <strong>{p['full_name']}</strong> {status_badge('ONLINE' if p['online'] else 'OFFLINE')}<br>
                        ⭐ {p['rating']:.1f} • {p['distance']:.1f} km • {format_currency(p['hourly_rate'])}/hr • {p['completed_jobs']} jobs
                    </div>
                    """, unsafe_allow_html=True)
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("View Profile", key=f"view_{p['id']}"):
                            st.session_state.selected_provider = p['id']
                            st.session_state.page = "provider_detail"
                            st.rerun()
                    with col_b:
                        if st.button("Request Service", key=f"req_{p['id']}", type="primary"):
                            st.session_state.selected_provider = p['id']
                            st.session_state.request_service = service
                            st.session_state.page = "create_request"
                            st.rerun()

def get_nearby_providers(lat, lon, radius_km, skill=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT pp.*, pl.latitude, pl.longitude
        FROM provider_profiles pp
        JOIN provider_locations pl ON pp.id = pl.provider_id
        WHERE pp.online = 1 AND pp.account_status != 'BLOCKED'
    """)
    rows = c.fetchall()
    results = []
    for r in rows:
        dist = calculate_distance(lat, lon, r["latitude"], r["longitude"])
        if dist <= radius_km:
            # check skill
            c.execute("SELECT skill FROM provider_skills WHERE provider_id=?", (r["id"],))
            skills = [s[0] for s in c.fetchall()]
            if skill and skill not in skills:
                continue
            results.append({
                "id": r["id"],
                "full_name": r["full_name"],
                "rating": r["rating"],
                "hourly_rate": r["hourly_rate"],
                "completed_jobs": r["completed_jobs"],
                "online": r["online"],
                "distance": dist,
                "lat": r["latitude"],
                "lon": r["longitude"],
                "skills": skills,
                "bio": r["bio"]
            })
    results.sort(key=lambda x: (-x["online"], x["distance"], -x["rating"]))
    conn.close()
    return results

def customer_map():
    st.subheader("Nearby Providers Map")
    lat = st.session_state.customer_lat
    lon = st.session_state.customer_lon
    providers = get_nearby_providers(lat, lon, 20)
    m = folium.Map(location=[lat, lon], zoom_start=13)
    folium.Marker([lat, lon], popup="You", icon=folium.Icon(color="blue", icon="home")).add_to(m)
    for p in providers:
        popup = f"""
        <b>{p['full_name']}</b><br>
        ⭐ {p['rating']:.1f}<br>
        {', '.join(p['skills'])}<br>
        {p['distance']:.1f} km • {format_currency(p['hourly_rate'])}/hr
        """
        folium.Marker(
            [p["lat"], p["lon"]],
            popup=popup,
            icon=folium.Icon(color="green" if p["online"] else "gray", icon="wrench")
        ).add_to(m)
    st_folium(m, width=700, height=450)

def customer_create_request():
    pid = st.session_state.get("selected_provider")
    if not pid:
        st.warning("No provider selected")
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM provider_profiles WHERE id=?", (pid,))
    p = c.fetchone()
    conn.close()
    if not p:
        st.error("Provider not found")
        return

    st.subheader(f"Request Service from {p['full_name']}")
    service = st.selectbox("Service", SERVICE_CATEGORIES, index=0)
    description = st.text_area("Description", placeholder="Kitchen socket is not working…")
    col1, col2 = st.columns(2)
    with col1:
        date = st.date_input("Preferred Date")
    with col2:
        time_str = st.time_input("Preferred Time")
    budget = st.number_input("Estimated Budget (PKR)", min_value=500, value=3000, step=100)

    if st.button("Send Request", type="primary"):
        conn = get_conn()
        c = conn.cursor()
        tid = generate_transaction_id()
        now = datetime.utcnow().isoformat()
        c.execute("""
            INSERT INTO bookings 
            (transaction_id, customer_id, provider_id, service_category, description,
             scheduled_date, scheduled_time, quoted_amount, final_amount, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (tid, st.session_state.user_id, pid, service, description,
              str(date), str(time_str), budget, budget, "REQUESTED", now))
        bid = c.lastrowid
        c.execute("""
            INSERT INTO booking_status_history (booking_id, old_status, new_status, changed_by, timestamp)
            VALUES (?,?,?,?,?)
        """, (bid, None, "REQUESTED", st.session_state.user_id, now))
        conn.commit()
        conn.close()
        st.success(f"Request sent! Transaction ID: {tid}")
        st.session_state.page = "My Requests"
        st.rerun()

def customer_requests():
    st.subheader("My Requests")
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT b.*, pp.full_name FROM bookings b
        JOIN provider_profiles pp ON b.provider_id = pp.id
        WHERE b.customer_id = ? ORDER BY b.created_at DESC
    """, (st.session_state.user_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        st.info("No requests yet.")
        return
    for r in rows:
        with st.expander(f"{r['transaction_id']} • {r['service_category']} • {r['status']}"):
            st.write(f"**Provider:** {r['full_name']}")
            st.write(f"**Description:** {r['description']}")
            st.write(f"**Amount:** {format_currency(r['quoted_amount'])}")
            st.write(f"**Created:** {r['created_at'][:16]}")

def customer_active_jobs():
    st.subheader("Active Jobs")
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT b.*, pp.full_name FROM bookings b
        JOIN provider_profiles pp ON b.provider_id = pp.id
        WHERE b.customer_id = ? AND b.status IN ('ACCEPTED','EN_ROUTE','IN_PROGRESS')
        ORDER BY b.created_at DESC
    """, (st.session_state.user_id,))
    rows = c.fetchall()
    conn.close()
    for r in rows:
        st.markdown(f"**{r['transaction_id']}** – {r['full_name']} – `{r['status']}`")

def customer_receipts():
    st.subheader("Digital Receipts")
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT b.*, pp.full_name FROM bookings b
        JOIN provider_profiles pp ON b.provider_id = pp.id
        WHERE b.customer_id = ? AND b.status = 'COMPLETED'
        ORDER BY b.completed_at DESC
    """, (st.session_state.user_id,))
    rows = c.fetchall()
    conn.close()
    for r in rows:
        with st.expander(f"Receipt {r['transaction_id']}"):
            st.markdown(f"""
            **SKILLINK DIGITAL SERVICE RECEIPT**  
            Transaction ID: `{r['transaction_id']}`  
            Booking ID: {r['id']}  
            Customer: You  
            Provider: {r['full_name']}  
            Service: {r['service_category']}  
            Job Amount: {format_currency(r['final_amount'])}  
            Platform Commission (25%): {format_currency(r['final_amount'] * 0.25)}  
            Provider Net: {format_currency(r['final_amount'] * 0.75)}  
            Status: COMPLETED  
            Timestamp: {r['completed_at'][:16] if r['completed_at'] else '-'}
            """)

def customer_history():
    customer_requests()

def customer_profile():
    st.subheader("My Profile")
    st.write(f"**Phone:** {st.session_state.phone}")
    st.write(f"**User ID:** {st.session_state.user_id}")
    new_name = st.text_input("Display Name")
    if st.button("Update Name"):
        conn = get_conn()
        c = conn.cursor()
        c.execute("UPDATE users SET name=? WHERE id=?", (new_name, st.session_state.user_id))
        conn.commit()
        conn.close()
        st.success("Updated")

# ------------------------------------------------------------
# PROVIDER DASHBOARD
# ------------------------------------------------------------
def render_provider():
    # apply penalties on every load
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM provider_profiles WHERE user_id=?", (st.session_state.user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        check_and_apply_penalties(row["id"])

    with st.sidebar:
        st.markdown("### 🛠 SkillLink")
        st.caption(f"Provider • {st.session_state.phone}")
        page = st.radio(
            "Navigation",
            ["Dashboard", "Job Requests", "Active Jobs", "Completed Jobs",
             "Earnings", "Commissions", "Payment Upload", "AI Verification",
             "Account Standing", "Profile", "Logout"],
            label_visibility="collapsed"
        )
        if page == "Logout":
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    if page == "Dashboard":
        provider_dashboard()
    elif page == "Job Requests":
        provider_job_requests()
    elif page == "Active Jobs":
        provider_active_jobs()
    elif page == "Completed Jobs":
        provider_completed()
    elif page == "Earnings":
        provider_earnings()
    elif page == "Commissions":
        provider_commissions()
    elif page == "Payment Upload":
        provider_payment_upload()
    elif page == "AI Verification":
        provider_ai_logs()
    elif page == "Account Standing":
        provider_standing()
    elif page == "Profile":
        provider_profile()

def get_provider_id() -> Optional[int]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM provider_profiles WHERE user_id=?", (st.session_state.user_id,))
    row = c.fetchone()
    conn.close()
    return row["id"] if row else None

def provider_dashboard():
    pid = get_provider_id()
    if not pid:
        st.warning("Complete your profile first.")
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM provider_profiles WHERE id=?", (pid,))
    p = c.fetchone()
    c.execute("SELECT COALESCE(SUM(commission_amount),0) FROM commission_records WHERE provider_id=? AND status='UNPAID'", (pid,))
    due = c.fetchone()[0] or 0
    conn.close()

    st.markdown(f"""
    <div class="main-header">
        <h2 style="margin:0;">Welcome, {p['full_name']}</h2>
        <p style="margin:0.3rem 0 0 0;">
            {status_badge('ONLINE' if p['online'] else 'OFFLINE')} 
            &nbsp; Account: {status_badge(p['account_status'])}
        </p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("Jobs Completed", str(p["completed_jobs"]))
    with c2: metric_card("Rating", f"{p['rating']:.1f}")
    with c3: metric_card("Hourly Rate", format_currency(p["hourly_rate"]))
    with c4: metric_card("Commission Due", format_currency(due))

    # Online toggle
    if p["account_status"] == "BLOCKED":
        st.error("🔴 ACCOUNT BLOCKED – You cannot go online or accept new jobs. Upload payment proof to resolve.")
    else:
        if st.button("Toggle Online / Offline", type="primary"):
            new_val = 0 if p["online"] else 1
            conn = get_conn()
            c = conn.cursor()
            c.execute("UPDATE provider_profiles SET online=? WHERE id=?", (new_val, pid))
            conn.commit()
            conn.close()
            st.rerun()

def provider_job_requests():
    pid = get_provider_id()
    if not pid:
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT account_status FROM provider_profiles WHERE id=?", (pid,))
    status = c.fetchone()["account_status"]
    c.execute("""
        SELECT b.*, u.name as customer_name FROM bookings b
        JOIN users u ON b.customer_id = u.id
        WHERE b.provider_id = ? AND b.status = 'REQUESTED'
        ORDER BY b.created_at DESC
    """, (pid,))
    rows = c.fetchall()
    conn.close()

    if status == "BLOCKED":
        st.error("Account is BLOCKED. You cannot accept new requests.")
        return

    if not rows:
        st.info("No new job requests.")
        return

    for r in rows:
        with st.container():
            st.markdown(f"""
            **NEW JOB REQUEST**  
            Customer: {r['customer_name']}  
            Service: {r['service_category']}  
            Budget: {format_currency(r['quoted_amount'])}  
            Description: {r['description']}
            """)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("ACCEPT", key=f"acc_{r['id']}", type="primary"):
                    update_booking_status(r["id"], "ACCEPTED", st.session_state.user_id)
                    st.rerun()
            with col2:
                if st.button("REJECT", key=f"rej_{r['id']}"):
                    update_booking_status(r["id"], "REJECTED", st.session_state.user_id)
                    st.rerun()

def update_booking_status(booking_id: int, new_status: str, changed_by: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT status, provider_id, final_amount FROM bookings WHERE id=?", (booking_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return
    old = row["status"]
    if new_status not in STATUS_FLOW.get(old, []):
        st.error(f"Invalid transition {old} → {new_status}")
        conn.close()
        return
    now = datetime.utcnow().isoformat()
    extra = ""
    if new_status == "ACCEPTED":
        extra = ", accepted_at=?"
        params = [new_status, now, booking_id]
    elif new_status == "IN_PROGRESS":
        extra = ", started_at=?"
        params = [new_status, now, booking_id]
    elif new_status == "COMPLETED":
        extra = ", completed_at=?"
        params = [new_status, now, booking_id]
    elif new_status == "CANCELLED":
        extra = ", cancelled_at=?"
        params = [new_status, now, booking_id]
    else:
        params = [new_status, booking_id]
        extra = ""

    if extra:
        c.execute(f"UPDATE bookings SET status=? {extra} WHERE id=?", params)
    else:
        c.execute("UPDATE bookings SET status=? WHERE id=?", (new_status, booking_id))

    c.execute("""
        INSERT INTO booking_status_history (booking_id, old_status, new_status, changed_by, timestamp)
        VALUES (?,?,?,?,?)
    """, (booking_id, old, new_status, changed_by, now))

    # Create commission on completion
    if new_status == "COMPLETED":
        amount = row["final_amount"] or 0
        commission = round(amount * COMMISSION_RATE, 2)
        due = (datetime.utcnow() + timedelta(hours=24)).isoformat()
        c.execute("""
            INSERT INTO commission_records 
            (booking_id, provider_id, job_amount, commission_rate, commission_amount, status, created_at, due_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (booking_id, row["provider_id"], amount, COMMISSION_RATE, commission, "UNPAID", now, due))
        # increment completed jobs
        c.execute("UPDATE provider_profiles SET completed_jobs = completed_jobs + 1 WHERE id=?", (row["provider_id"],))

    conn.commit()
    conn.close()

def provider_active_jobs():
    pid = get_provider_id()
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM bookings WHERE provider_id=? AND status IN ('ACCEPTED','EN_ROUTE','IN_PROGRESS')
        ORDER BY created_at DESC
    """, (pid,))
    rows = c.fetchall()
    conn.close()
    for r in rows:
        st.markdown(f"**{r['transaction_id']}** – `{r['status']}` – {r['service_category']}")
        cols = st.columns(4)
        if r["status"] == "ACCEPTED":
            if cols[0].button("Mark EN_ROUTE", key=f"en_{r['id']}"):
                update_booking_status(r["id"], "EN_ROUTE", st.session_state.user_id)
                st.rerun()
        if r["status"] == "EN_ROUTE":
            if cols[1].button("Mark IN_PROGRESS", key=f"ip_{r['id']}"):
                update_booking_status(r["id"], "IN_PROGRESS", st.session_state.user_id)
                st.rerun()
        if r["status"] == "IN_PROGRESS":
            if cols[2].button("Mark COMPLETED", key=f"cp_{r['id']}", type="primary"):
                update_booking_status(r["id"], "COMPLETED", st.session_state.user_id)
                st.success("Job completed. Commission generated.")
                st.rerun()

def provider_completed():
    pid = get_provider_id()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM bookings WHERE provider_id=? AND status='COMPLETED' ORDER BY completed_at DESC", (pid,))
    rows = c.fetchall()
    conn.close()
    for r in rows:
        st.write(f"{r['transaction_id']} – {format_currency(r['final_amount'])} – {r['completed_at'][:16]}")

def provider_earnings():
    pid = get_provider_id()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(final_amount),0) FROM bookings WHERE provider_id=? AND status='COMPLETED'", (pid,))
    gross = c.fetchone()[0] or 0
    c.execute("SELECT COALESCE(SUM(commission_amount),0) FROM commission_records WHERE provider_id=? AND status='PAID'", (pid,))
    paid_comm = c.fetchone()[0] or 0
    conn.close()
    st.metric("Gross Earnings", format_currency(gross))
    st.metric("Commission Paid", format_currency(paid_comm))
    st.metric("Net Earnings", format_currency(gross - paid_comm))

def provider_commissions():
    pid = get_provider_id()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM commission_records WHERE provider_id=? ORDER BY created_at DESC", (pid,))
    rows = c.fetchall()
    conn.close()
    for r in rows:
        st.markdown(f"""
        Booking #{r['booking_id']} • {format_currency(r['commission_amount'])} • 
        **{r['status']}** • Created {r['created_at'][:16]}
        """)

def provider_payment_upload():
    pid = get_provider_id()
    if not pid:
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM commission_records WHERE provider_id=? AND status='UNPAID'", (pid,))
    unpaid = c.fetchall()
    conn.close()

    if not unpaid:
        st.success("No outstanding commissions. Great job!")
        return

    st.subheader("Upload Commission Payment Proof")
    selected = st.selectbox(
        "Select unpaid commission",
        unpaid,
        format_func=lambda x: f"#{x['id']} – {format_currency(x['commission_amount'])} (Booking {x['booking_id']})"
    )
    method = st.selectbox("Payment Method", ["EasyPaisa", "JazzCash", "Bank Transfer"])
    ref = st.text_input("Reference / Transaction ID")
    uploaded = st.file_uploader("Upload Screenshot (PNG/JPG/WEBP, max 5 MB)", type=["png", "jpg", "jpeg", "webp"])

    if st.button("Submit Payment", type="primary"):
        if not ref or not uploaded:
            st.error("Reference ID and screenshot are required.")
            return
        ok, msg = validate_image(uploaded)
        if not ok:
            st.error(msg)
            return

        # Save image
        img_path = UPLOAD_DIR / f"receipt_{selected['id']}_{uuid.uuid4().hex[:8]}.jpg"
        with open(img_path, "wb") as f:
            f.write(uploaded.getvalue())

        # Gemini verification
        with st.spinner("Analyzing payment receipt with Gemini…"):
            result = analyze_receipt_with_gemini(uploaded.getvalue(), selected["commission_amount"], selected["id"])

        # Business rules
        status = "NEEDS_REVIEW"
        if result.get("valid") and result.get("amount") is not None:
            detected = float(result["amount"])
            expected = selected["commission_amount"]
            if abs(detected - expected) / expected <= 0.05:  # 5% tolerance
                # check duplicate transaction
                conn = get_conn()
                c = conn.cursor()
                c.execute("SELECT id FROM payment_receipts WHERE reference_id=?", (result.get("transaction_id") or ref,))
                if c.fetchone():
                    status = "REJECTED"
                    reason = "Duplicate transaction ID"
                else:
                    status = "VERIFIED"
                conn.close()
            else:
                status = "REJECTED"
        else:
            status = "NEEDS_REVIEW"

        # Persist
        conn = get_conn()
        c = conn.cursor()
        now = datetime.utcnow().isoformat()
        try:
            c.execute("""
                INSERT INTO payment_receipts (commission_id, provider_id, payment_method, reference_id, image_path, uploaded_at)
                VALUES (?,?,?,?,?,?)
            """, (selected["id"], pid, method, result.get("transaction_id") or ref, str(img_path), now))
        except sqlite3.IntegrityError:
            st.error("Duplicate transaction ID already exists.")
            conn.close()
            return

        c.execute("""
            INSERT INTO ai_verification_logs
            (commission_id, provider_id, model, timestamp, raw_response, extracted_amount,
             transaction_id, confidence, verification_status, error_message)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            selected["id"], pid, "gemini-2.5-flash", now,
            result.get("raw", ""), result.get("amount"),
            result.get("transaction_id"), result.get("confidence"),
            status, result.get("reason")
        ))

        if status == "VERIFIED":
            c.execute("UPDATE commission_records SET status='PAID', paid_at=? WHERE id=?", (now, selected["id"]))
            c.execute("UPDATE provider_profiles SET account_status='ACTIVE' WHERE id=?", (pid,))
            st.success("✅ Payment VERIFIED by Gemini. Commission marked as PAID.")
        elif status == "REJECTED":
            st.error(f"❌ Payment REJECTED – {result.get('reason', 'Amount mismatch or duplicate')}")
        else:
            st.warning("⚠ Needs admin review.")

        conn.commit()
        conn.close()
        check_and_apply_penalties(pid)
        st.rerun()

def provider_ai_logs():
    pid = get_provider_id()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM ai_verification_logs WHERE provider_id=? ORDER BY timestamp DESC LIMIT 20", (pid,))
    rows = c.fetchall()
    conn.close()
    for r in rows:
        st.markdown(f"""
        **{r['timestamp'][:16]}** – Status: `{r['verification_status']}`  
        Amount: {r['extracted_amount']} • Confidence: {r['confidence']}  
        Reason: {r['error_message'] or '-'}
        """)

def provider_standing():
    pid = get_provider_id()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT account_status FROM provider_profiles WHERE id=?", (pid,))
    status = c.fetchone()["account_status"]
    c.execute("SELECT * FROM commission_records WHERE provider_id=? AND status='UNPAID'", (pid,))
    unpaid = c.fetchall()
    conn.close()
    st.markdown(f"Current status: {status_badge(status)}", unsafe_allow_html=True)
    if unpaid:
        for u in unpaid:
            hours = (datetime.utcnow() - datetime.fromisoformat(u["created_at"])).total_seconds() / 3600
            st.write(f"Unpaid #{u['id']}: {format_currency(u['commission_amount'])} – {hours:.1f} hours old")

def provider_profile():
    pid = get_provider_id()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM provider_profiles WHERE id=?", (pid,))
    p = c.fetchone()
    c.execute("SELECT skill FROM provider_skills WHERE provider_id=?", (pid,))
    skills = [s[0] for s in c.fetchall()]
    conn.close()

    name = st.text_input("Full Name", value=p["full_name"] if p else "")
    bio = st.text_area("Bio", value=p["bio"] if p else "")
    rate = st.number_input("Hourly Rate (PKR)", value=int(p["hourly_rate"]) if p else 1000)
    selected_skills = st.multiselect("Skills", SERVICE_CATEGORIES, default=skills)
    lat = st.number_input("Latitude", value=33.6844, format="%.4f")
    lon = st.number_input("Longitude", value=73.0479, format="%.4f")

    if st.button("Save Profile", type="primary"):
        conn = get_conn()
        c = conn.cursor()
        now = datetime.utcnow().isoformat()
        if p:
            c.execute("""
                UPDATE provider_profiles SET full_name=?, bio=?, hourly_rate=? WHERE id=?
            """, (name, bio, rate, pid))
        else:
            c.execute("""
                INSERT INTO provider_profiles (user_id, full_name, bio, hourly_rate, created_at)
                VALUES (?,?,?,?,?)
            """, (st.session_state.user_id, name, bio, rate, now))
            pid = c.lastrowid
        c.execute("DELETE FROM provider_skills WHERE provider_id=?", (pid,))
        for s in selected_skills:
            c.execute("INSERT INTO provider_skills (provider_id, skill) VALUES (?,?)", (pid, s))
        c.execute("""
            INSERT OR REPLACE INTO provider_locations (provider_id, latitude, longitude, updated_at)
            VALUES (?,?,?,?)
        """, (pid, lat, lon, now))
        conn.commit()
        conn.close()
        st.success("Profile saved")

# ------------------------------------------------------------
# ADMIN DASHBOARD
# ------------------------------------------------------------
def render_admin():
    with st.sidebar:
        st.markdown("### 🛠 SkillLink Admin")
        st.caption(f"Admin • {st.session_state.phone}")
        page = st.radio(
            "Navigation",
            ["Dashboard", "Users", "Providers", "Bookings", "Commissions",
             "Payment Audits", "AI Verification", "Blocked Providers",
             "Admin Logs", "Logout"],
            label_visibility="collapsed"
        )
        if page == "Logout":
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    if page == "Dashboard":
        admin_dashboard()
    elif page == "Users":
        admin_users()
    elif page == "Providers":
        admin_providers()
    elif page == "Bookings":
        admin_bookings()
    elif page == "Commissions":
        admin_commissions()
    elif page == "Payment Audits":
        admin_payment_audits()
    elif page == "AI Verification":
        admin_ai_logs()
    elif page == "Blocked Providers":
        admin_blocked()
    elif page == "Admin Logs":
        admin_logs()

def admin_dashboard():
    st.markdown('<div class="main-header"><h2 style="margin:0;">Admin Dashboard</h2></div>', unsafe_allow_html=True)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM provider_profiles")
    total_prov = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM provider_profiles WHERE online=1")
    online = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM bookings")
    total_book = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM bookings WHERE status='COMPLETED'")
    completed = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(final_amount),0) FROM bookings WHERE status='COMPLETED'")
    volume = c.fetchone()[0] or 0
    c.execute("SELECT COALESCE(SUM(commission_amount),0) FROM commission_records")
    total_comm = c.fetchone()[0] or 0
    c.execute("SELECT COALESCE(SUM(commission_amount),0) FROM commission_records WHERE status='UNPAID'")
    outstanding = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM provider_profiles WHERE account_status='BLOCKED'")
    blocked = c.fetchone()[0]
    conn.close()

    cols = st.columns(4)
    with cols[0]: metric_card("Total Users", str(total_users))
    with cols[1]: metric_card("Providers", str(total_prov))
    with cols[2]: metric_card("Online Now", str(online))
    with cols[3]: metric_card("Blocked", str(blocked))
    cols2 = st.columns(4)
    with cols2[0]: metric_card("Bookings", str(total_book))
    with cols2[1]: metric_card("Completed", str(completed))
    with cols2[2]: metric_card("Marketplace Volume", format_currency(volume))
    with cols2[3]: metric_card("Outstanding Commission", format_currency(outstanding))

def admin_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 100")
    rows = c.fetchall()
    conn.close()
    st.dataframe([dict(r) for r in rows], use_container_width=True)

def admin_providers():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM provider_profiles ORDER BY id")
    rows = c.fetchall()
    conn.close()
    st.dataframe([dict(r) for r in rows], use_container_width=True)

def admin_bookings():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM bookings ORDER BY created_at DESC LIMIT 100")
    rows = c.fetchall()
    conn.close()
    st.dataframe([dict(r) for r in rows], use_container_width=True)

def admin_commissions():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM commission_records ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    st.dataframe([dict(r) for r in rows], use_container_width=True)

def admin_payment_audits():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT pr.*, cr.commission_amount, pp.full_name
        FROM payment_receipts pr
        JOIN commission_records cr ON pr.commission_id = cr.id
        JOIN provider_profiles pp ON pr.provider_id = pp.id
        ORDER BY pr.uploaded_at DESC
    """)
    rows = c.fetchall()
    conn.close()
    for r in rows:
        with st.expander(f"{r['full_name']} – {format_currency(r['commission_amount'])} – {r['uploaded_at'][:16]}"):
            st.write(f"Method: {r['payment_method']} • Ref: {r['reference_id']}")
            if st.button("Manually Approve", key=f"app_{r['id']}"):
                log_admin_action("APPROVE_PAYMENT", "commission", r["commission_id"], f"Manual approve receipt {r['id']}")
                conn = get_conn()
                c = conn.cursor()
                c.execute("UPDATE commission_records SET status='PAID', paid_at=? WHERE id=?",
                          (datetime.utcnow().isoformat(), r["commission_id"]))
                c.execute("UPDATE provider_profiles SET account_status='ACTIVE' WHERE id=?", (r["provider_id"],))
                conn.commit()
                conn.close()
                st.success("Approved")
                st.rerun()

def admin_ai_logs():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM ai_verification_logs ORDER BY timestamp DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    st.dataframe([dict(r) for r in rows], use_container_width=True)

def admin_blocked():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM provider_profiles WHERE account_status='BLOCKED'")
    rows = c.fetchall()
    conn.close()
    for r in rows:
        st.markdown(f"**{r['full_name']}** (ID {r['id']}) – BLOCKED")
        if st.button("Unblock", key=f"unb_{r['id']}", type="primary"):
            log_admin_action("UNBLOCK_PROVIDER", "provider", r["id"], "Manual unblock")
            conn = get_conn()
            c = conn.cursor()
            c.execute("UPDATE provider_profiles SET account_status='ACTIVE' WHERE id=?", (r["id"],))
            conn.commit()
            conn.close()
            st.success("Unblocked")
            st.rerun()

def admin_logs():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM admin_actions ORDER BY timestamp DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    st.dataframe([dict(r) for r in rows], use_container_width=True)

def log_admin_action(action_type, target_type, target_id, details):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO admin_actions (admin_id, action_type, target_type, target_id, details, timestamp)
        VALUES (?,?,?,?,?,?)
    """, (st.session_state.user_id, action_type, target_type, target_id, details, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="SkillLink – On-Demand Services",
        page_icon="🛠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    load_css()
    init_session()
    init_db()

    if not st.session_state.authenticated:
        if st.session_state.get("page") == "role_select":
            render_role_select()
        else:
            render_login()
    else:
        role = st.session_state.role
        if role == "customer":
            # handle special pages
            if st.session_state.get("page") == "create_request":
                customer_create_request()
            else:
                render_customer()
        elif role == "provider":
            render_provider()
        elif role == "admin":
            render_admin()
        else:
            st.error("Unknown role")

if __name__ == "__main__":
    main()
