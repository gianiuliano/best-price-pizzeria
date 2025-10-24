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
# ===== FOOD COST / RECETAS =====

# Conversión simple opcional (actívala si lo necesitas)
UNIT_FACTORS = {
    ('kg','g'): 1000.0,
    ('g','kg'): 1/1000.0,
    ('L','ml'): 1000.0,
    ('ml','L'): 1/1000.0,
    ('lb','oz'): 16.0,
    ('oz','lb'): 1/16.0,
}

def convert_qty(qty, from_u, to_u):
    if from_u == to_u:
        return float(qty)
    key = (from_u, to_u)
    if key in UNIT_FACTORS:
        return float(qty) / UNIT_FACTORS[(to_u, from_u)] if (to_u, from_u) in UNIT_FACTORS else float(qty) * UNIT_FACTORS[key]
    # Si no hay conversión conocida, asumimos misma unidad (MVP)
    return float(qty)

def build_item_cost_map(vendors, items, vendor_items, qty_for_breaks:int=1):
    """
    Devuelve dict {item_id: {'cost_per_unit': float, 'unit': str, 'vendor_id': str, 'vendor_name': str}}
    usando el mejor precio efectivo (con price breaks según qty_for_breaks).
    """
    # Reusa tu función de best price
    from utils import compute_best  # importe local para evitar ciclos
    best, _, _ = compute_best(vendors, items, vendor_items, qty=qty_for_breaks, selected_lines=None)
    best_map = {}
    for _, r in best.iterrows():
        best_map[r['item_id']] = {
            'cost_per_unit': float(r['eff_unit_price']),
            'unit': r['unit'],
            'vendor_id': r['vendor_id'],
            'vendor_name': r['vendor_name']
        }
    return best_map

def compute_recipe_costs(recipes_df, recipe_items_df, items_df, item_cost_map, default_waste_pct=0.0):
    """
    Calcula costo por receta y por porción.
    Retorna (resumen_df, detalle_df)
    """
    details = []
    for _, row in recipe_items_df.iterrows():
        rid = row['recipe_id']
        iid = row['item_id']
        qty = float(row['qty'])
        unit = str(row['unit'])
        waste = float(row.get('waste_pct', default_waste_pct) or 0.0)

        # información del item (unidad base)
        item_row = items_df[items_df['item_id']==iid]
        if item_row.empty or iid not in item_cost_map:
            # ítem sin costo disponible → lo saltamos o lo marcamos
            details.append({
                'recipe_id': rid, 'item_id': iid, 'item_name': '(ITEM SIN COSTO)',
                'qty': qty, 'unit': unit, 'waste_pct': waste,
                'unit_cost': 0.0, 'unit_base': unit, 'qty_in_base': qty, 'extended': 0.0,
                'vendor_name': ''
            })
            continue

        item_name = item_row.iloc[0]['name']
        base_unit = item_cost_map[iid]['unit']
        unit_cost = item_cost_map[iid]['cost_per_unit']
        vendor_name = item_cost_map[iid]['vendor_name']

        # convertir cantidad a la unidad base de costo si hace falta
        qty_in_base = convert_qty(qty, unit, base_unit)
        # aplicar merma (waste)
        effective_qty = qty_in_base * (1.0 + waste)
        extended = effective_qty * unit_cost

        details.append({
            'recipe_id': rid, 'item_id': iid, 'item_name': item_name,
            'qty': qty, 'unit': unit, 'waste_pct': waste,
            'unit_cost': unit_cost, 'unit_base': base_unit,
            'qty_in_base': effective_qty, 'extended': extended,
            'vendor_name': vendor_name
        })

    detail_df = pd.DataFrame(details)

    # resumen por receta
    summary_rows = []
    for _, r in recipes_df.iterrows():
        rid = r['recipe_id']
        sub = detail_df[detail_df['recipe_id']==rid]
        recipe_cost = float(sub['extended'].sum()) if not sub.empty else 0.0
        portions = float(r.get('portions', 1) or 1)
        cost_per_portion = recipe_cost / portions if portions > 0 else recipe_cost
        target_pct = float(r.get('target_food_cost_pct', 0.30) or 0.30)
        suggested_price = cost_per_portion / target_pct if target_pct > 0 else 0.0

        summary_rows.append({
            'recipe_id': rid,
            'recipe_name': r['recipe_name'],
            'recipe_cost': round(recipe_cost, 2),
            'portions': portions,
            'cost_per_portion': round(cost_per_portion, 2),
            'target_food_cost_pct': target_pct,
            'suggested_price': round(suggested_price, 2)
        })
    summary_df = pd.DataFrame(summary_rows)
    return summary_df, detail_df
