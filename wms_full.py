#!/usr/bin/env python3
"""
WMS Warehouse Management System - Single File Flask App
Uses Feishu Bitable API as data storage
"""
import os, json, time, http.client, urllib.parse
from datetime import datetime
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
app.secret_key = os.urandom(24)

FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', '')
APP_TOKEN = os.environ.get('FEISHU_APP_TOKEN', 'JajpbgTYPaABHwscQt6cc8FBnhd')
PORT = int(os.environ.get('PORT', 10000))

TABLES = {
    'Material_Master': 'tblxDgMgYBLdo4SM',
    'Store_Master': 'tbldgnfPzUtECSF5',
    'Contact_Master': 'tblRnTtZoiz8pACk',
    'Receiver_Master': 'tbltk49GR8y6tYhh',
    'Region_Config': 'tbleSOGLdkuPvj543',
    'Inbound': 'tblovFMwOvIOtPmn',
    'Outbound_Batch': 'tblWqCNtfFQ5aafD',
    'Outbound_Record': 'tblxRHYmxlMFRlHa',
    'Request': 'tbluO7aooUImAh0i',
    'Stock': 'tblctz10sRKDTx7Z',
    'Scrap': 'tbldBRM87JBNWxK9',
    'Consumption_History': 'tblSLbnfpmE9ld33',
}

_token_cache = {'token': None, 'expires': 0}

def get_tenant_token():
    now = time.time()
    if _token_cache['token'] and _token_cache['expires'] > now + 60:
        return _token_cache['token']
    body = json.dumps({'app_id': FEISHU_APP_ID, 'app_secret': FEISHU_APP_SECRET})
    conn = http.client.HTTPSConnection('open.feishu.cn')
    conn.request('POST', '/open-apis/auth/v3/tenant_access_token/internal',
                 body=body, headers={'Content-Type': 'application/json; charset=utf-8'})
    resp = conn.getresponse()
    data = json.loads(resp.read().decode('utf-8'))
    conn.close()
    if data.get('code') == 0:
        _token_cache['token'] = data['tenant_access_token']
        _token_cache['expires'] = now + data.get('expire', 7200)
        return _token_cache['token']
    raise Exception(f'Token error: {data}')

