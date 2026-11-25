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
    for route in ['/','/menu','/menu/1','/admin/menu','/admin/menu/new','/kitchen','/orders','/order/new','/order/confirmation']:
        assert client.get(route).status_code==200,route
    assert client.get('/menu/999999').status_code==404
    assert client.get('/items/999999/edit').status_code==404
    assert client.get('/items/1/delete').status_code==405
    assert client.post('/items/999999/delete').status_code==404
    print('Existing pages, database list/detail, and missing-id 404: PASS')
    response=client.post('/admin/menu/new',data={'name':'  ','price':'1','category':'coffee'})
    assert response.status_code==400 and b'Name is required.' in response.data
    response=client.post('/admin/menu/new',data={
        'name':'.','price':'1','category':'coffee','description':'Keep this value',
    })
    assert response.status_code==400
    assert b'Include at least one letter or number in the item name.' in response.data
    assert b'value="."' in response.data and b'Keep this value' in response.data
    for price in ['0','-1','50.01','NaN','1.999','bad']:
        assert client.post('/admin/menu/new',data={'name':'Invalid','price':price,'category':'coffee'}).status_code==400
    for name,price,category in [('Café','3.25','bakery'),('Iced café con leche','4.50','coffee')]:
        r=client.post('/admin/menu/new',data={'name':name,'price':price,'category':category,'available':'1'})
        assert r.status_code==302 and r.location=='/menu'
    # A new client/request opens a new SQLite connection after teardown.
    assert b'Caf\xc3\xa9' in app.test_client().get('/menu').data
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
    edit_page=client.get('/items/1/edit')
    assert edit_page.status_code==200 and b'value="Caf' in edit_page.data and b'value="3.50"' in edit_page.data
    invalid_edits=[
        {'name':'  ','price':'2.00','category':'coffee'},
        {'name':'.','price':'2.00','category':'coffee'},
        {'name':'Invalid','price':'0','category':'coffee'},
        {'name':'Invalid','price':'50.01','category':'coffee'},
        {'name':'Invalid','price':'2.00','category':'invalid'},
    ]
    for invalid in invalid_edits:
        response=client.post('/items/1/edit',data=invalid)
        assert response.status_code==400
        assert invalid['name'].encode() in response.data
        assert ('value="'+invalid['price']+'"').encode() in response.data
    response=client.post('/items/1/edit',data={
        'name':'.','price':'2.00','category':'coffee',
    })
    assert response.status_code==400
    assert b'Include at least one letter or number in the item name.' in response.data
    assert b'value="."' in response.data
    response=client.post('/items/1/edit',data={
        'name':'Keep these values','price':'0','category':'bakery',
        'description':'Keep this description','available':'1','supports_milk':'1',
    })
    assert response.status_code==400
    assert b'Keep this description' in response.data
    assert b'name="available" type="checkbox" value="1" checked' in response.data
    assert b'name="supports_milk" type="checkbox" value="1" checked' in response.data
    response=client.post('/items/1/edit',data={
        'name':'Edited café con leche','price':'50','category':'coffee',
        'description':'Updated description','available':'1','supports_milk':'1',
    })
    assert response.status_code==302 and response.location=='/admin/menu'
    staff_list=client.get(response.location)
    assert b'Edited caf' in staff_list.data
    assert b'updated successfully.' in staff_list.data
    with app.app_context():
        edited=get_db().execute(
            'SELECT name, category, price_cents, description, available, supports_milk '
            'FROM menu_items WHERE id = ?', (1,)
        ).fetchone()
        assert tuple(edited)==('Edited café con leche','coffee',5000,'Updated description',1,1)
    print('Edit prefill, validation, parameterized update, commit, flash, and redirect: PASS')
    staff_list=client.get('/admin/menu')
    assert b"confirm('Delete this item?')" in staff_list.data
    assert b'method="post"' in staff_list.data
    response=client.post('/items/1/delete')
    assert response.status_code==302 and response.location=='/admin/menu'
    staff_list=client.get(response.location)
    assert b'Edited caf' in staff_list.data
    assert b'marked unavailable.' in staff_list.data
    with app.app_context():
        item=get_db().execute(
            'SELECT available FROM menu_items WHERE id = ?', (1,)
        ).fetchone()
        assert item['available']==0
        assert get_db().execute(
            'SELECT COUNT(*) FROM order_items WHERE menu_item_id = ?', (1,)
        ).fetchone()[0] > 0
    response=client.post('/items/6/delete')
    assert response.status_code==302 and response.location=='/admin/menu'
    staff_list=client.get(response.location)
    assert b'Mariquitas was deleted.' in staff_list.data
    with app.app_context():
        assert get_db().execute(
            'SELECT id FROM menu_items WHERE id = ?', (6,)
        ).fetchone() is None
    print('Delete confirmation, referenced-item preservation, unreferenced delete, flash, and redirect: PASS')
    assert client.get('/orders/1042/status').status_code==405
    board=client.get('/kitchen')
    assert b'<mark>received</mark>' in board.data
    assert b'name="status" value="Preparing"' in board.data
    response=client.post('/orders/1042/status',data={'status':'Preparing'})
    assert response.status_code==302 and response.location=='/kitchen'
    with app.app_context():
        status=get_db().execute(
            'SELECT status FROM orders WHERE id = ?', (1042,)
        ).fetchone()['status']
        assert status=='Preparing'
    response=client.post('/orders/1042/status',data={'status':'Preparing'})
    assert response.status_code==302 and response.location=='/kitchen'
    board=client.get(response.location)
    assert b'role="alert"' in board.data and b'This order has moved on.' in board.data
    with app.app_context():
        status=get_db().execute(
            'SELECT status FROM orders WHERE id = ?', (1042,)
        ).fetchone()['status']
        assert status=='Preparing'
    for next_status,expected in [('Ready','Ready'),('Picked up','Picked up')]:
        response=client.post('/orders/1042/status',data={'status':next_status})
        assert response.status_code==302 and response.location=='/kitchen'
        with app.app_context():
            status=get_db().execute(
                'SELECT status FROM orders WHERE id = ?', (1042,)
            ).fetchone()['status']
            assert status==expected
    board=client.get('/kitchen')
    assert b'<mark>picked up</mark>' in board.data
    assert b'action="/orders/1042/status"' not in board.data
    response=client.post('/orders/1042/status',data={})
    assert response.status_code==302 and response.location=='/kitchen'
    with app.app_context():
        status=get_db().execute(
            'SELECT status FROM orders WHERE id = ?', (1042,)
        ).fetchone()['status']
        assert status=='Picked up'
    print('Kitchen status transitions, stale move rejection, persisted final badge, and POST-only route: PASS')
print('All checks passed. Isolated test database deleted; project seed database unchanged.')
