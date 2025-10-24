import streamlit as st
import pandas as pd
from utils import load_all, compute_best, build_vendor_orders, vendor_email_body
# NUEVO (para recetas)
from utils import build_item_cost_map, compute_recipe_costs

st.set_page_config(page_title='Best Price • Pizzería', layout='wide')

@st.cache_data
def get_data():
    return load_all()

vendors, items, vendor_items = get_data()
# Cargar CSV de recetas
recipes = pd.read_csv('data/recipes.csv')
recipe_items = pd.read_csv('data/recipe_items.csv')

st.title("🍕 Best Price • Pizzería")
st.caption("Compara precios por producto y línea, arma carrito y genera órdenes por proveedor.")

with st.sidebar:
    st.header("Parámetros")
    qty = st.number_input("Cantidad objetivo (activa price breaks)", min_value=1, value=1, step=1)
    lines = sorted(items['line'].dropna().unique().tolist())
    selected_lines = st.multiselect("Filtrar por líneas", options=lines, default=lines)

best, board, vi = compute_best(vendors, items, vendor_items, qty, selected_lines)

tab1, tab2, tab3, tab4 = st.tabs(["Mejor precio", "Ranking proveedores", "Armar orden", "Recetas & Food Cost"])

with tab1:
    st.subheader("🏷️ Mejor precio por producto")
    show = best[['item_id','name','line','vendor_name','vendor_sku','pack_size','unit','eff_unit_price']].rename(columns={
        'item_id':'SKU','name':'Producto','line':'Línea','vendor_name':'Proveedor',
        'vendor_sku':'SKU Proveedor','pack_size':'Pack','unit':'UOM','eff_unit_price':'Precio'
    })
    st.dataframe(show, use_container_width=True)
    csv = best.to_csv(index=False).encode('utf-8')
    st.download_button("Descargar CSV (mejor precio)", csv, file_name="best_price_per_product.csv", mime="text/csv")

with tab2:
    st.subheader("🥇 Ranking de proveedores por línea")
    showb = board[['line','vendor_name','cheapest_wins','coverage_items','avg_price_offered']].rename(columns={
        'line':'Línea','vendor_name':'Proveedor','cheapest_wins':'# Ítems más barato',
        'coverage_items':'Cobertura','avg_price_offered':'Precio medio'
    })
    st.dataframe(showb, use_container_width=True)
    csvb = board.to_csv(index=False).encode('utf-8')
    st.download_button("Descargar CSV (ranking proveedores)", csvb, file_name="best_vendors_by_line.csv", mime="text/csv")

with tab3:
    st.subheader("🛒 Carrito y Orden por proveedor")
    st.write("Selecciona productos y cantidades para armar tu pedido.")

    sel = st.multiselect("Agrega productos al carrito", options=best['name'].tolist(), default=[])
    default_qty = st.number_input("Cantidad a agregar (por ítem seleccionado)", min_value=1, value=1, step=1)

    if "cart" not in st.session_state:
        st.session_state.cart = pd.DataFrame(columns=[
            'item_id','name','line','vendor_id','vendor_name','vendor_sku','unit','eff_unit_price','qty'
        ])

    if st.button("➕ Agregar seleccionados"):
        to_add = best[best['name'].isin(sel)].copy()
        if not to_add.empty:
            to_add = to_add[['item_id','name','line','vendor_id','vendor_name','vendor_sku','unit','eff_unit_price']]
            to_add['qty'] = default_qty
            st.session_state.cart = pd.concat([st.session_state.cart, to_add], ignore_index=True)

    if not st.session_state.cart.empty:
        st.write("**Carrito actual** (puedes editar cantidades):")
        cart_edit = st.data_editor(st.session_state.cart, num_rows="dynamic", use_container_width=True, key="cart_editor")
        st.session_state.cart = cart_edit

        orders = build_vendor_orders(st.session_state.cart, vendors)

        st.markdown("---")
        st.subheader("📦 Órdenes por proveedor")
        for vid, block in orders.items():
            warn = ""
            if block['subtotal'] < block['min_order_amount']:
                warn = f" | ⚠️ Por debajo del mínimo ${block['min_order_amount']:.2f}"
            st.markdown(f"**{block['vendor_name']}** — Subtotal: **${block['subtotal']:.2f}**{warn}  \nEmail: `{block['email']}`")
            df = pd.DataFrame(block['items'])[['item_id','name','line','vendor_sku','unit','qty','eff_unit_price','extended']] \
                    .rename(columns={'item_id':'SKU','name':'Producto','line':'Línea','vendor_sku':'SKU Prov','unit':'UOM',
                                     'qty':'Cant','eff_unit_price':'Precio','extended':'Importe'})
            st.dataframe(df, use_container_width=True)
            st.download_button(f"⬇️ Descargar CSV — {block['vendor_name']}",
                               df.to_csv(index=False).encode('utf-8'),
                               file_name=f"PO_{block['vendor_name'].replace(' ','_')}.csv",
                               mime="text/csv")
            st.code(vendor_email_body(block), language="markdown")
    else:
        st.info("El carrito está vacío. Agrega productos desde el listado de Mejor precio.")
