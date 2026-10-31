from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os, json, smtplib
from io import BytesIO
from email.message import EmailMessage
from datetime import date, datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
try:
    import stripe
except ImportError:
    stripe = None
try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ImportError:
    BackgroundScheduler = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "brightloop.db")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deployment")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
      password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'staff', customer_id INTEGER);
    CREATE TABLE IF NOT EXISTS customers(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL,
      phone TEXT DEFAULT '', company TEXT DEFAULT '', status TEXT DEFAULT 'Active',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS products(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT DEFAULT 'Software',
      sales_price REAL NOT NULL DEFAULT 0, cost_price REAL NOT NULL DEFAULT 0,
      variant TEXT DEFAULT '', variant_extra REAL DEFAULT 0, notes TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS plans(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, product_id INTEGER,
      price REAL NOT NULL DEFAULT 0, frequency TEXT NOT NULL DEFAULT 'Monthly',
      min_quantity INTEGER DEFAULT 1, auto_close INTEGER DEFAULT 0, allow_pause INTEGER DEFAULT 1,
      allow_early_close INTEGER DEFAULT 1, allow_renew INTEGER DEFAULT 1,
      FOREIGN KEY(product_id) REFERENCES products(id));
    CREATE TABLE IF NOT EXISTS discounts(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, kind TEXT NOT NULL,
      value REAL NOT NULL, min_quantity INTEGER DEFAULT 1, start_date TEXT DEFAULT '',
      end_date TEXT DEFAULT '', usage_limit INTEGER DEFAULT 0, used_count INTEGER DEFAULT 0,
      active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS subscriptions(
      id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL, plan_id INTEGER NOT NULL,
      start_date TEXT NOT NULL, end_date TEXT NOT NULL, quantity INTEGER DEFAULT 1,
      status TEXT DEFAULT 'Active', discount_id INTEGER,
      FOREIGN KEY(customer_id) REFERENCES customers(id), FOREIGN KEY(plan_id) REFERENCES plans(id),
      FOREIGN KEY(discount_id) REFERENCES discounts(id));
    CREATE TABLE IF NOT EXISTS invoices(
      id INTEGER PRIMARY KEY AUTOINCREMENT, subscription_id INTEGER NOT NULL, invoice_date TEXT NOT NULL,
      due_date TEXT NOT NULL, subtotal REAL NOT NULL, discount REAL DEFAULT 0, tax_rate REAL DEFAULT 0,
      tax_amount REAL DEFAULT 0, total REAL NOT NULL, paid REAL DEFAULT 0,
      status TEXT DEFAULT 'Draft', period_key TEXT NOT NULL,
      FOREIGN KEY(subscription_id) REFERENCES subscriptions(id),
      UNIQUE(subscription_id, period_key));
    CREATE TABLE IF NOT EXISTS payments(
      id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL, method TEXT NOT NULL,
      amount REAL NOT NULL, payment_date TEXT NOT NULL, note TEXT DEFAULT '',
      FOREIGN KEY(invoice_id) REFERENCES invoices(id));
    CREATE TABLE IF NOT EXISTS quotations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL, plan_id INTEGER NOT NULL,
      quantity INTEGER DEFAULT 1, valid_until TEXT NOT NULL, status TEXT DEFAULT 'Draft',
      FOREIGN KEY(customer_id) REFERENCES customers(id), FOREIGN KEY(plan_id) REFERENCES plans(id));
    """)
    # Safe, additive migrations for databases created by the earlier MVP.
    user_cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    if "customer_id" not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN customer_id INTEGER")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS reminder_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL,
      reminder_type TEXT NOT NULL, sent_at TEXT NOT NULL, recipient TEXT NOT NULL,
      result TEXT NOT NULL, UNIQUE(invoice_id, reminder_type, recipient));
    CREATE TABLE IF NOT EXISTS payment_gateway_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, invoice_id INTEGER,
      event_type TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS subscription_reminder_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, subscription_id INTEGER NOT NULL,
      reminder_type TEXT NOT NULL, sent_at TEXT NOT NULL, recipient TEXT NOT NULL,
      result TEXT NOT NULL, UNIQUE(subscription_id, reminder_type, recipient));
    """)
    if not c.execute("SELECT id FROM users WHERE email='admin@brightloop.demo'").fetchone():
        c.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",
                  ("Brightloop Admin","admin@brightloop.demo",generate_password_hash("Brightloop@123"),"admin"))
    if c.execute("SELECT COUNT(*) n FROM customers").fetchone()["n"] == 0:
        c.execute("INSERT INTO customers(name,email,phone,company) VALUES('Arun Kumar','arun@example.com','9876543210','Arun Traders')")
        c.execute("INSERT INTO customers(name,email,phone,company) VALUES('Meera Stores','meera@example.com','9876501234','Meera Stores')")
        c.execute("INSERT INTO products(name,type,sales_price,cost_price,variant,variant_extra,notes) VALUES('Business Suite','Software',2000,700,'Standard',0,'Core business software')")
        c.execute("INSERT INTO products(name,type,sales_price,cost_price,variant,variant_extra,notes) VALUES('Inventory Add-on','Add-on',500,150,'Odoo',560,'Inventory extension')")
        c.execute("INSERT INTO plans(name,product_id,price,frequency,min_quantity) VALUES('Monthly Business Plan',1,2000,'Monthly',1)")
        c.execute("INSERT INTO plans(name,product_id,price,frequency,min_quantity) VALUES('Annual Business Plan',1,20000,'Yearly',1)")
    # Create demo customer portal logins, linked to their own customer records.
    for customer in c.execute("SELECT id,name,email FROM customers").fetchall():
        if not c.execute("SELECT id FROM users WHERE email=?", (customer["email"].lower(),)).fetchone():
            c.execute("INSERT INTO users(name,email,password,role,customer_id) VALUES(?,?,?,?,?)",
                      (customer["name"], customer["email"].lower(), generate_password_hash("Customer@123"), "customer", customer["id"]))
        else:
            c.execute("UPDATE users SET customer_id=? WHERE email=? AND role='customer'",
                      (customer["id"], customer["email"].lower()))
    c.commit()
    c.close()

