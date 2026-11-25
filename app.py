# Import Flask helpers for the app and its templates.
import os
import sqlite3
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


@app.route("/order/new", methods=["GET", "POST"])
def order_new():
    connection = get_db()
    menu_rows = connection.execute(
        "SELECT id, name, description, category, price_cents, available "
        "FROM menu_items ORDER BY name"
    ).fetchall()
    items_by_id = {item["id"]: item for item in menu_rows}
    form_items = {
        item["id"]: item for item in menu_rows if item["available"]
    }

    errors = []
    selected_items = []
    total_cents = 0 if request.method == "GET" else None
    pickup_name = request.form.get("pickup", "")
    notes = request.form.get("notes", "")

    if request.method == "POST":
        quantity_error = False
        seen_item_ids = set()
        quantity_fields = [
            field for field in request.form if field.startswith("quantity_")
        ]
        for field in quantity_fields:
            item_id_text = field[len("quantity_"):]
            if not item_id_text.isascii() or not item_id_text.isdecimal():
                errors.append("A submitted menu item is invalid.")
                quantity_error = True
                continue
            try:
                item_id = int(item_id_text)
            except ValueError:
                errors.append("A submitted menu item is invalid.")
                quantity_error = True
                continue

            item = items_by_id.get(item_id)
            if item is None:
                errors.append(
                    "A selected menu item could not be found. Refresh the page and try again."
                )
                quantity_error = True
                continue
            form_items[item_id] = item
            if item_id in seen_item_ids:
                errors.append(f"Quantity for {item['name']} was submitted more than once.")
                quantity_error = True
                continue
            seen_item_ids.add(item_id)

            values = request.form.getlist(field)
            if len(values) != 1:
                errors.append(f"Quantity for {item['name']} must be submitted once.")
                quantity_error = True
                continue
            quantity_text = values[0].strip()
            if not quantity_text.isascii() or not quantity_text.isdecimal():
                errors.append(
                    f"Quantity for {item['name']} must be a whole number from 0 to 20."
                )
                quantity_error = True
                continue
            try:
                quantity = int(quantity_text)
            except ValueError:
                errors.append(
                    f"Quantity for {item['name']} must be a whole number from 0 to 20."
                )
                quantity_error = True
                continue
            if quantity > 20:
                errors.append(f"Quantity for {item['name']} cannot exceed 20.")
                quantity_error = True
                continue
            if quantity == 0:
                continue
            if not item["available"]:
                errors.append(f"{item['name']} is no longer available.")
                quantity_error = True
                continue
            selected_items.append({
                "id": item_id,
                "name": item["name"],
                "quantity": quantity,
            })

        if not pickup_name.strip():
            errors.append("Pickup name is required.")
        if not selected_items and not quantity_error:
            errors.append("Select at least one menu item.")

        if not errors:
            connection.execute("BEGIN IMMEDIATE")
            current_items = {}
            unavailable_item = None
            for selected in selected_items:
                current_item = connection.execute(
                    "SELECT id, name, description, category, price_cents, available "
                    "FROM menu_items WHERE id = ?",
                    (selected["id"],),
                ).fetchone()
                if current_item is None or not current_item["available"]:
                    unavailable_item = selected["name"]
                    if current_item is not None:
                        form_items[selected["id"]] = current_item
                    break
                current_items[selected["id"]] = current_item

            if unavailable_item is not None:
                connection.rollback()
                errors.append(f"{unavailable_item} is no longer available.")
            else:
                try:
                    order_cursor = connection.execute(
                        "INSERT INTO orders (customer_name, status, notes) "
                        "VALUES (?, ?, ?)",
                        (pickup_name.strip(), "Received", notes.strip()),
                    )
                    order_id = order_cursor.lastrowid
                    connection.executemany(
                        "INSERT INTO order_items (order_id, menu_item_id, quantity) "
                        "VALUES (?, ?, ?)",
                        [
                            (order_id, selected["id"], selected["quantity"])
                            for selected in selected_items
                        ],
                    )
                    connection.commit()
                except sqlite3.IntegrityError:
                    connection.rollback()
                    errors.append(
                        "The order could not be saved. Review the menu selections and try again."
                    )
                else:
                    total_cents = sum(
                        current_items[selected["id"]]["price_cents"]
                        * selected["quantity"]
                        for selected in selected_items
                    )
                    flash(
                        f"Order #{order_id} placed successfully. "
                        f"Total: ${total_cents / 100:.2f}.",
                        "success",
                    )
                    return redirect(
                        url_for("order_confirmation", order_id=order_id)
                    )

    return render_template(
        "order.html",
        menu_items=sorted(form_items.values(), key=lambda item: item["name"]),
        errors=errors,
        total_cents=total_cents,
    ), (400 if errors else 200)