with tab4:
    st.subheader("🍳 Recetas & Food Cost")
    st.caption("Calcula el costo de cada receta usando el mejor precio actual por ingrediente.")

    # Cantidad para evaluar price breaks en el costo de ingredientes
    qty_for_breaks = st.number_input("Cantidad para price breaks (cálculo de costos)", min_value=1, value=1, step=1)

    # Mapa de costos por ítem (usa el mejor precio actual)
    item_cost_map = build_item_cost_map(vendors, items, vendor_items, qty_for_breaks=qty_for_breaks)

    # Cálculo de costos de recetas
    summary_df, detail_df = compute_recipe_costs(recipes, recipe_items, items, item_cost_map)

    # --- Resumen por receta ---
    st.markdown("#### Resumen por receta")
    show_sum = summary_df[['recipe_name','recipe_cost','portions','cost_per_portion','target_food_cost_pct','suggested_price']]\
        .rename(columns={'recipe_name':'Receta','recipe_cost':'Costo Receta','portions':'Porciones',
                         'cost_per_portion':'Costo/Porción','target_food_cost_pct':'% Objetivo',
                         'suggested_price':'Precio Sugerido'})
    st.dataframe(show_sum, use_container_width=True)
    st.download_button("⬇️ Descargar CSV (resumen recetas)", summary_df.to_csv(index=False).encode('utf-8'),
                       file_name="recipe_costs_summary.csv", mime="text/csv")

    # --- Detalle por receta ---
    st.markdown("#### Detalle por receta")
    selected_recipe = st.selectbox("Ver detalle de:", options=recipes['recipe_name'].tolist())
    rid = recipes[recipes['recipe_name']==selected_recipe].iloc[0]['recipe_id']
    det = detail_df[detail_df['recipe_id']==rid].copy()
    if det.empty:
        st.info("Esta receta no tiene ingredientes cargados.")
    else:
        show_det = det[['item_name','qty','unit','waste_pct','unit_cost','unit_base','qty_in_base','extended','vendor_name']]\
            .rename(columns={'item_name':'Ingrediente','qty':'Cantidad','unit':'Unidad Receta',
                             'waste_pct':'Merma','unit_cost':'Costo/Unidad','unit_base':'Unidad Costo',
                             'qty_in_base':'Cant. Efectiva','extended':'Importe','vendor_name':'Proveedor'})
        st.dataframe(show_det, use_container_width=True)
        st.download_button("⬇️ Descargar CSV (detalle receta)", det.to_csv(index=False).encode('utf-8'),
                           file_name=f"recipe_detail_{rid}.csv", mime="text/csv")