init_db()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required():
    return session.get("role") == "admin"

MODULES = {
 "customers": {"title":"Customers","fields":[("name","Customer name","text"),("email","Email","email"),("phone","Phone","text"),("company","Company","text"),("status","Status","select:Active,Inactive")]},
 "products": {"title":"Products","fields":[("name","Product name","text"),("type","Product type","text"),("sales_price","Sales price (₹)","number"),("cost_price","Cost price (₹)","number"),("variant","Variant","text"),("variant_extra","Variant extra (₹)","number"),("notes","Notes","text")]},
 "plans": {"title":"Subscription plans","fields":[("name","Plan name","text"),("product_id","Product ID","number"),("price","Plan price (₹)","number"),("frequency","Billing frequency","select:Daily,Weekly,Monthly,Yearly"),("min_quantity","Minimum quantity","number")]},
 "discounts": {"title":"Discounts","fields":[("name","Discount name","text"),("kind","Discount type","select:Percentage,Fixed"),("value","Discount value","number"),("min_quantity","Minimum quantity","number"),("start_date","Start date","date"),("end_date","End date","date"),("usage_limit","Usage limit (0 = unlimited)","number")]},
}
@login_required
def dashboard():
    c=db()
    stats = {
      "customers": c.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
      "subscriptions": c.execute("SELECT COUNT(*) FROM subscriptions WHERE status='Active'").fetchone()[0],
      "revenue": c.execute("SELECT COALESCE(SUM(paid),0) FROM invoices").fetchone()[0],
      "outstanding": c.execute("SELECT COALESCE(SUM(total-paid),0) FROM invoices WHERE status!='Cancelled'").fetchone()[0],
      "overdue": c.execute("SELECT COUNT(*) FROM invoices WHERE due_date < ? AND paid < total AND status!='Cancelled'",(date.today().isoformat(),)).fetchone()[0],
      "invoices": c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
    }
    recent = c.execute("""SELECT i.*, cu.name customer FROM invoices i
      JOIN subscriptions s ON s.id=i.subscription_id JOIN customers cu ON cu.id=s.customer_id
      ORDER BY i.id DESC LIMIT 6""").fetchall()
    c.close()
    return render_template("page.html", page="dashboard", stats=stats, recent=recent)

@app.route("/")
@login_required
def home():
    if session.get("role")=="customer": return redirect(url_for("customer_portal"))
    return dashboard()

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        c=db(); u=c.execute("SELECT * FROM users WHERE email=?",(request.form.get("email","").strip().lower(),)).fetchone(); c.close()
        if u and check_password_hash(u["password"],request.form.get("password","")):
            session.update(user_id=u["id"],name=u["name"],role=u["role"],customer_id=u["customer_id"])
            return redirect(url_for("customer_portal") if u["role"]=="customer" else url_for("home"))
        flash("Invalid email or password.","error")
    return render_template("login.html")
