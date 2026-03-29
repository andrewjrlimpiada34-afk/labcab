import os
import uuid
from datetime import datetime, date, timedelta
from functools import wraps

from bson import ObjectId
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from backend.utils.pdf import build_receipt_pdf
except ImportError:
    from utils.pdf import build_receipt_pdf


mongo_client = None


def get_db():
    global mongo_client
    mongo_url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB", "labcab")
    if mongo_client is None:
        mongo_client = MongoClient(mongo_url)
    return mongo_client[db_name]


def status_badge(total_quantity, available_quantity):
    if available_quantity <= 0:
        return "in_use"
    low_threshold = max(1, int(total_quantity * 0.2))
    if available_quantity <= low_threshold:
        return "low_stock"
    return "available"


def serialize_apparatus(doc):
    total = doc.get("total_quantity", 0)
    available = doc.get("available_quantity", 0)
    return {
        "id": str(doc.get("_id")),
        "name": doc.get("name"),
        "total_quantity": total,
        "available_quantity": available,
        "borrowed_quantity": max(0, total - available),
        "status": status_badge(total, available),
    }


def serialize_user(doc):
    return {
        "id": str(doc.get("_id")),
        "name": doc.get("name"),
        "email": doc.get("email"),
        "role": doc.get("role"),
    }


def serialize_notification(doc):
    return {
        "id": str(doc.get("_id")),
        "user_id": str(doc.get("user_id")),
        "message": doc.get("message"),
        "status": doc.get("status"),
        "date": doc.get("created_at").isoformat(),
    }


def serialize_record(doc, user=None, apparatus=None):
    return {
        "id": str(doc.get("_id")),
        "user_id": str(doc.get("user_id")),
        "user_name": (user or {}).get("name"),
        "apparatus_id": str(doc.get("apparatus_id")),
        "apparatus_name": (apparatus or {}).get("name"),
        "quantity": doc.get("quantity"),
        "borrow_date": doc.get("borrow_date"),
        "due_date": doc.get("due_date"),
        "status": doc.get("status"),
        "transaction_id": doc.get("transaction_id"),
    }


def parse_object_id(value):
    try:
        return ObjectId(value)
    except Exception:
        return None


