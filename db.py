"""Request-scoped SQLite connection and explicit, destructive seed command."""
import sqlite3
import click
from flask import current_app, g
from flask.cli import with_appcontext


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db():
    connection = get_db()
    with current_app.open_resource("schema.sql") as source:
        connection.executescript(source.read().decode("utf-8"))
    connection.commit()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Erase existing data and rebuild tables and seed records."""
    init_db()
    click.echo("Initialized the database.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
