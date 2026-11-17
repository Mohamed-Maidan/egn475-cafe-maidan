import sys, sqlite3, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app import app
from db import get_db
with tempfile.TemporaryDirectory() as directory:
    app.config.update(TESTING=True,DATABASE=str(Path(directory)/'test.sqlite'))
    cli=app.test_cli_runner()
    for _ in range(2):
        result=cli.invoke(args=['init-db']); assert result.exit_code==0,result.output
    print(result.output.strip())
    with app.app_context():
        conn=get_db()
        print('Seed counts:', {t:conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['menu_items','orders','order_items']})
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0]==1
        try:
            conn.execute('INSERT INTO order_items (order_id, menu_item_id, quantity) VALUES (?, ?, ?)', (9999,1,1))
        except sqlite3.IntegrityError: conn.rollback(); print('Foreign key constraint: PASS')
        else: raise AssertionError('Foreign key failed')
    client=app.test_client()
    for route in ['/','/menu','/menu/1','/admin/menu/new','/kitchen','/orders','/order/new','/order/confirmation']:
        assert client.get(route).status_code==200,route
    assert client.get('/menu/999999').status_code==404
    print('Existing pages, database list/detail, and missing-id 404: PASS')
    assert client.post('/admin/menu/new',data={'name':'  ','price':'1','category':'coffee'}).status_code==400
    for price in ['-1','NaN','1.999','bad']:
        assert client.post('/admin/menu/new',data={'name':'Invalid','price':price,'category':'coffee'}).status_code==400
    for name,price,category in [('Cheese pastelito','3.25','bakery'),('Iced café con leche','4.50','coffee')]:
        r=client.post('/admin/menu/new',data={'name':name,'price':price,'category':category,'available':'1'})
        assert r.status_code==302 and r.location=='/menu'
    # A new client/request opens a new SQLite connection after teardown.
    assert b'Cheese pastelito' in app.test_client().get('/menu').data
    with app.app_context():
        rows=get_db().execute('SELECT name, price_cents FROM menu_items WHERE id > ? ORDER BY id',(6,)).fetchall()
        assert [r['price_cents'] for r in rows]==[325,450]
        print('Two POST saves, redirects, and persistence across connections:',[dict(r) for r in rows])
        get_db().execute('INSERT INTO menu_items (name, category, price_cents) VALUES (?, ?, ?)',('NO COMMIT TEST','coffee',100))
        print('Uncommitted row visible on same connection:',get_db().execute('SELECT COUNT(*) FROM menu_items WHERE name = ?',('NO COMMIT TEST',)).fetchone()[0])
    with app.app_context():
        count=get_db().execute('SELECT COUNT(*) FROM menu_items WHERE name = ?',('NO COMMIT TEST',)).fetchone()[0]
        assert count==0
        print('Uncommitted row after connection closes:',count)
    attack="Robert'); DROP TABLE menu_items; --"
    assert client.post('/admin/menu/new',data={'name':attack,'price':'1.25','category':'coffee','available':'1'}).status_code==302
    with app.app_context():
        assert get_db().execute('SELECT name FROM menu_items WHERE name = ?',(attack,)).fetchone()['name']==attack
    print('SQL-like input saved as literal text; table remains intact: PASS')
print('All checks passed. Isolated test database deleted; project seed database unchanged.')
