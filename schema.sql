DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS menu_items;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'customer'
        CHECK (role IN ('customer', 'kitchen', 'manager'))
);
CREATE TABLE menu_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL CHECK (category IN ('coffee', 'bakery', 'snacks')),
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    available INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0, 1)),
    supports_milk INTEGER NOT NULL DEFAULT 0 CHECK (supports_milk IN (0, 1))
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    customer_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Received'
        CHECK (status IN ('Received', 'Preparing', 'Ready', 'Picked up')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    menu_item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (menu_item_id) REFERENCES menu_items(id)
);

INSERT INTO menu_items (id, name, description, category, price_cents, available, supports_milk) VALUES (1, 'Café con leche', 'Espresso with warm milk.', 'coffee', 350, 1, 1);
INSERT INTO menu_items (id, name, description, category, price_cents, available, supports_milk) VALUES (2, 'Cortadito', 'Strong Cuban espresso softened with steamed milk.', 'coffee', 275, 1, 0);
INSERT INTO menu_items (id, name, description, category, price_cents, available, supports_milk) VALUES (3, 'Guava pastelito', 'Flaky pastry filled with guava.', 'bakery', 295, 1, 0);
INSERT INTO menu_items (id, name, description, category, price_cents, available, supports_milk) VALUES (4, 'Ham croqueta', 'Crispy Cuban-style ham croquette.', 'snacks', 195, 0, 0);
INSERT INTO menu_items (id, name, description, category, price_cents, available, supports_milk) VALUES (5, 'Café Cubano', 'Rich Cuban espresso with a sweet crema.', 'coffee', 225, 1, 0);
INSERT INTO menu_items (id, name, description, category, price_cents, available, supports_milk) VALUES (6, 'Mariquitas', 'Crispy plantain chips served as a café snack.', 'snacks', 250, 1, 0);

INSERT INTO orders (id, customer_name, status, created_at) VALUES
    (1040, 'Carlos Perez', 'Ready', '2026-11-17 09:00:00'),
    (1041, 'Ana Lopez', 'Preparing', '2026-11-17 09:05:00'),
    (1042, 'Marta Rodriguez', 'Received', '2026-11-17 09:10:00');
INSERT INTO order_items (order_id, menu_item_id, quantity) VALUES
    (1040, 2, 1), (1041, 3, 1), (1042, 1, 2), (1042, 3, 1);