@app.route("/register", methods=["GET", "POST"])
def register():

    # If the user is already logged in, redirect them.
    if session.get("user_id"):
        if session.get("role") == "customer":
            return redirect(url_for("customer_portal"))
        return redirect(url_for("home"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        company = request.form.get("company", "").strip()

        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Check required fields.
        if not name or not email or not password:
            flash("Please fill in all required fields.", "error")
            return render_template("register.html")

        # Check password length.
        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
            return render_template("register.html")

        # Check whether passwords match.
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        c = db()

        try:

            # Check whether this email is already registered.
            existing = c.execute(
                "SELECT id FROM users WHERE email = ?",
                (email,)
            ).fetchone()

            if existing:
                flash("An account with this email already exists.", "error")
                return render_template("register.html")

            # Check whether a customer record already exists.
            customer = c.execute(
                "SELECT id FROM customers WHERE lower(email) = ?",
                (email,)
            ).fetchone()

            if customer:
                customer_id = customer["id"]

            else:
                # Create a new customer record.
                c.execute(
                    """INSERT INTO customers(name, email, phone, company)
                       VALUES (?, ?, ?, ?)""",
                    (name, email, phone, company)
                )

                customer_id = c.execute(
                    "SELECT last_insert_rowid()"
                ).fetchone()[0]

            # Create a customer login account.
            c.execute(
                """INSERT INTO users(name, email, password, role, customer_id)
                   VALUES (?, ?, ?, 'customer', ?)""",
                (
                    name,
                    email,
                    generate_password_hash(password),
                    customer_id
                )
            )

            c.commit()

            flash("Account created successfully. Please log in.", "success")

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:

            c.rollback()

            flash("This email is already registered.", "error")

            return render_template("register.html")

        finally:
            c.close()

    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/<module>", methods=["GET","POST"])
@login_required
def module_page(module):
    if not staff_or_admin(): return redirect(url_for("customer_portal"))
    if module not in MODULES: return "Not found",404
    spec=MODULES[module]
    c=db()
    if request.method=="POST":
        if module in ("products","plans","discounts") and not admin_required():
            flash("Only an admin can modify this section.","error")
            return redirect(url_for("module_page",module=module))
        vals=[]
        for field,label,typ in spec["fields"]:
            raw=request.form.get(field,"").strip()
            if typ=="number": raw=float(raw or 0)
            vals.append(raw)
        cols=",".join(x[0] for x in spec["fields"])
        marks=",".join("?" for _ in vals)
        c.execute(f"INSERT INTO {module} ({cols}) VALUES ({marks})",vals)
        c.commit(); c.close()
        flash(f"{spec['title'].rstrip('s')} saved successfully.","success")
        return redirect(url_for("module_page",module=module))
    rows=c.execute(f"SELECT * FROM {module} ORDER BY id DESC").fetchall()
    products=c.execute("SELECT id,name FROM products ORDER BY name").fetchall() if module=="plans" else []
    c.close()
    return render_template("page.html",page="module",module=module,spec=spec,rows=rows,products=products)

@app.route("/subscriptions", methods=["GET","POST"])
@login_required
def subscriptions():
    if not staff_or_admin(): return redirect(url_for("customer_portal"))
    c=db()
    if request.method=="POST":
        try:
            customer_id=int(request.form["customer_id"]); plan_id=int(request.form["plan_id"])
            start=request.form["start_date"]; end=request.form["end_date"]; qty=max(1,int(request.form.get("quantity",1)))
            c.execute("INSERT INTO subscriptions(customer_id,plan_id,start_date,end_date,quantity,status,discount_id) VALUES(?,?,?,?,?,'Active',?)",
                      (customer_id,plan_id,start,end,qty,request.form.get("discount_id") or None))
            c.commit(); flash("Subscription created.","success")
        except Exception as e:
            c.rollback(); flash("Could not create subscription. Check the selected customer and plan.","error")
        c.close(); return redirect(url_for("subscriptions"))
    rows=c.execute("""SELECT s.*,cu.name customer,p.name plan,p.price,p.frequency
      FROM subscriptions s JOIN customers cu ON cu.id=s.customer_id JOIN plans p ON p.id=s.plan_id ORDER BY s.id DESC""").fetchall()
    customers=c.execute("SELECT id,name FROM customers ORDER BY name").fetchall()
    plans=c.execute("SELECT id,name,price,frequency FROM plans ORDER BY name").fetchall()
    discounts=c.execute("SELECT id,name FROM discounts WHERE active=1").fetchall()
    c.close()
    return render_template("page.html",page="subscriptions",rows=rows,customers=customers,plans=plans,discounts=discounts)

@app.route("/subscriptions/<int:sid>/status/<status>")
@login_required
def subscription_status(sid,status):
    if not staff_or_admin(): return redirect(url_for("customer_portal"))
    if status not in ["Active","Paused","Closed"]: return "Invalid status",400
    c=db(); c.execute("UPDATE subscriptions SET status=? WHERE id=?",(status,sid)); c.commit(); c.close()
    flash("Subscription status updated.","success"); return redirect(url_for("subscriptions"))

@app.route("/quotations", methods=["GET","POST"])
@login_required
def quotations():
    if not staff_or_admin(): return redirect(url_for("customer_portal"))
    c=db()
    if request.method=="POST":
        c.execute("INSERT INTO quotations(customer_id,plan_id,quantity,valid_until,status) VALUES(?,?,?,?, 'Quotation')",
                  (request.form["customer_id"],request.form["plan_id"],request.form.get("quantity",1),request.form["valid_until"]))
        c.commit(); c.close(); flash("Quotation created.","success"); return redirect(url_for("quotations"))
    rows=c.execute("""SELECT q.*,cu.name customer,p.name plan,p.price FROM quotations q
      JOIN customers cu ON cu.id=q.customer_id JOIN plans p ON p.id=q.plan_id ORDER BY q.id DESC""").fetchall()
    customers=c.execute("SELECT id,name FROM customers").fetchall(); plans=c.execute("SELECT id,name FROM plans").fetchall()
    c.close(); return render_template("page.html",page="quotations",rows=rows,customers=customers,plans=plans)

@app.route("/quotations/<int:qid>/convert")
@login_required
def convert_quote(qid):
    if not staff_or_admin(): return redirect(url_for("customer_portal"))
    c=db(); q=c.execute("SELECT * FROM quotations WHERE id=?",(qid,)).fetchone()
    if q:
        start=date.today(); end=start+timedelta(days=30)
        c.execute("INSERT INTO subscriptions(customer_id,plan_id,start_date,end_date,quantity,status) VALUES(?,?,?,?,?,'Active')",
                  (q["customer_id"],q["plan_id"],start.isoformat(),end.isoformat(),q["quantity"]))
        c.execute("UPDATE quotations SET status='Accepted' WHERE id=?",(qid,))
        c.commit(); flash("Quotation converted to an active subscription.","success")
    c.close(); return redirect(url_for("quotations"))

@app.route("/billing/run")
@login_required
def run_billing():
    if not staff_or_admin(): return redirect(url_for("customer_portal"))
    c=db(); today=date.today().isoformat(); created=0
    subs=c.execute("""SELECT s.*,p.price,p.frequency FROM subscriptions s JOIN plans p ON p.id=s.plan_id
      WHERE s.status='Active' AND s.start_date<=? AND s.end_date>=?""",(today,today)).fetchall()
    for s in subs:
        period=date.today().strftime("%Y-%m")
        if s["frequency"]=="Yearly": period=date.today().strftime("%Y")
        elif s["frequency"]=="Weekly": period=date.today().strftime("%Y-W%W")
        elif s["frequency"]=="Daily": period=today
        exists=c.execute("SELECT id FROM invoices WHERE subscription_id=? AND period_key=?",(s["id"],period)).fetchone()
        if exists: continue
        subtotal=float(s["price"])*int(s["quantity"])
        discount=0
        if s["discount_id"]:
            d=c.execute("SELECT * FROM discounts WHERE id=? AND active=1",(s["discount_id"],)).fetchone()
            if d and (not d["end_date"] or d["end_date"]>=today) and (not d["start_date"] or d["start_date"]<=today) and (not d["usage_limit"] or d["used_count"]<d["usage_limit"]):
                discount=subtotal*float(d["value"])/100 if d["kind"]=="Percentage" else float(d["value"])
                discount=min(discount,subtotal)
                c.execute("UPDATE discounts SET used_count=used_count+1 WHERE id=?",(d["id"],))
        taxable=max(0,subtotal-discount); tax=taxable*0.18
        due=(date.today()+timedelta(days=7)).isoformat()
        c.execute("""INSERT INTO invoices(subscription_id,invoice_date,due_date,subtotal,discount,tax_rate,tax_amount,total,period_key,status)
          VALUES(?,?,?,?,?,?,?,?,?,'Confirmed')""",(s["id"],today,due,subtotal,discount,18,tax,taxable+tax,period))
        created+=1
    c.commit(); c.close()
    flash(f"Billing run completed. {created} invoice(s) generated; duplicates were skipped.","success")
    return redirect(url_for("invoices"))

@app.route("/invoices")
@login_required
def invoices():
    if not staff_or_admin(): return redirect(url_for("customer_portal"))
    c=db(); rows=c.execute("""SELECT i.*,cu.name customer FROM invoices i JOIN subscriptions s ON s.id=i.subscription_id
      JOIN customers cu ON cu.id=s.customer_id ORDER BY i.id DESC""").fetchall(); c.close()
    return render_template("page.html",page="invoices",rows=rows)

@app.route("/invoices/<int:iid>/paid")
@login_required
def mark_paid(iid):
    if not staff_or_admin(): return redirect(url_for("customer_portal"))
    c=db(); c.execute("UPDATE invoices SET paid=total,status='Paid' WHERE id=?",(iid,)); c.commit(); c.close()
    flash("Invoice marked as paid. Use Record Payment to maintain a payment entry.","success"); return redirect(url_for("invoices"))

@app.route("/payments",methods=["GET","POST"])
@login_required
def payments():
    if not staff_or_admin(): return redirect(url_for("customer_portal"))
    c=db()
    if request.method=="POST":
        iid=int(request.form["invoice_id"]); amount=float(request.form["amount"])
        inv=c.execute("SELECT * FROM invoices WHERE id=?",(iid,)).fetchone()
        if not inv or amount<=0 or amount>float(inv["total"])-float(inv["paid"])+0.001:
            flash("Invalid payment amount or invoice.","error")
        else:
            c.execute("INSERT INTO payments(invoice_id,method,amount,payment_date,note) VALUES(?,?,?,?,?)",
                      (iid,request.form["method"],amount,request.form["payment_date"],request.form.get("note","")))
            new_paid=float(inv["paid"])+amount
            status="Paid" if new_paid+0.001>=float(inv["total"]) else "Partially Paid"
            c.execute("UPDATE invoices SET paid=?,status=? WHERE id=?",(new_paid,status,iid)); c.commit()
            flash("Payment recorded successfully.","success")
        c.close(); return redirect(url_for("payments"))
    rows=c.execute("""SELECT p.*,i.id invoice_no,cu.name customer FROM payments p JOIN invoices i ON i.id=p.invoice_id
      JOIN subscriptions s ON s.id=i.subscription_id JOIN customers cu ON cu.id=s.customer_id ORDER BY p.id DESC""").fetchall()
    invs=c.execute("""SELECT i.id,i.total,i.paid,cu.name customer FROM invoices i JOIN subscriptions s ON s.id=i.subscription_id
      JOIN customers cu ON cu.id=s.customer_id WHERE i.status!='Paid' AND i.status!='Cancelled'""").fetchall()
    c.close(); return render_template("page.html",page="payments",rows=rows,invoices=invs)

@app.route("/reports")
@login_required
def reports():
    if session.get("role")=="customer": return redirect(url_for("customer_portal"))
    c=db()
    by_month=c.execute("""SELECT substr(payment_date,1,7) month,ROUND(SUM(amount),2) revenue FROM payments
      GROUP BY substr(payment_date,1,7) ORDER BY month DESC LIMIT 12""").fetchall()
    by_plan=c.execute("""SELECT p.name plan,ROUND(COALESCE(SUM(i.paid),0),2) revenue
      FROM plans p LEFT JOIN subscriptions s ON s.plan_id=p.id LEFT JOIN invoices i ON i.subscription_id=s.id
      GROUP BY p.id ORDER BY revenue DESC""").fetchall()
    kpis={
      "mrr":c.execute("SELECT COALESCE(SUM(p.price*s.quantity),0) FROM subscriptions s JOIN plans p ON p.id=s.plan_id WHERE s.status='Active' AND p.frequency='Monthly'").fetchone()[0],
      "collected":c.execute("SELECT COALESCE(SUM(amount),0) FROM payments").fetchone()[0],
      "outstanding":c.execute("SELECT COALESCE(SUM(total-paid),0) FROM invoices WHERE status!='Cancelled'").fetchone()[0],
      "avg_invoice":c.execute("SELECT COALESCE(AVG(total),0) FROM invoices").fetchone()[0],
      "active":c.execute("SELECT COUNT(*) FROM subscriptions WHERE status='Active'").fetchone()[0],
      "cancelled":c.execute("SELECT COUNT(*) FROM subscriptions WHERE status='Closed'").fetchone()[0]
    }
    c.close(); return render_template("page.html",page="reports",by_month=by_month,by_plan=by_plan,kpis=kpis)

@app.route("/staff",methods=["GET","POST"])
@login_required
def staff():
    if not admin_required(): flash("Admin access required.","error"); return redirect(url_for("home"))
    c=db()
    if request.method=="POST":
        try:
            c.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,'staff')",
                      (request.form["name"],request.form["email"].lower(),generate_password_hash(request.form["password"])))
            c.commit(); flash("Staff account created.","success")
        except sqlite3.IntegrityError: flash("That email already exists.","error")
        c.close(); return redirect(url_for("staff"))
    rows=c.execute("SELECT id,name,email,role FROM users ORDER BY id").fetchall(); c.close()
    return render_template("page.html",page="staff",rows=rows)


