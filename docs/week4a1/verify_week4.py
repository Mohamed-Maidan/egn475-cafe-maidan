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
    response=client.post('/admin/menu/new',data={
        'name':'.','price':'50.01','category':'invalid',
    })
    assert response.status_code==400
    assert b'Include at least one letter or number in the item name.' in response.data
    assert b'Choose a valid category.' in response.data
    assert b'Enter a price greater than $0 and at most $50' in response.data
    assert b'<option value="invalid" selected>invalid</option>' in response.data
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
        'name':'.','price':'50.01','category':'invalid',
        'description':'Keep edit values',
    })
    assert response.status_code==400
    assert b'Include at least one letter or number in the item name.' in response.data
    assert b'Choose a valid category.' in response.data
    assert b'Enter a price greater than $0 and at most $50' in response.data
    assert b'value="."' in response.data
    assert b'value="50.01"' in response.data
    assert b'<option value="invalid" selected>invalid</option>' in response.data
    assert b'Keep edit values' in response.data
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
    order_page=client.get('/order/new')
    assert order_page.status_code==200
    assert b'method="post"' in order_page.data
    assert b'name="quantity_2"' in order_page.data
    assert b'min="0" max="20" step="1"' in order_page.data
    assert b'Ham croqueta' not in order_page.data
    response=client.post('/order/new',data={
        'pickup':'  ','notes':'Preserve this note','quantity_2':'1',
    })
    assert response.status_code==400
    assert b'Pickup name is required.' in response.data
    assert b'value="1"' in response.data and b'Preserve this note' in response.data
    response=client.post('/order/new',data={
        'pickup':'Marta','quantity_2':'0',
    })
    assert response.status_code==400 and b'Select at least one menu item.' in response.data
    for quantity,message in [
        ('-1','whole number from 0 to 20'),
        ('1.5','whole number from 0 to 20'),
        ('abc','whole number from 0 to 20'),
        ('21','cannot exceed 20'),
    ]:
        response=client.post('/order/new',data={
            'pickup':'Marta','notes':'Preserve this note','quantity_2':quantity,
        })
        assert response.status_code==400 and message.encode() in response.data
        assert ('value="'+quantity+'"').encode() in response.data
        assert b'Preserve this note' in response.data
    response=client.post('/order/new',data={
        'pickup':'Marta','quantity_4':'1',
    })
    assert response.status_code==400 and b'Ham croqueta is no longer available.' in response.data
    assert b'value="1"' in response.data
    response=client.post('/order/new',data={
        'pickup':'Marta','quantity_999':'1',
    })
    assert response.status_code==400
    assert b'A selected menu item could not be found.' in response.data
    with app.app_context():
        orders_before=get_db().execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    response=client.post('/order/new',data={
        'pickup':'Marta Rodriguez','notes':'No sugar',
        'quantity_2':'20','quantity_3':'1','quantity_5':'0','price_2':'0.01',
    })
    assert response.status_code==302
    assert response.location.startswith('/order/confirmation?order_id=')
    order_id=int(response.location.rsplit('=',1)[1])
    confirmation=client.get(response.location)
    assert confirmation.status_code==200
    assert f'Order #{order_id} placed successfully.'.encode() in confirmation.data
    assert b'Total: $57.95.' in confirmation.data
    assert b'$57.95' in confirmation.data
    assert b'No sugar' in confirmation.data
    with app.app_context():
        saved=get_db().execute(
            'SELECT customer_name, status, notes FROM orders WHERE id = ?', (order_id,)
        ).fetchone()
        assert tuple(saved)==('Marta Rodriguez','Received','No sugar')
        lines=get_db().execute(
            'SELECT menu_item_id, quantity FROM order_items '
            'WHERE order_id = ? ORDER BY menu_item_id', (order_id,)
        ).fetchall()
        assert [tuple(line) for line in lines]==[(2,20),(3,1)]
        assert get_db().execute('SELECT COUNT(*) FROM orders').fetchone()[0]==orders_before+1
    assert client.get(response.location).status_code==200
    with app.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM orders').fetchone()[0]==orders_before+1
    kitchen_page=client.get('/kitchen')
    assert str(order_id).encode() in kitchen_page.data
    assert b'20 \xc3\x97 Cortadito' in kitchen_page.data
    print('Order creation, server validation, database prices, Kitchen Board display, and refresh-safe GET confirmation: PASS')
    with app.app_context():
        connection=get_db()
        orders_before=get_db().execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        items_before=get_db().execute('SELECT COUNT(*) FROM order_items').fetchone()[0]
        connection.execute(
            "CREATE TRIGGER fail_order_item_insert BEFORE INSERT ON order_items "
            "WHEN NEW.menu_item_id = 3 BEGIN "
            "SELECT RAISE(ABORT, 'test order-item failure'); END"
        )
        connection.commit()
    response=client.post('/order/new',data={
        'pickup':'Marta','quantity_2':'1','quantity_3':'1',
    })
    assert response.status_code==400
    assert b'The order could not be saved.' in response.data
    assert b'value="1"' in response.data
    with app.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM orders').fetchone()[0]==orders_before
        assert get_db().execute('SELECT COUNT(*) FROM order_items').fetchone()[0]==items_before
    print('Order and order_items rollback after a forced insert failure: PASS')
print('All checks passed. Isolated test database deleted; project seed database unchanged.')
