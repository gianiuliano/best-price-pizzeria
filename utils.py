import pandas as pd

def effective_unit_price(row, desired_qty:int=1):
    price = float(row['unit_price'])
    pbq = row.get('price_break_qty')
    try:
        if pd.notna(pbq) and desired_qty >= int(pbq):
            return float(row.get('price_break_unit_price', price))
    except Exception:
        pass
    return price

def load_all():
    vendors = pd.read_csv('data/vendors.csv')
    items = pd.read_csv('data/items.csv')
    vendor_items = pd.read_csv('data/vendor_items.csv')
    return vendors, items, vendor_items

def compute_best(vendors, items, vendor_items, qty:int=1, selected_lines=None):
    df_items = items.copy()
    if selected_lines:
        df_items = df_items[df_items['line'].isin(selected_lines)]
    vi = vendor_items.merge(df_items[['item_id','name','unit','line']], on='item_id', how='inner')
    vi = vi.merge(
        vendors[['vendor_id','name','email','min_order_amount','lead_time_days']].rename(columns={'name':'vendor_name'}),
        on='vendor_id', how='left'
    )
    vi['eff_unit_price'] = vi.apply(lambda r: effective_unit_price(r, qty), axis=1)
    idx = vi.groupby('item_id')['eff_unit_price'].idxmin()
    best = vi.loc[idx, ['item_id','name','line','vendor_id','vendor_name','email','vendor_sku','pack_size',
                        'unit','eff_unit_price','unit_price','price_break_qty','price_break_unit_price']].copy()
    best = best.sort_values(['line','name']).reset_index(drop=True)

    # ranking por línea
    cheapest = vi.loc[idx, ['item_id','name','line','vendor_id','vendor_name','eff_unit_price']]
    wins = cheapest.groupby(['line','vendor_id','vendor_name'])['item_id'].count().rename('cheapest_wins').reset_index()
    coverage = vi.groupby(['line','vendor_id','vendor_name'])['item_id'].nunique().rename('coverage_items').reset_index()
    avg_price = vi.groupby(['line','vendor_id','vendor_name'])['eff_unit_price'].mean().rename('avg_price_offered').reset_index()
    board = wins.merge(coverage, on=['line','vendor_id','vendor_name'], how='outer') \
                .merge(avg_price, on=['line','vendor_id','vendor_name'], how='outer')
    board['cheapest_wins'] = board['cheapest_wins'].fillna(0).astype(int)
    board = board.sort_values(['line','cheapest_wins','avg_price_offered'], ascending=[True, False, True]).reset_index(drop=True)
    return best, board, vi

def build_vendor_orders(cart_df, vendors_df):
    cart_df = cart_df.copy()
    cart_df['extended'] = cart_df['qty'] * cart_df['eff_unit_price']
    grouped = {}
    for vid, block in cart_df.groupby('vendor_id'):
        vendor = vendors_df[vendors_df['vendor_id']==vid].iloc[0]
        subtotal = round(block['extended'].sum(), 2)
        grouped[vid] = {
            'vendor_name': vendor['name'],
            'email': vendor['email'],
            'min_order_amount': float(vendor['min_order_amount']),
            'lead_time_days': int(vendor['lead_time_days']),
            'subtotal': subtotal,
            'items': block.to_dict(orient='records')
        }
    return grouped

def vendor_email_body(vendor_block, location_name='La Leggenda - Miami Beach'):
    lines = []
    for i, r in enumerate(vendor_block['items'], start=1):
        lines.append(f"{i}. {r['name']} ({r['item_id']}) — {r['qty']} {r['unit']} @ ${r['eff_unit_price']:.2f} "
                     f"= ${r['extended']:.2f}  | SKU Prov: {r['vendor_sku']}")
    warn = ''
    if vendor_block['subtotal'] < vendor_block['min_order_amount']:
        warn = (f"\n⚠️ Aviso: Subtotal ${vendor_block['subtotal']:.2f} "
                f"está por debajo del mínimo del proveedor (${vendor_block['min_order_amount']:.2f}).")
    body = f"""Subject: Purchase Order — {location_name}

Hola {vendor_block['vendor_name']},

Por favor confirmar el siguiente pedido:

{chr(10).join(lines)}

Subtotal: ${vendor_block['subtotal']:.2f}{warn}

Gracias,
Compras — {location_name}
"""
    return body
