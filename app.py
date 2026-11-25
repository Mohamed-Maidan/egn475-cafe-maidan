# Import Flask helpers for the app and its templates.
import os
from decimal import Decimal, InvalidOperation

from flask import Flask, abort, flash, redirect, render_template, request, url_for
import db
from db import get_db

# Create the Flask app for this file.
app = Flask(__name__)
app.config["DATABASE"] = os.path.join(app.instance_path, "cafe.sqlite")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or os.urandom(24)
os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)

SAMPLE_CART = [
    {
        "name": "Café con leche",
        "options": "Oat milk",
        "quantity": 2,
        "price_cents": 350,
    },
    {
        "name": "Guava pastelito",
        "options": None,
        "quantity": 1,
        "price_cents": 295,
    },
]

ORDER_STATUS_TRANSITIONS = {
    "Received": "Preparing",
    "Preparing": "Ready",
    "Ready": "Picked up",
    "Picked up": None,
}

SAMPLE_HISTORY = [
    {
        "id": 1037,
        "completed": "Today, 9:02 AM",
        "items": "1 × Guava pastelito",
        "status": "Picked up",
    },
    {
        "id": 1038,
        "completed": "Today, 9:15 AM",
        "items": "1 × Café con leche",
        "status": "Picked up",
    },
    {
        "id": 1039,
        "completed": "Today, 9:27 AM",
        "items": "2 × Cortadito",
        "status": "Picked up",
    },
]


@app.route("/", endpoint="home")
def home():
    return render_template("index.html")


@app.route("/menu", endpoint="menu")
def menu():
    items = get_db().execute(
        "SELECT * FROM menu_items ORDER BY name"
    ).fetchall()
    return render_template("menu.html", items=items)


@app.route("/order/new")
def order_new():
    total_cents = calculate_cart_total(SAMPLE_CART)
    return render_template(
        "order.html", cart=SAMPLE_CART, total_cents=total_cents
    )

def calculate_cart_total(cart):
    return sum(
        item["price_cents"] * item["quantity"]
        for item in cart
    )
@app.route("/order/confirmation")
def order_confirmation():
    total_cents = calculate_cart_total(SAMPLE_CART)
    confirmation = {
        "order_number": 1042,
        "status": "Received",
        "pickup_name": "Marta Rodriguez",
    }
    return render_template(
        "confirmation.html",
        confirmation=confirmation,
        cart=SAMPLE_CART,
        total_cents=total_cents,
    )


@app.route("/kitchen")
def kitchen():
    orders = get_db().execute(
        "SELECT orders.id AS order_id, orders.status, orders.notes, "
        "GROUP_CONCAT(order_items.quantity || ' × ' || menu_items.name, ', ') AS items "
        "FROM orders "
        "LEFT JOIN order_items ON order_items.order_id = orders.id "
        "LEFT JOIN menu_items ON menu_items.id = order_items.menu_item_id "
        "GROUP BY orders.id ORDER BY orders.id"
    ).fetchall()
    return render_template(
        "kitchen.html",
        orders=orders,
        status_transitions=ORDER_STATUS_TRANSITIONS,
    )


@app.route("/orders/<int:order_id>/status", methods=["POST"])
def update_order_status(order_id):
    connection = get_db()
    order = connection.execute(
        "SELECT status FROM orders WHERE id = ?", (order_id,)
    ).fetchone()
    if order is None:
        abort(404)

    current_status = order["status"]
    next_status = request.form.get("status")
    expected_status = ORDER_STATUS_TRANSITIONS.get(current_status)
    if expected_status is None or next_status != expected_status:
        flash("This order has moved on. Refresh the board before trying again.", "error")
        return redirect(url_for("kitchen"))

    result = connection.execute(
        "UPDATE orders SET status = ? WHERE id = ? AND status = ?",
        (next_status, order_id, current_status),
    )
    if result.rowcount == 1:
        connection.commit()
        flash(f"Order #{order_id} is now {next_status.lower()}.", "success")
    else:
        connection.rollback()
        flash("This order has moved on. Refresh the board before trying again.", "error")
    return redirect(url_for("kitchen"))


