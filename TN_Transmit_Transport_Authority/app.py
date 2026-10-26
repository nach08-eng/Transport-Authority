from flask import Flask, render_template, request, jsonify
import sqlite3, os, json
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "authority.db"
app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            vehicle_id TEXT NOT NULL DEFAULT 'UNKNOWN',
            route TEXT NOT NULL DEFAULT 'Unknown route',
            stop_name TEXT NOT NULL DEFAULT 'Unknown location',
            event_type TEXT NOT NULL DEFAULT 'crowd',
            severity TEXT NOT NULL DEFAULT 'medium',
            occupancy INTEGER,
            capacity INTEGER,
            message TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'driver',
            status TEXT NOT NULL DEFAULT 'NEW',
            created_at TEXT NOT NULL,
            acknowledged_at TEXT,
            resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id TEXT UNIQUE NOT NULL,
            route TEXT NOT NULL DEFAULT 'Unassigned',
            status TEXT NOT NULL DEFAULT 'AVAILABLE',
            driver_name TEXT NOT NULL DEFAULT '',
            last_location TEXT NOT NULL DEFAULT 'Depot',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER,
            vehicle_id TEXT NOT NULL,
            route TEXT NOT NULL,
            assigned_to TEXT NOT NULL DEFAULT '',
            eta_minutes INTEGER NOT NULL DEFAULT 10,
            status TEXT NOT NULL DEFAULT 'ASSIGNED',
            created_at TEXT NOT NULL,
            FOREIGN KEY(alert_id) REFERENCES alerts(id)
        );
        """)
        count = con.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
        if count == 0:
            con.executemany("""INSERT INTO vehicles(vehicle_id,route,status,driver_name,last_location,updated_at)
                VALUES(?,?,?,?,?,?)""", [
                ("TN-RESERVE-101", "Standby", "AVAILABLE", "Standby Driver A", "Central Depot", now_iso()),
                ("TN-RESERVE-102", "Standby", "AVAILABLE", "Standby Driver B", "North Depot", now_iso()),
                ("TN-RESERVE-103", "Standby", "AVAILABLE", "Standby Driver C", "South Depot", now_iso()),
                ("TN-BUS-204", "Route 21G", "ON_ROUTE", "Driver Demo", "Anna Nagar", now_iso()),
            ])

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/dashboard")
def dashboard():
    with db() as con:
        alerts = [dict(r) for r in con.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 100")]
        vehicles = [dict(r) for r in con.execute("SELECT * FROM vehicles ORDER BY vehicle_id")]
        allocations = [dict(r) for r in con.execute("""
            SELECT a.*, al.stop_name, al.event_type FROM allocations a
            LEFT JOIN alerts al ON al.id=a.alert_id ORDER BY a.id DESC LIMIT 50
        """)]
        totals = {
            "active_alerts": con.execute("SELECT COUNT(*) FROM alerts WHERE status != 'RESOLVED'").fetchone()[0],
            "emergencies": con.execute("SELECT COUNT(*) FROM alerts WHERE event_type IN ('medical_emergency','driver_injured','safety_threat') AND status != 'RESOLVED'").fetchone()[0],
            "available_buses": con.execute("SELECT COUNT(*) FROM vehicles WHERE status='AVAILABLE'").fetchone()[0],
            "crowd_events": con.execute("SELECT COUNT(*) FROM alerts WHERE event_type IN ('crowd','overcrowding','congestion')").fetchone()[0],
        }
        # Group crowd events by hour from local ISO timestamp; malformed values safely skipped.
        rows = con.execute("SELECT created_at FROM alerts WHERE event_type IN ('crowd','overcrowding','congestion')").fetchall()
        hours = [0] * 24
        for row in rows:
            try:
                h = datetime.fromisoformat(row["created_at"]).hour
                hours[h] += 1
            except Exception:
                pass
        # recurring locations
        hotspots = [dict(r) for r in con.execute("""
            SELECT stop_name, route, COUNT(*) AS events,
                   MAX(created_at) AS last_seen
            FROM alerts WHERE event_type IN ('crowd','overcrowding','congestion')
            GROUP BY stop_name, route ORDER BY events DESC LIMIT 8
        """)]
    return jsonify({"alerts": alerts, "vehicles": vehicles, "allocations": allocations,
                    "totals": totals, "hourly": hours, "hotspots": hotspots})

@app.post("/api/alerts")
def receive_alert():
    data = request.get_json(silent=True) or request.form.to_dict()
    vehicle_id = str(data.get("vehicle_id") or data.get("bus_id") or "UNKNOWN")[:80]
    event_type = str(data.get("event_type") or "crowd").lower()[:50]
    allowed = {"crowd", "overcrowding", "congestion", "medical_emergency", "driver_injured",
               "vehicle_breakdown", "safety_threat", "door_obstruction", "other"}
    if event_type not in allowed:
        event_type = "other"
    severity = str(data.get("severity") or ("critical" if event_type in {"medical_emergency","driver_injured","safety_threat"} else "high" if event_type in {"overcrowding","congestion","door_obstruction"} else "medium")).lower()
    if severity not in {"low","medium","high","critical"}:
        severity = "medium"
    try: occupancy = int(data.get("occupancy")) if data.get("occupancy") not in (None, "") else None
    except (ValueError, TypeError): occupancy = None
    try: capacity = int(data.get("capacity") or data.get("maximum_capacity")) if data.get("capacity") or data.get("maximum_capacity") else None
    except (ValueError, TypeError): capacity = None
    created = str(data.get("timestamp") or now_iso())[:80]
    with db() as con:
        cur = con.execute("""INSERT INTO alerts(event_id,vehicle_id,route,stop_name,event_type,severity,occupancy,capacity,message,source,status,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
            str(data.get("event_id") or "")[:100], vehicle_id,
            str(data.get("route") or "Unknown route")[:100],
            str(data.get("stop_name") or data.get("location") or "Unknown location")[:160],
            event_type, severity, occupancy, capacity,
            str(data.get("message") or data.get("details") or "")[:1000],
            str(data.get("source") or "bus_system")[:40], "NEW", created))
        alert_id = cur.lastrowid
    return jsonify({"ok": True, "alert_id": alert_id, "status": "NEW", "received_at": now_iso()}), 201