def staff_or_admin():
    return session.get("role") in ("admin", "staff")

def send_email(to_address, subject, body):
    host=os.environ.get("SMTP_HOST")
    if not host:
        return False, "Email is not configured; reminder was logged only."
    msg=EmailMessage(); msg["Subject"]=subject; msg["From"]=os.environ.get("SMTP_FROM",os.environ.get("SMTP_USER","brightloop@example.com")); msg["To"]=to_address; msg.set_content(body)
    try:
        with smtplib.SMTP(host,int(os.environ.get("SMTP_PORT","587")),timeout=15) as server:
            server.starttls()
            user=os.environ.get("SMTP_USER"); password=os.environ.get("SMTP_PASSWORD")
            if user: server.login(user,password or "")
            server.send_message(msg)
        return True, "Email sent"
    except Exception as exc:
        return False, f"Email failed: {exc}"

def run_reminders():
    c=db(); today=date.today(); sent=0; logged=0
    candidates=c.execute("""SELECT i.id,i.due_date,i.total,i.paid,cu.name,cu.email
      FROM invoices i JOIN subscriptions s ON s.id=i.subscription_id JOIN customers cu ON cu.id=s.customer_id
      WHERE i.status!='Cancelled' AND i.paid<i.total AND i.due_date<=?""",((today+timedelta(days=7)).isoformat(),)).fetchall()
    for inv in candidates:
        due=date.fromisoformat(inv["due_date"]); overdue=due<today
        kind="overdue_invoice" if overdue else "invoice_due"
        exists=c.execute("SELECT id FROM reminder_logs WHERE invoice_id=? AND reminder_type=? AND recipient=?",(inv["id"],kind,inv["email"])).fetchone()
        if exists: continue
        subject=f"Brightloop invoice INV-{inv['id']:04d} {'overdue' if overdue else 'due soon'}"
        body=(f"Hello {inv['name']},\n\nYour invoice INV-{inv['id']:04d} has an outstanding balance of ₹{inv['total']-inv['paid']:.2f}. Due date: {inv['due_date']}. Please sign in to your Brightloop customer portal to review it.\n\nBrightloop Software")
        ok, result=send_email(inv["email"],subject,body)
        c.execute("INSERT OR IGNORE INTO reminder_logs(invoice_id,reminder_type,sent_at,recipient,result) VALUES(?,?,?,?,?)",
                  (inv["id"],kind,datetime.now().isoformat(timespec="seconds"),inv["email"],result))
        logged+=1; sent+=int(ok)
    renewals=c.execute("""SELECT s.id,s.end_date,cu.name,cu.email,p.name plan FROM subscriptions s
      JOIN customers cu ON cu.id=s.customer_id JOIN plans p ON p.id=s.plan_id
      WHERE s.status='Active' AND s.end_date>=? AND s.end_date<=?""",
      (today.isoformat(),(today+timedelta(days=7)).isoformat())).fetchall()
    for sub in renewals:
        kind="subscription_renewal"
        exists=c.execute("SELECT id FROM subscription_reminder_logs WHERE subscription_id=? AND reminder_type=? AND recipient=?",(sub["id"],kind,sub["email"])).fetchone()
        if exists: continue
        subject=f"Brightloop subscription renewal reminder — {sub['plan']}"
        body=f"Hello {sub['name']},\n\nYour {sub['plan']} subscription is scheduled to end on {sub['end_date']}. Please sign in to your Brightloop customer portal or contact your account team to discuss renewal.\n\nBrightloop Software"
        ok,result=send_email(sub["email"],subject,body)
        c.execute("INSERT OR IGNORE INTO subscription_reminder_logs(subscription_id,reminder_type,sent_at,recipient,result) VALUES(?,?,?,?,?)",
                  (sub["id"],kind,datetime.now().isoformat(timespec="seconds"),sub["email"],result))
        logged+=1; sent+=int(ok)
    c.commit(); c.close(); return logged,sent