def create_app():
    base_dir = os.path.dirname(__file__)
    frontend_dir = os.path.abspath(os.path.join(base_dir, "..", "frontend"))
    app = Flask(__name__, static_folder=frontend_dir, static_url_path="")
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "dev-secret-key")
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")

    CORS(app)
    JWTManager(app)

    with app.app_context():
        seed_data()

    def role_required(role):
        def decorator(fn):
            @wraps(fn)
            @jwt_required()
            def wrapper(*args, **kwargs):
                user = current_user()
                if not user or user.get("role") != role:
                    return jsonify({"error": "Unauthorized"}), 403
                return fn(*args, **kwargs)

            return wrapper

        return decorator

    def current_user():
        db = get_db()
        user_id = parse_object_id(get_jwt_identity())
        if not user_id:
            return None
        return db.users.find_one({"_id": user_id})

    def notify_user(user_id, message):
        db = get_db()
        db.notifications.insert_one(
            {
                "user_id": user_id,
                "message": message,
                "status": "unread",
                "created_at": datetime.utcnow(),
            }
        )

    def notify_admins(message):
        db = get_db()
        admins = db.users.find({"role": "admin"})
        notifications = [
            {
                "user_id": admin["_id"],
                "message": message,
                "status": "unread",
                "created_at": datetime.utcnow(),
            }
            for admin in admins
        ]
        if notifications:
            db.notifications.insert_many(notifications)

    def notification_exists(user_id, message):
        db = get_db()
        return (
            db.notifications.find_one({"user_id": user_id, "message": message})
            is not None
        )

    def update_overdue_and_due_soon():
        db = get_db()
        today = date.today()
        due_soon = today + timedelta(days=2)
        records = db.borrow_records.find({"status": {"$in": ["Borrowed"]}})
        for record in records:
            due_date = datetime.fromisoformat(record.get("due_date")).date()
            if due_date < today:
                db.borrow_records.update_one(
                    {"_id": record["_id"]}, {"$set": {"status": "Overdue"}}
                )
                msg = (
                    f"Overdue: {record.get('apparatus_name', 'Apparatus')} "
                    f"(Transaction {record.get('transaction_id')})"
                )
                if not notification_exists(record["user_id"], msg):
                    notify_user(record["user_id"], msg)
            elif due_date <= due_soon:
                msg = (
                    f"Due soon: {record.get('apparatus_name', 'Apparatus')} "
                    f"is due on {record.get('due_date')}"
                )
                if not notification_exists(record["user_id"], msg):
                    notify_user(record["user_id"], msg)

    @app.post("/api/auth/register")
    def register():
        db = get_db()
        data = request.get_json() or {}
        name = data.get("name")
        email = data.get("email")
        password = data.get("password")
        role = data.get("role", "borrower")

        if not name or not email or not password:
            return jsonify({"error": "Missing fields"}), 400

        if db.users.find_one({"email": email}):
            return jsonify({"error": "Email already exists"}), 400

        if role not in ["admin", "borrower"]:
            role = "borrower"

        user = {
            "name": name,
            "email": email,
            "password_hash": generate_password_hash(password),
            "role": role,
        }
        db.users.insert_one(user)
        return jsonify({"message": "Registered successfully"})

    @app.post("/api/auth/login")
    def login():
        db = get_db()
        data = request.get_json() or {}
        email = data.get("email")
        password = data.get("password")

        user = db.users.find_one({"email": email})
        if not user or not check_password_hash(user.get("password_hash"), password):
            return jsonify({"error": "Invalid credentials"}), 401

        token = create_access_token(identity=str(user["_id"]))
        return jsonify({"access_token": token, "user": serialize_user(user)})

    @app.get("/api/apparatus")
    @jwt_required()
    def list_apparatus():
        db = get_db()
        apparatus = db.apparatus.find().sort("name", 1)
        return jsonify([serialize_apparatus(item) for item in apparatus])

    @app.post("/api/apparatus")
    @role_required("admin")
    def create_apparatus():
        db = get_db()
        data = request.get_json() or {}
        name = data.get("name")
        total_quantity = int(data.get("total_quantity", 0))
        available_quantity = int(data.get("available_quantity", total_quantity))

        if not name:
            return jsonify({"error": "Name required"}), 400

        existing = db.apparatus.find_one({"name": name})
        if existing:
            db.apparatus.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "total_quantity": total_quantity,
                        "available_quantity": available_quantity,
                    }
                },
            )
            existing = db.apparatus.find_one({"_id": existing["_id"]})
            return jsonify(serialize_apparatus(existing))

        apparatus = {
            "name": name,
            "total_quantity": total_quantity,
            "available_quantity": available_quantity,
        }
        result = db.apparatus.insert_one(apparatus)
        apparatus["_id"] = result.inserted_id
        return jsonify(serialize_apparatus(apparatus))

    @app.post("/api/borrow-requests")
    @jwt_required()
    def create_borrow_request():
        db = get_db()
        user = current_user()
        data = request.get_json() or {}
        apparatus_id = parse_object_id(data.get("apparatus_id"))
        quantity = int(data.get("quantity", 1))
        due_date_str = data.get("due_date")

        apparatus = db.apparatus.find_one({"_id": apparatus_id}) if apparatus_id else None
        if not apparatus:
            return jsonify({"error": "Invalid apparatus"}), 404

        if quantity <= 0:
            return jsonify({"error": "Quantity must be positive"}), 400

        if not due_date_str:
            return jsonify({"error": "Due date required"}), 400

        due_date = datetime.fromisoformat(due_date_str).date()
        if due_date < date.today():
            return jsonify({"error": "Due date must be today or later"}), 400

        record = {
            "user_id": user["_id"],
            "apparatus_id": apparatus["_id"],
            "quantity": quantity,
            "borrow_date": None,
            "due_date": due_date.isoformat(),
            "status": "Pending",
            "transaction_id": None,
            "apparatus_name": apparatus.get("name"),
        }
        result = db.borrow_records.insert_one(record)
        record["_id"] = result.inserted_id

        notify_admins(
            f"Borrow request: {user.get('name')} requested {quantity} {apparatus.get('name')}."
        )

        return jsonify(serialize_record(record, user, apparatus)), 201

    @app.post("/api/borrow-cart/confirm")
    @jwt_required()
    def confirm_borrow_cart():
        db = get_db()
        user = current_user()
        data = request.get_json() or {}
        hours = int(data.get("hours", 0))
        items = data.get("items", [])

        if hours <= 0:
            return jsonify({"error": "Hours must be positive"}), 400
        if not items:
            return jsonify({"error": "Cart is empty"}), 400

        apparatus_map = {}
        for item in items:
            apparatus_id = parse_object_id(item.get("apparatus_id"))
            quantity = int(item.get("quantity", 0))
            if not apparatus_id or quantity <= 0:
                return jsonify({"error": "Invalid cart item"}), 400
            apparatus = db.apparatus.find_one({"_id": apparatus_id})
            if not apparatus:
                return jsonify({"error": "Invalid apparatus"}), 404
            if apparatus.get("available_quantity", 0) < quantity:
                return jsonify({"error": f"Insufficient stock for {apparatus.get('name')}"}), 400
            apparatus_map[str(apparatus_id)] = (apparatus, quantity)

        due_datetime = datetime.utcnow() + timedelta(hours=hours)
        borrow_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        batch_id = uuid.uuid4().hex[:10].upper()

        records = []
        for index, (apparatus_id_str, payload) in enumerate(apparatus_map.items(), start=1):
            apparatus, quantity = payload
            db.apparatus.update_one(
                {"_id": apparatus["_id"]},
                {"$inc": {"available_quantity": -quantity}},
            )
            record = {
                "user_id": user["_id"],
                "apparatus_id": apparatus["_id"],
                "quantity": quantity,
                "borrow_date": borrow_date,
                "due_date": due_datetime.date().isoformat(),
                "status": "Borrowed",
                "transaction_id": f"{batch_id}-{index}",
                "apparatus_name": apparatus.get("name"),
            }
            records.append(record)

        if records:
            db.borrow_records.insert_many(records)
            notify_user(
                user["_id"],
                f"Borrow confirmed: {len(records)} item(s) due on {due_datetime.date().isoformat()}.",
            )

        return jsonify({"message": "Borrow confirmed", "count": len(records)})

    @app.get("/api/borrow-records")
    @role_required("admin")
    def list_borrow_records():
        db = get_db()
        update_overdue_and_due_soon()

        query = {}
        apparatus_name = request.args.get("apparatus")
        borrower = request.args.get("borrower")
        status = request.args.get("status")

        if status:
            query["status"] = status

        if apparatus_name:
            apparatus_ids = [
                item["_id"]
                for item in db.apparatus.find({"name": {"$regex": apparatus_name, "$options": "i"}})
            ]
            query["apparatus_id"] = {"$in": apparatus_ids}

        if borrower:
            user_ids = [
                item["_id"]
                for item in db.users.find({"name": {"$regex": borrower, "$options": "i"}})
            ]
            query["user_id"] = {"$in": user_ids}

        records = list(db.borrow_records.find(query).sort("_id", -1))

        users = {str(u["_id"]): u for u in db.users.find({"_id": {"$in": [r["user_id"] for r in records]}})}
        apparatus = {str(a["_id"]): a for a in db.apparatus.find({"_id": {"$in": [r["apparatus_id"] for r in records]}})}

        return jsonify(
            [
                serialize_record(
                    record,
                    users.get(str(record["user_id"])),
                    apparatus.get(str(record["apparatus_id"])),
                )
                for record in records
            ]
        )

    @app.get("/api/borrow-records/me")
    @jwt_required()
    def list_my_records():
        db = get_db()
        update_overdue_and_due_soon()
        user = current_user()
        records = list(
            db.borrow_records.find({"user_id": user["_id"]}).sort("_id", -1)
        )
        apparatus = {
            str(a["_id"]): a
            for a in db.apparatus.find({"_id": {"$in": [r["apparatus_id"] for r in records]}})
        }
        return jsonify(
            [
                serialize_record(record, user, apparatus.get(str(record["apparatus_id"])))
                for record in records
            ]
        )

    @app.patch("/api/borrow-requests/<string:record_id>")
    @role_required("admin")
    def approve_or_reject(record_id):
        db = get_db()
        data = request.get_json() or {}
        action = data.get("action")
        record_obj_id = parse_object_id(record_id)
        record = db.borrow_records.find_one({"_id": record_obj_id})
        if not record:
            return jsonify({"error": "Record not found"}), 404
        apparatus = db.apparatus.find_one({"_id": record.get("apparatus_id")})

        if record.get("status") != "Pending":
            return jsonify({"error": "Record already processed"}), 400

        if action == "approve":
            if apparatus.get("available_quantity", 0) < record.get("quantity", 0):
                return jsonify({"error": "Insufficient stock"}), 400
            db.apparatus.update_one(
                {"_id": apparatus["_id"]},
                {"$inc": {"available_quantity": -record.get("quantity", 0)}},
            )
            transaction_id = uuid.uuid4().hex[:12].upper()
            db.borrow_records.update_one(
                {"_id": record["_id"]},
                {
                    "$set": {
                        "status": "Borrowed",
                        "borrow_date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                        "transaction_id": transaction_id,
                    }
                },
            )
            notify_user(
                record["user_id"],
                f"Approved: Your request for {record.get('quantity')} {apparatus.get('name')} was approved.",
            )
        elif action == "reject":
            db.borrow_records.update_one(
                {"_id": record["_id"]}, {"$set": {"status": "Rejected"}}
            )
            notify_user(
                record["user_id"],
                f"Rejected: Your request for {record.get('quantity')} {apparatus.get('name')} was rejected.",
            )
        else:
            return jsonify({"error": "Invalid action"}), 400

        record = db.borrow_records.find_one({"_id": record["_id"]})
        user = db.users.find_one({"_id": record["user_id"]})
        apparatus = db.apparatus.find_one({"_id": record["apparatus_id"]})
        return jsonify(serialize_record(record, user, apparatus))

    @app.patch("/api/borrow-records/<string:record_id>/return")
    @role_required("admin")
    def mark_returned(record_id):
        db = get_db()
        record_obj_id = parse_object_id(record_id)
        record = db.borrow_records.find_one({"_id": record_obj_id})
        if not record:
            return jsonify({"error": "Record not found"}), 404

        if record.get("status") not in ["Borrowed", "Overdue"]:
            return jsonify({"error": "Record not borrowed"}), 400

        db.borrow_records.update_one(
            {"_id": record["_id"]}, {"$set": {"status": "Returned"}}
        )
        db.apparatus.update_one(
            {"_id": record["apparatus_id"]},
            {"$inc": {"available_quantity": record.get("quantity", 0)}},
        )
        notify_user(
            record["user_id"],
            f"Returned: {record.get('apparatus_name')} marked as returned.",
        )
        record = db.borrow_records.find_one({"_id": record["_id"]})
        user = db.users.find_one({"_id": record["user_id"]})
        apparatus = db.apparatus.find_one({"_id": record["apparatus_id"]})
        return jsonify(serialize_record(record, user, apparatus))

    @app.get("/api/notifications")
    @jwt_required()
    def list_notifications():
        db = get_db()
        user = current_user()
        notifications = db.notifications.find({"user_id": user["_id"]}).sort("_id", -1)
        return jsonify([serialize_notification(note) for note in notifications])

    @app.patch("/api/notifications/<string:note_id>/read")
    @jwt_required()
    def mark_notification_read(note_id):
        db = get_db()
        user = current_user()
        note_obj_id = parse_object_id(note_id)
        note = db.notifications.find_one({"_id": note_obj_id})
        if not note:
            return jsonify({"error": "Notification not found"}), 404
        if note.get("user_id") != user["_id"]:
            return jsonify({"error": "Unauthorized"}), 403
        db.notifications.update_one({"_id": note_obj_id}, {"$set": {"status": "read"}})
        note = db.notifications.find_one({"_id": note_obj_id})
        return jsonify(serialize_notification(note))

    @app.get("/api/borrow-records/<string:record_id>/receipt")
    @jwt_required()
    def download_receipt(record_id):
        db = get_db()
        user = current_user()
        record_obj_id = parse_object_id(record_id)
        record = db.borrow_records.find_one({"_id": record_obj_id})
        if not record:
            return jsonify({"error": "Record not found"}), 404
        if user.get("role") != "admin" and record.get("user_id") != user.get("_id"):
            return jsonify({"error": "Unauthorized"}), 403
        if record.get("status") not in ["Borrowed", "Returned", "Overdue"]:
            return jsonify({"error": "Receipt unavailable"}), 400

        apparatus = db.apparatus.find_one({"_id": record.get("apparatus_id")})
        record_user = db.users.find_one({"_id": record.get("user_id")})
        receipt_buffer = build_receipt_pdf(record, record_user, apparatus)
        filename = f"labcab_receipt_{record.get('transaction_id')}.pdf"
        return send_file(
            receipt_buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    @app.get("/api/dashboard/summary")
    @role_required("admin")
    def dashboard_summary():
        db = get_db()
        update_overdue_and_due_soon()
        total_apparatus = sum(item.get("total_quantity", 0) for item in db.apparatus.find())
        available_inventory = sum(
            item.get("available_quantity", 0) for item in db.apparatus.find()
        )
        total_borrowed = sum(
            record.get("quantity", 0)
            for record in db.borrow_records.find({"status": {"$in": ["Borrowed", "Overdue"]}})
        )
        overdue_items = db.borrow_records.count_documents({"status": "Overdue"})

        return jsonify(
            {
                "total_apparatus": total_apparatus,
                "total_borrowed": total_borrowed,
                "overdue_items": overdue_items,
                "available_inventory": available_inventory,
            }
        )

    @app.get("/api/hero-images")
    @jwt_required()
    def list_hero_images():
        db = get_db()
        images = db.hero_images.find()
        result = {item.get("page"): item.get("image_data") for item in images}
        return jsonify(result)

    @app.post("/api/hero-images")
    @role_required("admin")
    def upload_hero_image():
        db = get_db()
        data = request.get_json() or {}
        page = data.get("page")
        image_data = data.get("image_data")
        if not page or not image_data:
            return jsonify({"error": "Missing fields"}), 400
        db.hero_images.update_one(
            {"page": page},
            {"$set": {"image_data": image_data, "uploaded_at": datetime.utcnow()}},
            upsert=True,
        )
        return jsonify({"message": "Hero image updated"})

    @app.get("/")
    def serve_index():
        return app.send_static_file("index.html")

    return app


def seed_data():
    db = get_db()
    if db.users.count_documents({}) > 0:
        return

    admin = {
        "name": "Admin User",
        "email": "admin@labcab.local",
        "password_hash": generate_password_hash("admin123"),
        "role": "admin",
    }
    borrower = {
        "name": "Student Borrower",
        "email": "student@labcab.local",
        "password_hash": generate_password_hash("student123"),
        "role": "borrower",
    }

    db.users.insert_many([admin, borrower])

    apparatus_items = [
        {"name": "Beaker", "total_quantity": 20, "available_quantity": 16},
        {"name": "Erlenmeyer Flask", "total_quantity": 15, "available_quantity": 10},
        {"name": "Test Tubes", "total_quantity": 50, "available_quantity": 50},
        {"name": "Stirring Rods", "total_quantity": 30, "available_quantity": 25},
        {"name": "Funnels", "total_quantity": 12, "available_quantity": 8},
    ]
    db.apparatus.insert_many(apparatus_items)


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
