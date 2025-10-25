import streamlit as st
import pandas as pd
from utils import load_all, compute_best, build_vendor_orders, vendor_email_body

st.set_page_config(page_title='Best Price • Pizzería', layout='wide')

@st.cache_data
def get_data():
    return load_all()

vendors, items, vendor_items = get_data()

st.title("🍕 Best Price • Pizzería")
st.caption("Compara precios por producto y línea, arma carrito y genera órdenes por proveedor.")

with st.sidebar:
    st.header("Parámetros")
    qty = st.number_input("Cantidad objetivo (activa price breaks)", min_value=1, value=1, step=1)
    lines = sorted(items['line'].dropna().unique().tolist())
    selected_lines = st.multiselect("Filtrar por líneas", options=lines, default=lines)

best, board, vi = compute_best(vendors, items, vendor_items, qty, selected_lines)

tab1, tab2, tab3 = st.tabs(["Mejor precio", "Ranking proveedores", "Armar orden"])

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