@app.route("/customer")
@login_required
def customer_portal():
    if session.get("role")!="customer": return redirect(url_for("home"))
    cid=session.get("customer_id")
    c=db()
    subscriptions=c.execute("""SELECT s.*,p.name plan,p.price,p.frequency FROM subscriptions s JOIN plans p ON p.id=s.plan_id
      WHERE s.customer_id=? ORDER BY s.id DESC""",(cid,)).fetchall()
    invoices=c.execute("""SELECT i.* FROM invoices i JOIN subscriptions s ON s.id=i.subscription_id
      WHERE s.customer_id=? ORDER BY i.id DESC""",(cid,)).fetchall()
    payments=c.execute("""SELECT p.*,i.id invoice_no FROM payments p JOIN invoices i ON i.id=p.invoice_id
      JOIN subscriptions s ON s.id=i.subscription_id WHERE s.customer_id=? ORDER BY p.id DESC""",(cid,)).fetchall()
    c.close()
    return render_template("customer_portal.html",page="customer_portal",subscriptions=subscriptions,invoices=invoices,payments=payments)

@app.route("/invoices/<int:iid>/pdf")
@login_required
def invoice_pdf(iid):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c=db()
    row=c.execute("""SELECT i.*,cu.name customer,cu.email,cu.company,cu.phone,p.name plan
      FROM invoices i JOIN subscriptions s ON s.id=i.subscription_id JOIN customers cu ON cu.id=s.customer_id
      JOIN plans p ON p.id=s.plan_id WHERE i.id=?""",(iid,)).fetchone()
    if not row or (session.get("role")=="customer" and session.get("customer_id")!=c.execute("SELECT customer_id FROM subscriptions WHERE id=?",(row["subscription_id"],)).fetchone()[0]):
        c.close(); return "Invoice not found",404
    c.close(); buffer=BytesIO(); pdf=canvas.Canvas(buffer,pagesize=A4); width,height=A4
    y=height-65
    pdf.setFont("Helvetica-Bold",22); pdf.drawString(50,y,"BRIGHTLOOP")
    pdf.setFont("Helvetica",10); pdf.drawString(50,y-20,"Subscription Management · Tax invoice (demo format)")
    pdf.setFont("Helvetica-Bold",15); pdf.drawString(50,y-65,f"INVOICE  INV-{iid:04d}")
    pdf.setFont("Helvetica",11)
    lines=[f"Customer: {row['customer']}",f"Email: {row['email']}",f"Company: {row['company'] or '-'}",f"Plan: {row['plan']}",f"Invoice date: {row['invoice_date']}",f"Due date: {row['due_date']}",f"Status: {row['status']}"]
    yy=y-100
    for line in lines: pdf.drawString(50,yy,line); yy-=19
    yy-=12; pdf.line(50,yy,width-50,yy); yy-=28
    for label,value in [("Subtotal",row["subtotal"]),("Discount",-row["discount"]),(f"Tax ({row['tax_rate']:.1f}%)",row["tax_amount"]),("Invoice total",row["total"]),("Amount paid",row["paid"]),("Balance due",row["total"]-row["paid"])]:
        pdf.drawString(50,yy,label); pdf.drawRightString(width-50,yy,f"INR {value:,.2f}"); yy-=23
    pdf.setFont("Helvetica-Oblique",9); pdf.drawString(50,55,"Generated by Brightloop demo application. Configure tax rules before business use.")
    pdf.save(); buffer.seek(0)
    from flask import send_file
    return send_file(buffer,mimetype="application/pdf",as_attachment=True,download_name=f"Brightloop_INV-{iid:04d}.pdf")