def calculate_cart_total(cart):
    return sum(
        item["price_cents"] * item["quantity"]
        for item in cart
    )
@app.route("/order/confirmation")
def order_confirmation():
    requested_order_id = request.args.get("order_id")
    if requested_order_id is not None:
        try:
            order_id = int(requested_order_id)
        except ValueError:
            abort(404)
        order = get_db().execute(
            "SELECT id, customer_name, status, notes "
            "FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order is None:
            abort(404)
        cart = get_db().execute(
            "SELECT menu_items.name, order_items.quantity, menu_items.price_cents, "
            "NULL AS options "
            "FROM order_items "
            "JOIN menu_items ON menu_items.id = order_items.menu_item_id "
            "WHERE order_items.order_id = ? ORDER BY order_items.id",
            (order_id,),
        ).fetchall()
        total_cents = sum(
            item["price_cents"] * item["quantity"] for item in cart
        )
        confirmation = {
            "order_number": order["id"],
            "status": order["status"],
            "pickup_name": order["customer_name"],
        }
        return render_template(
            "confirmation.html",
            confirmation=confirmation,
            cart=cart,
            total_cents=total_cents,
            sample=False,
            order_notes=order["notes"],
        )

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
        sample=True,
        order_notes="",
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
    errors = []
    price_cents = 0

    if not name:
        errors.append("Name is required.")
    elif not any(character.isalnum() for character in name):
        errors.append("Include at least one letter or number in the item name.")
    if category not in ("coffee", "bakery", "snacks"):
        errors.append("Choose a valid category.")

    try:
        price = Decimal(request.form.get("price", ""))
        if not price.is_finite() or price <= 0 or price > Decimal("50"):
            raise ValueError
        cents = price * 100
        if cents != cents.to_integral_value():
            raise ValueError
        price_cents = int(cents)
    except (InvalidOperation, ValueError, OverflowError):
        errors.append(
            "Enter a price greater than $0 and at most $50 with no more than two decimal places."
        )

    if errors:
        return None, errors
    return (name, category, price_cents), errors


@app.route("/admin/menu")
def admin_menu():
    items = get_db().execute(
        "SELECT * FROM menu_items ORDER BY name"
    ).fetchall()
    return render_template("admin_menu.html", items=items)


@app.route("/admin/menu/new", methods=["GET", "POST"])
def menu_new():
    errors = []
    if request.method == "POST":
        values, errors = validate_menu_item_form()
        if not errors:
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
    return render_template(
        "menu_new.html", errors=errors, item=None
    ), (400 if errors else 200)


@app.route("/items/<int:item_id>/edit", methods=["GET", "POST"])
def menu_edit(item_id):
    connection = get_db()
    item = connection.execute(
        "SELECT * FROM menu_items WHERE id = ?", (item_id,)
    ).fetchone()
    if item is None:
        abort(404)

    errors = []
    if request.method == "POST":
        values, errors = validate_menu_item_form()
        if not errors:
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
    return render_template(
        "menu_new.html", errors=errors, item=item
    ), (400 if errors else 200)


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