@app.post("/api/driver-report")
def driver_report():
    data = request.get_json(silent=True) or {}
    data["source"] = "driver"
    if not data.get("event_type"):
        data["event_type"] = "crowd"
    # Reuse same validation/insertion pathway without making an internal HTTP request.
    with app.test_request_context(json=data):
        return receive_alert()

@app.post("/api/alerts/<int:alert_id>/status")
def alert_status(alert_id):
    data = request.get_json(silent=True) or {}
    status = str(data.get("status") or "").upper()
    if status not in {"ACKNOWLEDGED", "RESOLVED"}:
        return jsonify({"ok": False, "error": "status must be ACKNOWLEDGED or RESOLVED"}), 400
    with db() as con:
        row = con.execute("SELECT id FROM alerts WHERE id=?", (alert_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Alert not found"}), 404
        if status == "ACKNOWLEDGED":
            con.execute("UPDATE alerts SET status=?, acknowledged_at=? WHERE id=?", (status, now_iso(), alert_id))
        else:
            con.execute("UPDATE alerts SET status=?, resolved_at=? WHERE id=?", (status, now_iso(), alert_id))
    return jsonify({"ok": True, "id": alert_id, "status": status})

@app.delete("/api/alerts/<int:alert_id>")
def delete_alert(alert_id):
    with db() as con:
        cur = con.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
    return jsonify({"ok": cur.rowcount > 0})

@app.delete("/api/alerts")
def clear_alerts():
    with db() as con:
        con.execute("DELETE FROM alerts")
    return jsonify({"ok": True})

@app.post("/api/vehicles")
def add_vehicle():
    data = request.get_json(silent=True) or {}
    vehicle_id = str(data.get("vehicle_id") or "").strip()[:80]
    if not vehicle_id:
        return jsonify({"ok": False, "error": "vehicle_id is required"}), 400
    with db() as con:
        try:
            con.execute("""INSERT INTO vehicles(vehicle_id,route,status,driver_name,last_location,updated_at)
              VALUES(?,?,?,?,?,?)""", (vehicle_id, str(data.get("route") or "Standby"),
              str(data.get("status") or "AVAILABLE").upper(), str(data.get("driver_name") or ""),
              str(data.get("last_location") or "Depot"), now_iso()))
        except sqlite3.IntegrityError:
            return jsonify({"ok": False, "error": "Vehicle ID already exists"}), 409
    return jsonify({"ok": True}), 201

@app.post("/api/allocations")
def allocate_bus():
    data = request.get_json(silent=True) or {}
    vehicle_id = str(data.get("vehicle_id") or "")
    try: alert_id = int(data.get("alert_id")) if data.get("alert_id") else None
    except (ValueError, TypeError): alert_id = None
    try: eta = max(0, min(240, int(data.get("eta_minutes") or 10)))
    except (ValueError, TypeError): eta = 10
    with db() as con:
        vehicle = con.execute("SELECT * FROM vehicles WHERE vehicle_id=?", (vehicle_id,)).fetchone()
        if not vehicle:
            return jsonify({"ok": False, "error": "Vehicle not found"}), 404
        if vehicle["status"] != "AVAILABLE":
            return jsonify({"ok": False, "error": "This bus is not marked AVAILABLE"}), 409
        alert = con.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone() if alert_id else None
        route = str(data.get("route") or (alert["route"] if alert else vehicle["route"]))
        cur = con.execute("""INSERT INTO allocations(alert_id,vehicle_id,route,assigned_to,eta_minutes,status,created_at)
          VALUES(?,?,?,?,?,?,?)""", (alert_id, vehicle_id, route, str(data.get("assigned_to") or "Control Room"),
          eta, "ASSIGNED", now_iso()))
        con.execute("UPDATE vehicles SET status='ALLOCATED', route=?, updated_at=? WHERE vehicle_id=?", (route, now_iso(), vehicle_id))
        allocation_id = cur.lastrowid
    return jsonify({"ok": True, "allocation_id": allocation_id, "vehicle_id": vehicle_id, "route": route}), 201

@app.post("/api/allocations/<int:allocation_id>/status")
def allocation_status(allocation_id):
    data = request.get_json(silent=True) or {}
    status = str(data.get("status") or "").upper()
    if status not in {"EN_ROUTE", "ARRIVED", "CANCELLED", "COMPLETED"}:
        return jsonify({"ok": False, "error": "Unsupported allocation status"}), 400
    with db() as con:
        row = con.execute("SELECT vehicle_id FROM allocations WHERE id=?", (allocation_id,)).fetchone()
        if not row: return jsonify({"ok": False, "error": "Allocation not found"}), 404
        con.execute("UPDATE allocations SET status=? WHERE id=?", (status, allocation_id))
        if status in {"CANCELLED", "COMPLETED"}:
            con.execute("UPDATE vehicles SET status='AVAILABLE', updated_at=? WHERE vehicle_id=?", (now_iso(), row["vehicle_id"]))
        else:
            con.execute("UPDATE vehicles SET status='ALLOCATED', updated_at=? WHERE vehicle_id=?", (now_iso(), row["vehicle_id"]))
    return jsonify({"ok": True, "status": status})

@app.delete("/api/vehicles/<path:vehicle_id>")
def delete_vehicle(vehicle_id):
    with db() as con:
        cur = con.execute("DELETE FROM vehicles WHERE vehicle_id=?", (vehicle_id,))
    return jsonify({"ok": cur.rowcount > 0})

@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "TN Transmit Transport Authority", "time": now_iso()})

init_db()
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