@app.route("/exports/<kind>.xlsx")
@login_required
def export_excel(kind):
    if not staff_or_admin(): return "Forbidden",403
    from openpyxl import Workbook
    c=db(); wb=Workbook(); ws=wb.active
    if kind=="customers":
        ws.title="Customers"; rows=c.execute("SELECT id,name,email,phone,company,status,created_at FROM customers ORDER BY id").fetchall(); headers=["ID","Name","Email","Phone","Company","Status","Created"]
    elif kind=="invoices":
        ws.title="Invoices"; rows=c.execute("SELECT i.id,cu.name,i.invoice_date,i.due_date,i.subtotal,i.discount,i.tax_amount,i.total,i.paid,i.total-i.paid balance,i.status FROM invoices i JOIN subscriptions s ON s.id=i.subscription_id JOIN customers cu ON cu.id=s.customer_id ORDER BY i.id").fetchall(); headers=["ID","Customer","Invoice date","Due date","Subtotal","Discount","Tax","Total","Paid","Balance","Status"]
    elif kind=="payments":
        ws.title="Payments"; rows=c.execute("SELECT p.id,p.invoice_id,cu.name,p.method,p.payment_date,p.amount,p.note FROM payments p JOIN invoices i ON i.id=p.invoice_id JOIN subscriptions s ON s.id=i.subscription_id JOIN customers cu ON cu.id=s.customer_id ORDER BY p.id").fetchall(); headers=["ID","Invoice ID","Customer","Method","Date","Amount","Note"]
    else: c.close(); return "Unknown export",404
    c.close(); ws.append(headers)
    for row in rows: ws.append([row[h] for h in row.keys()])
    for col in ws.columns:
        letter=col[0].column_letter; ws.column_dimensions[letter].width=min(max(max(len(str(cell.value or "")) for cell in col)+2,12),34)
    out=BytesIO(); wb.save(out); out.seek(0)
    from flask import send_file
    return send_file(out,mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",as_attachment=True,download_name=f"brightloop_{kind}.xlsx")

@app.route("/reminders",methods=["GET","POST"])
@login_required
def reminders():
    if not staff_or_admin(): return redirect(url_for("customer_portal"))
    result=None
    if request.method=="POST":
        logged,sent=run_reminders(); result=f"Processed {logged} reminder(s); {sent} email(s) sent. Configure SMTP to deliver emails."
        flash(result,"success")
    c=db(); logs=c.execute("""SELECT 'Invoice '||invoice_id reference,reminder_type,sent_at,recipient,result FROM reminder_logs
      UNION ALL SELECT 'Subscription '||subscription_id reference,reminder_type,sent_at,recipient,result FROM subscription_reminder_logs
      ORDER BY sent_at DESC LIMIT 40""").fetchall(); c.close()
    return render_template("reminders.html",logs=logs,result=result)

@app.route("/assistant",methods=["GET","POST"])
@login_required
def revenue_assistant():
    if not staff_or_admin(): return redirect(url_for("customer_portal"))
    answer=None; question=""
    if request.method=="POST":
        question=request.form.get("question","").strip().lower(); c=db()
        collected=c.execute("SELECT COALESCE(SUM(amount),0) FROM payments").fetchone()[0]
        outstanding=c.execute("SELECT COALESCE(SUM(total-paid),0) FROM invoices WHERE status!='Cancelled'").fetchone()[0]
        active=c.execute("SELECT COUNT(*) FROM subscriptions WHERE status='Active'").fetchone()[0]
        overdue=c.execute("SELECT COUNT(*) FROM invoices WHERE due_date<? AND paid<total AND status!='Cancelled'",(date.today().isoformat(),)).fetchone()[0]
        top=c.execute("""SELECT p.name,COALESCE(SUM(i.paid),0) revenue FROM plans p LEFT JOIN subscriptions s ON s.plan_id=p.id LEFT JOIN invoices i ON i.subscription_id=s.id GROUP BY p.id ORDER BY revenue DESC LIMIT 1""").fetchone()
        month=c.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE substr(payment_date,1,7)=?",(date.today().strftime("%Y-%m"),)).fetchone()[0]
        c.close()
        if any(w in question for w in ["top plan","best plan","highest plan","most revenue"]): answer=f"Your top plan by recorded payment revenue is {top['name'] if top else 'not available'}, with ₹{(top['revenue'] if top else 0):,.2f}."
        elif "overdue" in question: answer=f"There are {overdue} overdue invoice(s). Review the invoice register and send reminders from the Reminders page."
        elif any(w in question for w in ["outstanding","unpaid","pending"]): answer=f"Total outstanding balance across non-cancelled invoices is ₹{outstanding:,.2f}."
        elif any(w in question for w in ["active subscription","how many subscription"]): answer=f"There are {active} active subscription(s) currently."
        elif any(w in question for w in ["this month","monthly revenue","month revenue"]): answer=f"Payments recorded this month ({date.today():%B %Y}) total ₹{month:,.2f}."
        elif any(w in question for w in ["revenue","collected","received"]): answer=f"Total recorded payments are ₹{collected:,.2f}. This is cash received, not invoice value."
        else: answer=f"Quick snapshot: ₹{collected:,.2f} received, ₹{outstanding:,.2f} outstanding, {active} active subscriptions, and {overdue} overdue invoices. Try asking about top plan, this month's revenue, overdue invoices, or outstanding balance."
    return render_template("assistant.html",answer=answer,question=question)

@app.route("/checkout/<int:iid>")
@login_required
def checkout(iid):
    if stripe is None: flash("Stripe package is missing. Install requirements first.","error"); return redirect(url_for("invoices"))
    secret=os.environ.get("STRIPE_SECRET_KEY")
    if not secret: flash("Stripe test mode is not configured. Add STRIPE_SECRET_KEY to your environment.","error"); return redirect(url_for("invoices"))
    c=db(); inv=c.execute("""SELECT i.*,cu.name customer FROM invoices i JOIN subscriptions s ON s.id=i.subscription_id JOIN customers cu ON cu.id=s.customer_id WHERE i.id=?""",(iid,)).fetchone()
    if not inv or (session.get("role")=="customer" and c.execute("SELECT customer_id FROM subscriptions WHERE id=?",(inv["subscription_id"],)).fetchone()[0]!=session.get("customer_id")):
        c.close(); return "Invoice not found",404
    balance=round(float(inv["total"])-float(inv["paid"]),2); c.close()
    if balance<=0: flash("This invoice has no outstanding balance.","success"); return redirect(url_for("customer_portal") if session.get("role")=="customer" else url_for("invoices"))
    stripe.api_key=secret
    try:
        checkout_session=stripe.checkout.Session.create(mode="payment",payment_method_types=["card"],
          line_items=[{"price_data":{"currency":"inr","product_data":{"name":f"Brightloop invoice INV-{iid:04d}"},"unit_amount":int(round(balance*100))},"quantity":1}],
          metadata={"invoice_id":str(iid)},success_url=url_for("checkout_success",_external=True)+"?session_id={CHECKOUT_SESSION_ID}",cancel_url=url_for("checkout_cancel",iid=iid,_external=True))
        return redirect(checkout_session.url,code=303)
    except Exception as exc: flash(f"Could not start checkout: {exc}","error"); return redirect(url_for("invoices"))

@app.route("/checkout/success")
@login_required
def checkout_success():
    sid=request.args.get("session_id"); secret=os.environ.get("STRIPE_SECRET_KEY")
    if not sid or not secret or stripe is None: return "Payment session could not be verified",400
    stripe.api_key=secret
    try:
        checkout_session=stripe.checkout.Session.retrieve(sid)
        iid=int(checkout_session.metadata.get("invoice_id"))
        if checkout_session.payment_status=="paid":
            c=db(); inv=c.execute("SELECT * FROM invoices WHERE id=?",(iid,)).fetchone()
            if inv and session.get("role")=="customer":
                owner=c.execute("SELECT customer_id FROM subscriptions WHERE id=?",(inv["subscription_id"],)).fetchone()
                if not owner or owner[0]!=session.get("customer_id"):
                    c.close(); return "Invoice does not belong to this customer",403
            if inv and float(inv["paid"])<float(inv["total"]):
                amount=round(float(inv["total"])-float(inv["paid"]),2)
                c.execute("INSERT INTO payments(invoice_id,method,amount,payment_date,note) VALUES(?,?,?,?,?)",(iid,"Stripe",amount,date.today().isoformat(),f"Stripe checkout {sid}"))
                c.execute("UPDATE invoices SET paid=total,status='Paid' WHERE id=?",(iid,)); c.commit()
            c.close(); flash("Stripe test payment verified and recorded.","success")
        else: flash("Payment is not marked paid by Stripe yet.","error")
    except Exception as exc: return f"Unable to verify payment: {exc}",400
    return redirect(url_for("customer_portal") if session.get("role")=="customer" else url_for("invoices"))

@app.route("/checkout/cancel/<int:iid>")
@login_required
def checkout_cancel(iid):
    flash("Checkout was cancelled. No payment was recorded.","error")
    return redirect(url_for("customer_portal") if session.get("role")=="customer" else url_for("invoices"))

@app.route("/stripe/webhook",methods=["POST"])
def stripe_webhook():
    if stripe is None: return "Stripe package missing",500
    secret=os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret: return "Webhook secret not configured",400
    from flask import abort
    payload=request.get_data(); sig=request.headers.get("Stripe-Signature","")
    try: event=stripe.Webhook.construct_event(payload,sig,secret)
    except Exception: abort(400)
    if event["type"]=="checkout.session.completed":
        obj=event["data"]["object"]; iid=int(obj.get("metadata",{}).get("invoice_id",0) or 0)
        if iid and obj.get("payment_status")=="paid":
            c=db(); seen=c.execute("SELECT id FROM payment_gateway_events WHERE event_id=?",(event["id"],)).fetchone()
            if not seen:
                inv=c.execute("SELECT * FROM invoices WHERE id=?",(iid,)).fetchone()
                if inv and inv["paid"]<inv["total"]:
                    amount=round(inv["total"]-inv["paid"],2)
                    c.execute("INSERT INTO payments(invoice_id,method,amount,payment_date,note) VALUES(?,?,?,?,?)",(iid,"Stripe",amount,date.today().isoformat(),"Stripe webhook"))
                    c.execute("UPDATE invoices SET paid=total,status='Paid' WHERE id=?",(iid,))
                c.execute("INSERT INTO payment_gateway_events(event_id,invoice_id,event_type) VALUES(?,?,?)",(event["id"],iid,event["type"]))
                c.commit()
            c.close()
    return "ok",200

# Daily reminders run in the app process. For production, move this job to a dedicated worker.
_scheduler=None
if BackgroundScheduler and os.environ.get("BRIGHTLOOP_DISABLE_SCHEDULER")!="1":
    try:
        _scheduler=BackgroundScheduler(daemon=True)
        _scheduler.add_job(run_reminders,"cron",hour=9,minute=0,id="brightloop_reminders",replace_existing=True)
        _scheduler.start()
    except Exception:
        _scheduler=None

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