def feishu_request(method, path, body=None, params=None):
    token = get_tenant_token()
    url_path = path
    if params:
        url_path += '?' + urllib.parse.urlencode(params)
    conn = http.client.HTTPSConnection('open.feishu.cn')
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json; charset=utf-8'}
    conn.request(method, url_path, body=json.dumps(body) if body else None, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode('utf-8')
    conn.close()
    return json.loads(data)

def bitable_list(table_id, filter_expr=None, page_size=100, page_token=None):
    params = {'page_size': str(page_size)}
    if page_token: params['page_token'] = page_token
    if filter_expr: params['filter'] = filter_expr
    return feishu_request('GET', f'/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records', params=params)

def bitable_create(table_id, fields):
    return feishu_request('POST', f'/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records', body={'fields': fields})

def bitable_update(table_id, record_id, fields):
    return feishu_request('PUT', f'/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}', body={'fields': fields})

def bitable_delete(table_id, record_id):
    return feishu_request('DELETE', f'/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}')

def get_all_records(table_id, filter_expr=None, max_pages=10):
    all_records = []
    page_token = None
    for _ in range(max_pages):
        result = bitable_list(table_id, filter_expr=filter_expr, page_token=page_token, page_size=100)
        if result.get('code') != 0: break
        all_records.extend(result.get('data', {}).get('items', []))
        if not result.get('data', {}).get('has_more', False): break
        page_token = result.get('data', {}).get('page_token')
    return all_records

def generate_code(prefix, table_id, field_name):
    records = get_all_records(table_id)
    max_num = 0
    for r in records:
        code = r.get('fields', {}).get(field_name, '')
        if code and code.startswith(prefix) and len(code) == len(prefix) + 4:
            try: max_num = max(max_num, int(code[len(prefix):]))
            except ValueError: pass
    return f'{prefix}{max_num + 1:04d}'

# Read HTML from companion file
HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
def get_html():
    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        return f.read()

@app.route('/')
def index():
    return Response(get_html(), content_type='text/html; charset=utf-8')

@app.route('/api/token-check')
def token_check():
    try:
        t = get_tenant_token()
        return jsonify({'ok': True, 'token_preview': t[:8] + '...'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/<table_name>')
def api_list(table_name):
    # Case-insensitive table name lookup
    real_name = None
    for k in TABLES:
        if k.lower() == table_name.lower():
            real_name = k
            break
    if not real_name: return jsonify({'error': 'Unknown table'}), 404
    table_id = TABLES[real_name]
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 20))
    search = request.args.get('search', '').strip()
    filter_expr = request.args.get('filter', '')
    result = bitable_list(table_id, filter_expr=filter_expr or None, page_size=200)
    if result.get('code') != 0:
        return jsonify({'error': result.get('msg', 'API error'), 'code': result.get('code')}), 500
    records = []
    for item in result.get('data', {}).get('items', []):
        fields = item.get('fields', {})
        fields['_record_id'] = item.get('record_id', '')
        records.append(fields)
    if search:
        sl = search.lower()
        records = [r for r in records if any(sl in str(v).lower() for v in r.values() if v)]
    total = len(records)
    start = (page - 1) * page_size
    return jsonify({'data': records[start:start+page_size], 'total': total, 'page': page,
                    'page_size': page_size, 'total_pages': (total + page_size - 1) // page_size})

@app.route('/api/<table_name>', methods=['POST'])
def api_create(table_name):
    real_name = None
    for k in TABLES:
        if k.lower() == table_name.lower():
            real_name = k
            break
    if not real_name: return jsonify({'error': 'Unknown table'}), 404
    data = request.get_json()
    if not data: return jsonify({'error': 'No data'}), 400
    result = bitable_create(TABLES[table_name], data)
    if result.get('code') != 0: return jsonify({'error': result.get('msg')}), 500
    return jsonify({'ok': True, 'data': result.get('data', {}).get('record', {})})

@app.route('/api/<table_name>/<record_id>', methods=['PUT'])
def api_update(table_name, record_id):
    real_name = None
    for k in TABLES:
        if k.lower() == table_name.lower():
            real_name = k
            break
    if not real_name: return jsonify({'error': 'Unknown table'}), 404
    data = request.get_json()
    if not data: return jsonify({'error': 'No data'}), 400
    result = bitable_update(TABLES[table_name], record_id, data)
    if result.get('code') != 0: return jsonify({'error': result.get('msg')}), 500
    return jsonify({'ok': True, 'data': result.get('data', {}).get('record', {})})

@app.route('/api/<table_name>/<record_id>', methods=['DELETE'])
def api_delete(table_name, record_id):
    real_name = None
    for k in TABLES:
        if k.lower() == table_name.lower():
            real_name = k
            break
    if not real_name: return jsonify({'error': 'Unknown table'}), 404
    result = bitable_delete(TABLES[table_name], record_id)
    if result.get('code') != 0: return jsonify({'error': result.get('msg')}), 500
    return jsonify({'ok': True})

# Business APIs
@app.route('/api/inbound/create', methods=['POST'])
def inbound_create():
    data = request.get_json()
    code = generate_code('IB', TABLES['Inbound'], 'Inbound Code')
    data['Inbound Code'] = code
    data['Record Status'] = 'Planned'
    data['Actual Inbound Qty'] = 0
    result = bitable_create(TABLES['Inbound'], data)
    if result.get('code') != 0: return jsonify({'error': result.get('msg')}), 500
    return jsonify({'ok': True, 'code': code, 'data': result.get('data', {}).get('record', {})})

@app.route('/api/inbound/confirm/<record_id>', methods=['POST'])
def inbound_confirm(record_id):
    data = request.get_json() or {}
    actual_qty = data.get('actual_qty', 0)
    result = bitable_update(TABLES['Inbound'], record_id, {'Actual Inbound Qty': actual_qty, 'Record Status': 'Completed'})
    if result.get('code') != 0: return jsonify({'error': result.get('msg')}), 500
    rec = result.get('data', {}).get('record', {})
    fields = rec.get('fields', {})
    mc, mn, dept = fields.get('Material Code',''), fields.get('Material Name',''), fields.get('Material Department','')
    if mc and actual_qty > 0:
        stock_records = get_all_records(TABLES['Stock'])
        existing = next((sr for sr in stock_records if sr.get('fields',{}).get('Material Code') == mc), None)
        if existing:
            sf = existing.get('fields', {})
            cq, ca = sf.get('Stock Qty',0) or 0, sf.get('Available Qty',0) or 0
            bitable_update(TABLES['Stock'], existing['record_id'], {'Stock Qty': cq+actual_qty, 'Available Qty': ca+actual_qty})
        else:
            bitable_create(TABLES['Stock'], {'Material Code':mc,'Material Name':mn,'Stock Qty':actual_qty,'Available Qty':actual_qty,'Plan Allocation Qty':0,'Wait Repair Qty':0,'Material Department':dept})
    return jsonify({'ok': True})

@app.route('/api/request/create', methods=['POST'])
def request_create():
    data = request.get_json()
    code = generate_code('REQ', TABLES['Request'], 'Request Code')
    data['Request Code'] = code
    data['Approval Status'] = 'Pending'
    result = bitable_create(TABLES['Request'], data)
    if result.get('code') != 0: return jsonify({'error': result.get('msg')}), 500
    return jsonify({'ok': True, 'code': code})

@app.route('/api/request/approve/<record_id>', methods=['POST'])
def request_approve(record_id):
    data = request.get_json() or {}
    result = bitable_update(TABLES['Request'], record_id, {'Approval Status':'Approved','Approved Qty':data.get('approved_qty',0)})
    if result.get('code') != 0: return jsonify({'error': result.get('msg')}), 500
    return jsonify({'ok': True})

@app.route('/api/request/reject/<record_id>', methods=['POST'])
def request_reject(record_id):
    result = bitable_update(TABLES['Request'], record_id, {'Approval Status':'Rejected'})
    if result.get('code') != 0: return jsonify({'error': result.get('msg')}), 500
    return jsonify({'ok': True})

@app.route('/api/outbound/create-batch', methods=['POST'])
def outbound_create_batch():
    data = request.get_json() or {}
    code = generate_code('OB', TABLES['Outbound_Batch'], 'Batch Code')
    result = bitable_create(TABLES['Outbound_Batch'], {'Batch Code':code,'Batch Status':'Created','Included Request Count':data.get('request_count',0)})
    if result.get('code') != 0: return jsonify({'error': result.get('msg')}), 500
    return jsonify({'ok': True, 'code': code})

@app.route('/api/outbound/confirm-receive/<record_id>', methods=['POST'])
def outbound_confirm_receive(record_id):
    data = request.get_json() or {}
    result = bitable_update(TABLES['Outbound_Record'], record_id, {'Shipment Status':'Received','Confirmed Receive Qty':data.get('qty',0)})
    if result.get('code') != 0: return jsonify({'error': result.get('msg')}), 500
    return jsonify({'ok': True})

@app.route('/api/stock/scrap', methods=['POST'])
def stock_scrap():
    data = request.get_json()
    mc, sq, reason = data.get('material_code',''), data.get('scrap_qty',0), data.get('reason','')
    for sr in get_all_records(TABLES['Stock']):
        sf = sr.get('fields', {})
        if sf.get('Material Code') == mc:
            cq, ca = sf.get('Stock Qty',0) or 0, sf.get('Available Qty',0) or 0
            bitable_update(TABLES['Stock'], sr['record_id'], {'Stock Qty':max(0,cq-sq),'Available Qty':max(0,ca-sq)})
            break
    bitable_create(TABLES['Scrap'], {'Material Code':mc,'Scrap Qty':sq,'Reason':reason,'Scrap Date':datetime.now().strftime('%Y-%m-%d')})
    return jsonify({'ok': True})

@app.route('/api/dashboard/stats')
def dashboard_stats():
    stats = {}
    for name, tid in TABLES.items():
        result = bitable_list(tid, page_size=1)
        stats[name] = result.get('data',{}).get('total',0) if result.get('code')==0 else 0
    stock_records = get_all_records(TABLES['Stock'])
    ts, ta, dd = 0, 0, {}
    for sr in stock_records:
        sf = sr.get('fields', {})
        q = float(sf.get('Stock Qty',0) or 0)
        a = float(sf.get('Available Qty',0) or 0)
        d = sf.get('Material Department','Unknown') or 'Unknown'
        ts += q; ta += a; dd[d] = dd.get(d,0) + q
    stats['total_stock'] = ts; stats['total_available'] = ta; stats['dept_distribution'] = dd
    return jsonify(stats)

@app.route('/api/materials/all')
def materials_all():
    return jsonify([{'code':r.get('fields',{}).get('Material Code',''),'name':r.get('fields',{}).get('Material Name',''),'dept':r.get('fields',{}).get('Material Department',''),'uom':r.get('fields',{}).get('UOM',''),'spec':r.get('fields',{}).get('Spec','')} for r in get_all_records(TABLES['Material_Master'])])

@app.route('/api/regions/all')
def regions_all():
    return jsonify([r.get('fields',{}).get('Region Name','') for r in get_all_records(TABLES['Region_Config']) if r.get('fields',{}).get('Status')=='Active'])

@app.route('/api/receivers/all')
def receivers_all():
    return jsonify([{'name':r.get('fields',{}).get('Name',''),'mi_id':r.get('fields',{}).get('MI ID',''),'phone':r.get('fields',{}).get('Phone',''),'region':r.get('fields',{}).get('Region',''),'dept':r.get('fields',{}).get('Department','')} for r in get_all_records(TABLES['Receiver_Master'])])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)
