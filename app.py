import os
import secrets
import sqlite3
from datetime import date, datetime
from functools import wraps
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "foodshare.db")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-development-secret"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,  # Set True when deployed behind HTTPS.
)

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    with open(os.path.join(BASE_DIR, "schema.sql"), "r", encoding="utf-8") as f:
        db.executescript(f.read())
    db.commit()

def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]

app.jinja_env.globals["csrf_token"] = csrf_token

@app.before_request
def protect_post_requests():
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf_token", "")):
            abort(400, description="Invalid CSRF token.")

@app.context_processor
def inject_user():
    user = None
    if session.get("user_id"):
        user = get_db().execute(
            "SELECT id, name, email FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
    return {"current_user": user, "today": date.today().isoformat()}

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def validate_item_form(form):
    name = form.get("name", "").strip()
    category = form.get("category", "").strip()
    unit = form.get("unit", "").strip()
    location = form.get("location", "").strip()
    notes = form.get("notes", "").strip()
    expiry = form.get("expiry_date", "").strip()
    try:
        quantity = float(form.get("quantity", ""))
        if quantity <= 0:
            raise ValueError
    except ValueError:
        return None, "Quantity must be a positive number."
    try:
        datetime.strptime(expiry, "%Y-%m-%d")
    except ValueError:
        return None, "Please provide a valid expiry date."
    if not name or not unit or not expiry:
        return None, "Name, unit and expiry date are required."
    if len(name) > 100 or len(category) > 60 or len(unit) > 20 or len(location) > 100 or len(notes) > 500:
        return None, "One or more fields are too long."
    return {
        "name": name, "category": category, "quantity": quantity, "unit": unit,
        "expiry_date": expiry, "location": location, "notes": notes
    }, None

@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    db = get_db()
    shared = db.execute("""
        SELECT fs.*, u.name AS owner_name
        FROM food_shares fs
        JOIN users u ON u.id = fs.owner_id
        WHERE fs.status = 'available' AND fs.expiry_date >= date('now')
        ORDER BY fs.expiry_date ASC
        LIMIT 6
    """).fetchall()
    return render_template("index.html", shared=shared)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Name, valid email and a password of at least 8 characters are required.", "danger")
            return render_template("register.html")
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Please provide a valid email address.", "danger")
            return render_template("register.html")
        db = get_db()
        try:
            db.execute(
                "INSERT INTO users(name,email,password_hash) VALUES(?,?,?)",
                (name, email, generate_password_hash(password, method="scrypt"))
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("That email is already registered.", "warning")
            return render_template("register.html")
        flash("Account created. Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    uid = session["user_id"]
    items = db.execute("""
        SELECT *,
          CASE
            WHEN expiry_date < date('now') THEN 'Expired'
            WHEN expiry_date <= date('now','+3 day') THEN 'Urgent'
            WHEN expiry_date <= date('now','+7 day') THEN 'Soon'
            ELSE 'Fresh'
          END AS expiry_status,
          CAST(julianday(expiry_date) - julianday(date('now')) AS INTEGER) AS days_left
        FROM inventory_items
        WHERE owner_id = ?
        ORDER BY expiry_date ASC
    """, (uid,)).fetchall()
    stats = db.execute("""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN expiry_date < date('now') THEN 1 ELSE 0 END) AS expired,
          SUM(CASE WHEN expiry_date BETWEEN date('now') AND date('now','+3 day') THEN 1 ELSE 0 END) AS urgent,
          SUM(CASE WHEN expiry_date >= date('now') THEN 1 ELSE 0 END) AS active
        FROM inventory_items WHERE owner_id = ?
    """, (uid,)).fetchone()
    shares = db.execute("""
        SELECT * FROM food_shares WHERE owner_id = ? ORDER BY expiry_date ASC
    """, (uid,)).fetchall()
    return render_template("dashboard.html", items=items, stats=stats, shares=shares)

@app.route("/inventory/add", methods=["GET", "POST"])
@login_required
def add_item():
    if request.method == "POST":
        data, error = validate_item_form(request.form)
        if error:
            flash(error, "danger")
            return render_template("item_form.html", item=None, action="Add")
        db = get_db()
        db.execute("""
            INSERT INTO inventory_items(owner_id,name,category,quantity,unit,expiry_date,location,notes)
            VALUES(?,?,?,?,?,?,?,?)
        """, (session["user_id"], data["name"], data["category"], data["quantity"], data["unit"],
              data["expiry_date"], data["location"], data["notes"]))
        db.commit()
        flash("Food item added to inventory.", "success")
        return redirect(url_for("dashboard"))
    return render_template("item_form.html", item=None, action="Add")

@app.route("/inventory/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_item(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM inventory_items WHERE id=? AND owner_id=?",
                      (item_id, session["user_id"])).fetchone()
    if not item:
        abort(404)
    if request.method == "POST":
        data, error = validate_item_form(request.form)
        if error:
            flash(error, "danger")
            return render_template("item_form.html", item=item, action="Edit")
        db.execute("""
            UPDATE inventory_items
            SET name=?, category=?, quantity=?, unit=?, expiry_date=?, location=?, notes=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND owner_id=?
        """, (data["name"], data["category"], data["quantity"], data["unit"], data["expiry_date"],
              data["location"], data["notes"], item_id, session["user_id"]))
        db.commit()
        flash("Inventory item updated.", "success")
        return redirect(url_for("dashboard"))
    return render_template("item_form.html", item=item, action="Edit")

@app.post("/inventory/<int:item_id>/delete")
@login_required
def delete_item(item_id):
    db = get_db()
    db.execute("DELETE FROM inventory_items WHERE id=? AND owner_id=?",
               (item_id, session["user_id"]))
    db.commit()
    flash("Inventory item deleted.", "success")
    return redirect(url_for("dashboard"))

@app.post("/share/<int:item_id>")
@login_required
def create_share(item_id):
    db = get_db()
    item = db.execute("""
        SELECT * FROM inventory_items WHERE id=? AND owner_id=?
    """, (item_id, session["user_id"])).fetchone()
    if not item:
        abort(404)
    if item["expiry_date"] < date.today().isoformat():
        flash("Expired food cannot be listed for sharing.", "danger")
        return redirect(url_for("dashboard"))
    existing = db.execute(
        "SELECT id FROM food_shares WHERE inventory_id=? AND status='available'", (item_id,)
    ).fetchone()
    if existing:
        flash("This item is already listed for sharing.", "info")
        return redirect(url_for("dashboard"))
    db.execute("""
        INSERT INTO food_shares(inventory_id,owner_id,name,quantity,unit,expiry_date,location,notes)
        VALUES(?,?,?,?,?,?,?,?)
    """, (item_id, item["owner_id"], item["name"], item["quantity"], item["unit"],
          item["expiry_date"], item["location"], item["notes"]))
    db.commit()
    flash("Food listed for community sharing.", "success")
    return redirect(url_for("dashboard"))

@app.route("/community")
@login_required
def community():
    shares = get_db().execute("""
        SELECT fs.*, u.name AS owner_name
        FROM food_shares fs JOIN users u ON u.id=fs.owner_id
        WHERE fs.status='available' AND fs.expiry_date >= date('now')
        ORDER BY fs.expiry_date ASC
    """).fetchall()
    return render_template("community.html", shares=shares)

@app.post("/share/<int:share_id>/claim")
@login_required
def claim_share(share_id):
    db = get_db()
    share = db.execute("""
        SELECT * FROM food_shares
        WHERE id=? AND status='available' AND expiry_date >= date('now')
    """, (share_id,)).fetchone()
    if not share:
        flash("That food item is no longer available.", "warning")
        return redirect(url_for("community"))
    if share["owner_id"] == session["user_id"]:
        flash("You cannot claim your own listing.", "warning")
        return redirect(url_for("community"))
    try:
        db.execute("INSERT INTO claims(share_id, claimant_id) VALUES(?,?)",
                   (share_id, session["user_id"]))
        db.execute("UPDATE food_shares SET status='claimed', claimed_at=CURRENT_TIMESTAMP WHERE id=?",
                   (share_id,))
        db.commit()
        flash("Claim recorded. Please coordinate pickup with the owner.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("This item has already been claimed.", "warning")
    return redirect(url_for("community"))

@app.post("/share/<int:share_id>/cancel")
@login_required
def cancel_share(share_id):
    db = get_db()
    db.execute("""
        UPDATE food_shares SET status='cancelled'
        WHERE id=? AND owner_id=? AND status='available'
    """, (share_id, session["user_id"]))
    db.commit()
    flash("Sharing listing cancelled.", "success")
    return redirect(url_for("dashboard"))

@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=error.description), 400

@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", code=404, message="The requested resource was not found."), 404

if __name__ == "__main__":
    with app.app_context():
        if not os.path.exists(DATABASE):
            init_db()
    app.run(debug=True)
