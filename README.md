# 🌌 BrightHaven — Ultra Pro Max Cloud IoT Platform

**BrightHaven** is a premium, high-performance Smart Home Automation System designed for maximum speed, security, and stability. Built on a modular Flask architecture and powered by Firebase Real-time Database, it offers a seamless interface for controlling ESP32/ESP8266 devices globally.

---

## ✨ Key Features (Ultra Pro Max Edition)

- **⚡ Zero-Latency UI**: Optimized with `sessionStorage` to ensure brand loaders only appear once per session.
- **🛡️ LIFO Request Handling**: Advanced `exclusiveFetch` logic prevents race conditions by aborting older overlapping requests.
- **📊 Real-time Monitoring**: Live device status via SSE (Server-Sent Events) and hardware monitoring dashboards.
- **🔐 Enterprise Security**: Firebase Auth integration with RBAC (Role-Based Access Control) for Admins and Super Admins.
- **💾 System Resilience**: Built-in Backup & Restore functionality for effortless configuration management.
- **🎨 Premium Aesthetics**: Modern dark glassmorphism design with animated mesh gradients and micro-animations.

---

## 📁 Optimized Project Structure

The project has been refactored for a "Clean Root" architecture:

```text
brighthaven/
├── app/                        # Main Application Package
│   ├── core/                   # Hardware, MQTT, Firebase & Timer Engines
│   ├── routes/                 # Modular Blueprints (Public, User, Admin, Super)
│   ├── static/                 # CSS (Tailored), JS (Exclusive Fetch), Images
│   └── templates/              # Jinja2 Templates (Modularized)
├── run.py                      # Production-ready Entry Point
├── run.sh                      # Optimized Launcher (Auto-Env & Logging)
├── requirements.txt            # System Dependencies
├── firebase_key.json           # Service Credentials
└── README.md                   # You are here
```

> **Note:** Configuration files (`.env`, `.gitignore`, `Dockerfile`) and the virtual environment (`.venv`) are stored in the parent directory to keep the workspace clutter-free.

---

## 🚀 Quick Start

### 1. Requirements
Ensure you have Python 3.9+ installed.
```bash
pip install -r requirements.txt
```

### 2. Configuration
Ensure your `.env` file is present in the parent directory with the following:
```env
FLASK_SECRET_KEY=your_secure_key
FIREBASE_PROJECT_ID=your_project_id
# MQTT & Blynk credentials...
```

### 3. Launching
Use the optimized launcher to handle dependencies and environment loading:
```bash
chmod +x run.sh
./run.sh
```
Open: `http://127.0.0.1:5000`

---

## 🔌 Hardware Integration

BrightHaven supports any ESP32/ESP8266 board via **Blynk** or **MQTT**.

| Property | Description |
|----------|-------------|
| **Blynk** | Cloud-sync for virtual pins and mobile app fallback. |
| **MQTT**  | Local/Edge low-latency control via TLS. |
| **GPIO**  | Native Raspberry Pi pin control (Active-Low relays). |

**Main Define Codes:**
- **Blynk Token**: Board-specific authentication.
- **Template ID**: Blynk 2.0 template identification.
- **Template Name**: Human-readable device identity.

---

## 🛠️ Administration

- **User Panel**: Room-by-room control, scenes, and notification center.
- **Admin Panel**: User management, system logs, and detailed reports.
- **Super Admin**: Hardware board registration, room creation, and database tools.

---

*BrightHaven © 2026 — Designed for the Future of Smart Living by Maulin K Patel*