@app.route("/orders")
def orders():
    return render_template("history.html", history=SAMPLE_HISTORY)


@app.route("/menu/<int:item_id>")
def item_detail(item_id):
    item = get_db().execute(
        "SELECT * FROM menu_items WHERE id = ?", (item_id,)
    ).fetchone()
    if item is None:
        abort(404)
    return render_template("item.html", item=item)


@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html"), 404


@app.route("/about")
def about():
    return "Maidan Cafe is a welcoming café in South Florida."


def validate_menu_item_form():
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "coffee")
    if not name:
        return None, "Name is required."
    if not any(character.isalnum() for character in name):
        return None, "Include at least one letter or number in the item name."
    if category not in ("coffee", "bakery", "snacks"):
        return None, "Choose a valid category."
    try:
        price = Decimal(request.form.get("price", ""))
        if not price.is_finite() or price <= 0 or price > Decimal("50"):
            raise ValueError
        cents = price * 100
        if cents != cents.to_integral_value():
            raise ValueError
    except (InvalidOperation, ValueError, OverflowError):
        return None, "Enter a price greater than $0 and at most $50 with no more than two decimal places."
    return (name, category, int(cents)), None


@app.route("/admin/menu")
def admin_menu():
    items = get_db().execute(
        "SELECT * FROM menu_items ORDER BY name"
    ).fetchall()
    return render_template("admin_menu.html", items=items)


@app.route("/admin/menu/new", methods=["GET", "POST"])
def menu_new():
    error = None
    if request.method == "POST":
        values, error = validate_menu_item_form()
        if values is not None:
            name, category, price_cents = values
            connection = get_db()
            connection.execute(
                "INSERT INTO menu_items "
                "(name, category, price_cents, available, description, supports_milk) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, category, price_cents,
                 int(request.form.get("available") == "1"),
                 request.form.get("description", "").strip(),
                 int(request.form.get("supports_milk") == "1")),
            )
            connection.commit()
            return redirect(url_for("menu"))
    return render_template("menu_new.html", error=error, item=None), (400 if error else 200)


@app.route("/items/<int:item_id>/edit", methods=["GET", "POST"])
def menu_edit(item_id):
    connection = get_db()
    item = connection.execute(
        "SELECT * FROM menu_items WHERE id = ?", (item_id,)
    ).fetchone()
    if item is None:
        abort(404)

    error = None
    if request.method == "POST":
        values, error = validate_menu_item_form()
        if values is not None:
            name, category, price_cents = values
            connection.execute(
                "UPDATE menu_items "
                "SET name = ?, category = ?, price_cents = ?, description = ?, "
                "available = ?, supports_milk = ? WHERE id = ?",
                (name, category, price_cents,
                 request.form.get("description", "").strip(),
                 int(request.form.get("available") == "1"),
                 int(request.form.get("supports_milk") == "1"),
                 item_id),
            )
            connection.commit()
            flash(f"{name} updated successfully.", "success")
            return redirect(url_for("admin_menu"))
    return render_template("menu_new.html", error=error, item=item), (400 if error else 200)


@app.route("/items/<int:item_id>/delete", methods=["POST"])
def menu_delete(item_id):
    connection = get_db()
    item = connection.execute(
        "SELECT name FROM menu_items WHERE id = ?", (item_id,)
    ).fetchone()
    if item is None:
        abort(404)

    order_item = connection.execute(
        "SELECT 1 FROM order_items WHERE menu_item_id = ? LIMIT 1", (item_id,)
    ).fetchone()
    if order_item is not None:
        connection.execute(
            "UPDATE menu_items SET available = 0 WHERE id = ?", (item_id,)
        )
        message = f"{item['name']} appears in an order and was marked unavailable."
    else:
        connection.execute(
            "DELETE FROM menu_items WHERE id = ?", (item_id,)
        )
        message = f"{item['name']} was deleted."

    connection.commit()
    flash(message, "success")
    return redirect(url_for("admin_menu"))
